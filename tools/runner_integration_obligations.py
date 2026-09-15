"""Exact maintained abrupt-role declarations; no inferred case membership."""

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class AbruptDeclaration:
    nodeid: str
    role: str
    expected_returncode: int
    checkpoint: str
    launch_owner: str


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
                      "repomap_kg.coordinator._portable_worker_launch.run_worker_spec"),
    AbruptDeclaration(SCALE28_NODE, "scale28-leader-abrupt", 17, "descendant-created",
                      "scale28_preparation_worker._start_without_ambient_parent_main"),
    AbruptDeclaration(GO_HANG_NODE, "go-helper-hang", -15, "file_end",
                      "repomap_kg.extractors.languages.go_protocol.subprocess.Popen"),
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
                or type(d.expected_returncode) is not int or d.expected_returncode == 0):
            raise ValueError("invalid exact abrupt declaration")


def find_declaration(nodeid: str | None, declarations=MAINTAINED_ABRUPT_DECLARATIONS):
    return next((declaration for declaration in declarations
                 if declaration.nodeid == nodeid), None)
