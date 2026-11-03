"""Source and runtime validation for durable retrieval experiment admission."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_evaluation_heldout import HeldOutAdmissionPrerequisite, validate_held_out_admission
from retrieval_evaluation_native import probe_git_version, resolve_git_executable
from retrieval_evaluation_schema import AttemptDeclaration, FreezeManifest, TaskCatalog


def candidate_source_files(repo_root: Path) -> dict[str, bytes]:
    """Snapshot the W2/W3 retrieval, lexical, PostgreSQL navigation, and evaluation closure."""
    required = (
        "src/main/python/common_lore_index/retrieval",
        "pyproject.toml",
        "src/main/python/common_lore_index/cli/_ops_baselines_dispatch.py",
        "src/main/python/common_lore_index/cli/_parser_ops_graph.py",
        "src/main/python/common_lore_index/cli/_parser_ops_lexical.py",
        "src/main/python/common_lore_index/cli/dispatch.py",
        "src/main/python/common_lore_index/cli/ops_lexical_commands.py",
        "src/main/python/common_lore_index/cli/parser.py",
        "src/main/python/common_lore_index/ops/_portable_retention.py",
        "src/main/python/common_lore_index/ops/portable_refresh.py",
        "src/main/python/common_lore_index/runtime/_backup_lifecycle.py",
        "src/main/python/common_lore_index/runtime/_extension_restore_lifecycle.py",
        "src/main/python/common_lore_index/runtime/_lexical_restore.py",
        "src/main/python/common_lore_index/runtime/backup_restore_sets.py",
        "src/main/python/common_lore_index/runtime/database_roles.py",
        "src/main/python/common_lore_index/runtime/postgres_route.py",
        "src/main/python/common_lore_index/server/_mcp_locations.py",
        "src/main/python/common_lore_index/server/_mcp_navigation.py",
        "src/main/python/common_lore_index/server/_postgres_investigation_queries.py",
        "src/main/python/common_lore_index/server/investigation_read_store.py",
        "src/main/python/common_lore_index/storage/postgres_node_locations.py",
        "src/main/python/common_lore_index/ops/config_local.py",
        "src/main/python/common_lore_index/ops/config_records.py",
        "src/main/python/common_lore_index/server/ops.py",
        "src/main/python/common_lore_index/storage/context_postgres_identity.py",
        "src/main/python/common_lore_index/storage/graph_readback_sql.py",
        "src/main/python/common_lore_index/storage/navigation_search.py",
        "src/main/python/common_lore_index/storage/node_locations.py",
        "src/main/python/common_lore_index/storage/readback_driver.py",
        "src/main/python/common_lore_index/storage/sql_core.py",
        "src/main/python/common_lore_index/storage/sqlite_local/__init__.py",
        "src/main/python/common_lore_index/storage/sqlite_local/raw_payload.py",
        "src/main/python/common_lore_index/storage/sqlite_local/connection.py",
        "src/main/python/common_lore_index/storage/sqlite_local/context_expansion_queries.py",
        "tools/retrieval_semantic_primitives.py",
        "tools/retrieval_semantic_provenance.py",
        "tools/retrieval_semantic_record_validation.py",
        "tools/retrieval_semantic_representation.py",
        "src/main/resources/rdbms/2026/10/31-001-cloe-lexical-create-derived-schema.sql",
        "tools/retrieval_evaluation_harness.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_canaries.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_fixture.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_publication.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_publication_readback.py",
    )
    for rel in required:
        if not (repo_root / rel).exists():
            raise FileNotFoundError(f"required candidate closure file missing: {rel}")
    paths = set((repo_root / "src/main/python/common_lore_index/retrieval").glob("*.py"))
    paths.update((repo_root / "src/main/python/common_lore_index/storage").glob("lexical_*.py"))
    paths.update((repo_root / "src/main/python/common_lore_index/storage").glob("postgres_navigation_*.py"))
    paths.update((repo_root / "src/main/python/common_lore_index/ops").glob("lexical_*.py"))
    paths.update((repo_root / "tools").glob("retrieval_evaluation*.py"))
    paths.update(repo_root / rel for rel in required[1:])
    return {path.relative_to(repo_root).as_posix(): path.read_bytes() for path in sorted(paths)}


def source_digests(files: dict[str, bytes]) -> dict[str, str]:
    return {rel: "sha256:" + hashlib.sha256(data).hexdigest() for rel, data in files.items()}


def validate_admitted_input_manifest(
    journal: AttemptJournal, *, fixture_root: Path = MIXED_V1_FIXTURE_ROOT
) -> None:
    """Fail closed when live fixture bytes differ from the admitted archive manifest."""
    if fixture_root.is_symlink() or not fixture_root.is_dir():
        raise ValueError("admitted fixture root is not a regular directory")
    manifest_path = journal.directory / "source-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("admitted input manifest is unreadable") from error
    if not isinstance(manifest, Mapping) or manifest.get(
        "schema_version"
    ) != "cloe-retrieval-attempt-source-manifest-v1":
        raise ValueError("admitted input manifest has an unsupported schema")
    expected_raw = manifest.get("input_files")
    if not isinstance(expected_raw, Mapping):
        raise ValueError("admitted input manifest lacks input_files")
    expected: dict[str, str] = {}
    for raw_path, raw_digest in expected_raw.items():
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or raw_path.startswith(("/", "\\"))
            or "\\" in raw_path
            or ":" in raw_path
            or any(part in {"", ".", ".."} for part in raw_path.split("/"))
            or not isinstance(raw_digest, str)
            or len(raw_digest) != 71
            or not raw_digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in raw_digest[7:])
        ):
            raise ValueError("admitted input manifest contains an unsafe entry")
        expected[raw_path] = raw_digest

    actual: dict[str, str] = {}
    try:
        paths = sorted(fixture_root.rglob("*"))
        for path in paths:
            relative = path.relative_to(fixture_root).as_posix()
            if "baseline" in path.relative_to(fixture_root).parts:
                continue
            if path.is_symlink():
                raise ValueError("admitted fixture input contains a symlink")
            if path.is_file():
                actual[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("admitted fixture inputs are unreadable") from error
    if actual != expected:
        raise ValueError("live fixture inputs differ from the admitted input manifest")


def runtime_profile(pg_port: int) -> dict[str, Any]:
    """Only public-safe runtime identity fields, with no host/user or scratch paths."""
    executable = resolve_git_executable()
    predecessor = subprocess.run(
        [executable, "--no-replace-objects", "-C", str(MIXED_V1_FIXTURE_ROOT.parents[4]), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    if len(predecessor) != 40 or any(character not in "0123456789abcdef" for character in predecessor):
        raise ValueError("candidate predecessor must be a full Git commit identity")
    return {
        "git_executable": executable, "git_version": probe_git_version(),
        "python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
        "system": platform.system(), "machine": platform.machine(), "pg_port": pg_port,
        "predecessor_head_commit": predecessor,
    }


def admit_evaluation(
    declaration: AttemptDeclaration,
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    attempt_root: Path,
    pg_port: int,
    supported_arms: tuple[str, ...],
    held_out_prerequisite: HeldOutAdmissionPrerequisite | None = None,
    accepted_criteria_v2: Mapping[str, Any] | None = None,
    calibration_directory: Path | None = None,
    allow_held_out_in_current_milestone: bool = False,
) -> AttemptJournal:
    source_files = candidate_source_files(MIXED_V1_FIXTURE_ROOT.parents[4])
    live_digests = source_digests(source_files)
    if declaration.split in {"held-out", "held_out"} or held_out_prerequisite is not None:
        validate_held_out_admission(
            held_out_prerequisite,
            accepted_criteria_v2,
            catalog,
            freeze,
            live_candidate_digests=live_digests,
            calibration_directory=calibration_directory,
            allow_held_out_in_current_milestone=allow_held_out_in_current_milestone,
        )
    declaration.validate()
    if declaration.freeze_sha256 != freeze.freeze_digest():
        raise ValueError("declaration freeze_sha256 mismatch against FreezeManifest")
    if declaration.catalog_sha256 != catalog.catalog_digest():
        raise ValueError("declaration catalog_sha256 mismatch against TaskCatalog")
    if declaration.ordered_task_ids != tuple(task.task_id for task in catalog.calibration_tasks()):
        raise ValueError("declaration ordered_task_ids mismatch against calibration tasks")
    if not declaration.arms or len(set(declaration.arms)) != len(declaration.arms):
        raise ValueError("declaration requires distinct non-empty arms")
    if not set(declaration.arms).issubset(supported_arms):
        raise ValueError("declaration contains unsupported evaluation arms")
    actual_runtime = runtime_profile(pg_port)
    for key, value in actual_runtime.items():
        if declaration.runner_profile.get(key) != value:
            raise ValueError(f"declared runner profile mismatch: {key}")
    purpose = declaration.runner_profile.get("execution_purpose")
    if purpose not in {"functional_check", "retained_calibration"}:
        raise ValueError("declaration requires an explicit execution_purpose")
    if purpose == "retained_calibration" and (
        len(declaration.arms) not in {5, len(supported_arms)}
        or not set(declaration.arms).issubset(supported_arms)
        or declaration.repetitions_per_task != 3
    ):
        raise ValueError("retained calibration requires all five or six arms and three repetitions")
    if dict(declaration.candidate_closure_digests) != live_digests:
        raise ValueError("declaration candidate_closure_digests mismatch against live candidate source")
    inputs = {
        path.relative_to(MIXED_V1_FIXTURE_ROOT).as_posix(): path.read_bytes()
        for path in sorted(MIXED_V1_FIXTURE_ROOT.rglob("*"))
        if path.is_file() and "baseline" not in path.relative_to(MIXED_V1_FIXTURE_ROOT).parts
    }
    return admit_attempt(attempt_root, declaration.to_dict(), source_files, input_files=inputs)
