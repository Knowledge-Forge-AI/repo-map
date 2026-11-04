"""Current mixed-v1 bindings and freeze helpers for the optional W5 test."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import CandidatePublication
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT,
    MIXED_V1_GRAPH_ID,
    build_mixed_v1_projection_policy,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import publish_and_load_postgres_corpus
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask, TaskCatalog, load_task_catalog
from retrieval_semantic_experiment_contracts import (
    ExperimentCell,
    ExperimentPlan,
    ExperimentRefusal,
    digest_bytes,
    digest_json,
    make_plan,
    validate_calibration_tasks,
)
from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_experiment_scope import selected_public_binding_ids as _selected_public_binding_ids
from test_sandbox_contract import INNER_REPORT_ROOT
from repomap_test_support.w5_experiment_journal import record_baseline, record_cell

PUBLIC_ALIASES: tuple[str, ...] = ("core", "companion", "feeds")
DECLARED_PROFILE_IDENTITY = "sha256:033cf41ffc5ca108b6e26638573554bac64b84be744903809904ef3364722180"
EXPERIMENT_ATTEMPTS_ROOT = INNER_REPORT_ROOT / "w5-semantic-attempts"
EXPERIMENT_SOURCE_PATHS: tuple[str, ...] = (
    'tools/retrieval_evaluation_admission_w5_capture.py',
    'tools/retrieval_evaluation_admission_w5.py',
    'tools/retrieval_evaluation_admission_w5_contracts.py',
    'tools/retrieval_evaluation_admission_w5_runner.py',
    'tools/retrieval_semantic_baseline_expectations.py',
    'tools/retrieval_evaluation_scope.py',
    'tools/retrieval_evaluation_matching.py',
    'tools/retrieval_evaluation_graph_records.py',
    'tools/retrieval_evaluation_graph_pages.py',
    'tools/retrieval_evaluation_graph_traversal.py',
    'tools/retrieval_semantic_baseline_inputs.py',
    'tools/retrieval_semantic_baseline_envelope.py',
    'tools/retrieval_semantic_baseline_scope.py',
    "src/test/support/python/repomap_test_support/w5_experiment_journal.py",
    "tools/retrieval_semantic_bridge_transport.py", "tools/retrieval_semantic_bridge_transport_io.py",
    "tools/retrieval_semantic_bridge_transport_bundle.py", "tools/retrieval_semantic_experiment_bridge.py",
    "tools/retrieval_semantic_experiment_contracts.py",
    "tools/retrieval_semantic_experiment_evaluator.py",
    "tools/retrieval_semantic_experiment_scope.py",
    "tools/retrieval_semantic_arm_validation.py",
    "tools/retrieval_semantic_fusion.py",
    "tools/retrieval_semantic_grading.py",
    "tools/retrieval_semantic_provenance.py",
    "tools/retrieval_semantic_representation.py",
    "tools/portable_handoff.py",
    "tools/source_navigation_consumer.py",
    "src/main/python/common_lore_index/storage/semantic_candidate_import.py",
    "src/main/python/common_lore_index/storage/semantic_candidate_readback.py",
    "src/main/python/common_lore_index/storage/semantic_candidate_sql.py",
    "src/main/python/common_lore_index/storage/semantic_candidates.py",
    "src/main/python/common_lore_index/storage/errors.py",
    "src/main/python/common_lore_index/storage/psql.py",
    "src/main/python/common_lore_index/storage/publication_readback.py",
    "src/main/python/common_lore_index/storage/authority.py",
    "src/main/python/common_lore_index/storage/publication.py",
    "src/test/support/python/repomap_test_support/w5_experiment_postgres.py",
    "src/test/support/python/repomap_test_support/w5_experiment_ann.py",
    "src/test/support/python/repomap_test_support/w5_experiment_vector.py",
    "src/test/support/python/repomap_test_support/w5_experiment_support.py",
    "src/test/support/python/repomap_test_support/semantic_candidate_restore.py",
    "src/test/support/python/repomap_test_support/semantic_candidate_cleanup.py",
    "src/test/support/python/repomap_test_support/postgres_logical_backup.py",
    "src/test/support/python/repomap_test_support/postgres_harness.py", "src/test/support/python/repomap_test_support/w5_generator_support.py", "src/test/support/python/repomap_test_support/w5_semantic_support.py", "src/test/support/python/repomap_test_support/w5_semantic_store_support.py",
    "src/test/int/python/repomap_kg/retrieval/semantic_pgvector_experiment.int.test.py", "src/main/python/common_lore_index/ops/config.py", "src/main/python/common_lore_index/ops/config_local.py", "src/main/python/common_lore_index/ops/config_records.py", "src/main/python/common_lore_index/canonicalization/_go_family.py",
    "src/test/unit/python/tools/retrieval_semantic_experiment.unit.test.py", "tools/test_sandbox_contract.py", "src/main/python/common_lore_index/storage/context_postgres_identity.py", "src/main/python/common_lore_index/storage/readback_driver.py", "src/main/python/common_lore_index/storage/sqlite_local/connection.py",
)

def load_calibration_catalog() -> TaskCatalog:
    return load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")

def calibration_tasks_for_generation(
    catalog: TaskCatalog, generation: int
) -> tuple[EvaluationTask, ...]:
    tasks = tuple(
        task for task in catalog.calibration_tasks() if task.generation == generation
    )
    return validate_calibration_tasks(tasks, generation=generation)

def calibration_task_manifest(catalog: TaskCatalog) -> bytes:
    tasks = validate_calibration_tasks(catalog.calibration_tasks())
    if len(tasks) != 24:
        raise ExperimentRefusal("calibration_catalog_population")
    value = {
        "schema": "cloe-w5-calibration-task-manifest-v1",
        "catalog_sha256": catalog.catalog_digest(),
        "task_ids": [task.task_id for task in tasks],
        "task_digests": [digest_json(task.to_dict()) for task in tasks],
        "split": "calibration",
        "held_out_executed": False,
    }
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")

def worker_source_closure(repo_root: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    """Read the same explicit worker file list that the component journals."""
    if not isinstance(repo_root, Path) or not repo_root.is_dir() or repo_root.is_symlink():
        raise ExperimentRefusal("source_root_unavailable")
    files: dict[str, bytes] = {}
    for name in WORKER_SOURCE_FILES:
        path = repo_root / "tools" / name
        if not path.is_file() or path.is_symlink():
            raise ExperimentRefusal("worker_source_missing")
        files[name] = path.read_bytes()
    return files, {name: digest_bytes(raw) for name, raw in sorted(files.items())}

def experiment_source_closure(repo_root: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    """Archive the maintained W3 closure plus every semantic/W5 runtime owner."""
    from retrieval_evaluation_admission import candidate_source_files

    worker_files, _worker_closure = worker_source_closure(repo_root)
    files = candidate_source_files(repo_root)
    files.update({f"tools/{name}": raw for name, raw in worker_files.items()})
    additional = set(EXPERIMENT_SOURCE_PATHS)
    additional.update(
        path.relative_to(repo_root).as_posix()
        for path in sorted((repo_root / "tools").glob("retrieval_semantic_*.py"))
    )
    additional.update(
        path.relative_to(repo_root).as_posix()
        for path in sorted(
            (repo_root / "src/test/support/python/repomap_test_support").glob("w5_experiment*.py")
        )
    )
    for relative in sorted(additional):
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise ExperimentRefusal("experiment_source_missing")
        files[relative] = path.read_bytes()
    for relative in tuple(files):
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise ExperimentRefusal("experiment_source_missing")
    return files, {name: digest_bytes(raw) for name, raw in sorted(files.items())}

def make_generation_plan(
    *,
    attempt_id: str,
    generation: int,
    tasks: Sequence[EvaluationTask],
    inputs: PublicGenerationInput,
    controller_admission_sha256: str,
    source_closure: Mapping[str, str],
    fixture_id: str,
    freeze_sha256: str,
    policy_digest: str,
) -> ExperimentPlan:
    if type(inputs) is not PublicGenerationInput:
        raise ExperimentRefusal("generation_input_required")
    publication_identity = digest_json(inputs.provenance.to_dict())
    return make_plan(
        attempt_id=attempt_id,
        generation=generation,
        tasks=tasks,
        input_identity=inputs.input_identity,
        representation_report_identity=inputs.representation_report_identity,
        publication_identity=publication_identity,
        artifact_profile_identity=DECLARED_PROFILE_IDENTITY,
        controller_admission_sha256=controller_admission_sha256,
        source_closure=source_closure,
        fixture_id=fixture_id,
        freeze_sha256=freeze_sha256,
        policy_digest=policy_digest,
    )

def make_public_reader(published: Any, *, psql_command: str) -> GeneratorFixtureReader:
    policy = build_mixed_v1_projection_policy(
        MIXED_V1_GRAPH_ID, selected_aliases=PUBLIC_ALIASES
    )
    return GeneratorFixtureReader(published, policy, "postgresql", psql_command)


def prepare_postgres_generation(
    root: Path,
    *,
    database: Any,
    generation: int,
) -> tuple[Any, GeneratorFixtureReader]:
    working = materialize_mixed_v1_working_copy(
        root / f"working-g{generation}", generation=generation
    )
    home = write_mixed_v1_postgres_home(
        root / f"pg-home-g{generation}",
        working,
        host=database.host,
        port=database.port,
        database=database.database,
        user=database.user,
        password=database.password,
        declared_aliases=PUBLIC_ALIASES,
    )
    published = publish_and_load_postgres_corpus(
        home, selected_aliases=PUBLIC_ALIASES, psql_command=database.psql_command
    )
    return published, make_public_reader(published, psql_command=database.psql_command)

def candidate_publication(reader: GeneratorFixtureReader) -> CandidatePublication:
    """Build CandidatePublication from fresh verified pin data."""
    pin = reader.read_pin()
    return CandidatePublication(
        pin.repository_identity,
        RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt),
    ).validate()

def selected_public_binding_ids(task: EvaluationTask) -> tuple[str, ...]:
    """Resolve only the task-declared public aliases to canonical binding IDs."""
    return _selected_public_binding_ids(task)

def merge_candidate_rows(
    rows_by_binding: Mapping[str, Sequence[Mapping[str, Any]]], *, limit: int = 20
) -> tuple[dict[str, Any], ...]:
    """Merge bounded per-binding candidates with a stable, provenance-aware order."""
    if not isinstance(rows_by_binding, Mapping) or not rows_by_binding:
        raise ExperimentRefusal("candidate_rows_required")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ExperimentRefusal("invalid_vector_limit")
    merged: list[tuple[float, str, str, str, dict[str, Any]]] = []
    for binding, rows in rows_by_binding.items():
        if type(binding) is not str or not binding or not isinstance(rows, Sequence):
            raise ExperimentRefusal("candidate_rows_malformed")
        for row in rows:
            if not isinstance(row, Mapping) or row.get("source_binding_id") != binding:
                raise ExperimentRefusal("candidate_source_scope_mismatch")
            canonical_key = row.get("canonical_key")
            input_digest = row.get("input_digest")
            distance = row.get("distance")
            if type(canonical_key) is not str or not canonical_key:
                raise ExperimentRefusal("candidate_row_identity")
            if type(input_digest) is not str or not input_digest:
                raise ExperimentRefusal("candidate_row_identity")
            if type(distance) not in (int, float):
                raise ExperimentRefusal("candidate_row_identity")
            assert isinstance(canonical_key, str)
            assert isinstance(input_digest, str)
            assert isinstance(distance, (int, float))
            if not math.isfinite(distance):
                raise ExperimentRefusal("candidate_row_identity")
            merged.append(
                (float(distance), canonical_key, binding, input_digest, dict(row))
            )
    merged.sort(key=lambda item: (item[0], item[1].encode("utf-8"), item[2].encode("utf-8"), item[3].encode("utf-8")))
    return tuple(item[4] for item in merged[:limit])

def combine_scoped_cells(
    cells: Sequence[ExperimentCell], *, arm_id: str, task_id: str
) -> ExperimentCell:
    """Collapse per-binding outcomes without hiding refusal or availability gaps."""
    if not cells:
        raise ExperimentRefusal("scoped_cells_required")
    states = tuple(cell.execution_state for cell in cells)
    for cell in cells:
        if cell.arm_id != arm_id or cell.task_id != task_id:
            raise ExperimentRefusal("scoped_cell_identity")
        cell.validate()
    selected = ExecutionState.NOT_RUN
    for state in (
        ExecutionState.FAILED,
        ExecutionState.REFUSED,
        ExecutionState.UNAVAILABLE,
        ExecutionState.NOT_RUN,
        ExecutionState.COMPLETED,
    ):
        if state in states:
            selected = state
            break
    reasons = tuple(sorted({cell.reason for cell in cells if cell.reason}))
    cleanup = (
        "verified" if all(cell.cleanup_status == "verified" for cell in cells)
        else "not_applicable" if all(cell.cleanup_status == "not_applicable" for cell in cells)
        else "failed" if any(cell.cleanup_status == "failed" for cell in cells)
        else "pending"
    )
    return ExperimentCell(
        arm_id, task_id, selected, ";".join(reasons) if reasons else None,
        cleanup_status=cleanup,
    ).validate()

def archive_inputs(
    *,
    request_raw: bytes,
    admission_raw: bytes,
    task_manifest_raw: bytes,
    generation: int,
    publication: Mapping[str, Any],
) -> dict[str, bytes]:
    """Return only bounded data files; no raw fixture or private path is added."""
    if type(generation) is not int or generation not in (1, 2):
        raise ExperimentRefusal("invalid_generation")
    if not isinstance(publication, Mapping):
        raise ExperimentRefusal("publication_manifest_required")
    values = {
        "request.json": request_raw,
        "admission.json": admission_raw,
        "calibration-tasks.json": task_manifest_raw,
        f"generation-{generation}-publication.json": json.dumps(
            dict(publication),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii"),
    }
    if any(type(raw) is not bytes or not raw for raw in values.values()):
        raise ExperimentRefusal("invalid_input_archive")
    return values

__all__ = [
    "DECLARED_PROFILE_IDENTITY", "EXPERIMENT_ATTEMPTS_ROOT", "MIXED_V1_FIXTURE_ROOT", "MIXED_V1_GRAPH_ID", "PUBLIC_ALIASES",
    "archive_inputs", "calibration_task_manifest", "calibration_tasks_for_generation",
    "candidate_publication", "load_calibration_catalog", "make_generation_plan",
    "make_public_reader", "prepare_postgres_generation", "experiment_source_closure",
    "record_baseline", "record_cell", "worker_source_closure",
    "selected_public_binding_ids", "merge_candidate_rows", "combine_scoped_cells",
]
