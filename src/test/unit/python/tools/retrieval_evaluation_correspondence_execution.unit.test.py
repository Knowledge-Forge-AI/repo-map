"""Pure execution-boundary contracts for W5 baseline correspondence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import (
    DEFAULT_ORDERING_POLICY_VERSION,
    CapabilityState,
    EvaluationLocator,
    MatchSurface,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    QUERY_CONTRACT_VERSION,
)
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_semantic_support import (
    InMemoryStoreReadbackCell,
    make_w5_calibration_task,
    make_w5_readback_adapter,
    make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_baseline_capture import (
    BaselinePinSnapshot,
    IssuedBaselineCapture,
    execute_with_live_baseline_pins,
    generation_aliases_for,
)
from retrieval_semantic_baseline_work import CorrespondenceVerificationFailure
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_experiment_scope import (
    BaselineCorrespondenceSidecar,
    CorrespondenceCostSample,
    verify_baseline_correspondence_sidecar,
)
from retrieval_semantic_provenance import VerifiedPublicationPin


def _envelope(
    pin: VerifiedPublicationPin,
    task: EvaluationTask,
    *,
    backend: str,
) -> QueryEnvelope:
    scope = QueryScope(
        graph_id=pin.graph_id,
        backend=backend,
        publication_bundle_id=pin.publication_bundle_id,
        snapshot_manifest_id=pin.snapshot_manifest_id,
        selected_binding_ids=tuple(task.selected_bindings),
        source_path_prefix=task.source_path_prefix,
    ).validate()
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode(task.requested_mode),
        effective_mode=QueryMode(task.requested_mode),
        match_surface=MatchSurface.STORED_METADATA,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        scope_complete=True,
        provenance={"accepted_run_id": pin.run_id, "run_id": pin.run_id},
    ).validate()


def _observed_backend(arm_id: str) -> str:
    if arm_id == "native_tools_baseline":
        return "native_filesystem"
    if arm_id.startswith("captured_projection_reference:"):
        return "captured_reference"
    return arm_id.rsplit(":", 1)[-1]


def _capture_bundle(
    arm_id: str = "current_graph_baseline:sqlite",
) -> tuple[
    EvaluationTask,
    QueryEnvelope,
    IssuedBaselineCapture,
    list[str],
    list[str],
    InMemoryStoreReadbackCell,
    InMemoryStoreReadbackCell,
]:
    task = make_w5_calibration_task()
    sqlite_state = make_w5_readback_adapter(backend="sqlite")
    postgres_state = make_w5_readback_adapter(backend="postgresql")
    sqlite_reads: list[str] = []
    postgres_reads: list[str] = []

    def read_sqlite() -> VerifiedPublicationPin:
        sqlite_reads.append("sqlite")
        return make_w5_verified_pin(backend="sqlite", readback_adapter=sqlite_state)

    def read_postgres() -> VerifiedPublicationPin:
        postgres_reads.append("postgresql")
        return make_w5_verified_pin(backend="postgresql", readback_adapter=postgres_state)

    def execute(pre: BaselinePinSnapshot) -> tuple[None, QueryEnvelope]:
        return None, _envelope(
            pre.target_for_arm(arm_id), task, backend=_observed_backend(arm_id)
        )

    result, capture = execute_with_live_baseline_pins(
        arm_id=arm_id,
        task=task,
        generation_aliases=("core", "companion", "docs_meta"),
        execute=execute,
        read_sqlite=read_sqlite,
        read_postgres=read_postgres,
    )
    return task, result[1], capture, sqlite_reads, postgres_reads, sqlite_state, postgres_state


def _sidecar(
    capture: IssuedBaselineCapture,
    arm_id: str,
    *,
    aliases: tuple[str, ...] | None = None,
) -> BaselineCorrespondenceSidecar:
    return BaselineCorrespondenceSidecar(
        arm_id=arm_id,
        task_id=capture.task_id,
        sqlite_pin=capture.pre.sqlite,
        postgres_pin=capture.pre.postgres,
        pre_query_pin=capture.pre.target_for_arm(arm_id),
        post_query_pin=capture.post.target_for_arm(arm_id),
        capture=capture,
        generation_aliases=capture.generation_aliases if aliases is None else aliases,
    )


def test_capture_factory_reads_both_stores_before_and_after_with_fresh_pins() -> None:
    task, _envelope_value, capture, sqlite_reads, postgres_reads, _, _ = _capture_bundle()

    assert task.task_id == capture.task_id
    assert capture.validate() is capture
    assert capture.read_attempts == 4
    assert len(sqlite_reads) == len(postgres_reads) == 2
    assert capture.pre.sqlite is not capture.post.sqlite
    assert capture.pre.postgres is not capture.post.postgres
    assert capture.pre.sqlite.backend == "sqlite"
    assert capture.pre.postgres.backend == "postgresql"


def test_dataclass_replace_cannot_forge_a_factory_issued_capture() -> None:
    _task, _envelope_value, capture, *_ = _capture_bundle()

    forged = replace(capture, arm_id="current_graph_baseline:postgresql")
    with pytest.raises(ExperimentRefusal, match="baseline_capture_not_issued"):
        forged.validate()


def test_query_exception_is_preserved_when_both_post_reads_fail() -> None:
    task = make_w5_calibration_task()
    sqlite_state = make_w5_readback_adapter(backend="sqlite")
    postgres_state = make_w5_readback_adapter(backend="postgresql")
    sqlite_calls = 0
    postgres_calls = 0
    query_failure = RuntimeError("query failure")

    def read_sqlite() -> VerifiedPublicationPin:
        nonlocal sqlite_calls
        sqlite_calls += 1
        if sqlite_calls > 1:
            raise OSError("post sqlite read failed")
        return make_w5_verified_pin(backend="sqlite", readback_adapter=sqlite_state)

    def read_postgres() -> VerifiedPublicationPin:
        nonlocal postgres_calls
        postgres_calls += 1
        if postgres_calls > 1:
            raise OSError("post postgres read failed")
        return make_w5_verified_pin(backend="postgresql", readback_adapter=postgres_state)

    def execute(_pre: BaselinePinSnapshot) -> tuple[None, QueryEnvelope]:
        raise query_failure

    with pytest.raises(RuntimeError) as caught:
        execute_with_live_baseline_pins(
            arm_id="current_graph_baseline:sqlite",
            task=task,
            generation_aliases=("core",),
            execute=execute,
            read_sqlite=read_sqlite,
            read_postgres=read_postgres,
        )

    assert caught.value is query_failure
    assert isinstance(getattr(caught.value, "baseline_capture_read_ns"), int)
    assert getattr(caught.value, "baseline_capture_read_ns") >= 0
    assert getattr(caught.value, "baseline_capture_read_attempts") == 4
    assert getattr(caught.value, "baseline_capture_read_failures") == 2
    assert sqlite_calls == postgres_calls == 2


def test_projection_fixture_answers_whole_view_and_public_subset_without_private_reads(
    tmp_path: Path,
) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    core_id = next(binding.binding_id for binding in inputs.manifest.bindings if binding.alias == "core")
    public_entries = tuple(entry for entry in inputs.manifest.entries if entry.binding_id == core_id)

    assert projection.aggregate_input_bytes_read == sum(
        entry.reference.size_bytes for entry in public_entries
    )
    assert len(projection.projected_files) == len(public_entries)
    whole = query_captured_text(
        projection,
        CapturedTextQueryRequest(query="BOUNDARY_START_TOKEN"),
        current_accepted_reference=inputs.accepted_reference,
    )
    subset = query_captured_text(
        projection,
        CapturedTextQueryRequest(
            query="BOUNDARY_START_TOKEN",
            selected_binding_ids=(core_id,),
            source_path_prefix="pkg/alpha.py",
        ),
        current_accepted_reference=inputs.accepted_reference,
    )
    assert whole.capability_state == subset.capability_state == CapabilityState.AVAILABLE
    assert whole.hits and subset.hits
    assert all(hit.locator.binding_id == core_id for hit in subset.hits)
    assert all(hit.locator.source_relative_path == "pkg/alpha.py" for hit in subset.hits)


def test_cost_sample_keeps_actual_artifact_bytes_and_unknown_total_explicit(
    tmp_path: Path,
) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    cost = CorrespondenceCostSample(
        correspondence_verification_ns=17,
        correspondence_verification_bytes_read=None,
        known_artifact_bytes_read=projection.aggregate_input_bytes_read,
        known_materialized_bytes_read=0,
        correspondence_failures=1,
    ).validate()

    assert cost.to_dict() == {
        "correspondence_verification_ns": 17,
        "correspondence_verification_bytes_read": None,
        "known_artifact_bytes_read": projection.aggregate_input_bytes_read,
        "known_materialized_bytes_read": 0,
        "correspondence_failures": 1,
    }


@pytest.mark.parametrize(
    ("arm_id", "expected"),
    (
        ("native_tools_baseline", "native_materialization_witness_required"),
        ("captured_projection_reference:sqlite", "projection_reference_required"),
    ),
)
def test_missing_native_or_projection_inputs_refuse_before_credit(
    arm_id: str, expected: str,
) -> None:
    task, envelope_value, capture, *_ = _capture_bundle(arm_id)
    sidecar = _sidecar(capture, arm_id)

    with pytest.raises(ExperimentRefusal, match=expected):
        verify_baseline_correspondence_sidecar(
            sidecar,
            task=task,
            arm_id=arm_id,
            state=ExecutionState.COMPLETED,
            envelope=envelope_value,
        )


def test_missing_independent_generation_aliases_refuses() -> None:
    task, envelope_value, capture, *_ = _capture_bundle()
    sidecar = _sidecar(capture, "current_graph_baseline:sqlite", aliases=())

    with pytest.raises(ExperimentRefusal, match="baseline_capture_alias_scope_mismatch"):
        verify_baseline_correspondence_sidecar(
            sidecar,
            task=task,
            arm_id="current_graph_baseline:sqlite",
            state=ExecutionState.COMPLETED,
            envelope=envelope_value,
        )


def test_capture_digest_binds_the_actual_envelope_not_just_its_scope() -> None:
    task, envelope_value, capture, *_ = _capture_bundle()
    sidecar = _sidecar(capture, "current_graph_baseline:sqlite")
    forged_hit = QueryHit(
        locator=EvaluationLocator(
            binding_id=task.selected_bindings[0], source_relative_path="pkg/forged.py"
        ),
        match_surface=MatchSurface.STORED_METADATA,
        rank=1,
        score=1.0,
    ).validate()
    forged = replace(envelope_value, hits=(forged_hit,)).validate()

    with pytest.raises(CorrespondenceVerificationFailure, match="baseline_capture_envelope_mismatch"):
        verify_baseline_correspondence_sidecar(
            sidecar,
            task=task,
            arm_id="current_graph_baseline:sqlite",
            state=ExecutionState.COMPLETED,
            envelope=forged,
        )


def test_verified_sidecar_serialization_uses_registered_pin_and_cost_after_advance() -> None:
    task, envelope_value, capture, sqlite_reads, postgres_reads, sqlite_state, _ = _capture_bundle()
    sidecar = _sidecar(capture, "current_graph_baseline:sqlite")
    verified_pin, cost = verify_baseline_correspondence_sidecar(
        sidecar,
        task=task,
        arm_id="current_graph_baseline:sqlite",
        state=ExecutionState.COMPLETED,
        envelope=envelope_value,
    )
    reads_before_advance = (len(sqlite_reads), len(postgres_reads))
    sqlite_state.advance(run_id=2, generation=2)
    public_map = sidecar.to_dict(
        observed_backend="sqlite",
        target_backend="sqlite",
        status="verified",
        verified_pin=verified_pin,
        cost=cost,
    )

    assert public_map["verification"]["verified"] is True
    assert public_map["verification"]["cost"] == cost.to_dict()
    assert (len(sqlite_reads), len(postgres_reads)) == reads_before_advance
    with pytest.raises(ExperimentRefusal, match="verified_sidecar_pin_required"):
        sidecar.to_dict(
            observed_backend="sqlite",
            target_backend="sqlite",
            status="verified",
            verified_pin=replace(verified_pin, repository_identity="repo1:foreign"),
            cost=cost,
        )
    with pytest.raises(ExperimentRefusal, match="verified_sidecar_pin_required"):
        sidecar.to_dict(
            observed_backend="sqlite",
            target_backend="sqlite",
            status="verified",
            verified_pin=verified_pin,
            cost=replace(cost, correspondence_failures=1),
        )


@pytest.mark.parametrize("aliases", [(), (None,), ("",), ("core", "core")])
def test_global_aliases_cannot_silently_drop_or_duplicate_bindings(aliases: tuple[object, ...]) -> None:
    manifest = SimpleNamespace(bindings=tuple(SimpleNamespace(alias=alias) for alias in aliases))
    with pytest.raises(ExperimentRefusal, match="generation_aliases_"):
        generation_aliases_for(manifest)


def test_global_aliases_retain_denied_binding_in_the_independent_set() -> None:
    aliases = ("core", "companion", "feeds", "denied-mailbox")
    manifest = SimpleNamespace(bindings=tuple(SimpleNamespace(alias=alias) for alias in aliases))
    assert generation_aliases_for(manifest) == aliases
