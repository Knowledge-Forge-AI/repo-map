"""Shared adapters for first-use workload scenarios.

Local selection and packs run through the guarded ``LocalHarness`` children;
Server selection and packs call the product CLI entry point in process with
captured streams, exactly as the incumbent Server owner does. The adapters
return parsed records for witnesses and never retain raw packets in evidence.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common_lore_index.cli.main import main as cli_main
from first_use_workload_census import Census, load_census
from first_use_workload_reconcile import Verdict
from first_use_workload_recipe import MAX_PACK_BYTES
from first_use_workload_recipe_shapes import PackSpec, RecipeStep
from first_use_workload_source_identity import current_intent
from repomap_test_support.first_use_workflow import guard_first_use_root
from repomap_test_support.first_use_workload_driver import (
    CallOutcome, CleanupRegistry, Observed, ScenarioRun, StepPlan,
    default_bundle_base, new_attempt, run_rows, write_bundle,
)
from repomap_test_support.first_use_workload_witness import (
    bounded, canary_free, census_facts, encoded_size, packet_refs,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
)
from repomap_test_support.sqlite_local_harness import LocalHarness

PlanBuilder = Callable[["ScenarioContext"], Mapping[tuple[int, int], StepPlan]]


@dataclass
class ScenarioContext:
    """Attempt-owned paths, the frozen census, the cleanup registry and row state."""

    root: Path
    census: Census
    registry: CleanupRegistry
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def work(self) -> Path:
        return self.root / "workflow"

    @property
    def working_copy(self) -> Path:
        return self.work / "working-copy"

    def fresh_path(self, stem: str) -> Path:
        """A new, never-reused attempt-owned file path under ``work/files``."""
        counter = self.state.setdefault("_counter", 0) + 1
        self.state["_counter"] = counter
        directory = self.work / "files"
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory / f"{counter:03d}-{stem}.json"


def materialize(context: ScenarioContext, generation: int) -> Path:
    """Guard every rebuild target before the destructive materializer runs."""
    context.work.mkdir(mode=0o700, exist_ok=True)
    target = guard_first_use_root(context.working_copy, context.work)
    materialize_mixed_v1_working_copy(target, generation=generation)
    return target


def census_plan(context: ScenarioContext, step: RecipeStep) -> StepPlan:
    """``census_verify``: prepare the g1 copy, then compare the frozen inventory."""
    generation = step.generation or 1
    facts: dict[str, Any] = {}

    def prepare() -> None:
        materialize(context, generation)

    def call() -> CallOutcome:
        # A drifted materialization raises StaleInput before any product call.
        facts.update(census_facts(context.working_copy, context.census, generation, step.aliases))
        return CallOutcome()

    return StepPlan(prepare, call, lambda _outcome: Observed(dict(facts)))


def capture_cli(argv: Sequence[str]) -> tuple[int, str, str]:
    """Run the product CLI in process; stdout/stderr are captured, never echoed."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli_main(list(argv))
        except SystemExit as exit_request:
            # A product usage exit is this call's result, never a driver interrupt.
            code = exit_request.code if isinstance(exit_request.code, int) else 2
    out.flush()
    err.flush()
    assert isinstance(out.buffer, io.BytesIO) and isinstance(err.buffer, io.BytesIO)
    return code, out.buffer.getvalue().decode("utf-8"), err.buffer.getvalue().decode("utf-8")


