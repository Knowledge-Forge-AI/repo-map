"""Real temporary-file ownership across nested report delivery failures."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.resource_reports import _delivery as delivery
from repomap_test_support.resource_report_cli_files import private_directory, report_leftovers


def _temporary_fds(monkeypatch: pytest.MonkeyPatch) -> set[int]:
    owned: set[int] = set()
    real_open = os.open

    def open_file(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if str(path).startswith(".cloe-resource-report-"):
            owned.add(descriptor)
        return descriptor

    monkeypatch.setattr(delivery.os, "open", open_file)
    return owned


def _interrupt_writes(
    monkeypatch: pytest.MonkeyPatch, owned: set[int], primary: BaseException,
) -> None:
    real_write = os.write

    def write(descriptor: int, data: Any) -> int:
        if descriptor in owned:
            raise primary
        return real_write(descriptor, data)

    monkeypatch.setattr(delivery.os, "write", write)


@pytest.mark.parametrize("primary_is_interrupt", (False, True))
def test_temporary_close_preserves_an_original_interrupt_and_honors_a_fresh_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary_is_interrupt: bool,
) -> None:
    reports = private_directory(tmp_path / "reports")
    destination = delivery.admit_destination(str(reports / "report.json"))
    owned = _temporary_fds(monkeypatch)
    primary = KeyboardInterrupt() if primary_is_interrupt else OSError(errno.EIO, "write")
    secondary = SystemExit(17)
    _interrupt_writes(monkeypatch, owned, primary)
    real_close = os.close

    def close(descriptor: int) -> None:
        real_close(descriptor)
        if descriptor in owned:
            owned.remove(descriptor)
            raise secondary

    monkeypatch.setattr(delivery.os, "close", close)
    try:
        with pytest.raises(BaseException) as raised:
            delivery.deliver(destination, b"bounded\n")
        assert raised.value is (primary if primary_is_interrupt else secondary)
        assert not (reports / "report.json").exists() and report_leftovers(reports) == []
        assert owned == set()
    finally:
        destination.close()


def test_an_original_write_interrupt_survives_a_temporary_unlink_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports = private_directory(tmp_path / "reports")
    destination = delivery.admit_destination(str(reports / "report.json"))
    owned = _temporary_fds(monkeypatch)
    primary = KeyboardInterrupt()
    _interrupt_writes(monkeypatch, owned, primary)
    real_unlink = os.unlink

    def unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        real_unlink(path, *args, **kwargs)
        if str(path).startswith(".cloe-resource-report-"):
            raise SystemExit(23)

    monkeypatch.setattr(delivery.os, "unlink", unlink)
    try:
        with pytest.raises(BaseException) as raised:
            delivery.deliver(destination, b"bounded\n")
        assert raised.value is primary
        assert not (reports / "report.json").exists() and report_leftovers(reports) == []
    finally:
        destination.close()


def test_synced_temporary_close_failure_refuses_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports = private_directory(tmp_path / "reports")
    destination = delivery.admit_destination(str(reports / "report.json"))
    owned = _temporary_fds(monkeypatch)
    real_close = os.close

    def close(descriptor: int) -> None:
        real_close(descriptor)
        if descriptor in owned:
            owned.remove(descriptor)
            raise OSError(errno.EIO, "close")

    monkeypatch.setattr(delivery.os, "close", close)
    try:
        with pytest.raises(delivery.DeliveryError) as raised:
            delivery.deliver(destination, b"complete\n")
        assert (raised.value.category, raised.value.installed) == ("file_close_failed", False)
        assert not (reports / "report.json").exists() and report_leftovers(reports) == []
        assert owned == set()
    finally:
        destination.close()
