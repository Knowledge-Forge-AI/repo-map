"""Public-safe filesystem samples for paired-report unit/integration owners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


_DIGEST = "sha256:" + "a" * 64
ARMS = (
    "native_tools_baseline",
    "current_graph_baseline:sqlite",
    "current_graph_baseline:postgresql",
    "captured_projection_reference:sqlite",
    "captured_projection_reference:postgresql",
    "postgres_native_fts:postgresql",
    "exact_vector",
    "hnsw_vector",
    "hybrid_rrf",
)
TASKS = ("cal-01",)
REPETITIONS = 3
MEMBERS = (
    "declaration.json",
    "source-manifest.json",
    "sources.zip",
    "observations.jsonl",
    "report.json",
    "terminal.json",
)


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _plan(generation: int) -> dict[str, object]:
    attempt_id = f"w5-semantic-g{generation}"
    return {
        "schema": "cloe-w5-semantic-experiment-v1",
        "attempt_id": attempt_id,
        "generation": generation,
        "task_ids": list(TASKS),
        "task_digests": [_DIGEST],
        "input_identity": _DIGEST,
        "representation_report_identity": _DIGEST,
        "publication_identity": _DIGEST,
        "artifact_profile_identity": _DIGEST,
        "controller_admission_sha256": _DIGEST,
        "source_closure": {"tools/public_fixture.py": _DIGEST},
        "fixture_id": "mixed-v1-public-fixture",
        "freeze_sha256": _DIGEST,
        "policy_digest": _DIGEST,
        "arms": list(ARMS),
        "repetitions": REPETITIONS,
        "timeout_policy": {
            "controller_admission_seconds": 120,
            "model_seconds": 550,
            "component_response_seconds": 600,
        },
    }


def _observations(generation: int) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for arm_id in ARMS:
        for repetition in range(1, REPETITIONS + 1):
            identity = {
                "arm_id": arm_id,
                "task_id": TASKS[0],
                "repetition": repetition,
            }
            records.append({"event": "query_started", **identity})
            unsupported = arm_id == "exact_vector"
            observed = {
                "event": "query_observed",
                **identity,
                "execution_state": "unavailable" if unsupported else "completed",
                "reason": "unsupported_semantic_query_mode" if unsupported else None,
                "elapsed_ns": 7,
                "query_bytes": None,
                "envelope": {
                    "capability_state": "unavailable" if unsupported else "available",
                    "hits": [] if unsupported else [{"rank": 1, "score": 1.0}],
                    "omissions": [],
                    "scope_complete": not unsupported,
                    "unavailable_reason": "unsupported_semantic_query_mode" if unsupported else None,
                    "refusal_code": None,
                    "byte_accounting": {
                        "observed_output_payload_bytes": 11,
                        "raw_process_stdout_bytes": 11,
                    },
                },
            }
            if arm_id == "hybrid_rrf":
                rational_hit = {
                    "rank": 1,
                    "score_numerator": 61,
                    "score_denominator": 60,
                    "contributing_arms": [{
                        "arm_id": "postgres_native_fts:postgresql",
                        "file_identity": {"binding_id": "public", "snapshot_id": "s1", "source_relative_path": "docs/a.md"},
                        "ordinal_rank": 1,
                        "rrf_numerator": 1,
                        "rrf_denominator": 60,
                    }],
                }
                envelope = observed["envelope"]
                assert isinstance(envelope, dict)
                envelope["hits"] = [rational_hit]
            if arm_id == "hnsw_vector":
                observed["exact_reference_recall"] = 0.75
                observed["slot"] = {
                    "execution_state": "completed",
                    "capability_state": "available",
                    "grading_rule": "ranked_positive",
                    "grading_state": "correct",
                    "file_grading_policy_version": "cloe-w5-file-grading-v2",
                    "safety_refusal_correct": None,
                    "absent_answer_correct": None,
                    "metrics": {"recall@5": 1.0, "mrr@5": 1.0, "ndcg@5": 1.0},
                    "timing": {"raw_samples_ns": [7], "sample_count": 1},
                    "byte_accounting": {"observed_output_payload_bytes": 11},
                }
            records.append(observed)
            if arm_id == "native_tools_baseline":
                records.append({
                    "event": "task_graded",
                    **identity,
                    "file_grading_policy_version": "cloe-w5-file-grading-v2",
                    "file_metrics": {"file_recall@5": 1.0},
                    "file_metrics_status": "verified",
                    "span_metrics": {"recall@5": 1.0},
                    "slot": {
                        "execution_state": "completed",
                        "capability_state": "available",
                        "grading_rule": "ranked_positive",
                        "grading_state": "correct",
                        "safety_refusal_correct": None,
                        "absent_answer_correct": None,
                        "metrics": {"recall@5": 1.0, "mrr@5": 1.0, "ndcg@5": 1.0},
                        "timing": {"raw_samples_ns": [7], "sample_count": 1},
                        "byte_accounting": {"observed_output_payload_bytes": 11},
                    },
                })
            elif arm_id in {
                "current_graph_baseline:sqlite",
                "current_graph_baseline:postgresql",
            }:
                records.append({
                    "event": "task_graded",
                    **identity,
                    **(
                        {"file_grading_policy_version": "cloe-w5-file-grading-v2"}
                        if arm_id.endswith(":sqlite")
                        else {}
                    ),
                    "file_metrics": {"file_recall@5": 0.0},
                    "file_metrics_status": "verified",
                    "slot": {
                        "execution_state": "completed",
                        "capability_state": "available",
                        "grading_rule": "safety_refusal",
                        "grading_state": "not_applicable",
                        "safety_refusal_correct": False if arm_id.endswith(":sqlite") else None,
                        "absent_answer_correct": None,
                        "metrics": {"recall@5": 0.0, "mrr@5": 0.0, "ndcg@5": 0.0},
                        "timing": {"raw_samples_ns": [7], "sample_count": 1},
                        "byte_accounting": {"observed_output_payload_bytes": 11},
                    },
                })
    return records


def _correspondence_record(arm_id: str) -> dict[str, object]:
    cost = {
        "correspondence_verification_ns": 1,
        "correspondence_verification_bytes_read": 0,
        "correspondence_failures": 0,
        "known_artifact_bytes_read": 0,
        "known_materialized_bytes_read": 0,
    }
    return {
        "identity": {"arm_id": arm_id, "task_id": TASKS[0], "repetition": 1},
        "sidecar": {
            "schema": "cloe-w5-baseline-correspondence-v1",
            "arm_id": arm_id,
            "task_id": TASKS[0],
            "observed_backend": "postgresql",
            "target_backend": "postgresql",
            "verification": {
                "status": "verified", "gap_reason": None, "verified": True, "cost": cost,
            },
        },
        "cost": cost,
    }


def _byte_work_record(arm_id: str) -> dict[str, object]:
    return {
        "identity": {"arm_id": arm_id, "task_id": TASKS[0], "repetition": 1},
        "accounting": {
            "schema_version": "cloe-w5-byte-accounting-v1",
            "raw_process_stdout_bytes": 495781,
            "direct_selected_text_bytes": 0,
            "native_process_stdout_cap_bytes": 1048576,
            "decoded_candidate_count": 1,
            "returned_hit_count": 1,
            "serialized_envelope_bytes": 1,
            "observed_output_payload_bytes": 1,
            "correspondence_verification_bytes_read": 0,
            "correspondence_verification_ns": 0,
        },
    }


def _write_json(path: Path, value: object) -> bytes:
    raw = _json(value) + b"\n"
    path.write_bytes(raw)
    return raw


def make_pair_artifacts(root: Path, generation: int) -> tuple[Path, Path]:
    """Create a valid six-member journal and valid failed result-v2 sample."""

    attempt = root / f"w5-semantic-g{generation}"
    attempt.mkdir(parents=True, exist_ok=True)
    plan = _plan(generation)
    observations = _observations(generation)
    observation_raw = b"".join(_json(item) + b"\n" for item in observations)
    archive_raw = b"public-fixture-archive"
    members: dict[str, bytes] = {
        "declaration.json": _json(plan) + b"\n",
        "source-manifest.json": b"",
        "sources.zip": archive_raw,
        "observations.jsonl": observation_raw,
        "report.json": _json({"generation": generation, "status": "failed", "failure_code": "fixture_failed"}) + b"\n",
        "terminal.json": b"",
    }
    members["source-manifest.json"] = _json({
        "schema_version": "cloe-retrieval-attempt-source-manifest-v1",
        "archive_sha256": _digest(archive_raw),
        "input_files": {},
        "source_files": {},
    }) + b"\n"
    members["terminal.json"] = _json({
        "declaration_sha256": _digest(members["declaration.json"]),
        "journal_sha256": _digest(observation_raw),
        "observation_count": len(observations),
        "report_sha256": _digest(members["report.json"]),
        "source_manifest_sha256": _digest(members["source-manifest.json"]),
        "sources_archive_sha256": _digest(archive_raw),
        "status": "failed",
    }) + b"\n"
    for name in MEMBERS:
        (attempt / name).write_bytes(members[name])

    cells = []
    for arm_id in ARMS:
        for repetition in range(1, REPETITIONS + 1):
            identity = {"arm_id": arm_id, "task_id": TASKS[0], "repetition": repetition}
            unsupported = arm_id == "exact_vector"
            cells.append({
                "identity": identity,
                "cell": {
                    "arm_id": arm_id,
                    "task_id": TASKS[0],
                    "execution_state": "unavailable" if unsupported else "completed",
                    "reason": "unsupported_semantic_query_mode" if unsupported else None,
                    "candidates": ([{
                        "rank": 1,
                        "score_numerator": 61,
                        "score_denominator": 60,
                        "contributing_arms": [{
                            "arm_id": "postgres_native_fts:postgresql",
                            "file_identity": {"binding_id": "public", "snapshot_id": "s1", "source_relative_path": "docs/a.md"},
                            "ordinal_rank": 1,
                            "rrf_numerator": 1,
                            "rrf_denominator": 60,
                        }],
                    }] if arm_id == "hybrid_rrf" else []),
                    "elapsed_ns": 7,
                    "query_bytes": None,
                    "cleanup_status": "not_applicable",
                },
            })
    result = {
        "schema": "cloe-w5-semantic-experiment-v2",
        "attempt_id": plan["attempt_id"],
        "generation": generation,
        "status": "failed",
        "failure_code": "fixture_failed",
        "plan": plan,
        "cells": cells,
        "correspondence": [_correspondence_record("postgres_native_fts:postgresql")],
        "byte_work": [_byte_work_record("postgres_native_fts:postgresql")],
        "raw_journal": {
            name: {"length": len(members[name]), "sha256": _digest(members[name])}
            for name in MEMBERS
        },
    }
    result_path = root / f"w5-semantic-g{generation}-result-v2.json"
    _write_json(result_path, result)
    return attempt, result_path


__all__ = ["ARMS", "MEMBERS", "make_pair_artifacts"]
