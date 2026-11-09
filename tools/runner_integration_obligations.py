"""Exact maintained abrupt-role declarations; no inferred case membership."""

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class AbruptDeclaration:
    nodeid: str
    role: str
    expected_returncode: int
    checkpoint: str
    launch_owner: str
    fault_owner: str = ""
    termination_owner: str = ""
    cleanup_owner: str = ""
    launch_case: str | None = None
    owner_sha256: str = ""

    def __post_init__(self) -> None:
        # Legacy declarations predate explicit owner hashes. Derive their
        # stable call-owner identity while requiring all new roles to name
        # their lifecycle owners explicitly in the table below.
        if not self.owner_sha256:
            object.__setattr__(self, "owner_sha256", hashlib.sha256(
                f"{self.nodeid} (call)".encode()
            ).hexdigest())


SEAM_NODE = (
    "src/test/int/python/repomap_kg/artifacts/seam_pipeline.int.test.py"
    "::test_pipeline_parent_reclaims_materialization_after_abrupt_child_exit"
)
SCALE28_NODE = (
    "src/test/int/python/repomap_kg/storage/scale28_preparation_worker.int.test.py"
    "::test_crashed_worker_leader_settles_its_surviving_process_group"
)
GO_HANG_NODE = (
    "src/test/int/python/repomap_kg/coordinator/go_helper_composition.int.test.py"
    "::GoHelperCompositionIntegrationTests"
    "::test_protocol_handles_hanging_helper_termination_and_trailing_messages"
)
MAINTAINED_ABRUPT_DECLARATIONS = (
    AbruptDeclaration(SEAM_NODE, "conformance-abrupt", 17, "during_semantic",
                      "common_lore_index.coordinator._portable_worker_launch.run_worker_spec"),
    AbruptDeclaration(SCALE28_NODE, "scale28-leader-abrupt", 17, "descendant-created",
                      "scale28_preparation_worker._start_without_ambient_parent_main"),
    AbruptDeclaration(GO_HANG_NODE, "go-helper-hang", -15, "file_end",
                      "common_lore_index.extractors.languages.go_protocol.subprocess.Popen"),
    AbruptDeclaration(
        "src/test/int/python/repomap_kg/coordinator/usage_reaper.int.test.py"
        "::test_sigkill_still_yields_rusage_and_a_negative_return_code",
        "usage-self-sigkill", -9, "pre_hello",
        "common_lore_index.coordinator._portable_worker_launch.run_worker_spec",
        "repomap_test_support.usage_worker._prepare",
        "common_lore_index.coordinator._usage_reaper.ChildUsageReaper",
        "common_lore_index.coordinator._protocol_execution._run_protocol_worker",
        "sigkill",
    ),
    AbruptDeclaration(
        "src/test/int/python/repomap_kg/coordinator/usage_reaper.int.test.py"
        "::test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original",
        "usage-parent-interrupt", -9, "pre_hello",
        "common_lore_index.coordinator._portable_worker_launch.run_worker_spec",
        "usage_reaper.int.test._InterruptingEvent.is_set",
        "common_lore_index.coordinator._usage_interrupt.interrupt_cleanup",
        "common_lore_index.coordinator._protocol_execution._run_protocol_worker",
        "block",
    ),
)
# SCALE28's descendant is a required cleanup observation, not another measured
# child: _retain_minimal_worker_environment clears bootstrap/env before Popen.
# Graceful sys.exit(42), SIGINT unwind and emergency teardown stay measured.


def validate_declarations(declarations: Sequence[AbruptDeclaration]) -> None:
    nodes = [d.nodeid for d in declarations]
    if len(nodes) != len(set(nodes)):
        raise ValueError("duplicate abrupt declaration")
    for d in declarations:
        if (not d.nodeid.startswith("src/test/int/python/") or "::" not in d.nodeid
                or any(char in d.nodeid for char in ("*", "?"))
                or not d.role or not d.checkpoint or not d.launch_owner
                or not d.owner_sha256
                or type(d.expected_returncode) is not int or d.expected_returncode == 0):
            raise ValueError("invalid exact abrupt declaration")
        for owner in (d.fault_owner, d.termination_owner, d.cleanup_owner):
            if d.launch_case is not None and not owner:
                raise ValueError("new abrupt declarations require lifecycle owners")
        if d.launch_case is not None and d.launch_case not in {
            "sigkill", "block"
        }:
            raise ValueError("unknown usage abrupt launch case")


def find_declaration(nodeid: str | None, declarations=MAINTAINED_ABRUPT_DECLARATIONS):
    return next((declaration for declaration in declarations
                 if declaration.nodeid == nodeid), None)


@dataclass(frozen=True, slots=True)
class IntentionalVictimDeclaration:
    nodeid: str
    owner_sha256: str
    role: str
    permitted_exitcodes: tuple[int, ...]
    max_victims: int


COV5G_NODE = (
    "src/test/int/python/repomap_kg/storage/test_cov5g_r1_process_containment.int.test.py"
    "::test_cov5g_r1_twenty_process_containment_feasibility_cases"
)
COV5G_OWNER_SHA256 = (
    "e0d161f049355f99326012d6730a079fc946ea779313dddcc55c4d7e93a29fa6"
)

MAINTAINED_INTENTIONAL_VICTIM_DECLARATIONS = (
    IntentionalVictimDeclaration(
        nodeid=COV5G_NODE,
        owner_sha256=COV5G_OWNER_SHA256,
        role="intentional-victim",
        permitted_exitcodes=(-15, -9),
        max_victims=20,
    ),
)


def validate_intentional_victim_declarations(
    declarations: Sequence[IntentionalVictimDeclaration],
) -> None:
    nodes = [d.nodeid for d in declarations]
    if len(nodes) != len(set(nodes)):
        raise ValueError("duplicate intentional victim declaration")
    for d in declarations:
        if (
            not d.nodeid.startswith("src/test/int/python/")
            or "::" not in d.nodeid
            or any(char in d.nodeid for char in ("*", "?"))
            or not d.role
            or not d.owner_sha256
            or not d.permitted_exitcodes
            or any(type(code) is not int or code >= 0 for code in d.permitted_exitcodes)
            or d.max_victims <= 0
        ):
            raise ValueError("invalid exact intentional victim declaration")
        computed = hashlib.sha256(f"{d.nodeid} (call)".encode()).hexdigest()
        if computed != d.owner_sha256:
            raise ValueError(
                f"intentional victim nodeid does not match owner_sha256: {computed} != {d.owner_sha256}"
            )


validate_intentional_victim_declarations(MAINTAINED_INTENTIONAL_VICTIM_DECLARATIONS)


def find_intentional_victim_declaration(
    owner_sha256: str | None,
    declarations: Sequence[IntentionalVictimDeclaration] = MAINTAINED_INTENTIONAL_VICTIM_DECLARATIONS,
) -> IntentionalVictimDeclaration | None:
    if not owner_sha256:
        return None
    return next(
        (d for d in declarations if d.owner_sha256 == owner_sha256),
        None,
    )
