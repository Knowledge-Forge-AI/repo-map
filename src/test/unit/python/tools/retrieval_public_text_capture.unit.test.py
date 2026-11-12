"""Read observation is transparent; the global projection and complete-object checks are unchanged."""

from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.artifacts._store_common import ArtifactIntegrityError, ArtifactStore
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from retrieval_public_text_capture import (
    MEASUREMENT_UNKNOWNS, ExcerptReadLedger, ReadObservationStore, capture_projection, metadata_digests,
    preflight_projection_policy, read_verified_object,
)
from retrieval_public_text_contracts import PROJECTION_POLICY_INCOMPATIBLE, PROJECTION_SETUP_REFUSED, PublicTextRefusal


class _Ref:
    def __init__(self, digest: str) -> None:
        self.content_digest = digest


class _Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.payload = b"payload"
        self.stream = io.BytesIO(b"stream")
        self.error: BaseException | None = None

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append((name, args, kwargs))
        if self.error is not None:
            raise self.error

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        self._record("read", args, kwargs)
        return self.payload

    def get(self, *args: Any, **kwargs: Any) -> bytes:
        self._record("get", args, kwargs)
        return self.payload

    def verify(self, *args: Any, **kwargs: Any) -> bool:
        self._record("verify", args, kwargs)
        return False

    def open_stream(self, *args: Any, **kwargs: Any) -> io.BytesIO:
        self._record("open_stream", args, kwargs)
        return self.stream


def test_observer_delegates_identical_arguments_results_and_exceptions() -> None:
    inner = _Recording()
    meta, source = _Ref("sha256:" + "a" * 64), _Ref("sha256:" + "b" * 64)
    observer = ReadObservationStore(inner, metadata_digests={meta.content_digest}, scope="unit")
    assert observer.read(meta, max_bytes=9) is inner.payload
    assert observer.read(source, 5) is inner.payload
    assert observer.get(reference=source) is inner.payload
    assert observer.verify(source, max_bytes=3) is False
    assert observer.open_stream(source) is inner.stream
    assert inner.calls == [
        ("read", (meta,), {"max_bytes": 9}), ("read", (source, 5), {}), ("get", (), {"reference": source}),
        ("verify", (source,), {"max_bytes": 3}), ("open_stream", (source,), {}),
    ]
    failure = ArtifactIntegrityError("bad")
    inner.error = failure
    with pytest.raises(ArtifactIntegrityError) as raised:
        observer.read(source)
    assert raised.value is failure
    with pytest.raises(ArtifactIntegrityError):
        observer.open_stream(source)
    counters = observer.counters()
    size = len(inner.payload)
    assert counters["read"] == {"attempts": 3, "returned": 2, "failed": 1, "metadata_payload_bytes": size,
                                "source_payload_bytes": size, "non_bytes_returns": 0}
    assert counters["get"]["source_payload_bytes"] == size and counters["get"]["attempts"] == 1
    assert counters["verify"] == {"attempts": 1, "returned": 1, "failed": 0, "true_results": 0, "false_results": 1}
    assert counters["open_stream"] == {"attempts": 2, "returned": 1, "failed": 1, "true_results": 0, "false_results": 0}
    assert counters["unknown"] == list(MEASUREMENT_UNKNOWNS)
    for method in (observer.put, observer.delete):
        with pytest.raises(ArtifactIntegrityError):
            method(b"x")
    assert repr(observer) == "ReadObservationStore(scope='unit')"


