"""Bounded stdlib-only HTTP transport and streaming guard for immutable A/B metadata."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import http.client
import json
import math
import re
import socket
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

LIVE_API_ORIGIN, LIVE_API_HOST = "https://api.github.com", "api.github.com"
IDENTITY_BYTE_CAP, TREE_BYTE_CAP, TREE_ENTRY_CAP = 32_768, 2_097_152, 10_000
LIVE_TIMEOUT_SECONDS = 15.0
SHA1_HEX_RE, CONTENT_LENGTH_RE = re.compile(r"[0-9a-f]{40}\Z"), re.compile(r"[0-9]{1,9}\Z")
SAFE_REASON_RE, LOOPBACK_ORIGIN_RE = re.compile(r"[a-z0-9_]{1,64}\Z"), re.compile(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}\Z")
PRIVATE_TEXT_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_.-])(?:/Users/|/home/|/private/|/var/folders/|/tmp/)|"
    r"[A-Za-z]:\\|file://|(?:postgres(?:ql)?|https?)://[^\s/\"']*@|"
    r"127\.0\.0\.1|(?://|@)localhost(?::|/|\b)|-----BEGIN)",
    re.I,
)
REQUEST_HEADERS: tuple[tuple[str, str], ...] = (
    ("Accept", "application/vnd.github+json"), ("Accept-Encoding", "identity"),
    ("Connection", "close"), ("User-Agent", "repomap-retrieval-inventory-metadata/1"),
    ("X-GitHub-Api-Version", "2022-11-28"),
)


class InventoryError(ValueError):
    """Public-safe fixed diagnostic code; never interpolate paths, URLs, or payloads."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if SAFE_REASON_RE.fullmatch(reason) else "internal_refusal"
        super().__init__(self.reason)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise InventoryError(reason)


@dataclass(frozen=True)
class CandidateSpec:
    candidate: str
    repository: str
    tag: str
    ref: str
    annotated_tag_sha: str
    commit_sha: str
    tree_sha: str
    package_root: str
    origin_review_paths: tuple[str, ...]
    origin_review_concern: str

    def endpoints(self, base_url: str = LIVE_API_ORIGIN) -> dict[str, str]:
        base = f"{base_url}/repos/{self.repository}/git"
        return {
            "ref": f"{base}/ref/tags/{self.tag}", "tag": f"{base}/tags/{self.annotated_tag_sha}",
            "commit": f"{base}/commits/{self.commit_sha}", "tree": f"{base}/trees/{self.tree_sha}?recursive=1",
        }


ROSTER: dict[str, CandidateSpec] = {
    "A": CandidateSpec(
        "A", "pallets/click", "8.1.8", "refs/tags/8.1.8", "d4ecb8a89a52ad3faacf3f1c65065d08c1d11c14",
        "934813e4d421071a1b3db3973c02fe2721359a6e", "48a3e9893840b8ad002fc31b14be47a31dfd96ed", "src/click",
        ("src/click/_winconsole.py", "src/click/_compat.py", "src/click/_termui_impl.py"), "platform_helper_origin_review",
    ),
    "B": CandidateSpec(
        "B", "pypa/packaging", "25.0", "refs/tags/25.0", "28fe66ae198ec7a9a63c47e8181a103e73acd0c7",
        "f58537628042c7f29780b9d33f31597e7fc9d664", "f14f13b00345dd5193ffd7bd73f93aa31adc8da4", "src/packaging",
        ("src/packaging/licenses/_spdx.py",), "spdx_license_data_origin_review",
    ),
}


@dataclass(frozen=True)
class _TestTransportSeam:
    """Internal test-only seam for lower caps or loopback HTTP; never exposed on CLI."""

    base_url: str = LIVE_API_ORIGIN
    identity_byte_cap: int = IDENTITY_BYTE_CAP
    tree_byte_cap: int = TREE_BYTE_CAP
    tree_entry_cap: int = TREE_ENTRY_CAP
    timeout_seconds: float = LIVE_TIMEOUT_SECONDS
    open_url: Callable[[urllib.request.Request, float], Any] | None = None

    def validate(self) -> _TestTransportSeam:
        require(self.base_url == LIVE_API_ORIGIN or LOOPBACK_ORIGIN_RE.fullmatch(self.base_url) is not None, "invalid_endpoint_origin")
        require(
            type(self.identity_byte_cap) is int and 1 <= self.identity_byte_cap <= IDENTITY_BYTE_CAP
            and type(self.tree_byte_cap) is int and 1 <= self.tree_byte_cap <= TREE_BYTE_CAP
            and type(self.tree_entry_cap) is int and 0 <= self.tree_entry_cap <= TREE_ENTRY_CAP,
            "invalid_cap_configuration",
        )
        require(
            isinstance(self.timeout_seconds, (int, float)) and not isinstance(self.timeout_seconds, bool)
            and math.isfinite(self.timeout_seconds) and 0 < float(self.timeout_seconds) <= LIVE_TIMEOUT_SECONDS,
            "invalid_timeout",
        )
        return self


