"""No-network owners for the exact two-transfer AMD acquisition boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

import ci.qualification_rust_acquisition as subject


class _Response:
    def __init__(self, body: bytes, url: str) -> None:
        self._body, self._url = body, url
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read1(self, limit: int) -> bytes:
        value, self._body = self._body[:limit], self._body[limit:]
        return value


class _Opener:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, str, float]] = []

    def open(self, request: Any, *, timeout: float) -> Any:
        self.calls.append((request.full_url, request.get_method(), timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _manifest(first: bytes = b"one", second: bytes = b"two") -> dict[str, Any]:
    def wheel(name: str, body: bytes, architecture: str, state: str) -> dict[str, Any]:
        return {
            "name": name, "url": "https://files.pythonhosted.org/packages/locked/" + name,
            "architecture": architecture, "state": state, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    return {"wheels": [
        wheel("first.whl", first, "amd64", "pending"),
        wheel("second.whl", second, "amd64", "pending"),
        wheel("arm-first.whl", b"arm-1", "arm64", "held"),
        wheel("arm-second.whl", b"arm-2", "arm64", "held"),
    ]}


def test_acquisition_fetches_exactly_two_locked_urls_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    opener = _Opener([
        _Response(b"one", manifest["wheels"][0]["url"]),
        _Response(b"two", manifest["wheels"][1]["url"]),
    ])
    monkeypatch.setattr(subject, "build_opener", lambda _handler: opener)
    result = subject.acquire_exact_amd_wheels(manifest, tmp_path / "wheels")
    assert [row[0] for row in opener.calls] == [record["url"] for record in manifest["wheels"][:2]]
    assert all(row[1:] == ("GET", 30) for row in opener.calls)
    assert [item["attempts"] for item in result] == [1, 1]
    assert (tmp_path / "wheels/first.whl").read_bytes() == b"one"
    assert (tmp_path / "wheels/second.whl").read_bytes() == b"two"


def test_redirect_is_refused_before_followup_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    opener = _Opener([_Response(b"one", "https://redirect.invalid/first.whl")])
    monkeypatch.setattr(subject, "build_opener", lambda _handler: opener)
    with pytest.raises(subject.AcquisitionError) as raised:
        subject.acquire_exact_amd_wheels(manifest, tmp_path / "wheels")
    assert raised.value.code == "redirect_refused"
    assert raised.value.attempted is True
    assert raised.value.completed == ()
    assert len(opener.calls) == 1
    assert not (tmp_path / "wheels/first.whl").exists()


def test_partial_failure_retains_first_receipt_and_does_not_retry_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    opener = _Opener([
        _Response(b"one", manifest["wheels"][0]["url"]),
        URLError("offline"),
    ])
    monkeypatch.setattr(subject, "build_opener", lambda _handler: opener)
    with pytest.raises(subject.AcquisitionError) as raised:
        subject.acquire_exact_amd_wheels(manifest, tmp_path / "wheels")
    assert raised.value.code == "wheel_fetch_failed"
    assert raised.value.attempted is True
    assert tuple(item["name"] for item in raised.value.completed) == ("first.whl",)
    assert len(opener.calls) == 2
    assert (tmp_path / "wheels/first.whl").read_bytes() == b"one"
    assert not (tmp_path / "wheels/second.whl").exists()


def test_expiry_retains_completed_transfer_and_never_opens_second_url(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import qualification_rust_shape as contracts
    clock = [0.0]
    monkeypatch.setattr(contracts.time, "monotonic", lambda: clock[0])
    manifest = _manifest()
    class Expiring(_Response):
        def __exit__(self, *_args: object) -> None:
            clock[0] = 10.0
    opener = _Opener([Expiring(b"one", manifest["wheels"][0]["url"])])
    monkeypatch.setattr(subject, "build_opener", lambda _handler: opener)
    with pytest.raises(subject.AcquisitionError) as refused:
        subject.acquire_exact_amd_wheels(manifest, tmp_path / "wheels", work_deadline=10.0)
    assert refused.value.code == "internal_deadline_exceeded"
    assert tuple(row["name"] for row in refused.value.completed) == ("first.whl",)
    assert len(opener.calls) == 1 and opener.calls[0][2] == 10.0
    assert not (tmp_path / "wheels/second.whl").exists()


def test_expiry_between_chunks_stops_without_a_retry(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import qualification_rust_shape as contracts
    clock = [0.0]
    monkeypatch.setattr(contracts.time, "monotonic", lambda: clock[0])
    manifest = _manifest()
    reads = []
    class Expiring(_Response):
        def read1(self, limit: int) -> bytes:
            reads.append(limit)
            clock[0] = 10.0
            return b"o"
    opener = _Opener([Expiring(b"one", manifest["wheels"][0]["url"])])
    monkeypatch.setattr(subject, "build_opener", lambda _handler: opener)
    with pytest.raises(subject.AcquisitionError) as refused:
        subject.acquire_exact_amd_wheels(manifest, tmp_path / "wheels", work_deadline=10.0)
    assert refused.value.code == "internal_deadline_exceeded"
    assert refused.value.completed == () and len(reads) == 1 and len(opener.calls) == 1