def test_wrapped_projection_keeps_global_membership_order_budget_and_digest(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    direct = build_captured_text_projection(inputs, policy)
    captured = capture_projection(inputs, policy)
    assert captured.projection.to_dict() == direct.to_dict()
    assert [f.source_relative_path for f in captured.projection.projected_files] == ["pkg/alpha.py", "pkg/beta.py"]
    sizes = {e.source_relative_path: e.reference.size_bytes for e in inputs.manifest.entries}
    counters = captured.counters
    assert counters["scope"] == "projection_pass"
    assert counters["read"]["source_payload_bytes"] == sizes["pkg/alpha.py"] + sizes["pkg/beta.py"]
    assert counters["read"]["metadata_payload_bytes"] > 0
    assert counters["verify"]["attempts"] == 3 and counters["open_stream"]["attempts"] == 1
    assert captured.authorized_openable_entries == 2
    assert {"verify_internal_reads", "open_stream_consumption_bytes"} <= set(counters["unknown"])
    excluded = {e.source_relative_path: e.reason.value for e in captured.projection.excluded_files}
    assert excluded == {"mailbox/secret.eml": "email_body_forbidden"}
    budgeted = replace(policy, max_projected_files=1).validate()
    assert capture_projection(inputs, budgeted).projection.to_dict() == build_captured_text_projection(inputs, budgeted).to_dict()


class _CountingStore:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.source_reads = 0

    def read(self, reference: Any, max_bytes: int | None = None) -> bytes:
        self.source_reads += 1
        return bytes(self.inner.read(reference, max_bytes))


def test_supplementally_denied_openable_body_refuses_the_whole_pass_before_reads(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    core = min(policy.bindings)
    widened = replace(policy.bindings[core], original_evidence_retention="metadata-only")
    incompatible = replace(policy, bindings={**policy.bindings, core: widened}).validate()
    counting = _CountingStore(inputs.store)
    with pytest.raises(PublicTextRefusal) as error:
        capture_projection(replace(inputs, store=cast(ArtifactStore, counting)), incompatible)
    assert error.value.code == PROJECTION_POLICY_INCOMPATIBLE and counting.source_reads == 0
    assert preflight_projection_policy(inputs, policy) == 2


def test_known_projection_setup_errors_refuse_without_fallback(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    foreign = replace(policy, graph_id="other-graph").validate()
    with pytest.raises(PublicTextRefusal) as error:
        capture_projection(inputs, foreign)
    assert error.value.code == PROJECTION_SETUP_REFUSED
    with pytest.raises(PublicTextRefusal) as missing:
        capture_projection(replace(inputs, bundle_reference=None), policy)
    assert missing.value.code == PROJECTION_SETUP_REFUSED


class _Store:
    def __init__(self, inner: Any, mode: str) -> None:
        self.inner, self.mode = inner, mode

    def read(self, reference: Any, max_bytes: int | None = None) -> Any:
        data = self.inner.read(reference, max_bytes)
        if self.mode == "prefix":
            return data[:-1]
        if self.mode == "bytearray":
            return bytearray(data)
        if self.mode == "tampered":
            return data[:-1] + b"#"
        if self.mode == "integrity":
            raise ArtifactIntegrityError("corrupt")
        if self.mode == "oserror":
            raise OSError("io")
        if self.mode == "bug":
            raise RuntimeError("programming error")
        return data


def test_excerpt_read_requires_independent_complete_object_verification(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    entry = next(e for e in inputs.manifest.entries if e.source_relative_path == "pkg/alpha.py")
    digests = metadata_digests(inputs)
    ledger = ExcerptReadLedger()
    good = read_verified_object(ReadObservationStore(_Store(inputs.store, "ok"), metadata_digests=digests, scope="x"),
                                entry, policy, ledger)
    assert good is not None and good.size_bytes == entry.reference.size_bytes
    assert good.content_digest == entry.reference.content_digest and "line 080" not in repr(good)
    for mode in ("prefix", "bytearray", "tampered", "integrity", "oserror"):
        observer = ReadObservationStore(_Store(inputs.store, mode), metadata_digests=digests, scope=mode)
        assert read_verified_object(observer, entry, policy, ledger) is None
    assert ledger.to_dict() == {
        "attempts": 6, "integrity_refused": 5, "verified_objects": 1,
        "verified_object_bytes": entry.reference.size_bytes, "selected_excerpt_bytes": 0,
    }
    with pytest.raises(RuntimeError):
        read_verified_object(ReadObservationStore(_Store(inputs.store, "bug"), metadata_digests=digests, scope="b"),
                             entry, policy, ledger)
