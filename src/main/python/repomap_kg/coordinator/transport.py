"""Test-owned authenticated local transport for the ASYNC2 synthetic pilot."""

from __future__ import annotations

from contextlib import AbstractContextManager
import hmac
import json
import os
from pathlib import Path
import socketserver
import stat
import sys
import threading
from typing import Any, Callable, Mapping

from repomap_kg.coordinator._transport_validation import (
    _contains_prohibited_authority,
    _valid_operation_payload,
    _valid_public_result,
    validate_public_result as validate_public_result,
)
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    reject_reparse_path,
    validate_owner_private_acl,
)


_OPERATIONS = frozenset({"submit", "status", "wait", "cancel", "health", "list"})
_REQUEST_FIELDS = frozenset(
    {"schema_version", "auth_token", "operation", "payload"}
)
_HARD_MAX_FRAME_BYTES = 1024 * 1024


class TransportError(ValueError):
    pass


class LocalRequestDispatcher:
    def __init__(
        self,
        auth_token: str,
        handlers: Mapping[str, Callable[[Mapping[str, object]], object]],
        *,
        max_in_flight: int,
    ) -> None:
        if not auth_token or set(handlers) != _OPERATIONS or max_in_flight <= 0:
            raise ValueError("transport configuration is invalid")
        self._auth_token = auth_token
        self._handlers = dict(handlers)
        self._max_in_flight = max_in_flight
        self._in_flight = 0
        self._lock = threading.Lock()

    def dispatch(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
            raise TransportError("invalid_request")
        if request["schema_version"] != 1:
            raise TransportError("incompatible_version")
        supplied_token = request["auth_token"]
        if (
            not isinstance(supplied_token, str)
            or not hmac.compare_digest(supplied_token, self._auth_token)
        ):
            raise TransportError("unauthorized")
        operation = request["operation"]
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise TransportError("unsupported_operation")
        payload = request["payload"]
        if (
            not isinstance(payload, dict)
            or _contains_prohibited_authority(payload)
            or not _valid_operation_payload(operation, payload)
        ):
            raise TransportError("invalid_request")
        with self._lock:
            if self._in_flight >= self._max_in_flight:
                raise TransportError("saturated")
            self._in_flight += 1
        try:
            result = self._handlers[operation](payload)
        finally:
            with self._lock:
                self._in_flight -= 1
        if not _valid_public_result(result):
            raise TransportError("invalid_response")
        return {"schema_version": 1, "ok": True, "result": result}


if sys.platform != "win32":
    _UNIX_SERVER_BASE = socketserver.UnixStreamServer
else:
    _UNIX_SERVER_BASE = getattr(socketserver, "UnixStreamServer", socketserver.TCPServer)


class _BoundedThreadingMixIn(socketserver.ThreadingMixIn, socketserver.BaseServer):
    daemon_threads = False
    block_on_close = True
    connection_slots: threading.BoundedSemaphore
    max_connections: int = 1
    _active_handlers: int
    _handler_lock: threading.Lock

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_handlers = 0
        self._handler_lock = threading.Lock()
        self._request_state = threading.local()

    def finish_request(self, request: Any, client_address: Any) -> None:
        self._request_state.response_ready = False
        with self._handler_lock:
            self._active_handlers += 1
        try:
            super().finish_request(request, client_address)
        finally:
            if not self._request_state.response_ready:
                with self._handler_lock:
                    self._active_handlers -= 1

    def response_ready(self) -> None:
        """Return work capacity before publishing the one completed response."""
        if not getattr(self._request_state, "response_ready", True):
            with self._handler_lock:
                self._active_handlers -= 1
                self._request_state.response_ready = True
                self.connection_slots.release()

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.connection_slots.acquire(blocking=False):
            with self._handler_lock:
                is_active = self._active_handlers >= getattr(self, "max_connections", 1)
            if is_active or not self.connection_slots.acquire(timeout=0.5):
                try:
                    request.sendall(_encode_response(_error_response("saturated")))
                finally:
                    self.shutdown_request(request)
                return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            if not getattr(self._request_state, "response_ready", False):
                self.connection_slots.release()


class _ThreadedUnixServer(_BoundedThreadingMixIn, _UNIX_SERVER_BASE):
    pass


class _ThreadedTcpServer(_BoundedThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False


class UnixSocketService(AbstractContextManager["UnixSocketService"]):
    def __init__(
        self,
        socket_path: Path,
        dispatcher: LocalRequestDispatcher,
        *,
        max_connections: int,
        max_frame_bytes: int = 64 * 1024,
    ) -> None:
        if os.name != "posix" or not hasattr(socketserver, "UnixStreamServer"):
            raise TransportError("unsupported_platform")
        if (
            max_connections <= 0
            or max_frame_bytes <= 0
            or max_frame_bytes > _HARD_MAX_FRAME_BYTES
        ):
            raise ValueError("transport configuration is invalid")
        self._path = Path(socket_path)
        _validate_socket_parent(self._path.parent)
        self._dispatcher = dispatcher
        self._max_frame = max_frame_bytes
        service = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                _handle_stream(service, self.rfile, _ResponseWriter(self.wfile, service._server.response_ready))

        self._server = _ThreadedUnixServer(str(self._path), Handler)
        self._server.connection_slots = threading.BoundedSemaphore(max_connections)
        self._server.max_connections = max_connections
        self._server.request_queue_size = max_connections
        os.chmod(self._path, 0o600)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="synthetic-coordinator-transport",
        )

    def __enter__(self) -> "UnixSocketService":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.ident is not None:
            self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("transport did not stop")
        self._path.unlink(missing_ok=True)

    @staticmethod
    def _write_error(stream, category: str) -> None:
        stream.write(_encode_response(_error_response(category)))


class LoopbackTcpService(AbstractContextManager["LoopbackTcpService"]):
    """Authenticated loopback TCP adapter used by the Windows runtime."""

    def __init__(
        self,
        endpoint_path: Path,
        dispatcher: LocalRequestDispatcher,
        *,
        auth_token: str,
        instance_id: str,
        fencing_epoch: int,
        max_connections: int,
        max_frame_bytes: int = 64 * 1024,
    ) -> None:
        if (
            max_connections <= 0
            or max_frame_bytes <= 0
            or max_frame_bytes > _HARD_MAX_FRAME_BYTES
        ):
            raise ValueError("transport configuration is invalid")
        self._path = Path(endpoint_path)
        _validate_transport_parent(self._path.parent)
        self._dispatcher = dispatcher
        self._max_frame = max_frame_bytes
        self._instance_id = instance_id
        self._fencing_epoch = fencing_epoch
        self._descriptor: LoopbackEndpointDescriptor | None = None
        service = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                _handle_stream(service, self.rfile, _ResponseWriter(self.wfile, service._server.response_ready))

        try:
            self._server = _ThreadedTcpServer(("127.0.0.1", 0), Handler)
            self._server.connection_slots = threading.BoundedSemaphore(
                max_connections
            )
            self._server.max_connections = max_connections
            self._server.request_queue_size = max_connections
            self._descriptor = LoopbackEndpointDescriptor(
                schema_version=1,
                host="127.0.0.1",
                port=int(self._server.server_address[1]),
                instance_id=instance_id,
                fencing_epoch=fencing_epoch,
                auth_token=auth_token,
            ).validate()
            write_endpoint_descriptor(self._path, self._descriptor)
        except (OSError, EndpointDescriptorError, WindowsSecurityError):
            try:
                self._server.server_close()
            except AttributeError:
                pass
            raise TransportError("endpoint_descriptor_failed") from None
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="coordinator-loopback-transport",
        )

    def __enter__(self) -> "LoopbackTcpService":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.ident is not None:
            self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("transport did not stop")
        try:
            current = load_endpoint_descriptor(
                self._path,
                expected_instance_id=self._instance_id,
                expected_fencing_epoch=self._fencing_epoch,
            )
        except EndpointDescriptorError:
            return
        if self._descriptor == current:
            self._path.unlink(missing_ok=True)

    @staticmethod
    def _write_error(stream, category: str) -> None:
        stream.write(_encode_response(_error_response(category)))


