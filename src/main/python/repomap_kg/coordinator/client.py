"""Explicit synchronous client for the machine-local coordinator service."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
import socket
import stat

from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
)
from repomap_kg.coordinator.transport import validate_public_result


_MAX_FRAME_BYTES = 64 * 1024
_ERROR_CATEGORIES = frozenset({
    "frame_too_large",
    "incompatible_version",
    "internal",
    "invalid_request",
    "invalid_response",
    "response_too_large",
    "saturated",
    "unauthorized",
    "unsupported_operation",
})


class CoordinatorClientError(RuntimeError):
    """Bounded local client failure with no automatic fallback."""


class LocalCoordinatorClient:
    """Call one already-running compatible local coordinator."""

    def __init__(
        self,
        socket_path: Path,
        token_path: Path | None,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("client timeout is invalid")
        self._socket_path: Path | None = Path(socket_path)
        self._endpoint: LoopbackEndpointDescriptor | None = None
        if token_path is None or Path(token_path) == self._socket_path:
            try:
                self._endpoint = load_endpoint_descriptor(self._socket_path)
            except EndpointDescriptorError:
                raise CoordinatorClientError("unsafe_credentials") from None
            self._token = self._endpoint.auth_token
        else:
            self._token = _read_private_token(Path(token_path))
        self._timeout = timeout_seconds

    def health(self) -> Mapping[str, object]:
        return self._request("health", {})

    def submit(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._request("submit", {"request": dict(request)})

    def status(self, job_id: str) -> Mapping[str, object]:
        return self._request("status", {"job_id": job_id})

    def wait(self, job_id: str) -> Mapping[str, object]:
        return self._request("wait", {"job_id": job_id})

    def cancel(self, job_id: str) -> Mapping[str, object]:
        return self._request("cancel", {"job_id": job_id})

    def list_jobs(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {"limit": limit}
        if graph_id is not None:
            payload["graph_id"] = graph_id
        if cursor is not None:
            payload["cursor"] = cursor
        return self._request("list", payload)

    def _request(
        self, operation: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        try:
            frame = json.dumps(
                {
                    "schema_version": 1,
                    "auth_token": self._token,
                    "operation": operation,
                    "payload": dict(payload),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
        except (TypeError, ValueError, UnicodeError):
            raise CoordinatorClientError("invalid_request") from None
        if len(frame) > _MAX_FRAME_BYTES:
            raise CoordinatorClientError("invalid_request")
        try:
            if self._endpoint is not None:
                connection = socket.create_connection(
                    (self._endpoint.host, self._endpoint.port),
                    timeout=self._timeout,
                )
            else:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(self._timeout)
                connection.connect(str(self._socket_path))
            with connection:
                connection.settimeout(self._timeout)
                connection.sendall(frame)
                response_frame = connection.makefile("rb").readline(
                    _MAX_FRAME_BYTES + 2
                )
        except (OSError, TimeoutError):
            raise CoordinatorClientError("unavailable") from None
        response = _decode_response(response_frame)
        if response.get("ok") is False:
            if set(response) != {"schema_version", "ok", "error_category"}:
                raise CoordinatorClientError("invalid_response")
            category = response.get("error_category")
            if category not in _ERROR_CATEGORIES:
                raise CoordinatorClientError("invalid_response")
            raise CoordinatorClientError(str(category))
        if set(response) != {"schema_version", "ok", "result"}:
            raise CoordinatorClientError("invalid_response")
        result = response["result"]
        if (
            response["ok"] is not True
            or not isinstance(result, dict)
            or not validate_public_result(result)
        ):
            raise CoordinatorClientError("invalid_response")
        return result


def _decode_response(frame: bytes) -> dict[str, object]:
    if not frame or len(frame) > _MAX_FRAME_BYTES + 1 or not frame.endswith(b"\n"):
        raise CoordinatorClientError("invalid_response")
    try:
        value = json.loads(frame)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise CoordinatorClientError("invalid_response") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or isinstance(value.get("schema_version"), bool)
    ):
        raise CoordinatorClientError("invalid_response")
    return value


def _read_private_token(path: Path) -> str:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        raise CoordinatorClientError("unsafe_credentials")
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size <= 0
            or details.st_size > 256
        ):
            raise CoordinatorClientError("unsafe_credentials")
        token = path.read_text(encoding="utf-8")
    except CoordinatorClientError:
        raise
    except (OSError, UnicodeError):
        raise CoordinatorClientError("unsafe_credentials") from None
    if not token or token.strip() != token or len(token) > 256:
        raise CoordinatorClientError("unsafe_credentials")
    return token


__all__ = ["CoordinatorClientError", "LocalCoordinatorClient"]
