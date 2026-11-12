"""Descriptor preparation binds current publication, span closure and exact raw excerpt bytes."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pytest

from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_semantic_support import InMemoryStoreReadbackCell, make_w5_accepted_pub_mapping
import retrieval_public_text_descriptors as descriptors_module
from retrieval_public_text_contracts import (
    AGGREGATE_BUDGET_EXCEEDED, ARTIFACT_INTEGRITY_REFUSED, DESCRIPTOR_CONSTRUCTION_REFUSED, DESCRIPTOR_SET_CHANGED,
    EXCERPT_PRIVACY_REFUSED, METADATA_PRIVACY_REFUSED, PRIVATE_MARKER_SCOPE_INVALID, PROJECTION_INPUTS_UNAVAILABLE,
    PROJECTION_TRUNCATED, PUBLICATION_MISMATCH, PUBLICATION_REVALIDATION_FAILED, SPAN_CORRESPONDENCE_REFUSED,
    SPAN_LINK_MISMATCH, PrivateMarkerScope, PublicTextRefusal, SpanRow,
)
from retrieval_public_text_descriptors import prepare_public_text_generation, require_unchanged_recomputation
from retrieval_semantic_primitives import AcceptedEvidenceRecord, AcceptedNodeRecord
from retrieval_semantic_provenance import AcceptedStoreReadback, verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

KEY = "python.function:pkg.alpha:boundary_fn"
CANARY = "CANARY-PRIVATE-HOME-7731"
EXCERPT = b"line 080: BOUNDARY_START_TOKEN\nline 081: BOUNDARY_END_TOKEN\n"
MODEL_TEXT = (
    b'{"v":"canonical-node-public-text-v2","canonical_key":"python.function:pkg.alpha:boundary_fn",'
    b'"kind":"Function","display_name":"boundary_fn","source_relative_path":"pkg/alpha.py",'
    b'"excerpt":"line 080: BOUNDARY_START_TOKEN\\nline 081: BOUNDARY_END_TOKEN\\n"}'
)


def _fixture(tmp_path: Path, *, store: Any = None, policy_change: dict[str, Any] | None = None):
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    if store is not None:
        inputs = replace(inputs, store=store(inputs.store))
    if policy_change:
        policy = replace(policy, **policy_change).validate()
    receipt = inputs.receipt
    publication = make_w5_accepted_pub_mapping(receipt, run_id=1, generation=1)
    cell = InMemoryStoreReadbackCell(AcceptedStoreReadback("mixed-v1", "repo1:mixed-v1", "sqlite", publication, receipt, inputs))
    pin = verify_publication_provenance_from_adapter(cell, policy=policy)
    core = min(policy.bindings)
    snapshot = dict((b, s) for b, _r, s in pin.snapshot_vector)[core]
    meta = {"binding_id": core, "snapshot_id": snapshot, "source_relative_path": "pkg/alpha.py"}
    node = AcceptedNodeRecord(KEY, "Function", "boundary_fn", 1, 1)
    evidence = AcceptedEvidenceRecord(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by")
    rows = [SpanRow(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by", 80, 81)]
    return inputs, policy, cell, pin, node, evidence, rows


def _prepare(fixture: tuple[Any, ...], scope: PrivateMarkerScope, **overrides: Any):
    inputs, policy, cell, pin, node, evidence, rows = fixture
    kwargs: dict[str, Any] = {
        "publication_pin": pin, "readback_adapter": cell, "policy": policy, "scope": scope,
        "read_representations": lambda: validate_canonical_node_representations(
            pin, accepted_nodes=(node,), accepted_evidence=(evidence,)),
        "read_v1_evidence": lambda: (evidence,), "read_span_rows": lambda: tuple(rows),
    }
    kwargs.update(overrides)
    return prepare_public_text_generation(**kwargs)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_usable_path_builds_an_exact_descriptor_and_private_model_text(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    inputs, _policy, _cell, pin, _node, _evidence, _rows = fixture
    scope = PrivateMarkerScope.create((CANARY,))
    prepared = _prepare(fixture, scope)
    assert len(prepared.documents) == 1 and prepared.exclusions == ()
    document = prepared.documents[0]
    entry = next(e for e in inputs.manifest.entries if e.source_relative_path == "pkg/alpha.py")
    raw = inputs.store.read(entry.reference)
    start = raw.index(EXCERPT)
    descriptor = document.descriptor.to_dict()
    assert document.model_text.encode("utf-8") == MODEL_TEXT
    assert descriptor["input_digest"] == _sha(MODEL_TEXT) and descriptor["model_text_bytes"] == len(MODEL_TEXT)
    assert (descriptor["span_start_byte"], descriptor["span_end_byte"]) == (start, start + len(EXCERPT))
    assert descriptor["excerpt_digest"] == _sha(EXCERPT) and descriptor["excerpt_bytes"] == len(EXCERPT)
    assert descriptor["artifact_content_digest"] == _sha(raw) and descriptor["artifact_size_bytes"] == len(raw)
    assert descriptor["accepted_reference"] == inputs.accepted_reference.to_dict()
    assert descriptor["privacy_scope_id"] == scope.scope_id and descriptor["candidate_id"] == pin.graph_candidate_id
    public = json.dumps(prepared.to_dict(), sort_keys=True)
    for private in ("BOUNDARY_START_TOKEN", "CANARY_PRIVATE_BODY", CANARY):
        assert private not in public and private not in repr(prepared) and private not in repr(document)
    measured = prepared.measurements
    assert measured["excerpt_ledger"]["verified_object_bytes"] == len(raw)
    assert measured["excerpt_ledger"]["selected_excerpt_bytes"] == len(EXCERPT)
    assert measured["excerpt_reads"]["read"]["source_payload_bytes"] == len(raw)
    assert measured["excerpt_reads"]["read"]["attempts"] == 1
    sizes = sum(e.reference.size_bytes for e in inputs.manifest.entries if e.source_relative_path.startswith("pkg/"))
    assert measured["projection"]["read"]["source_payload_bytes"] == sizes
    assert measured["correspondence"]["read"]["source_payload_bytes"] == 0


@pytest.mark.parametrize("name", [
    "boundary\u0085fn", "postgres" + "://user:" + "PUBLIC_TEST_VALUE" + "@db.invalid", "-----BEGIN PRIVATE KEY-----",
])
def test_descriptor_incompatible_metadata_excludes_before_projection(tmp_path: Path, name: str) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[4] = replace(fixture[4], display_name=name)
    prepared = _prepare(tuple(fixture), PrivateMarkerScope.create((CANARY,)))
    assert prepared.documents == () and not prepared.projection_invoked
    assert [item.reason for item in prepared.exclusions] == [METADATA_PRIVACY_REFUSED]
    assert prepared.measurements["projection"] is None and prepared.measurements["excerpt_reads"] is None


def test_fresh_recomputation_reproduces_and_detects_changed_exclusions(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    scope = PrivateMarkerScope.create((CANARY,))
    first = _prepare(fixture, scope)
    second = _prepare(fixture, scope)
    require_unchanged_recomputation(first, second, scope=scope)
    assert second.measurements["excerpt_reads"]["read"]["attempts"] == 1
    other = PrivateMarkerScope.create((CANARY,))
    with pytest.raises(PublicTextRefusal) as wrong_scope:
        require_unchanged_recomputation(first, _prepare(fixture, other), scope=scope)
    assert wrong_scope.value.code == PRIVATE_MARKER_SCOPE_INVALID
    fixture[6][0] = replace(fixture[6][0], end_line=80)
    drifted = _prepare(fixture, scope)
    with pytest.raises(PublicTextRefusal) as changed:
        require_unchanged_recomputation(first, drifted, scope=scope)
    assert changed.value.code == DESCRIPTOR_SET_CHANGED


def test_sql_span_drift_inside_the_file_refuses_before_the_raw_reread(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture[6][0] = replace(fixture[6][0], start_line=81, end_line=81)
    prepared = _prepare(fixture, PrivateMarkerScope.create((CANARY,)))
    assert prepared.documents == () and [e.reason for e in prepared.exclusions] == [SPAN_LINK_MISMATCH]
    assert prepared.measurements["excerpt_reads"]["read"]["attempts"] == 0


@pytest.mark.parametrize("mutate", ["extra", "missing", "duplicate", "metadata", "path"])
def test_span_row_correspondence_refuses_the_whole_preparation(tmp_path: Path, mutate: str) -> None:
    fixture = _fixture(tmp_path)
    rows = fixture[6]
    if mutate == "extra":
        rows.append(replace(rows[0], link_kind="observed"))
    elif mutate == "missing":
        rows.clear()
    elif mutate == "duplicate":
        rows.append(rows[0])
    elif mutate == "metadata":
        rows[0] = replace(rows[0], metadata_json={**rows[0].metadata_json, "source_relative_path": "pkg/beta.py"})
    else:
        rows[0] = replace(rows[0], path="core/pkg/beta.py")
    with pytest.raises(PublicTextRefusal) as error:
        _prepare(fixture, PrivateMarkerScope.create((CANARY,)))
    assert error.value.code == SPAN_CORRESPONDENCE_REFUSED


class _PrefixOnSecondSourceRead:
    def __init__(self, inner: Any) -> None:
        self.inner, self.seen = inner, 0

    def read(self, reference: Any, max_bytes: int | None = None) -> bytes:
        data = self.inner.read(reference, max_bytes)
        if reference.media_type == "text/x-python" and reference.size_bytes > 100:
            self.seen += 1
            if self.seen == 2:
                return data[:-1]
        return data

    def get(self, reference: Any, max_bytes: int | None = None) -> bytes:
        return self.read(reference, max_bytes)

    def verify(self, reference: Any, max_bytes: int | None = None) -> bool:
        return self.inner.verify(reference, max_bytes)

    def open_stream(self, reference: Any, max_bytes: int | None = None) -> Any:
        return self.inner.open_stream(reference, max_bytes)


def test_prefix_returning_store_is_not_complete_object_verification(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, store=_PrefixOnSecondSourceRead)
    prepared = _prepare(fixture, PrivateMarkerScope.create((CANARY,)))
    assert prepared.documents == ()
    assert [e.reason for e in prepared.exclusions] == [ARTIFACT_INTEGRITY_REFUSED]
    ledger = prepared.measurements["excerpt_ledger"]
    assert (ledger["integrity_refused"], ledger["verified_objects"], ledger["verified_object_bytes"]) == (1, 0, 0)


def test_privacy_markers_refuse_metadata_before_body_and_excerpts_without_redaction(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    metadata = _prepare(fixture, PrivateMarkerScope.create(("boundary_fn",)))
    assert [e.reason for e in metadata.exclusions] == [METADATA_PRIVACY_REFUSED]
    assert metadata.projection_invoked is False and metadata.measurements["projection"] is None
    excerpt = _prepare(fixture, PrivateMarkerScope.create(("BOUNDARY_END_TOKEN",)))
    assert [e.reason for e in excerpt.exclusions] == [EXCERPT_PRIVACY_REFUSED] and excerpt.documents == ()


def test_body_policy_denial_and_truncation_are_content_blind_pair_exclusions(tmp_path: Path) -> None:
    _probe, policy = build_fixture_projection(spool_dir=tmp_path / "probe")
    core = min(policy.bindings)
    denied = {**policy.bindings, core: replace(policy.bindings[core], original_evidence_retention="metadata-only")}
    prepared = _prepare(_fixture(tmp_path, policy_change={"bindings": denied}), PrivateMarkerScope.create((CANARY,)))
    assert [e.reason for e in prepared.exclusions] == ["public_text_body_policy_denied:retention_not_authorized"]
    assert prepared.projection_invoked is False
    truncated = _prepare(_fixture(tmp_path, policy_change={"max_projected_file_bytes": 64}), PrivateMarkerScope.create((CANARY,)))
    assert [e.reason for e in truncated.exclusions] == [PROJECTION_TRUNCATED]
    assert truncated.measurements["excerpt_reads"]["read"]["attempts"] == 0


def test_aggregate_budget_on_a_selected_file_stops_the_attempt(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, policy_change={"max_projected_files": 1})
    _inputs, _policy, _cell, pin, node, evidence, rows = fixture
    beta = "python.function:pkg.beta:helper"
    meta = {**dict(evidence.metadata_json), "source_relative_path": "pkg/beta.py"}
    beta_node = AcceptedNodeRecord(beta, "Function", "helper", 1, 1)
    beta_evidence = AcceptedEvidenceRecord(beta, "ev1:beta1", 1, 1, "core/pkg/beta.py", meta, "defined_by")
    beta_row = SpanRow(beta, "ev1:beta1", 1, 1, "core/pkg/beta.py", meta, "defined_by", 1, 1)
    with pytest.raises(PublicTextRefusal) as error:
        _prepare(
            fixture, PrivateMarkerScope.create((CANARY,)),
            read_representations=lambda: validate_canonical_node_representations(
                pin, accepted_nodes=(node, beta_node), accepted_evidence=(evidence, beta_evidence)),
            read_v1_evidence=lambda: (evidence, beta_evidence), read_span_rows=lambda: (rows[0], beta_row),
        )
    assert error.value.code == AGGREGATE_BUDGET_EXCEEDED


@pytest.mark.parametrize("error", [ValueError("x"), TypeError("x"), PublicTextRefusal(PUBLICATION_MISMATCH)])
def test_descriptor_construction_failure_refuses_the_whole_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception,
) -> None:
    def explode(_values: Any) -> Any:
        raise error

    monkeypatch.setattr(descriptors_module, "PublicTextDescriptor", explode)
    with pytest.raises(PublicTextRefusal) as refused:
        _prepare(_fixture(tmp_path), PrivateMarkerScope.create((CANARY,)))
    expected = error.code if isinstance(error, PublicTextRefusal) else DESCRIPTOR_CONSTRUCTION_REFUSED
    assert refused.value.code == expected


class _ObjectReads:
    """Read #1 is the maintained projection pass; read #2 is the explicit excerpt reread."""

    def __init__(self, inner: Any, digest: str, action: str) -> None:
        self.inner, self.digest, self.action, self.reads = inner, digest, action, 0
        self.on_advance: Callable[[], None] | None = None

    def read(self, reference: Any, max_bytes: int | None = None) -> bytes:
        data = self.inner.read(reference, max_bytes)
        if reference.content_digest == self.digest:
            self.reads += 1
            if self.reads == 1 and self.action == "advance":
                assert self.on_advance is not None
                self.on_advance()
            if self.reads == 2 and self.action == "flip":
                return bytes([data[0] ^ 0x01]) + data[1:]
        return data

    def get(self, reference: Any, max_bytes: int | None = None) -> bytes:
        return self.read(reference, max_bytes)

    def verify(self, reference: Any, max_bytes: int | None = None) -> bool:
        return self.inner.verify(reference, max_bytes)

    def open_stream(self, reference: Any, max_bytes: int | None = None) -> Any:
        return self.inner.open_stream(reference, max_bytes)


