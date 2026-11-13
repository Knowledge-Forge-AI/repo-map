"""Iterator cleanup owns real handles and never retries an uncertain release."""
from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

from common_lore_index.storage._preparation_iterators import (
    close_preparation_iterators, own_preparation_iterator,
)


class OwnedRows:
    def __init__(self, path: Path, error: OSError | None, release_first: bool) -> None:
        self.handle = path.open("w", encoding="utf-8")
        self.error = error
        self.release_first = release_first
        self.attempts = 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> dict[str, object]:
        raise StopIteration

    def close(self) -> None:
        self.attempts += 1
        if self.release_first:
            self.handle.close()
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize("release_first", [False, True])
@pytest.mark.parametrize("preserve_primary", [False, True])
def test_every_owned_iterator_gets_one_release_attempt_after_a_close_failure(
    tmp_path: Path, release_first: bool, preserve_primary: bool,
) -> None:
    marker = OSError("synthetic iterator close refusal")
    first = OwnedRows(tmp_path / "first", marker, release_first)
    second = OwnedRows(tmp_path / "second", None, True)
    try:
        if preserve_primary:
            close_preparation_iterators((first, second), preserve_primary=True)
        else:
            with pytest.raises(OSError) as caught:
                close_preparation_iterators((first, second))
            assert caught.value is marker
        assert first.attempts == second.attempts == 1
        assert first.handle.closed is release_first
        assert second.handle.closed
    finally:
        first.handle.close()
        second.handle.close()


@pytest.mark.parametrize("release_first", [False, True])
def test_actual_body_failure_survives_an_iterator_close_failure(
    tmp_path: Path, release_first: bool,
) -> None:
    marker = RuntimeError("synthetic preparation primary")
    rows = OwnedRows(tmp_path / "owned", OSError("synthetic cleanup refusal"), release_first)
    try:
        with pytest.raises(RuntimeError) as caught:
            with own_preparation_iterator(rows):
                raise marker
        assert caught.value is marker
        assert rows.attempts == 1
        assert rows.handle.closed is release_first
    finally:
        rows.handle.close()
