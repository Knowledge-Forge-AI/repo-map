"""Metered descriptor primitives: A2 sizing, A3 charging, cleanup and open() parity."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest

import common_lore_index.artifacts._metered_io as metered_io
from common_lore_index.artifacts._metered_io import (
    MeteredRaw,
    metered_hash,
    metered_open,
    metered_text,
    read_to_eof,
    request_length,
)
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from repomap_test_support.sealing_governance_fixtures import open_descriptor_count


def _file(tmp_path: Path, data: bytes, name: str = "body.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_request_sizes_follow_declared_bytes_then_one_budgeted_probe() -> None:
    meter = SealingMeter(SealingBudget(max_read_bytes=100), governed=True)
    assert request_length(meter, 64, 10) == 10
    assert request_length(meter, 64, 1000) == 64
    assert request_length(meter, 64, 0) == 64
    meter.admit_read(80)
    meter.charge_read("store", 80, 80)
    assert request_length(meter, 64, 0) == 20
    assert request_length(SealingMeter(None, governed=False), 64, 0) == 64


def test_read_to_eof_counts_every_call_including_the_empty_probe(tmp_path: Path) -> None:
    data = bytes(range(256)) * 10
    path = _file(tmp_path, data)
    meter = SealingMeter(None, governed=False)
    chunks: list[bytes] = []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        total = read_to_eof(meter, "capture", descriptor, chunk=1000, declared=len(data), consume=chunks.append)
    finally:
        os.close(descriptor)
    assert total == len(data) and b"".join(chunks) == data
    assert [len(item) for item in chunks] == [1000, 1000, 560]
    snapshot = meter.snapshot()
    assert snapshot.read_calls == 4 and snapshot.reader("capture") == len(data)


def test_growth_after_fstat_keeps_reading_until_eof_or_refusal(tmp_path: Path) -> None:
    path = _file(tmp_path, b"x" * 10)
    meter = SealingMeter(None, governed=False)
    seen = bytearray()
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with path.open("ab") as grower:
            grower.write(b"y" * 5)
        read_to_eof(meter, "discovery", descriptor, chunk=4, declared=10, consume=seen.extend)
    finally:
        os.close(descriptor)
    assert bytes(seen) == b"x" * 10 + b"y" * 5

    governed = SealingMeter(SealingBudget(max_read_bytes=12), governed=True)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
            read_to_eof(governed, "discovery", descriptor, chunk=4, declared=10, consume=lambda _: None)
    finally:
        os.close(descriptor)
    assert governed.snapshot().read_bytes == 12, "the probe was sized to the remaining budget"


def test_short_reads_are_charged_as_returned_and_the_request_recomputed(tmp_path: Path, monkeypatch) -> None:
    path = _file(tmp_path, b"abcdefghij")
    requests: list[int] = []
    real_read = os.read

    def short_read(descriptor: int, length: int) -> bytes:
        requests.append(length)
        return real_read(descriptor, min(length, 3))

    monkeypatch.setattr(metered_io.os, "read", short_read)
    meter = SealingMeter(SealingBudget(max_read_bytes=11), governed=True)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        read_to_eof(meter, "copy", descriptor, chunk=8, declared=10, consume=lambda _: None)
    finally:
        os.close(descriptor)
    assert requests == [8, 7, 4, 1, 1]
    assert meter.snapshot().read_bytes == 10 and meter.snapshot().read_calls == 5


def test_os_errors_charge_nothing_and_admitted_failed_opens_still_count(tmp_path: Path, monkeypatch) -> None:
    meter = SealingMeter(None, governed=False)
    with pytest.raises(FileNotFoundError):
        metered_open(meter, tmp_path / "missing", os.O_RDONLY)
    assert meter.snapshot().opens == 1

    def failing_read(descriptor: int, length: int) -> bytes:
        raise OSError(5, "input/output error")

    path = _file(tmp_path, b"abc")
    descriptor = os.open(path, os.O_RDONLY)
    monkeypatch.setattr(metered_io.os, "read", failing_read)
    try:
        with pytest.raises(OSError):
            metered_io.metered_read(meter, "copy", descriptor, 3)
    finally:
        os.close(descriptor)
    assert meter.snapshot().read_calls == 0 and meter.snapshot().read_bytes == 0


def test_metered_hash_equals_the_incumbent_digest_and_refuses_before_opening(tmp_path: Path) -> None:
    data = os.urandom(3 * 1024 * 1024 + 17)
    path = _file(tmp_path, data)
    digest = hashlib.sha256()
    meter = SealingMeter(None, governed=False)
    metered_hash(meter, "discovery", path, digest.update)
    assert digest.hexdigest() == hashlib.sha256(data).hexdigest()
    assert meter.snapshot().read_calls == 5 and meter.snapshot().opens == 1

    before = open_descriptor_count()
    tight = SealingMeter(SealingBudget(max_read_bytes=len(data) - 1), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        metered_hash(tight, "discovery", path, lambda _: None)
    assert tight.snapshot().opens == 0, "A5 refused before any open"
    assert open_descriptor_count() == before


def test_metered_hash_follows_symlinks_like_open_rb(tmp_path: Path) -> None:
    target = _file(tmp_path, b"target body")
    link = tmp_path / "link"
    link.symlink_to(target)
    digest = hashlib.sha256()
    metered_hash(SealingMeter(None, governed=False), "discovery", link, digest.update)
    assert digest.hexdigest() == hashlib.sha256(b"target body").hexdigest()


def test_raw_stream_uses_the_buffer_size_open_would_choose(tmp_path: Path) -> None:
    path = _file(tmp_path, b"line one\nline two\n")
    with open(path, "rb") as incumbent:
        expected = getattr(incumbent.raw, "_blksize")
    descriptor = os.open(path, os.O_RDONLY)
    raw = MeteredRaw(SealingMeter(None, governed=False), "classification", descriptor)
    try:
        assert raw.buffer_size == expected
        assert raw.readable() and not raw.seekable() and raw.fileno() == descriptor
        assert raw.readinto(bytearray()) == 0
    finally:
        raw.close()
    raw.close()  # idempotent
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize(
    "data",
    [
        b"#!/bin/zsh\r\nrest\n",
        b"\xef\xbb\xbfplain\rnext\n",
        "café second\n".encode(),
        b"x" * 9000 + b"\n\xff",
        b"ok\n" + b"\xff" * 3,
        b"",
    ],
)
def test_metered_text_matches_open_utf8_lines_and_decode_errors(tmp_path: Path, data: bytes) -> None:
    path = _file(tmp_path, data)

    def lines(handle: io.TextIOWrapper) -> object:
        try:
            return [handle.readline() for _ in range(3)]
        except UnicodeDecodeError as error:
            return ("error", error.start)

    with path.open(encoding="utf-8") as incumbent:
        expected = lines(incumbent)
    meter = SealingMeter(None, governed=False)
    with metered_text(meter, "classification", path) as handle:
        assert lines(handle) == expected
    assert meter.snapshot().reader("classification") <= len(data)
    assert meter.snapshot().opens == 1


def test_metered_text_closes_its_descriptor_when_the_stack_cannot_be_built(tmp_path: Path) -> None:
    before = open_descriptor_count()
    meter = SealingMeter(None, governed=False)
    with pytest.raises(IsADirectoryError):
        with metered_text(meter, "classification", tmp_path):
            pass
    assert open_descriptor_count() == before and meter.snapshot().opens == 1