def _object_read_fixture(tmp_path: Path, action: str):
    probe, _policy = build_fixture_projection(spool_dir=tmp_path / "probe")
    alpha = next(e for e in probe.manifest.entries if e.source_relative_path == "pkg/alpha.py").reference.content_digest
    holder: list[_ObjectReads] = []

    def wrap(inner: Any) -> _ObjectReads:
        holder.append(_ObjectReads(inner, alpha, action))
        return holder[0]

    fixture = _fixture(tmp_path, store=wrap)
    holder[0].on_advance = fixture[2].advance
    return fixture, holder[0]


def test_publication_advance_between_two_verified_object_reads_refuses_the_whole_preparation(tmp_path: Path) -> None:
    fixture, store = _object_read_fixture(tmp_path, "advance")
    with pytest.raises(PublicTextRefusal) as error:
        _prepare(fixture, PrivateMarkerScope.create((CANARY,)))
    assert error.value.code == PUBLICATION_REVALIDATION_FAILED
    assert store.reads == 1  # the explicit excerpt reread never happens


def test_object_bytes_changed_between_reads_refuse_that_group_as_integrity(tmp_path: Path) -> None:
    fixture, store = _object_read_fixture(tmp_path, "flip")
    prepared = _prepare(fixture, PrivateMarkerScope.create((CANARY,)))
    assert [(e.canonical_key, e.reason) for e in prepared.exclusions] == [(KEY, ARTIFACT_INTEGRITY_REFUSED)]
    assert prepared.documents == () and store.reads == 2
    ledger = prepared.measurements["excerpt_ledger"]
    assert (ledger["attempts"], ledger["integrity_refused"], ledger["verified_objects"]) == (1, 1, 0)


