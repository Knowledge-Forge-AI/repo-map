"""Boundaries for truthful W4 native evaluation and evidence custody."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    MatchSurface,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    QUERY_CONTRACT_VERSION,
)
from repomap_test_support.context_fixture import BINDING_PRIV, build_sqlite_context_fixture
import retrieval_evaluation_context_native as native
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_context import context_candidate_source_files
from retrieval_evaluation_context_catalog import build_default_context_v1_catalog
from retrieval_evaluation_context_grading import (
    NATIVE_GRADING_SCOPE,
    grade_graph_packet,
    grade_native_envelope,
)
from retrieval_evaluation_context_native import materialize_context_native_view
from retrieval_evaluation_context_manifest import MAX_NATIVE_SOURCE_FILE_BYTES
from retrieval_evaluation_context_prepare import prepare_context_v1_evaluation
from retrieval_evaluation_context_custody import (
    sanitized_failure_record,
    sanitized_failure_report,
)
from retrieval_evaluation_grading import ExecutionState


def _readback_identity(adapter: Any) -> dict[str, Any]:
    with adapter:
        identity = adapter.read_initial_identity(WorkLedger(backend="sqlite"))
    return {**identity, "backend": "sqlite"}


def test_native_destination_is_exclusive_and_never_erases_existing_files(
    tmp_path: Path,
) -> None:
    _, _, graph, _, adapter = build_sqlite_context_fixture(tmp_path / "fixture")
    identity = _readback_identity(adapter)
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("retain", encoding="utf-8")

    with pytest.raises(ValueError, match="absent"):
        materialize_context_native_view(
            destination,
            bindings=graph.source_bindings,
            accepted_identity=identity,
        )
    assert sentinel.read_text(encoding="utf-8") == "retain"


def test_native_materializer_requires_allowlisted_public_full_retention(
    tmp_path: Path,
) -> None:
    _, _, graph, _, adapter = build_sqlite_context_fixture(tmp_path / "fixture")
    identity = _readback_identity(adapter)
    unknown_policy = replace(graph.source_bindings[0], privacy="unclassified")

    with pytest.raises(ValueError, match="privacy or retention"):
        materialize_context_native_view(
            tmp_path / "native",
            bindings=(unknown_policy,),
            accepted_identity=identity,
        )


def test_native_materializer_refuses_oversized_regular_input(tmp_path: Path) -> None:
    _, _, graph, _, adapter = build_sqlite_context_fixture(tmp_path / "fixture")
    identity = _readback_identity(adapter)
    root = Path(graph.source_bindings[0].root_path)
    (root / "oversized.bin").write_bytes(b"x" * (MAX_NATIVE_SOURCE_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="size"):
        materialize_context_native_view(
            tmp_path / "native",
            bindings=graph.source_bindings,
            accepted_identity=identity,
        )


def test_private_metadata_only_binding_is_excluded_from_native_inputs(tmp_path: Path) -> None:
    prepared = prepare_context_v1_evaluation(
        tmp_path / "fixture", include_private_binding=True
    )
    assert BINDING_PRIV not in prepared.native_view.binding_metadata
    assert all(not path.startswith("priv/") for path in prepared.native_view.source_bytes)


def test_native_query_refuses_manifest_mutation_before_child_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_context_v1_evaluation(tmp_path / "fixture")
    source = next(path for path in prepared.native_view.view_root.rglob("*") if path.is_file())
    source.write_bytes(source.read_bytes() + b"mutated")

    def forbidden_process(*args: object, **kwargs: object) -> None:
        raise AssertionError("manifest mismatch must refuse before native execution")

    monkeypatch.setattr(native, "run_git_grep_process", forbidden_process)
    task = build_default_context_v1_catalog().calibration_tasks()[0]
    state, envelope, _, _ = native.execute_context_native_task(
        task,
        prepared.native_view,
        graph_id=prepared.graph_id,
        selected_binding_ids=tuple(prepared.native_view.binding_metadata),
    )
    assert state == ExecutionState.FAILED
    assert envelope.provenance["failure_reason"] == "native_manifest_mismatch"


def test_native_query_rejects_caller_identity_selection_not_bound_to_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_context_v1_evaluation(tmp_path / "fixture")
    monkeypatch.setattr(
        native,
        "run_git_grep_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("identity mismatch must refuse before child process")
        ),
    )
    task = build_default_context_v1_catalog().calibration_tasks()[0]
    state, envelope, _, _ = native.execute_context_native_task(
        task,
        prepared.native_view,
        graph_id=prepared.graph_id,
        selected_binding_ids=("caller-asserted-binding",),
    )
    assert state == ExecutionState.FAILED
    assert envelope.provenance["failure_reason"] == "native_identity_selection_mismatch"


def test_failed_attempt_terminal_receipt_is_sanitized_and_single_use(tmp_path: Path) -> None:
    source_bytes = b"owned source\n"
    source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    journal = admit_attempt(
        tmp_path / "attempts",
        {
            "attempt_id": "boundary-failure",
            "candidate_closure_digests": {"source.py": source_digest},
        },
        {"source.py": source_bytes},
    )
    error = RuntimeError("/private/path must not be persisted")
    journal.append(sanitized_failure_record(phase="native", error=error))
    report = sanitized_failure_report(phase="native", error=error)
    journal.finish("failed", report=report)

    terminal = json.loads((journal.directory / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["status"] == "failed"
    assert "/private/path" not in json.dumps(report)
    with pytest.raises(RuntimeError, match="terminal"):
        journal.finish("completed")


def test_context_source_closure_includes_native_and_corpus_owners() -> None:
    files = context_candidate_source_files()
    assert {
        "tools/retrieval_evaluation_context_native.py",
        "tools/retrieval_evaluation_context_prepare.py",
        "tools/retrieval_evaluation_context_manifest.py",
        "src/test/unit/python/tools/retrieval_evaluation_context_boundaries.unit.test.py",
        "src/test/support/python/repomap_test_support/context_fixture.py",
    } <= files.keys()
    assert not any(
        "/__pycache__/" in path or path.endswith((".pyc", ".pyo", ".DS_Store"))
        for path in files
    )
    assert all(isinstance(data, bytes) for data in files.values())


def test_grading_uses_primary_graph_gold_and_declares_native_path_only_scope() -> None:
    task = build_default_context_v1_catalog().calibration_tasks()[16]
    primary, secondary = task.gold_targets
    task = replace(
        task,
        gold_targets=(
            replace(primary, relevance_grade=3),
            replace(secondary, relevance_grade=2),
        ),
    )
    secondary_item = {
        "canonical_key": secondary.canonical_key,
        "locations": [{
            "source_binding_id": secondary.source_binding_id,
            "source_relative_path": secondary.source_relative_path,
        }],
    }
    assert grade_graph_packet(task, {"items": [secondary_item], "neighbors": []}) is None

    locator = EvaluationLocator(
        binding_id=secondary.source_binding_id,
        source_relative_path=secondary.source_relative_path,
        start_line=99,
        end_line=99,
    ).validate()
    envelope = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(graph_id="polyglot-ctx", backend="native_filesystem"),
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(QueryHit(locator=locator, match_surface=MatchSurface.CAPTURED_TEXT, rank=1),),
        scope_complete=True,
    ).validate()
    assert NATIVE_GRADING_SCOPE == "binding_path_only"
    assert grade_native_envelope(task, envelope) == 1
