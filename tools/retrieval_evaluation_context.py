"""W4 context-v1 evaluation admission and parent-controlled calibration helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from common_lore_index.retrieval.context_assembly import ContextReadPort, build_compact_context
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_admission import runtime_profile, source_digests
from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_evaluation_context_catalog import (
    CONTEXT_DECLARATION_SCHEMA_VERSION,
    CONTEXT_FIXTURE_ID,
    CONTEXT_FREEZE_SCHEMA_VERSION,
    DEFAULT_ATTEMPT_ID,
    EVALUATION_ARMS,
    ContextAttemptDeclaration,
    ContextFreezeManifest,
    ContextTaskCatalog,
    build_default_context_v1_catalog,
)
from retrieval_evaluation_context_custody import (
    CONTEXT_V1_FIXTURE_ROOT,
    context_candidate_source_files,
    context_input_files,
    sanitized_failure_record,
    sanitized_failure_report,
)
from retrieval_evaluation_context_native import validate_context_native_identity
from retrieval_evaluation_context_arms import _run_arm_observation
from retrieval_evaluation_context_prepare import (
    ContextEvaluationPreparation,
    prepare_context_v1_evaluation,
)

_POSTGRES_IDENTITY_SUPPORTED_FAMILIES = frozenset(
    {"definition", "docs", "tests", "messages"}
)


def write_context_v1_freeze_artifacts(
    context_fixture_root: Path = CONTEXT_V1_FIXTURE_ROOT,
    mixed_fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
) -> tuple[ContextTaskCatalog, ContextFreezeManifest, ContextAttemptDeclaration]:
    """Materialize task_catalog.json, freeze_manifest.json, and attempt_declaration.json."""
    context_fixture_root.mkdir(parents=True, exist_ok=True)
    catalog = build_default_context_v1_catalog()
    cat_bytes = (json.dumps(catalog.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    (context_fixture_root / "task_catalog.json").write_bytes(cat_bytes)
    cat_sha = "sha256:" + hashlib.sha256(cat_bytes).hexdigest()

    mixed_freeze_bytes = (mixed_fixture_root / "freeze-v1.json").read_bytes()
    mixed_freeze_sha = "sha256:" + hashlib.sha256(mixed_freeze_bytes).hexdigest()
    policy_sha = "sha256:" + hashlib.sha256(
        b"cloe-intent-rank-v1|cloe-compact-context-v1|cloe-source-selection-v1|cloe-advisory-freshness-v1"
    ).hexdigest()

    freeze = ContextFreezeManifest(
        schema_version=CONTEXT_FREEZE_SCHEMA_VERSION,
        fixture_id=CONTEXT_FIXTURE_ID,
        catalog_sha256=cat_sha,
        mixed_v1_freeze_sha256=mixed_freeze_sha,
        committed_fixture_files={
            "task_catalog.json": cat_sha,
            "mixed-v1/freeze-v1.json": mixed_freeze_sha,
        },
        policy_digest=policy_sha,
    ).validate()
    freeze_bytes = (json.dumps(freeze.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    (context_fixture_root / "freeze_manifest.json").write_bytes(freeze_bytes)
    freeze_sha = "sha256:" + hashlib.sha256(freeze_bytes).hexdigest()

    decl = ContextAttemptDeclaration(
        schema_version=CONTEXT_DECLARATION_SCHEMA_VERSION,
        attempt_id=DEFAULT_ATTEMPT_ID,
        phase_id="REPOMAP-CLOE-CONTEXT1",
        split="calibration",
        freeze_sha256=freeze_sha,
        catalog_sha256=cat_sha,
        ordered_task_ids=tuple(t.task_id for t in catalog.calibration_tasks()),
        arms=EVALUATION_ARMS,
        repetitions_per_task=3,
        budget_tiers=(4096, 16384, 65536),
    ).validate()
    (context_fixture_root / "attempt_declaration.json").write_text(
        json.dumps(decl.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return catalog, freeze, decl


def verify_context_v1_freeze(
    context_fixture_root: Path = CONTEXT_V1_FIXTURE_ROOT,
    mixed_fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
) -> tuple[ContextTaskCatalog, ContextFreezeManifest, ContextAttemptDeclaration]:
    """Load and verify cryptographic digests for context-v1 and mixed-v1."""
    cat_bytes = (context_fixture_root / "task_catalog.json").read_bytes()
    freeze_bytes = (context_fixture_root / "freeze_manifest.json").read_bytes()
    mixed_freeze_bytes = (mixed_fixture_root / "freeze-v1.json").read_bytes()
    catalog = ContextTaskCatalog.from_mapping(json.loads(cat_bytes.decode("utf-8")))
    freeze = ContextFreezeManifest.from_mapping(json.loads(freeze_bytes.decode("utf-8")))
    decl = ContextAttemptDeclaration.from_mapping(
        json.loads((context_fixture_root / "attempt_declaration.json").read_text(encoding="utf-8"))
    )
    actual_cat_sha = "sha256:" + hashlib.sha256(cat_bytes).hexdigest()
    actual_freeze_sha = "sha256:" + hashlib.sha256(freeze_bytes).hexdigest()
    actual_mixed_sha = "sha256:" + hashlib.sha256(mixed_freeze_bytes).hexdigest()
    if freeze.catalog_sha256 != actual_cat_sha or decl.catalog_sha256 != actual_cat_sha:
        raise ValueError("context-v1 task_catalog.json digest mismatch")
    if decl.freeze_sha256 != actual_freeze_sha:
        raise ValueError("context-v1 freeze_manifest.json digest mismatch")
    if freeze.mixed_v1_freeze_sha256 != actual_mixed_sha:
        raise ValueError("mixed-v1 freeze-v1.json was modified or mismatched")
    return catalog, freeze, decl


def _postgres_capability_report(
    observations: list[dict[str, Any]],
    tasks: tuple[Any, ...],
    repetitions: int,
) -> dict[str, Any]:
    postgres_arms = tuple(arm for arm in EVALUATION_ARMS if arm.endswith("_postgres"))
    supported_tasks = tuple(
        task for task in tasks
        if task.task_family in _POSTGRES_IDENTITY_SUPPORTED_FAMILIES
    )
    expected_families = {task.task_family for task in supported_tasks}
    expected_keys = {
        (task.task_id, arm, repetition)
        for task in supported_tasks for arm in postgres_arms
        for repetition in range(1, repetitions + 1)
    }
    expected_count = len(expected_keys)
    postgres_observations = [
        observation for observation in observations
        if observation.get("arm") in postgres_arms
    ]
    supported_observations = [
        observation for observation in postgres_observations
        if observation.get("task_family") in _POSTGRES_IDENTITY_SUPPORTED_FAMILIES
    ]
    compatible = [
        observation for observation in supported_observations
        if observation.get("status") in {"complete", "partial"}
        and observation.get("gold_locator_rank") is not None
    ]
    unavailable = [
        observation for observation in supported_observations
        if observation.get("status") == "unavailable"
    ]
    unsupported = [
        observation for observation in supported_observations
        if observation.get("status") not in {"complete", "partial", "unavailable"}
    ]
    compatible_families = {observation["task_family"] for observation in compatible}
    observed_supported_keys = {
        (observation.get("task_id"), observation.get("arm"), observation.get("repetition"))
        for observation in supported_observations
    }
    unsupported_family_observations = [
        observation for observation in postgres_observations
        if observation.get("task_family") not in _POSTGRES_IDENTITY_SUPPORTED_FAMILIES
    ]
    unsupported_family_statuses: dict[str, int] = {}
    for observation in unsupported_family_observations:
        status = str(observation.get("status"))
        unsupported_family_statuses[status] = unsupported_family_statuses.get(status, 0) + 1
    return {
        "declared_supported_task_families": sorted(expected_families),
        "observed_task_families": sorted(
            {observation["task_family"] for observation in postgres_observations}
        ),
        "expected_observation_count": expected_count,
        "observed_observation_count": len(postgres_observations),
        "compatible_observation_count": len(compatible),
        "unavailable_observation_count": len(unavailable),
        "unsupported_observation_count": len(unsupported),
        "missing_observation_count": len(expected_keys - observed_supported_keys),
        "compatible_task_families": sorted(compatible_families),
        "known_unsupported_task_families": sorted(
            {observation["task_family"] for observation in unsupported_family_observations}
        ),
        "known_unsupported_observation_count": len(unsupported_family_observations),
        "known_unsupported_status_counts": unsupported_family_statuses,
        "known_unsupported_disposition": "reported_only_no_identity_credit",
        "all_declared_supported_families_compatible": (
            expected_count > 0
            and len(supported_observations) == expected_count
            and observed_supported_keys == expected_keys
            and len(compatible) == expected_count
            and compatible_families == expected_families
        ),
    }


def execute_context_v1_calibration(
    *,
    attempts_root: Path,
    attempt_id: str = DEFAULT_ATTEMPT_ID,
    context_fixture_root: Path = CONTEXT_V1_FIXTURE_ROOT,
    mixed_fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
    postgres_adapter: ContextReadPort | None = None,
    pg_port: int | None = None,
) -> dict[str, Any]:
    """Run the 7-arm × 20-task × 3-repetition (420 observations) W4 calibration."""
    if postgres_adapter is None or getattr(postgres_adapter, "backend", None) != "postgresql":
        raise ValueError("real PostgreSQL adapter is required before W4 admission")
    if type(pg_port) is not int or not (1 <= pg_port <= 65535):
        raise ValueError("owned PostgreSQL port is required before W4 admission")
    catalog, _freeze, decl = verify_context_v1_freeze(context_fixture_root, mixed_fixture_root)
    cal_tasks, held_tasks = catalog.calibration_tasks(), catalog.held_out_tasks()
    if len(cal_tasks) != 20 or len(held_tasks) != 10:
        raise ValueError("invalid context-v1 task split")

    src_files = context_candidate_source_files()
    src_dig = source_digests(src_files)
    journal: AttemptJournal | None = None
    summary_path: Path | None = None
    with tempfile.TemporaryDirectory() as tmp_str:
        try:
            prepared = prepare_context_v1_evaluation(Path(tmp_str))
            sq_adapter = prepared.sqlite_adapter
            native_view = prepared.native_view
            postgres_bindings = postgres_adapter.configured_bindings_by_id()
            postgres_binding_metadata_match = all(
                (configured := postgres_bindings.get(binding_id)) is not None
                and configured.get("revision") == metadata["revision"]
                and configured.get("source_definition_id") == metadata["source_definition_id"]
                and configured.get("selection_policy_id") == metadata["selection_policy_id"]
                for binding_id, metadata in native_view.binding_metadata.items()
            )
            if (
                getattr(postgres_adapter, "graph_id", None) != prepared.graph_id
                or getattr(postgres_adapter, "repository_id", None) != prepared.repository_id
                or not {
                    binding_id for binding_id, _ in native_view.path_to_binding.values()
                }.issubset(
                    set(postgres_adapter.configured_bindings_by_id())
                )
                or not postgres_binding_metadata_match
            ):
                raise ValueError("PostgreSQL identity does not match the W4 fixture graph")
            native_identity = validate_context_native_identity(
                native_view,
                graph_id=prepared.graph_id,
                repository_id=prepared.repository_id,
                accepted_publication=prepared.accepted_publication,
                configured_binding_ids=prepared.configured_binding_ids,
            )
            in_files = context_input_files(
                context_fixture_root,
                mixed_fixture_root,
                extra_files=native_view.input_files(),
            )
            decl_payload = {
                **decl.to_dict(),
                "attempt_id": attempt_id,
                "candidate_closure_digests": src_dig,
                "runner_profile": {
                    **runtime_profile(pg_port),
                    "execution_purpose": "functional_check",
                    "native_source_manifest_sha256": native_view.manifest_sha256,
                    "native_publication_identity": native_identity,
                },
            }
            journal = admit_attempt(attempts_root, decl_payload, src_files, input_files=in_files)
            observations: list[dict[str, Any]] = []
            with sq_adapter:
                for task in cal_tasks:
                    for arm in EVALUATION_ARMS:
                        for rep in range(1, decl.repetitions_per_task + 1):
                            obs = _run_arm_observation(
                                arm,
                                task,
                                sqlite_adapter=sq_adapter,
                                postgres_adapter=postgres_adapter,
                                native_view=native_view,
                            )
                            rec = {
                                "attempt_id": attempt_id, "task_id": task.task_id,
                                "task_family": task.task_family, "intent": task.intent,
                                "arm": arm, "repetition": rep, **obs,
                            }
                            observations.append(rec)
                            journal.append(rec)

            rank_improvements = sum(
                1
                for task in cal_tasks
                if (
                    next(o for o in observations if o["task_id"] == task.task_id and o["arm"] == "intent_navigation_sqlite" and o["repetition"] == 1)["gold_locator_rank"] or 999
                )
                < (
                    next(o for o in observations if o["task_id"] == task.task_id and o["arm"] == "current_graph_navigation_sqlite" and o["repetition"] == 1)["gold_locator_rank"] or 999
                )
            )
            graph_observations = [o for o in observations if o["canonical_identity_claimed"]]
            postgres_capability = _postgres_capability_report(
                observations, cal_tasks, decl.repetitions_per_task
            )
            falsification_checks = {
                "scan_limit_not_routinely_exceeded": all(
                    o["omission_counts"].get("candidate_scan_incomplete", 0) == 0
                    for o in graph_observations
                ),
                "postgres_destination_identity_present": postgres_capability[
                    "all_declared_supported_families_compatible"
                ],
                "budget_and_actual_bytes_exact": all(
                    o["budget_compliant"] is True for o in graph_observations
                ),
                "tests_and_messages_located": all(
                    o["gold_locator_rank"] is not None
                    for o in graph_observations
                    if o["arm"] == "compact_context_16k_sqlite"
                    and o["task_family"] in ("tests", "messages")
                ),
                "intent_rank_improves_over_canonical_key_asc": rank_improvements > 0,
            }
            summary = {
                "schema_version": "cloe-context-evaluation-summary-v1",
                "attempt_id": attempt_id, "split": "calibration",
                "observation_count": len(observations),
                "held_out_context_v1_tasks_executed": 0,
                "held_out_mixed_v1_tasks_executed": 0,
                "arms": list(EVALUATION_ARMS),
                "intent_rank_improved_task_count": rank_improvements,
                "native_source_manifest_sha256": native_view.manifest_sha256,
                "postgres_capability": postgres_capability,
                "falsification_checks": falsification_checks,
                "all_falsification_checks_passed": all(falsification_checks.values()),
                "preserved_w3_facts": {
                    "w3_attempt_id": "w3-calibration-attempt-2", "w3_observation_count": 432,
                    "native_comparator_unbounded_bytes": 495781,
                    "postgres_vs_sqlite_absent_answer_discrepancy": "0/1 vs 1/1",
                },
            }
            summary_path = journal.directory / "calibration_summary.json"
            summary_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            journal.finish("completed", report=summary)
            return summary
        except BaseException as error:
            if journal is not None and (journal.directory / "terminal.json").exists():
                if summary_path is not None:
                    try:
                        summary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            if journal is not None and not (journal.directory / "terminal.json").exists():
                try:
                    journal.append(sanitized_failure_record(phase="calibration", error=error))
                except Exception:
                    pass
                try:
                    journal.finish("failed", report=sanitized_failure_report(phase="calibration", error=error))
                except Exception:
                    pass
            raise


__all__ = [
    "ContextEvaluationPreparation",
    "_run_arm_observation",
    "build_compact_context",
    "execute_context_v1_calibration",
    "prepare_context_v1_evaluation",
    "verify_context_v1_freeze",
    "write_context_v1_freeze_artifacts",
]
