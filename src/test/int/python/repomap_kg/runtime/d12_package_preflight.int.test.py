"""CI107 regression for the exact Debian package manifest observed by D12 E1."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from common_lore_index.runtime.release_manifest import D12_CANDIDATE_PACKAGE_MANIFEST
from src.test.unit.python.tools.system.d12_system_session_fixtures import (
    _establish,
    _matching_preflight_report,
)
from tools.system.config import SystemTestError
from tools.system.d12_system_session import SYSTEM_BUILD_INTENT_FILENAME


CURRENT_LINUX_LIBC_DEV = (
    "linux-libc-dev",
    "6.12.115-2",
    "all",
    "235ba2cb2ea677f4acaf402b027e76d305342870f6d80d822d7ee9713e2f0ff5",
)
STALE_LINUX_LIBC_DEV = (
    "linux-libc-dev",
    "6.12.113-1",
    "all",
    "b2d475e01aaf0030c72bd3a0300d311f8be64aa9e82d82eae5da1a04f4010071",
)


def _linux_libc_dev_rows(report: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    manifest = report["steps"]["candidate"]["manifest"]
    return [(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in manifest["builder"]
            if row[0] == "linux-libc-dev"]


def _with_linux_libc_dev(
    report: dict[str, Any], replacement: tuple[str, str, str, str],
) -> dict[str, Any]:
    changed = deepcopy(report)
    manifest = dict(changed["steps"]["candidate"]["manifest"])
    rows: list[list[Any]] = []
    replaced = 0
    for row in manifest["builder"]:
        values = list(row)
        if values[0] == "linux-libc-dev":
            values = list(replacement)
            replaced += 1
        rows.append(values)
    assert replaced == 1, rows
    manifest["builder"] = rows
    changed["steps"] = {**changed["steps"], "candidate": {
        **changed["steps"]["candidate"], "manifest": manifest,
    }}
    return changed


def _capture(report: dict[str, Any], calls: list[dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def factory(*_args: object, **kwargs: Any) -> dict[str, Any]:
        calls.append({key: kwargs[key] for key in ("platform", "expected_source_sha256", "expected_recipe_sha256")})
        return deepcopy(report)

    return factory


def test_current_linux_libc_dev_preflight_is_accepted_without_an_application_build(tmp_path: Path) -> None:
    current = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    assert [
        (row.name, row.version, row.architecture, row.sha256)
        for row in current.builder if row.name == "linux-libc-dev"
    ] == [CURRENT_LINUX_LIBC_DEV]

    session, context = _establish(tmp_path / "accepted")
    calls: list[dict[str, Any]] = []
    try:
        report = _matching_preflight_report(context)
        accepted = session.run_same_daemon_preflight(explore_fn=_capture(report, calls))
        assert _linux_libc_dev_rows(accepted) == [CURRENT_LINUX_LIBC_DEV]
        assert calls and calls[0]["platform"] == "linux/amd64"
        assert accepted["cleanup"]["zero_build"] == {
            "managed_system_candidate_image_build_count": 0,
            "product_or_build_profile_build_count": 0,
            "unmanaged_build_count": 0,
            "unmanaged_pull_count": 0,
        }
        assert session.image_id is None and session.intent_sha256 == ""
        assert session.config.report_dir is not None
        assert not (session.config.report_dir / SYSTEM_BUILD_INTENT_FILENAME).exists()
    finally:
        session.close_lock()


@pytest.mark.parametrize("replacement", [STALE_LINUX_LIBC_DEV, (CURRENT_LINUX_LIBC_DEV[0],
                                                                  CURRENT_LINUX_LIBC_DEV[1],
                                                                  CURRENT_LINUX_LIBC_DEV[2], "f" * 64)])
def test_stale_or_tampered_linux_libc_dev_is_refused_before_build_intent(
    tmp_path: Path, replacement: tuple[str, str, str, str],
) -> None:
    session, context = _establish(tmp_path / "refused")
    try:
        report = _with_linux_libc_dev(_matching_preflight_report(context), replacement)
        with pytest.raises(SystemTestError, match="candidate manifest mismatch"):
            session.run_same_daemon_preflight(explore_fn=lambda *_a, **_k: report)
        assert session.intent_sha256 == "" and session.image_id is None
        assert session.config.report_dir is not None
        assert not (session.config.report_dir / SYSTEM_BUILD_INTENT_FILENAME).exists()
    finally:
        session.close_lock()
