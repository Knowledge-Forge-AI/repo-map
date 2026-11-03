"""Unavailable/refused captures retain measured work without file-credit proof."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable
from typing import cast

import pytest

from common_lore_index.retrieval.query_contracts import (
    QueryEnvelope, QueryMode, QueryScope, refused_envelope, unavailable_envelope,
)
from repomap_test_support.w5_experiment_vector import baseline_file_metrics_with_correspondence
from repomap_test_support.w5_semantic_support import (
    make_w5_calibration_task, make_w5_policy, make_w5_readback_adapter, make_w5_verified_pin,
)
import repomap_test_support.w5_generator_support as generator
from repomap_test_support.retrieval_evaluation_publication import PublishedCorpusState
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_baseline_capture import BaselinePinSnapshot, IssuedBaselineCapture, execute_with_live_baseline_pins
from retrieval_semantic_baseline_work import CorrespondenceVerificationFailure
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_experiment_scope import (
    BaselineCorrespondenceSidecar, verify_baseline_correspondence_sidecar,
)
from retrieval_semantic_provenance import (
    AcceptedStoreReadback, RepresentationValidationError, VerifiedPublicationPin,
)


def _gap_capture(
    state: ExecutionState,
    *,
    postgres_policy_digest: str | None = None,
    advance_postgres: bool = False,
    reuse_postgres: bool = False,
) -> tuple[EvaluationTask, QueryEnvelope, BaselineCorrespondenceSidecar]:
    task = make_w5_calibration_task()
    sqlite = make_w5_readback_adapter(backend="sqlite")
    postgres = make_w5_readback_adapter(backend="postgresql")
    reused_postgres = (
        make_w5_verified_pin(backend="postgresql", readback_adapter=postgres)
        if reuse_postgres else None
    )

    def execute(pre: BaselinePinSnapshot) -> tuple[ExecutionState, QueryEnvelope]:
        pin = pre.sqlite
        scope = QueryScope(
            graph_id=task.graph_id, backend="sqlite",
            publication_bundle_id=pin.publication_bundle_id,
            snapshot_manifest_id=pin.snapshot_manifest_id,
            selected_binding_ids=tuple(task.selected_bindings),
            source_path_prefix=task.source_path_prefix,
        ).validate()
        if state == ExecutionState.REFUSED:
            envelope = refused_envelope(
                requested_mode=QueryMode(task.requested_mode), scope=scope,
                refusal_code="binding_privacy_not_authorized",
            )
        else:
            envelope = unavailable_envelope(
                requested_mode=QueryMode(task.requested_mode), scope=scope,
                reason="captured_text_surface_unsupported_by_metadata_graph",
            )
        if advance_postgres:
            postgres.advance(run_id=2, generation=2)
        return state, envelope

    def read_postgres() -> VerifiedPublicationPin:
        pin = reused_postgres or make_w5_verified_pin(
            backend="postgresql", readback_adapter=postgres
        )
        if postgres_policy_digest is not None:
            return replace(pin, policy_digest=postgres_policy_digest)
        return pin

    result, capture = execute_with_live_baseline_pins(
        arm_id="current_graph_baseline:sqlite", task=task,
        generation_aliases=("core", "companion", "docs_meta"), execute=execute,
        read_sqlite=lambda: make_w5_verified_pin(backend="sqlite", readback_adapter=sqlite),
        read_postgres=read_postgres,
    )
    sidecar = BaselineCorrespondenceSidecar(
        arm_id=capture.arm_id, task_id=task.task_id, capture=capture,
        sqlite_pin=capture.pre.sqlite, postgres_pin=capture.pre.postgres,
        pre_query_pin=capture.pre.sqlite, post_query_pin=capture.post.sqlite,
        generation_aliases=capture.generation_aliases,
    )
    return task, result[1], sidecar


@pytest.mark.parametrize(("state", "expected"), [
    (ExecutionState.REFUSED, "refused:binding_privacy_not_authorized"),
    (ExecutionState.UNAVAILABLE, "unavailable:captured_text_surface_unsupported_by_metadata_graph"),
])
def test_normal_gap_keeps_raw_reason_and_issued_read_cost_without_verification_credit(
    state: ExecutionState, expected: str,
) -> None:
    task, envelope, sidecar = _gap_capture(state)
    metrics, status, gap, cost = baseline_file_metrics_with_correspondence(
        task, sidecar.arm_id, state, envelope, sidecar,
    )
    assert metrics is None and status == "gap" and gap == expected
    assert cost.correspondence_failures == 0
    assert isinstance(sidecar.capture, IssuedBaselineCapture)
    assert cost.correspondence_verification_ns == sidecar.capture.read_ns
    assert cost.correspondence_verification_bytes_read is None
    retained = sidecar.to_dict(
        observed_backend="sqlite", target_backend="sqlite", status=status,
        gap_reason=gap, cost=cost,
    )
    assert retained["verification"]["verified"] is False
    with pytest.raises(ExperimentRefusal, match="verified_sidecar_pin_required"):
        sidecar.to_dict(
            observed_backend="sqlite", target_backend="sqlite", status="verified",
            verified_pin=sidecar.sqlite_pin, cost=cost,
        )


def test_gap_cost_rejects_copied_capture_and_changed_envelope() -> None:
    task, envelope, sidecar = _gap_capture(ExecutionState.UNAVAILABLE)
    assert isinstance(sidecar.capture, IssuedBaselineCapture)
    forged = replace(sidecar, capture=replace(sidecar.capture))
    with pytest.raises(ExperimentRefusal, match="baseline_capture_not_issued"):
        forged.captured_gap_cost(task, sidecar.arm_id, envelope)
    with pytest.raises(ExperimentRefusal, match="baseline_capture_identity_mismatch"):
        sidecar.captured_gap_cost(task, sidecar.arm_id, replace(envelope, unavailable_reason="different"))


def test_cross_store_policy_digest_drift_refuses_before_state_credit() -> None:
    task, envelope, sidecar = _gap_capture(
        ExecutionState.UNAVAILABLE, postgres_policy_digest="sha256:" + "f" * 64
    )
    with pytest.raises(CorrespondenceVerificationFailure, match="cross_store_binding_policy_mismatch"):
        verify_baseline_correspondence_sidecar(
            sidecar, task=task, arm_id=sidecar.arm_id,
            state=ExecutionState.UNAVAILABLE, envelope=envelope,
        )


def test_non_target_post_advance_refuses_even_when_sqlite_target_is_current() -> None:
    task, envelope, sidecar = _gap_capture(
        ExecutionState.UNAVAILABLE, advance_postgres=True
    )
    with pytest.raises(CorrespondenceVerificationFailure, match="baseline_non_target_post_pin_mismatch"):
        verify_baseline_correspondence_sidecar(
            sidecar, task=task, arm_id=sidecar.arm_id,
            state=ExecutionState.UNAVAILABLE, envelope=envelope,
        )


def test_reused_non_target_post_pin_refuses() -> None:
    task, envelope, sidecar = _gap_capture(
        ExecutionState.UNAVAILABLE, reuse_postgres=True
    )
    with pytest.raises(CorrespondenceVerificationFailure, match="baseline_capture_pre_post_not_independent"):
        verify_baseline_correspondence_sidecar(
            sidecar, task=task, arm_id=sidecar.arm_id,
            state=ExecutionState.UNAVAILABLE, envelope=envelope,
        )


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_generator_pin_uses_compact_live_readback_and_rechecks_privacy_on_revalidation(
    monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """The identity path never enumerates canonical rows or caches authorization."""
    published = cast(PublishedCorpusState, object())
    reader = generator.GeneratorFixtureReader(published, make_w5_policy(), backend)
    cell = make_w5_readback_adapter(backend=backend)
    allowed = True
    database_reads: list[str] = []

    def authorize(_reader: generator.GeneratorFixtureReader) -> None:
        if not allowed:
            raise RepresentationValidationError("graph_privacy_not_authorized", "revoked")

    def readback() -> AcceptedStoreReadback:
        database_reads.append(backend)
        return cell()

    def make_adapter(value: PublishedCorpusState, **_kwargs: object) -> Callable[[], AcceptedStoreReadback]:
        assert value is published
        return readback

    def forbid_enumeration(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pin identity must not enumerate canonical nodes/evidence")

    monkeypatch.setattr(generator.GeneratorFixtureReader, "_authorized_graph", authorize)
    monkeypatch.setattr(generator, "make_sqlite_readback_adapter", make_adapter)
    monkeypatch.setattr(generator, "make_postgres_readback_adapter", make_adapter)
    monkeypatch.setattr(generator, "load_sqlite_accepted_nodes_and_evidence", forbid_enumeration)
    monkeypatch.setattr(generator, "load_postgres_accepted_nodes_and_evidence", forbid_enumeration)
    pin = reader.read_pin()
    before = len(database_reads)
    pin.revalidate_current()
    assert len(database_reads) > before
    before = len(database_reads)
    allowed = False
    with pytest.raises(RepresentationValidationError, match="graph_privacy_not_authorized"):
        pin.revalidate_current()
    assert len(database_reads) == before