@dataclass
class TransportExchange:
    """Application-layer HTTPResponse.read(1) telemetry for one bounded GET exchange."""

    step: str
    canonical_endpoint: str
    method: str
    request_utc: str
    status_code: int | None = None
    bytes_requested: int = 0
    bytes_read: int = 0
    read_calls: int = 0
    max_single_read_request: int = 0
    response_closed: bool = False
    raw_sha256: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "step": self.step, "endpoint": self.canonical_endpoint, "method": self.method,
            "request_utc": self.request_utc, "status_code": self.status_code,
            "bytes_requested": self.bytes_requested, "bytes_read": self.bytes_read,
            "read_calls": self.read_calls, "max_single_read_request": self.max_single_read_request,
            "read_accounting_layer": "http_response_application_read",
            "response_closed": self.response_closed, "raw_sha256": self.raw_sha256,
        }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, req: Any, fp: Any, code: int, msg: str, headers: Any) -> Any:
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in out, "duplicate_json_key")
        out[key] = value
    return out


def _reject_nonfinite_constant(_token: str) -> Any:
    raise InventoryError("nonfinite_json_number")


def _validate_json_values(value: Any, depth: int = 0) -> None:
    require(depth <= 24, "json_depth_exceeded")
    if isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str) and len(key) <= 256 and not any(ord(c) < 32 for c in key), "malformed_json")
            _validate_json_values(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_json_values(item, depth + 1)
    elif isinstance(value, str):
        require(len(value) <= IDENTITY_BYTE_CAP and not any(ord(c) < 32 and c not in "\t\n\r" for c in value), "malformed_json")
    else:
        require(value is None or type(value) in (bool, int, float), "malformed_json")
        require(type(value) is not float or math.isfinite(value), "nonfinite_json_number")


def parse_strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite_constant)
    except InventoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise InventoryError("malformed_json") from None
    require(isinstance(parsed, dict), "invalid_json_object")
    _validate_json_values(parsed)
    return parsed


