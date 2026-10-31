"""Integration contracts for Order 3: artifact store streaming, filesystem/memory stores, references, canonical JSON, manifests, and conformance."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.artifacts._canonical import (
    CanonicalEncodingError,
    canonical_json,
    decode_canonical_json,
)
from common_lore_index.artifacts._manifest_records import (
    ArtifactLimits,
    ManifestArtifact,
    ManifestBinding,
    _binding_from_mapping,
    _entry_from_mapping,
)
from common_lore_index.artifacts._store_common import (
    _chunks,
    _materialize,
    _max_bytes,
    _validate_requested_digest,
)
from common_lore_index.artifacts._store_filesystem import _private_details
from common_lore_index.artifacts.conformance import (
    ArtifactExtractionConformanceAdapter,
    ConformanceRequest,
)
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.references import ArtifactLocator, ArtifactReference
from common_lore_index.artifacts.store import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
    InMemoryArtifactStore,
)
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


def test_verifying_artifact_stream_and_filesystem_store_contracts(tmp_path: Path) -> None:
    """FileSystemArtifactStore and VerifyingArtifactStream enforce bounds, EOF verification, and file safety."""
    tmp_path.chmod(0o700)
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)

    # Put via iterable of bytes
    ref = store.put(
        [b"", b"line1\n", b"line2\n"],
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.PUBLIC,
    )

    # Stream read(0), readinto, read(-1), repeated EOF read(-1), verify_complete
    with store.open_stream(ref) as s1_raw:
        s1: Any = s1_raw
        assert s1.read(0) == b""
        buf = bytearray(6)
        n = s1.readinto(buf)
        assert n == 6 and bytes(buf) == b"line1\n"
        rest = s1.read(-1)
        assert rest == b"line2\n"
        assert s1.read(-1) == b""
        s1.verify_complete()

    # Stream iteration (__next__) and verify_complete from unverified state
    with store.open_stream(ref) as s2:
        lines = list(s2)
        assert lines == [b"line1\n", b"line2\n"]
    with store.open_stream(ref) as s3_raw:
        s3: Any = s3_raw
        s3.verify_complete()

    # Early exit from context manager without full verification raises
    with pytest.raises(ArtifactIntegrityError, match="artifact stream verification incomplete"):
        with store.open_stream(ref) as s_early:
            _ = s_early.read(2)

    # Operations on closed stream
    s_closed: Any = store.open_stream(ref)
    s_closed.close()
    s_closed.close()
    with pytest.raises(ValueError, match="I/O operation on closed file"):
        s_closed.read(1)
    with pytest.raises(ValueError, match="I/O operation on closed file"):
        s_closed.readinto(bytearray(1))
    with pytest.raises(ValueError, match="I/O operation on closed file"):
        s_closed.readline()

    # Neutral object locator accepted by FileSystemArtifactStore
    neutral_loc = ArtifactLocator("object", f"tenant-neutral/{ref.content_digest[7:]}", ref.store_version)
    neutral_ref = replace(ref, locator=neutral_loc)
    assert store.read(neutral_ref) == b"line1\nline2\n"

    bad_loc = ArtifactLocator("object", "sha256/" + "0" * 64, ref.store_version)
    with pytest.raises(ArtifactIntegrityError, match="artifact locator does not address"):
        store.read(replace(ref, locator=bad_loc))

    # Stale store_version on stream EOF
    stale_ref = replace(ref, locator=ArtifactLocator(ref.locator.kind, ref.locator.value, "fs1-0-0"))
    with pytest.raises(ArtifactIntegrityError, match="artifact store version is stale"):
        with store.open_stream(stale_ref) as s_stale:
            _ = s_stale.read(-1)

    # Corrupted object bytes on disk -> digest mismatch on stream EOF and existing target collision
    ref2 = store.put(
        b"abcdef",
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.PUBLIC,
    )
    obj_path = store.object_path(ref2)
    obj_path.chmod(0o600)
    obj_path.write_bytes(b"abcdeg")
    obj_path.chmod(0o400)
    with pytest.raises(ArtifactIntegrityError, match="artifact digest does not match reference"):
        with store.open_stream(ref2) as s_corrupt:
            _ = s_corrupt.read(-1)
    with pytest.raises(ArtifactIntegrityError, match="artifact digest does not match reference"):
        store.put(
            b"abcdef",
            media_type="application/octet-stream",
            record_format="bytes-v1",
            privacy=PrivacyClassification.PUBLIC,
        )

    # Truncated object bytes on disk -> size mismatch on stream EOF and existing target
    obj_path.chmod(0o600)
    obj_path.write_bytes(b"abc")
    obj_path.chmod(0o400)
    with pytest.raises(ArtifactIntegrityError, match="artifact size does not match reference"):
        with store.open_stream(ref2) as s_trunc:
            _ = s_trunc.read(-1)
    with pytest.raises(ArtifactIntegrityError, match="artifact size does not match reference"):
        store.put(
            b"abcdef",
            media_type="application/octet-stream",
            record_format="bytes-v1",
            privacy=PrivacyClassification.PUBLIC,
        )

    # FileSystemArtifactStore input validation errors
    with pytest.raises(ArtifactIntegrityError, match="not a regular file"):
        _private_details(store_root, owner_uid=os.getuid())
    hl_src = tmp_path / "hl_src"
    hl_dst = tmp_path / "hl_dst"
    hl_src.write_bytes(b"1")
    hl_src.chmod(0o600)
    os.link(hl_src, hl_dst)
    with pytest.raises(ArtifactIntegrityError, match="link count is unsafe"):
        _private_details(hl_src, owner_uid=os.getuid())

    with pytest.raises(ArtifactIntegrityError, match="must be bytes or iterable"):
        store.put(cast(Any, 123), media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC)
    with pytest.raises(ArtifactIntegrityError, match="must be bytes or iterable"):
        store.put(cast(Any, ["not-bytes"]), media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC)
    with pytest.raises(ArtifactIntegrityError, match="artifact bounds exceeded"):
        store.put([b"12345"], media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC, max_bytes=2)
    with pytest.raises(ArtifactIntegrityError, match="does not match supplied digest"):
        store.put(b"123", media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC, content_digest="sha256:" + "0" * 64)
    with pytest.raises(ArtifactIntegrityError, match="artifact reference is invalid"):
        store.read(cast(Any, "bad"))
    with pytest.raises(ArtifactIntegrityError, match="artifact reference is invalid"):
        store.open_stream(cast(Any, "bad"))
    with pytest.raises(ArtifactIntegrityError, match="artifact bounds exceeded"):
        store.open_stream(ref, max_bytes=2)
    with pytest.raises(ArtifactIntegrityError, match="artifact reference is invalid"):
        store.delete(cast(Any, "bad"))

    unsafe_root = tmp_path / "unsafe_store"
    unsafe_root.mkdir(mode=0o755)
    unsafe_root.chmod(0o755)
    with pytest.raises(ArtifactIntegrityError, match="store root is unsafe"):
        FileSystemArtifactStore(unsafe_root)


def test_memory_store_common_references_canonical_manifest_and_conformance() -> None:
    """InMemoryArtifactStore, _store_common, references, _canonical, manifest, and conformance contracts."""
    mem = InMemoryArtifactStore()
    ref = mem.put(b"hello", media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC)
    assert mem.get(ref) == b"hello"
    with pytest.raises(ArtifactIntegrityError, match="does not match supplied digest"):
        mem.put(b"hello", media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC, content_digest="sha256:" + "0" * 64)
    with pytest.raises(ArtifactIntegrityError, match="artifact reference is invalid"):
        mem.read(cast(Any, None))
    fs_loc = ArtifactLocator("filesystem", f"sha256/{ref.content_digest[7:9]}/{ref.content_digest[7:]}")
    with pytest.raises(ArtifactIntegrityError, match="artifact locator does not address"):
        mem.read(replace(ref, locator=fs_loc))

    # _store_common
    with pytest.raises(ValueError, match="max_bytes must be a non-negative integer"):
        _max_bytes(-1)
    with pytest.raises(TypeError, match="artifact content must be bytes"):
        list(_chunks("string"))
    with pytest.raises(TypeError, match="artifact content chunks must be bytes"):
        list(_chunks([123]))
    with pytest.raises(ArtifactIntegrityError, match="artifact bounds exceeded"):
        _materialize([b"12345"], max_bytes=2)
    with pytest.raises(ValueError, match="invalid content digest"):
        _validate_requested_digest("sha256:short")

    # references.py
    with pytest.raises(ValueError, match="invalid store version"):
        ArtifactLocator("object", "sha256/" + "a" * 64, "bad version!")
    with pytest.raises(ValueError, match="invalid locator kind"):
        ArtifactLocator("bad_kind", "sha256/" + "a" * 64)
    loc_no_ver = ArtifactLocator("object", "sha256/" + "a" * 64, None)
    assert "store_version" not in loc_no_ver.to_mapping()
    for bad_map in (cast(Any, "str"), {"kind": "object", "value": "x", "extra": 1}, {"kind": 1, "value": "x"}, {"kind": "object", "value": "sha256/" + "a" * 64, "store_version": 1}):
        with pytest.raises(ValueError, match="invalid locator"):
            ArtifactLocator.from_mapping(bad_map)
    with pytest.raises(ValueError, match="invalid content digest"):
        ArtifactReference("bad", 1, "application/octet-stream", "bytes-v1", PrivacyClassification.PUBLIC, loc_no_ver)
    with pytest.raises(ValueError, match="invalid locator"):
        ArtifactReference("sha256:" + "a" * 64, 1, "application/octet-stream", "bytes-v1", PrivacyClassification.PUBLIC, cast(Any, "bad"))
    assert ref.__lt__("not-a-ref") is NotImplemented
    assert not (ref < ref)
    with pytest.raises(ValueError, match="invalid artifact reference"):
        ArtifactReference.from_mapping(cast(Any, "not-a-map"))

    # _canonical.py
    with pytest.raises(CanonicalEncodingError, match="must end with one LF"):
        decode_canonical_json(b'{"a":1}')
    with pytest.raises(CanonicalEncodingError, match="root must be an object"):
        decode_canonical_json(b"[1]\n")
    with pytest.raises(CanonicalEncodingError, match="not canonical"):
        decode_canonical_json(b'{"a": 1}\n')
    with pytest.raises(CanonicalEncodingError, match="canonical JSON is invalid"):
        decode_canonical_json(b'{"a":1.5}\n')
    with pytest.raises(CanonicalEncodingError, match="canonical JSON is invalid"):
        decode_canonical_json(b'{"a":1,"a":2}\n')
    with pytest.raises(CanonicalEncodingError, match="floats are outside"):
        canonical_json({"a": 1.5})
    with pytest.raises(CanonicalEncodingError, match="keys must be strings"):
        canonical_json({cast(Any, 1): "a"})
    with pytest.raises(CanonicalEncodingError, match="outside the canonical domain"):
        canonical_json({"a": object()})

    # _manifest_records.py, manifest.py, conformance.py
    with pytest.raises(ValueError, match="artifact limits must be positive integers"):
        ArtifactLimits(max_artifacts=0)
    b_no_sem = ManifestBinding(
        binding_id="bind1:a",
        revision=1,
        snapshot_id="snap1:a",
        source_definition_id="src1:a",
        source_kind="local-directory",
        acquisition_method="sealed-local-copy",
        selection_policy_id="select1:a",
        ignore_policy_id="ignore1:a",
        privacy_policy="public-dev",
        role="primary",
        input_name="repo",
    )
    assert "semantic_execution" not in b_no_sem.mapping()
    assert _binding_from_mapping(b_no_sem.mapping()) == b_no_sem
    with pytest.raises(ValueError, match="artifact reference is invalid"):
        ManifestArtifact("bind1:a", "a.py", cast(Any, "bad"), executable=False)
    with pytest.raises(ValueError, match="artifact executable mode is invalid"):
        ManifestArtifact("bind1:a", "a.py", ref, executable=cast(Any, "yes"))
    with pytest.raises(ValueError, match="manifest entry is invalid"):
        _entry_from_mapping("not-a-dict")

    entry = ManifestArtifact("bind1:a", "a.py", ref, executable=False)
    manifest = PortableSnapshotManifest.create(
        graph_id="graph-nav33", bindings=(b_no_sem,), entries=(entry,),
        source_generation="sg1:" + "a" * 64, config_generation="cg1:" + "b" * 64,
        extractor_generation="eg1:v1", canonicalizer_generation="kg1:v1",
        extractor_capability_identity="cap1:v1", resolver_identity="resolver1:v1",
        canonicalizer_identity="canon1:v1", semantic_contract_identity="semantic1:v1",
        quality_rule_identity="quality1:v1",
    )
    with pytest.raises(ValueError, match="graph identity is invalid"):
        PortableSnapshotManifest.create(
            graph_id="bad graph!", bindings=(b_no_sem,), entries=(entry,),
            source_generation="sg1:" + "a" * 64, config_generation="cg1:" + "b" * 64,
            extractor_generation="eg1:v1", canonicalizer_generation="kg1:v1",
            extractor_capability_identity="cap1:v1", resolver_identity="resolver1:v1",
            canonicalizer_identity="canon1:v1", semantic_contract_identity="semantic1:v1",
            quality_rule_identity="quality1:v1",
        )
    with pytest.raises(ValueError, match="manifest byte bounds exceeded"):
        PortableSnapshotManifest.create(
            graph_id="graph-nav33", bindings=(b_no_sem,), entries=(entry,),
            source_generation="sg1:" + "a" * 64, config_generation="cg1:" + "b" * 64,
            extractor_generation="eg1:v1", canonicalizer_generation="kg1:v1",
            extractor_capability_identity="cap1:v1", resolver_identity="resolver1:v1",
            canonicalizer_identity="canon1:v1", semantic_contract_identity="semantic1:v1",
            quality_rule_identity="quality1:v1",
            limits=ArtifactLimits(max_manifest_bytes=16),
        )
    with pytest.raises(ValueError, match="unsupported snapshot manifest schema"):
        PortableSnapshotManifest.from_bytes(canonical_json({"schema_version": 2}))

    with pytest.raises(ValueError, match="conformance request is invalid"):
        ConformanceRequest("", "j1", 1, "cand1:a", manifest.manifest_id, "cap1:v1", "1.0", "producer1:p")
    req = ConformanceRequest("req1", "j1", 1, "cand1:" + "a" * 64, manifest.manifest_id, "cap1:v1", "1.0", "producer1:p")
    adapter = ArtifactExtractionConformanceAdapter(mem)
    with pytest.raises(ValueError, match="snapshot manifest identity mismatch"):
        adapter.run(
            manifest=manifest,
            request=replace(req, snapshot_manifest_id="snapmanifest1:" + "0" * 64),
            semantic_engine=lambda _f: {},
        )
    res_cancel = adapter.run(manifest=manifest, request=req, semantic_engine=lambda _f: {}, cancellation_requested=True)
    assert res_cancel.receipt.outcome == "cancelled" and res_cancel.bundle is None
