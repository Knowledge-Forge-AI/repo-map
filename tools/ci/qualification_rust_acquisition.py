"""No-redirect, no-retry, exactly-two AMD wheel transfers."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ci.qualification_rust_shape import require_work_deadline
from common_lore_index.extractors.contracts.vocabulary import ContractError


class AcquisitionError(RuntimeError):
    def __init__(self, code: str, *, completed: tuple[dict[str, Any], ...] = (),
                 attempted: bool = False) -> None:
        super().__init__(code)
        self.code, self.completed, self.attempted = code, completed, attempted


class _NoRedirect(HTTPRedirectHandler):
    def http_error_301(self, req: Request, fp: Any, code: int, msg: str, headers: Any) -> Any:
        raise AcquisitionError("redirect_refused", attempted=True)

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


def _checkpoint(deadline: float | None, completed: list[dict[str, Any]], *, attempted: bool) -> None:
    try:
        require_work_deadline(deadline)
    except ContractError as error:
        raise AcquisitionError(error.code, completed=tuple(completed), attempted=attempted) from None


def acquire_exact_amd_wheels(manifest: dict[str, Any], destination: Path, *,
                             work_deadline: float | None = None) -> tuple[dict[str, Any], ...]:
    records = [record for record in manifest["wheels"] if record["architecture"] == "amd64"]
    if len(records) != 2 or any(record["state"] != "pending" for record in records):
        raise AcquisitionError("amd_wheel_budget")
    if any(record["architecture"] == "arm64" and record["state"] == "pending"
           for record in manifest["wheels"]):
        raise AcquisitionError("arm_transfer_forbidden")
    _checkpoint(work_deadline, [], attempted=False)
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError:
        raise AcquisitionError("wheel_destination") from None
    opener = build_opener(_NoRedirect())
    completed: list[dict[str, Any]] = []
    for record in records:
        _checkpoint(work_deadline, completed, attempted=False)
        name, url = record["name"], record["url"]
        size, expected = record["bytes"], record["sha256"]
        timeout = 30.0 if work_deadline is None else min(30.0, work_deadline - time.monotonic())
        if timeout <= 0:
            raise AcquisitionError("internal_deadline_exceeded", completed=tuple(completed), attempted=False)
        try:
            with opener.open(Request(url, method="GET"), timeout=timeout) as response:
                if response.geturl() != url:
                    raise AcquisitionError("redirect_refused", completed=tuple(completed), attempted=True)
                body = bytearray()
                while len(body) <= size:
                    _checkpoint(work_deadline, completed, attempted=True)
                    chunk = response.read1(min(65536, size + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                if len(body) > size:
                    raise AcquisitionError("wheel_size_mismatch", completed=tuple(completed), attempted=True)
                header = response.headers.get("Content-Length")
        except AcquisitionError as error:
            raise AcquisitionError(error.code, completed=tuple(completed), attempted=True) from None
        except (HTTPError, URLError, OSError):
            raise AcquisitionError("wheel_fetch_failed", completed=tuple(completed), attempted=True) from None
        try:
            header_size = None if header is None else int(header)
        except ValueError:
            raise AcquisitionError("wheel_size_header", completed=tuple(completed), attempted=True) from None
        if len(body) != size or (header_size is not None and header_size != size):
            raise AcquisitionError("wheel_size_mismatch", completed=tuple(completed), attempted=True)
        if hashlib.sha256(body).hexdigest() != expected:
            raise AcquisitionError("wheel_digest_mismatch", completed=tuple(completed), attempted=True)
        completed.append({"name": name, "bytes": size, "sha256": expected, "attempts": 1})
        _checkpoint(work_deadline, completed, attempted=True)
        try:
            with (destination / name).open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(body)
        except OSError:
            raise AcquisitionError("wheel_write_failed", completed=tuple(completed), attempted=True) from None
    return tuple(completed)
