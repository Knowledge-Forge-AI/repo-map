"""Host runner for the T2 negative containment probes (spec 14.2).

Each probe runs as the parser principal in its own freshly constructed and
verified container, under the parse budgets, and the parent classifies only
what it observed itself: exit status, bound events and host inspection.
Every container is settled with proven exact-ID absence before the next one;
an unproven absence stops the sequence. This is native-qualification
tooling: fake command responses can exercise its logic, never its evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.construction import (
    PARSE_DEADLINE,
    PYTHON_FLAGS,
    RuntimeMaterial,
    construct,
    container_state,
)
from common_lore_index.extractors.rust_pilot.docker_boundary import PARSER_USER, SCRATCH, DockerBoundary
from common_lore_index.extractors.rust_pilot.helper_protocol import MAX_OUTPUT

REFUSAL_PROBES = ("tcp", "udp", "write_root", "write_prefix", "write_prefix_file", "chmod_sealed",
                  "exec_scratch", "setuid", "docker_socket", "processes")
RESOURCE_PROBES = {"memory": "memory_bound", "sleep": "time_bound", "stdout_flood": "output_bound",
                   "stderr_flood": "diagnostic_bound", "abort": "crashed"}
ALL_PROBES = REFUSAL_PROBES + tuple(RESOURCE_PROBES)


@dataclass(frozen=True)
class ProbeOutcome:
    name: str
    expected: str
    observed: str
    absence_proven: bool

    @property
    def passed(self) -> bool:
        return self.expected == self.observed and self.absence_proven


def expected_outcome(name: str) -> str:
    if name in REFUSAL_PROBES:
        return "refused"
    if name in RESOURCE_PROBES:
        return RESOURCE_PROBES[name]
    raise ContractError("unknown_probe")


def classify_probe(name: str, result: ExecResult, oom_killed: bool) -> str:
    """Map the parent's own observations of one probe exec to a closed outcome."""

    if not result.settled or result.io_failed or not result.input_complete or result.callback_failed:
        return "client_cleanup_unproven"
    if oom_killed or (result.returncode == 137 and not result.events):
        return "memory_bound" if oom_killed else "killed"
    for event in ("time_bound", "output_bound", "diagnostic_bound"):
        if event in result.events:
            return event
    if name in REFUSAL_PROBES:
        if result.clean and result.stdout.startswith(f"REFUSED {name} ".encode("ascii")):
            return "refused"
        return "allowed" if result.returncode == 1 else "unexpected"
    if result.returncode not in (0, None):
        return "crashed"
    return "completed"


def run_containment_probes(boundary: DockerBoundary, *, run_id: str, first_seq: int, docker_arch: str,
                           image_id: str, material: RuntimeMaterial,
                           names: tuple[str, ...] = ALL_PROBES,
                           settle: Callable[[str], bool] | None = None) -> tuple[ProbeOutcome, ...]:
    """Run each named probe in a fresh container; stop at the first unproven absence."""

    outcomes: list[ProbeOutcome] = []
    settle_one = settle or boundary.settle
    for offset, name in enumerate(names):
        boundary.require_work_deadline()
        expected = expected_outcome(name)
        owned: list[str] = []
        observed = "construction_refused"
        try:
            built = construct(boundary, run_id=run_id, seq=first_seq + offset, docker_arch=docker_arch,
                              image_id=image_id, material=material, owned=owned)
            result = boundary.run_guest(built.container_id, user=PARSER_USER, workdir=SCRATCH,
                                   tail=[*PYTHON_FLAGS, "-c", material.sources.text("containment_probes"), name],
                                   stdin=None, stdout_limit=MAX_OUTPUT, deadline=PARSE_DEADLINE)
            try:
                end = boundary.begin_settlement(built.container_id)
                _running, oom = container_state(boundary, built.container_id, hard_end=end)
            except ContractError:
                oom = False
            observed = classify_probe(name, result, oom)
        except ContractError:
            pass
        proven = bool(owned) and all([settle_one(container_id) for container_id in owned])
        outcomes.append(ProbeOutcome(name, expected, observed, proven))
        if not proven:
            break
    return tuple(outcomes)