class _ResponseWriter:
    """Application work ends once a complete response is ready for delivery."""

    def __init__(self, writer: Any, ready: Callable[[], None]) -> None:
        self._writer = writer
        self._ready = ready

    def write(self, frame: bytes) -> Any:
        self._ready()
        return self._writer.write(frame)


def _handle_stream(service, reader, writer) -> None:
    try:
        frame = reader.readline(service._max_frame + 2)
        if not frame:
            return
        if len(frame) > service._max_frame + 1 or not frame.endswith(b"\n"):
            service._write_error(writer, "frame_too_large")
            return
        try:
            request = json.loads(frame)
            response = service._dispatcher.dispatch(request)
        except (json.JSONDecodeError, UnicodeDecodeError):
            service._write_error(writer, "invalid_request")
            return
        except TransportError as error:
            service._write_error(writer, str(error))
            return
        try:
            encoded = _encode_response(response)
            if len(encoded) > service._max_frame + 1:
                raise TransportError("response_too_large")
        except (TypeError, ValueError, TransportError):
            service._write_error(writer, "invalid_response")
            return
        writer.write(encoded)
    except (BrokenPipeError, ConnectionResetError):
        return
    except Exception:
        service._write_error(writer, "internal")


def _validate_transport_parent(parent: Path) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            reject_reparse_path(parent)
            details = parent.lstat()
            if not stat.S_ISDIR(details.st_mode):
                raise TransportError("unsafe_endpoint_directory")
            validate_owner_private_acl(parent)
        except (OSError, WindowsSecurityError):
            raise TransportError("unsafe_endpoint_directory") from None
        return
    _validate_socket_parent(parent)


def _encode_response(response: Mapping[str, object]) -> bytes:
    return json.dumps(response, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _error_response(category: str) -> dict[str, object]:
    return {"schema_version": 1, "ok": False, "error_category": category}


def _validate_socket_parent(parent: Path) -> None:
    details = parent.stat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise TransportError("unsafe_socket_directory")




__all__ = [
    "LocalRequestDispatcher",
    "LoopbackTcpService",
    "TransportError",
    "UnixSocketService",
    "validate_public_result",
]