class _StreamingJsonGuard:
    """Track top-level JSON structure and enforce the tree entry cap before reading the next entry."""

    def __init__(self, *, entry_cap: int | None) -> None:
        self.entry_cap, self.key_buf = entry_cap, bytearray()
        self.stack: list[str] = []
        self.started = self.top_level_closed = self.in_string = self.escape = False
        self.expect_top_key, self.last_top_key, self.tree_entries = True, "", 0
        self.capture_key = self.pending_tree_value = self.in_tree_array = self.expect_tree_entry = False
        self.seen_top_keys: set[str] = set()

    def _finish_top_key(self) -> None:
        try:
            key = json.loads((b'"' + bytes(self.key_buf) + b'"').decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InventoryError("malformed_json") from None
        require(isinstance(key, str) and key not in self.seen_top_keys, "duplicate_json_key")
        self.seen_top_keys.add(key)
        self.last_top_key, self.capture_key, self.expect_top_key = key, False, False

    def feed(self, b: int) -> None:
        ws = b in (0x20, 0x09, 0x0A, 0x0D)
        if self.top_level_closed:
            require(ws, "malformed_json")
            return
        if not self.started:
            if not ws:
                require(b == ord("{"), "invalid_json_object")
                self.started = True
                self.stack.append("{")
            return
        if self.in_string:
            if self.escape or b == ord("\\"):
                if self.capture_key:
                    require(len(self.key_buf) < 256, "malformed_json")
                    self.key_buf.append(b)
                self.escape = not self.escape
            elif b == ord('"'):
                self.in_string = False
                if self.capture_key:
                    self._finish_top_key()
            else:
                require(b >= 0x20 and (not self.capture_key or len(self.key_buf) < 256), "malformed_json")
                if self.capture_key:
                    self.key_buf.append(b)
            return
        if ws:
            return
        depth = len(self.stack)
        require(depth <= 24, "json_depth_exceeded")
        if depth == 1:
            if self.pending_tree_value:
                require(b == ord("["), "invalid_tree_field")
                self.stack.append("[")
                self.in_tree_array, self.pending_tree_value = True, False
            elif b == ord('"'):
                self.in_string = True
                if self.expect_top_key:
                    self.capture_key = True
                    self.key_buf.clear()
            elif b == ord(":"):
                require(not self.expect_top_key, "malformed_json")
                self.pending_tree_value = self.entry_cap is not None and self.last_top_key == "tree"
            elif b == ord(","):
                self.expect_top_key, self.last_top_key = True, ""
            elif b in (ord("{"), ord("[")):
                self.stack.append(chr(b))
            elif b == ord("}"):
                self.stack.pop()
                self.top_level_closed = True
            else:
                self.expect_top_key = False
        elif depth == 2 and self.in_tree_array:
            assert self.entry_cap is not None
            if b == ord("]"):
                require(not self.expect_tree_entry, "malformed_json")
                self.in_tree_array = False
                self.stack.pop()
            elif b == ord("{") and (self.tree_entries == 0 or self.expect_tree_entry):
                require(self.tree_entries < self.entry_cap, "tree_entry_cap_exceeded")
                self.tree_entries += 1
                self.expect_tree_entry = False
                self.stack.append("{")
            elif b == ord(",") and self.tree_entries > 0 and not self.expect_tree_entry:
                require(self.tree_entries < self.entry_cap, "tree_entry_cap_exceeded")
                self.expect_tree_entry = True
            else:
                raise InventoryError("invalid_tree_entry")
        elif b == ord('"'):
            self.in_string = True
        elif b in (ord("{"), ord("[")):
            self.stack.append(chr(b))
        elif b in (ord("}"), ord("]")):
            require(self.stack[-1] == ("{" if b == ord("}") else "["), "malformed_json")
            self.stack.pop()


def _header_values(headers: Any, name: str) -> list[str]:
    if headers is None:
        return []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all) and (vals := get_all(name)):
        return [str(v) for v in vals]
    if isinstance(headers, dict):
        return [str(v) for k, v in headers.items() if k.lower() == name.lower() and v is not None]
    val = getattr(headers, "get", lambda _k: None)(name)
    return [str(val)] if val is not None else []


def _validate_response_headers(headers: Any, byte_cap: int) -> int | None:
    require(not _header_values(headers, "Location"), "redirect_refused")
    for raw_enc in _header_values(headers, "Content-Encoding"):
        require([t.strip().lower() for t in raw_enc.split(",") if t.strip()] == ["identity"], "nonidentity_encoding_refused")
    for raw_te in _header_values(headers, "Transfer-Encoding"):
        tokens = [t.strip().lower() for t in raw_te.split(",") if t.strip()]
        require(all(t in ("identity", "chunked") for t in tokens), "nonidentity_encoding_refused")
    lengths = _header_values(headers, "Content-Length")
    if not lengths:
        return None
    require(len(lengths) == 1 and CONTENT_LENGTH_RE.fullmatch(lengths[0].strip()) is not None, "invalid_content_length")
    content_length = int(lengths[0].strip())
    require(content_length <= byte_cap, "byte_cap_exceeded")
    return content_length


def read_bounded_response(
    response: Any, *, byte_cap: int, entry_cap: int | None,
    exchange: TransportExchange, deadline: float | None = None,
) -> bytes:
    """Read at most byte_cap application bytes 1 byte at a time, enforcing entry_cap before next entry."""
    content_length = _validate_response_headers(getattr(response, "headers", None), byte_cap)
    guard, buf, eof_seen = _StreamingJsonGuard(entry_cap=entry_cap), bytearray(), False
    while len(buf) < byte_cap:
        require(deadline is None or time.monotonic() <= deadline, "request_timeout")
        exchange.bytes_requested += 1
        exchange.read_calls += 1
        exchange.max_single_read_request = max(exchange.max_single_read_request, 1)
        chunk = response.read(1)
        if chunk == b"":
            eof_seen = True
            break
        require(isinstance(chunk, (bytes, bytearray)) and len(chunk) == 1, "transport_read_violation")
        buf.extend(chunk)
        exchange.bytes_read += 1
        guard.feed(chunk[0])
    require((content_length is None or len(buf) == content_length) if eof_seen else content_length == byte_cap, "incomplete_body" if eof_seen else "byte_cap_exceeded")
    require(guard.top_level_closed, "malformed_json")
    return bytes(buf)


