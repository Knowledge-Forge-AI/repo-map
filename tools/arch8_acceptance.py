#!/usr/bin/env python3
"""Run the closed, public-safe ARCH8 acceptance evidence catalog."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AcceptanceGate:
    """One ARCH8 requirement and the executable evidence that covers it."""

    key: str
    evidence: tuple[str, ...]


class Arch8AcceptanceError(RuntimeError):
    """Raised when the bounded ARCH8 acceptance gate fails."""


REQUIRED_GATE_KEYS = frozenset(
    {
        "acquisition_only",
        "all_supported_upgrades",
        "baseline_and_drift",
        "cancellation",
        "cleanup_resources",
        "commit_unknown_recovery",
        "configuration_capability_failures",
        "container_restart",
        "coordinator_publication",
        "direct_coordinator_parity",
        "direct_publication",
        "fresh_initialization",
        "graph_backup_recovery",
        "http_privacy",
        "least_privilege",
        "legacy_api_boundary",
        "locale_encoding",
        "measurement_boundaries",
        "multi_graph_control_recovery",
        "ownership_refusal",
        "packaged_go_extraction",
        "partial_initialization_retry",
        "partial_restore_retry",
        "public_read_bounds",
        "rollback_and_retry",
        "source_cleanliness",
        "source_relocation",
        "unchanged_repeat_determinism",
    }
)


ACCEPTANCE_GATES = (
    AcceptanceGate(
        "acquisition_only",
        ("src/test/unit/python/repomap_kg/ops_ingestion/arch4b_acquisition_contracts.unit.test.py",),
    ),
    AcceptanceGate(
        "all_supported_upgrades",
        (
            "src/test/int/python/repomap_kg/storage/arch8_all_prior_graph_upgrades.int.test.py",
            "src/test/int/python/repomap_kg/coordinator/storage.int.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "baseline_and_drift",
        ("src/test/unit/python/repomap_kg/ops_refresh/baselines_drift.unit.test.py",),
    ),
    AcceptanceGate(
        "cancellation",
        ("src/test/unit/python/repomap_kg/storage/scale9e_cancellation.unit.test.py",),
    ),
    AcceptanceGate(
        "cleanup_resources",
        (
            "src/test/int/python/repomap_kg/storage/scale6_staging_cleanup.int.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "commit_unknown_recovery",
        (
            "src/test/int/python/repomap_kg/coordinator/refresh_worker.int.test.py",
            "src/test/int/python/repomap_kg/storage/scale8_staged_ingestion.int.test.py",
        ),
    ),
    AcceptanceGate(
        "configuration_capability_failures",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster.unit.test.py",
            "src/test/unit/python/repomap_kg/ops/helper_branches_preflight_config_mcp.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "container_restart",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster.unit.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch8_lifecycle_admin_operational.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "coordinator_publication",
        ("src/test/int/python/repomap_kg/coordinator/local_mode.int.test.py",),
    ),
    AcceptanceGate(
        "direct_coordinator_parity",
        (
            "src/test/int/python/repomap_kg/coordinator/refresh_worker.int.test.py",
            "src/test/unit/python/repomap_kg/storage/arch1c_publication_exclusion.unit.test.py",
            "src/test/int/python/repomap_kg/storage/arch1c_publication_exclusion.int.test.py",
            "src/test/int/python/repomap_kg/storage/arch5a4b_maintenance_ownership.int.test.py",
        ),
    ),
    AcceptanceGate(
        "direct_publication",
        ("src/test/int/python/repomap_kg/storage/arch4a_complete_publication.int.test.py",),
    ),
    AcceptanceGate(
        "fresh_initialization",
        (
            "src/test/unit/python/repomap_kg/runtime/arch5b_provisioning_recovery.unit.test.py",
            "src/test/int/python/repomap_kg/coordinator/arch5b_provisioning_recovery.int.test.py",
        ),
    ),
    AcceptanceGate(
        "graph_backup_recovery",
        ("src/test/unit/python/repomap_kg/runtime/arch7d1_private_atomic_streaming.unit.test.py",),
    ),
    AcceptanceGate(
        "http_privacy",
        ("src/test/unit/python/repomap_kg/server/local_server.unit.test.py",),
    ),
    AcceptanceGate(
        "least_privilege",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7e_declarative_database_roles.unit.test.py",
            "src/test/int/python/repomap_kg/runtime/arch7e_database_roles.int.test.py",
        ),
    ),
    AcceptanceGate(
        "legacy_api_boundary",
        ("src/test/unit/python/repomap_kg/storage/arch5e_obsolete_compatibility_removal.unit.test.py",),
    ),
    AcceptanceGate(
        "locale_encoding",
        ("src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster.unit.test.py",),
    ),
    AcceptanceGate(
        "measurement_boundaries",
        (
            "src/test/unit/python/repomap_kg/storage/arch2c_staging_observability.unit.test.py",
            "src/test/int/python/repomap_kg/storage/arch2c_staging_observability.int.test.py",
            "src/test/unit/python/repomap_kg/storage/arch6c_pipeline_lifetime_measurement.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "multi_graph_control_recovery",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7d2_exact_coordinated_backup_sets.unit.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch7d3_deterministic_complete_set_restore.unit.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch8_lifecycle_admin_operational.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "ownership_refusal",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7c1_exact_lifecycle_allowlist.unit.test.py",
            "src/test/unit/python/repomap_kg/runtime/arch7c2_stable_drop_maintenance.unit.test.py",
        ),
    ),
    AcceptanceGate(
        "packaged_go_extraction",
        (
            "src/test/unit/python/repomap_kg/runtime/arch7f_release_resources.unit.test.py",
            "src/test/int/python/repomap_kg/runtime/arch7f_release_wheel.int.test.py",
        ),
    ),
    AcceptanceGate(
        "partial_initialization_retry",
        ("src/test/unit/python/repomap_kg/runtime/arch5b_provisioning_recovery.unit.test.py",),
    ),
    AcceptanceGate(
        "partial_restore_retry",
        ("src/test/unit/python/repomap_kg/runtime/arch7d3_deterministic_complete_set_restore.unit.test.py",),
    ),
    AcceptanceGate(
        "public_read_bounds",
        ("src/test/unit/python/repomap_kg/cli/storage_canonical/arch7a1_public_read_pages.unit.test.py",),
    ),
    AcceptanceGate(
        "rollback_and_retry",
        (
            "src/test/int/python/repomap_kg/storage/arch5a1_graph_schema_authority.int.test.py",
            "src/test/int/python/repomap_kg/storage/arch5c3_identity_compatibility_rollback.int.test.py",
        ),
    ),
    AcceptanceGate(
        "source_cleanliness",
        ("src/test/unit/python/repomap_kg/runtime/arch7f_release_resources.unit.test.py",),
    ),
    AcceptanceGate(
        "source_relocation",
        ("src/test/unit/python/repomap_kg/runtime/arch5c2a_repository_identity_reconciliation.unit.test.py",),
    ),
    AcceptanceGate(
        "unchanged_repeat_determinism",
        ("src/test/int/python/repomap_kg/storage/scale8_staged_ingestion.int.test.py",),
    ),
)


def evidence_files() -> tuple[str, ...]:
    """Return the stable, deduplicated executable evidence set."""

    return tuple(sorted({path for gate in ACCEPTANCE_GATES for path in gate.evidence}))


def validate_catalog(repo_root: Path) -> None:
    """Reject incomplete, duplicated, missing, or out-of-scope evidence."""

    keys = [gate.key for gate in ACCEPTANCE_GATES]
    if set(keys) != REQUIRED_GATE_KEYS or len(keys) != len(REQUIRED_GATE_KEYS):
        raise Arch8AcceptanceError("arch8_catalog_invalid")
    for gate in ACCEPTANCE_GATES:
        if not gate.evidence or len(gate.evidence) != len(set(gate.evidence)):
            raise Arch8AcceptanceError("arch8_catalog_invalid")
        for relative in gate.evidence:
            path = Path(relative)
            if path.is_absolute() or path.parts[:2] != ("src", "test"):
                raise Arch8AcceptanceError("arch8_catalog_invalid")
            if not (repo_root / path).is_file():
                raise Arch8AcceptanceError("arch8_catalog_invalid")


def acceptance_payload(*, result: str) -> dict[str, object]:
    """Return only bounded, deterministic, public-safe acceptance fields."""

    return {
        "schema": "arch8.acceptance.v1",
        "result": result,
        "requirement_count": len(REQUIRED_GATE_KEYS),
        "evidence_file_count": len(evidence_files()),
        "requirements": sorted(REQUIRED_GATE_KEYS),
    }


def build_acceptance_command(
    repo_root: Path,
    *,
    python_executable: str,
    pg_container_port: int,
    pg_container_runtime: str,
) -> tuple[str, ...]:
    """Build the stable repository-owned test command for the catalog."""

    return (
        python_executable,
        str(repo_root / "tools" / "run_tests.py"),
        "--suite",
        "staging",
        "--no-coverage",
        "--pg-container-port",
        str(pg_container_port),
        "--pg-container-runtime",
        pg_container_runtime,
        "--",
        *evidence_files(),
    )


def run_acceptance(
    repo_root: Path,
    *,
    python_executable: str,
    pg_container_port: int,
    pg_container_runtime: str,
) -> dict[str, object]:
    """Execute the catalog without relaying private subprocess diagnostics."""

    validate_catalog(repo_root)
    completed = subprocess.run(
        build_acceptance_command(
            repo_root,
            python_executable=python_executable,
            pg_container_port=pg_container_port,
            pg_container_runtime=pg_container_runtime,
        ),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise Arch8AcceptanceError("arch8_acceptance_failed")
    return acceptance_payload(result="passed")


def main(argv: list[str] | None = None) -> int:
    """Print a planned catalog or run it and print its bounded result."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pg-container-port", type=int, default=55433)
    parser.add_argument("--pg-container-runtime", default="docker")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        validate_catalog(repo_root)
        payload = (
            run_acceptance(
                repo_root,
                python_executable=sys.executable,
                pg_container_port=args.pg_container_port,
                pg_container_runtime=args.pg_container_runtime,
            )
            if args.run
            else acceptance_payload(result="planned")
        )
    except Arch8AcceptanceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