def test_publication_advance_and_missing_projection_inputs_refuse(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    scope = PrivateMarkerScope.create((CANARY,))
    cell = fixture[2]
    original = cell.current
    cell.current = replace(original, projection_inputs=None)
    with pytest.raises(PublicTextRefusal) as unavailable:
        _prepare(fixture, scope)
    assert unavailable.value.code == PROJECTION_INPUTS_UNAVAILABLE
    cell.current = original
    cell.advance()
    with pytest.raises(PublicTextRefusal) as advanced:
        _prepare(fixture, scope)
    assert advanced.value.code == PUBLICATION_REVALIDATION_FAILED


@pytest.mark.parametrize("reader,code", [
    ("readback_adapter", "public_text_publication_mismatch"),
    ("read_representations", "public_text_representation_readback_refused"),
])
def test_external_reader_runtime_error_refuses_whole_preparation(tmp_path: Path, reader: str, code: str) -> None:
    fixture = _fixture(tmp_path)
    scope = PrivateMarkerScope.create((CANARY,))
    def unavailable() -> Any:
        raise RuntimeError(CANARY)
    with pytest.raises(PublicTextRefusal) as error:
        _prepare(fixture, scope, **{reader: unavailable})
    assert error.value.code == code
    assert CANARY not in str(error.value)


@pytest.mark.parametrize("name", ["read_span_rows", "read_v1_evidence"])
def test_failing_span_or_evidence_iterators_close_inside_the_read_wrapper(tmp_path: Path, name: str) -> None:
    """F1-F2: a generator failure is consumed inside the closed wrapper; the message never escapes."""
    fixture = _fixture(tmp_path)

    def failing() -> Any:
        yield fixture[6][0]
        raise LookupError(CANARY)

    with pytest.raises(PublicTextRefusal) as error:
        _prepare(fixture, PrivateMarkerScope.create((CANARY,)), **{name: failing})
    assert error.value.code == SPAN_CORRESPONDENCE_REFUSED and CANARY not in str(error.value)
    assert error.value.__cause__ is None