def _select_args(home: Path, output: Path, aliases: Sequence[str], pin: bool) -> list[str]:
    args = ["ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID]
    for alias in aliases:
        args.extend(["--binding", binding_id_for_alias(alias)])
    if pin:
        args.append("--pin-publication")
    return [*args, "--output", str(output)]


def _pack_args(home: Path, selection: Path, spec: PackSpec) -> list[str]:
    args = [
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--mode", spec.mode, "--selection", str(selection),
    ]
    if spec.query is not None:
        args.extend(["--query", spec.query])
    if spec.intent is not None:
        args.extend(["--intent", spec.intent])
    if spec.canonical_key is not None:
        args.extend(["--canonical-key", spec.canonical_key])
    return args


def _record(code: int, stdout: str) -> dict[str, Any]:
    if code != 0:
        raise AssertionError("first-use-select-failed")
    record = json.loads(stdout)
    if not isinstance(record, dict) or record.get("schema") != "cloe-source-selection-v1":
        raise AssertionError("first-use-select-invalid")
    return record


def _packet(code: int, stdout: str) -> dict[str, Any]:
    if code not in {0, 1, 3}:
        raise AssertionError("first-use-pack-failed")
    packet = json.loads(stdout)
    if not isinstance(packet, dict):
        raise AssertionError("first-use-pack-invalid")
    return packet


@dataclass(frozen=True)
class Backend:
    """One home on one backend; Local uses guarded children, Server in-process CLI.

    ``harness`` is a provider because the guarded harness exists only after the
    row that prepares the home has run.
    """

    name: str
    home: Path
    harness: Callable[[], LocalHarness] | None = None

    def _run(self, args: list[str]) -> tuple[int, str]:
        if self.harness is not None:
            completed = self.harness().run(*args)
            if completed.stderr:
                raise AssertionError("first-use-cli-stderr-unexpected")
            return completed.returncode, completed.stdout
        code, stdout, stderr = capture_cli(args)
        if stderr:
            raise AssertionError("first-use-cli-stderr-unexpected")
        return code, stdout

    def select(self, output: Path, aliases: Sequence[str], *, pin: bool) -> dict[str, Any]:
        return _record(*self._run(_select_args(self.home, output, aliases, pin)))

    def publication(self, context: ScenarioContext, aliases: Sequence[str]) -> dict[str, Any] | None:
        record = self.select(context.fresh_path(f"pin-{self.name}"), aliases, pin=True)
        publication = record.get("expected_publication")
        return publication if isinstance(publication, dict) else None

    def pack(self, selection: Path, spec: PackSpec) -> dict[str, Any]:
        return _packet(*self._run(_pack_args(self.home, selection, spec)))


def pack_facts(results: Sequence[tuple[PackSpec, Mapping[str, Any]]]) -> dict[str, Any]:
    """Closed pack facts for one backend; refs are bounded, never truncated."""
    refs: list[list[str]] = []
    for spec, packet in results:
        refs.extend(packet_refs(packet, spec.tag))
    investigation = [spec for spec, _packet in results if spec.investigation]
    supported: bool | None = None
    if investigation:
        supported = all(
            packet.get("effective_mode") == "graph_investigation"
            and (packet.get("expansion") or {}).get("reason") != "backend_unsupported"
            for spec, packet in results if spec.investigation
        )
    return {
        "status": sorted([spec.tag, packet.get("status")] for spec, packet in results),
        "reason": sorted([spec.tag, packet.get("reason")] for spec, packet in results),
        "encoded_bytes": sorted([spec.tag, encoded_size(packet)] for spec, packet in results),
        "observed_locations": bounded(sorted(refs)),
        "canary_free": all(canary_free(packet) for _spec, packet in results),
        "max_bytes": MAX_PACK_BYTES,
        "investigation_supported": supported,
    }


def execute_scenario(
    scenario: str,
    tmp_path: Path,
    build_plans: PlanBuilder,
    *,
    bundle_base: Path | None = None,
) -> tuple[Path, Verdict, ScenarioRun]:
    """Select custody first, run every row once, then write and reconcile the bundle."""
    base = default_bundle_base(tmp_path) if bundle_base is None else bundle_base
    census = load_census()
    run = ScenarioRun(scenario, new_attempt(), current_intent())
    registry = CleanupRegistry()
    context = ScenarioContext(root=tmp_path, census=census, registry=registry)
    run_rows(run, build_plans(context), registry)
    root, verdict = write_bundle(base, run, current_intent(), census)
    return root, verdict, run


__all__ = [
    "Backend", "PlanBuilder", "ScenarioContext", "capture_cli", "census_plan", "execute_scenario",
    "materialize", "pack_facts",
]