def _map_transport_error(err: BaseException) -> InventoryError:
    cause: Any = getattr(err, "reason", None) if isinstance(err, urllib.error.URLError) else err
    if isinstance(cause, (TimeoutError, socket.timeout)):
        return InventoryError("request_timeout")
    return InventoryError("incomplete_body" if isinstance(cause, http.client.IncompleteRead) else ("http_protocol_error" if isinstance(cause, http.client.HTTPException) else "network_unavailable"))


def _close_response_safely(response: Any, exchange: TransportExchange) -> None:
    if callable(getattr(response, "close", None)):
        try:
            response.close()
        except (OSError, http.client.HTTPException):
            pass
    closed_attr, isclosed_fn = getattr(response, "closed", None), getattr(response, "isclosed", None)
    exchange.response_closed = closed_attr if isinstance(closed_attr, bool) else (bool(isclosed_fn()) if callable(isclosed_fn) else True)


def fetch_endpoint_json(
    spec: CandidateSpec, step: str, *, byte_cap: int, entry_cap: int | None,
    seam: _TestTransportSeam, telemetry: list[TransportExchange],
) -> tuple[dict[str, Any], int, str, str]:
    """Execute one bounded GET, close response on all paths, and parse strict JSON."""
    seam.validate()
    target_url, canonical_url = spec.endpoints(seam.base_url).get(step, ""), spec.endpoints(LIVE_API_ORIGIN)[step]
    parsed_url = urllib.parse.urlsplit(target_url)
    require(bool(target_url) and parsed_url.username is None and parsed_url.password is None and not parsed_url.fragment, "unauthorized_endpoint")
    require((parsed_url.scheme == "https" and parsed_url.netloc == LIVE_API_HOST) if seam.base_url == LIVE_API_ORIGIN else LOOPBACK_ORIGIN_RE.fullmatch(f"{parsed_url.scheme}://{parsed_url.netloc}") is not None, "unauthorized_endpoint")
    request_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    exchange = TransportExchange(step=step, canonical_endpoint=canonical_url, method="GET", request_utc=request_utc)
    telemetry.append(exchange)
    req = urllib.request.Request(target_url, headers=dict(REQUEST_HEADERS), method="GET")
    require(req.get_method() == "GET" and not req.has_header("Authorization"), "unauthorized_request")
    default_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
    response: Any = None
    try:
        timeout_sec, deadline = float(seam.timeout_seconds), time.monotonic() + float(seam.timeout_seconds)
        response = seam.open_url(req, timeout_sec) if seam.open_url is not None else default_opener.open(req, timeout=timeout_sec)
        status = getattr(response, "status", None) or getattr(response, "code", None) or (response.getcode() if callable(getattr(response, "getcode", None)) else None)
        code = int(status) if isinstance(status, int) else None
        exchange.status_code = code
        require(code is not None, "http_status_refused")
        assert code is not None
        require(not (300 <= code < 400), "redirect_refused")
        require(code == 200, "http_status_refused")
        require((response.geturl() if callable(getattr(response, "geturl", None)) else target_url) == target_url, "redirect_refused")
        raw = read_bounded_response(response, byte_cap=byte_cap, entry_cap=entry_cap, exchange=exchange, deadline=deadline)
    except InventoryError:
        raise
    except urllib.error.HTTPError as err:
        exchange.status_code, exchange.response_closed = err.code, True
        err.close()
        raise InventoryError("redirect_refused" if 300 <= err.code < 400 else "http_status_refused") from None
    except (TimeoutError, socket.timeout, http.client.HTTPException, urllib.error.URLError, OSError) as err:
        raise _map_transport_error(err) from None
    finally:
        if response is not None:
            _close_response_safely(response, exchange)
    raw_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    exchange.raw_sha256 = raw_sha256
    return parse_strict_json_object(raw), len(raw), raw_sha256, request_utc
