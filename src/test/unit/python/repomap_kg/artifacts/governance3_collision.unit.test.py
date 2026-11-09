from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import common_lore_index.artifacts._store_metered as metered_store
import common_lore_index.artifacts._store_stream as stream_store
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._store_common import ArtifactIntegrityError
from repomap_test_support.sealing_governance_fixtures import open_descriptor_count


def _details(path: Path, *, owner_uid: int) -> os.stat_result:
    details = path.lstat()
    assert details.st_uid == owner_uid
    return details


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _invoke(
    kind: str,
    target: Path,
    temporary: Path,
    length: int,
    digest: str,
    bound: int,
    *,
    meter: SealingMeter | None = None,
) -> str:
    if kind == "plain":
        return stream_store.compare_and_verify_collision(
            target, temporary, length, digest, bound,
            owner_uid=os.getuid(), private_details_fn=_details,
        )
    return metered_store.metered_compare_and_verify_collision(
        target,
        temporary,
        length,
        digest,
        bound,
        owner_uid=os.getuid(), private_details_fn=_details,
        meter=meter or SealingMeter(None, governed=False),
    )


@pytest.mark.parametrize("kind", ("plain", "metered"))
@pytest.mark.parametrize(
    "payload",
    (b"", b"x" * 65_536 + b"tail"),
    ids=("zero", "chunk-boundary"),
)
def test_plain_and_metered_collision_success_closes_both_descriptors(
    tmp_path: Path, kind: str, payload: bytes
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    target.write_bytes(payload)
    temporary.write_bytes(payload)
    before = open_descriptor_count()

    version = _invoke(kind, target, temporary, len(payload), _digest(payload), len(payload))

    assert version.startswith("fs-")
    assert target.read_bytes() == payload
    assert temporary.read_bytes() == payload
    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("plain", "metered"))
@pytest.mark.parametrize(
    "temporary_payload",
    (b"short", b"payload-extra"),
    ids=("short", "extra"),
)
def test_short_and_extra_temporary_bytes_are_collisions_with_closed_descriptors(
    tmp_path: Path, kind: str, temporary_payload: bytes
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    payload = b"payload"
    target.write_bytes(payload)
    temporary.write_bytes(temporary_payload)
    before = open_descriptor_count()

    with pytest.raises(ArtifactIntegrityError, match="content-address collision"):
        _invoke(kind, target, temporary, len(payload), _digest(payload), len(payload))

    assert temporary.read_bytes() == temporary_payload
    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("plain", "metered"))
def test_real_temporary_open_failure_closes_the_target_descriptor(
    tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    missing = tmp_path / "missing-temporary"
    before = open_descriptor_count()

    with pytest.raises(ArtifactIntegrityError, match="artifact read failed"):
        _invoke(kind, target, missing, 7, _digest(b"payload"), 7)

    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("plain", "metered"))
@pytest.mark.parametrize(
    ("fault", "length", "digest", "bound", "message"),
    (
        ("size", 8, _digest(b"payload"), 8, "size does not match"),
        ("digest", 7, "sha256:" + "0" * 64, 7, "digest does not match"),
        ("bound", 7, _digest(b"payload"), 6, "bounds exceeded"),
    ),
    ids=("size", "digest", "bound"),
)
def test_size_digest_and_bound_refusals_preserve_descriptor_closure(
    tmp_path: Path,
    kind: str,
    fault: str,
    length: int,
    digest: str,
    bound: int,
    message: str,
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    payload = b"payload"
    target.write_bytes(payload)
    temporary.write_bytes(payload)
    before = open_descriptor_count()

    with pytest.raises(ArtifactIntegrityError, match=message):
        _invoke(kind, target, temporary, length, digest, bound)

    assert open_descriptor_count() == before
    assert temporary.read_bytes() == payload
    assert fault in {"size", "digest", "bound"}


@pytest.mark.parametrize("kind", ("plain", "metered"))
def test_target_inode_change_after_private_details_is_refused(
    tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    payload = b"stable"
    target.write_bytes(payload)
    temporary.write_bytes(payload)
    replacement = tmp_path / "replacement"

    def details_then_replace(path: Path, *, owner_uid: int) -> os.stat_result:
        details = _details(path, owner_uid=owner_uid)
        replacement.write_bytes(payload)
        path.unlink()
        replacement.replace(path)
        return details

    before = open_descriptor_count()
    with pytest.raises(ArtifactIntegrityError, match="changed during read"):
        if kind == "plain":
            stream_store.compare_and_verify_collision(
                target,
                temporary,
                len(payload),
                _digest(payload),
                len(payload),
                owner_uid=os.getuid(),
                private_details_fn=details_then_replace,
            )
        else:
            metered_store.metered_compare_and_verify_collision(
                target,
                temporary,
                len(payload),
                _digest(payload),
                len(payload),
                owner_uid=os.getuid(),
                private_details_fn=details_then_replace,
                meter=SealingMeter(None, governed=False),
            )
    assert open_descriptor_count() == before


@pytest.mark.parametrize("kind", ("plain", "metered"))
def test_target_version_change_after_read_is_refused_and_closes_descriptors(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    payload = b"versioned"
    target.write_bytes(payload)
    temporary.write_bytes(payload)
    module = stream_store if kind == "plain" else metered_store
    real_open = module.os.open
    real_fstat = module.os.fstat
    target_fds: list[int] = []
    target_fstats = 0

    def recording_open(path, flags, *args, **kwargs):
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path) == target:
            target_fds.append(descriptor)
        return descriptor

    def mutate_on_final_stat(descriptor: int):
        nonlocal target_fstats
        details = real_fstat(descriptor)
        if target_fds and descriptor == target_fds[0]:
            target_fstats += 1
            if target_fstats == 2:
                os.utime(
                    target,
                    ns=(details.st_atime_ns, details.st_mtime_ns + 1_000_000_000),
                )
                details = real_fstat(descriptor)
        return details

    monkeypatch.setattr(module.os, "open", recording_open)
    monkeypatch.setattr(module.os, "fstat", mutate_on_final_stat)
    before = open_descriptor_count()
    with pytest.raises(ArtifactIntegrityError, match="version is stale") as raised:
        _invoke(kind, target, temporary, len(payload), _digest(payload), len(payload))
    assert raised.value.code == "artifact_stale"
    assert open_descriptor_count() == before


def test_metered_collision_handles_real_short_reads_and_zero_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    temporary = tmp_path / "temporary"
    payload = b"short-read" * 10_000
    target.write_bytes(payload)
    temporary.write_bytes(payload)
    real_read = metered_store.os.read

    def short_read(descriptor: int, length: int) -> bytes:
        return real_read(descriptor, max(1, length // 2))

    monkeypatch.setattr(metered_store.os, "read", short_read)
    before = open_descriptor_count()
    version = _invoke(
        "metered",
        target,
        temporary,
        len(payload),
        _digest(payload),
        len(payload),
        meter=SealingMeter(None, governed=False),
    )
    assert version.startswith("fs-")
    assert open_descriptor_count() == before
