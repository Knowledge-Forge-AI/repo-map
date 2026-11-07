"""Persisted receipt states and refusal custody over real descriptor-backed files."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.extractors.contracts.bounded_io import (
    BoundedIOError,
    open_directory,
    write_new_regular_file,
)
from common_lore_index.extractors.contracts.receipt_codec import (
    MAX_RECEIPT_BYTES,
    encode_receipt,
    load_receipt,
    receipt_digest,
    receipt_file_name,
    store_receipt,
)
from common_lore_index.extractors.contracts.receipt_schema import check_transition
from common_lore_index.extractors.contracts.vocabulary import ContractError
from repomap_test_support.extractor_contracts.receipt_fixtures import (
    attempt,
    canonical,
    declared_receipt,
    observed,
    receipt,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    fd = open_directory(root)
    try:
        yield fd, root
    finally:
        os.close(fd)


def _snapshot(root: Path) -> tuple[tuple[str, int, int, int, bytes | None], ...]:
    """Capture entry kind, mode, inode and bytes without following links."""

    rows = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        info = path.lstat()
        data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        rows.append((path.name, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_ino, data))
    return tuple(rows)


def _state_values() -> tuple[Any, ...]:
    partial = attempt(
        exercised=("syntax.error_tolerant",),
        achieved=("syntax.error_tolerant",),
        completeness="partial",
    )
    return (
        declared_receipt(),
        receipt(
            state="incomplete",
            observed=observed(attempts=(partial,), cleanup="incomplete", exit_status=None),
        ),
        receipt(
            state="refused",
            refusal="inadmissible_effects",
            observed=observed(admitted="refused", attempts=()),
        ),
        receipt(
            state="unavailable",
            refusal="dependency_unavailable",
            observed=observed(installed="unavailable", admitted="undeclared", attempts=(),
                              artifact_sha256=None),
        ),
        receipt(),
    )


def test_each_persisted_state_round_trips_with_external_digest_and_private_inode(
    store: tuple[int, Path],
) -> None:
    fd, root = store
    persisted: list[tuple[str, Any]] = []

    for value in _state_values():
        data = encode_receipt(value)
        digest = store_receipt(fd, value)
        path = root / receipt_file_name(digest)
        assert path.read_bytes() == data
        assert receipt_digest(data) == digest
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
        assert load_receipt(fd, digest) == value
        persisted.append((digest, value))

    before = _snapshot(root)
    with pytest.raises(BoundedIOError) as raised:
        store_receipt(fd, _state_values()[0])
    assert raised.value.code == "target_exists"
    assert _snapshot(root) == before
    assert all(load_receipt(fd, digest) == value for digest, value in persisted)


def test_valid_states_are_persisted_only_after_monotonic_transition_checks(
    store: tuple[int, Path],
) -> None:
    fd, root = store
    first = attempt()
    second = attempt("input-2")
    declared = declared_receipt()
    incomplete_one = receipt(
        state="incomplete",
        observed=observed(attempts=(first,), cleanup="unknown", exit_status=None),
    )
    incomplete_two = receipt(
        state="incomplete",
        observed=observed(
            attempts=(first, second),
            resource_events=("time_bound",),
            cleanup="unknown",
            exit_status=None,
        ),
    )
    complete = receipt(
        state="complete",
        observed=observed(
            attempts=(first, second),
            resource_events=("time_bound",),
            cleanup="proven",
            exit_status=0,
        ),
    )
    chain = (declared, incomplete_one, incomplete_two, complete)
    stored: list[tuple[str, Any]] = []

    for previous, following in zip(chain, chain[1:]):
        check_transition(previous, following)
        digest = store_receipt(fd, following)
        stored.append((digest, following))
        assert load_receipt(fd, digest) == following

    assert len(list(root.iterdir())) == len(stored)
    assert all(load_receipt(fd, digest) == value for digest, value in stored)

    before = _snapshot(root)
    rewritten = replace(complete, run_id="run-0002")
    with pytest.raises(ContractError) as raised:
        check_transition(incomplete_two, rewritten)
    assert raised.value.code == "declaration_rewritten"
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda payload: payload.update(schema="cloe-extractor-run-receipt-v2"), "unsupported_schema"),
        (lambda payload: payload.update(capability_vocabulary="cap-v2"), "unsupported_vocabulary"),
        (lambda payload: payload.update(state="declared"), "invalid_state"),
    ],
)
def test_schema_vocabulary_and_state_refusals_leave_foreign_entries_untouched(
    store: tuple[int, Path], mutate: Any, code: str,
) -> None:
    fd, root = store
    foreign = root / "foreign-marker"
    foreign.write_bytes(b"retain-me")
    payload = json.loads(encode_receipt(receipt()))
    mutate(payload)
    forged = canonical(payload)
    digest = receipt_digest(forged)
    write_new_regular_file(fd, receipt_file_name(digest), forged, max_bytes=MAX_RECEIPT_BYTES)
    before = _snapshot(root)

    with pytest.raises(ContractError) as raised:
        load_receipt(fd, digest)
    assert raised.value.code == code
    assert _snapshot(root) == before
    assert foreign.read_bytes() == b"retain-me"
