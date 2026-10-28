"""Bounded JSON report I/O and prepare-refusal state persistence for hosted D12."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
import stat as stat_mod
from typing import Any

from repomap_kg.runtime.release import GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE

VERIFIED_AMD64_BASE_METADATA: dict[str, dict[str, str]] = {
    "go": {"reference": GO_RELEASE_IMAGE, "platform": "linux/amd64",
           "index": "sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af",
           "manifest": "sha256:88750ccdd0f2a77fcc00a14b1a48d6409bd8ddb5d7c2dd6ec0b4a2e916daf9d9",
           "config": "sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe"},
    "python": {"reference": PYTHON_RELEASE_IMAGE, "platform": "linux/amd64",
               "index": "sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159",
               "manifest": "sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b",
               "config": "sha256:ae4e8b7c575fabea88a029b6cae757f342ca2525e07f7c22272d5105c346b35e"},
    "postgres": {"reference": POSTGRES_RELEASE_IMAGE, "platform": "linux/amd64",
                 "index": "sha256:1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c",
                 "manifest": "sha256:b95b87e93ceb7594715d5c71fb6e09f6fc878851ab537735d617325eb9ba8b1b",
                 "config": "sha256:74d436cb49d3398cf7b5d7b33635d43623d9e4da4b93c22db453f7d5d81181b1"},
}

MAX_SAFE_JSON_REPORT_BYTES = 8 * 1024 * 1024
PREPARE_REFUSAL_SCHEMA = "repomap-d12-prepare-refusal-v1"
PREPARE_REFUSAL_FILENAME = "prepare-refusal.json"
PREPARE_STATE_FILENAME = "prepare-state.json"
REDACTED_REFUSAL_REASON = "<redacted-prepare-refusal-reason>"

REACHED_PREPARE_KEYS = (
    "pr_binding",
    "identity_binding",
    "native_environment",
    "entry_baseline",
    "post_sdk_baseline",
    "sdk_materialization",
)


class _SanitizationError(ValueError):
    """Raised when privacy redaction yields an unusable key, collision, or invalid structure."""


def _prov(
    status: str,
    byte_length: int,
    sha256: str | None,
    redacted: bool,
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": status,
        "byte_length": byte_length,
        "sha256": sha256,
        "redacted": redacted,
    }
    if max_bytes is not None:
        out["max_bytes"] = max_bytes
    return out


def _validate_parsed_tree(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("mapping key must be a string")
            _validate_parsed_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_parsed_tree(item)


def _apply_redact(value: Any, redact_fn: Callable[[Any], Any] | None) -> Any:
    if redact_fn is None:
        return value
    direct = redact_fn(value)
    if isinstance(value, Mapping):
        if not isinstance(direct, Mapping):
            raise _SanitizationError("redacted mapping is not a mapping")
        out: dict[str, Any] = {}
        for raw_k, raw_v in direct.items():
            if not isinstance(raw_k, str) or not raw_k.strip():
                raise _SanitizationError("mapping key must be a non-empty string")
            new_k = redact_fn(raw_k)
            if not isinstance(new_k, str) or not new_k.strip():
                raise _SanitizationError("redacted mapping key must be a non-empty string")
            if new_k in out:
                raise _SanitizationError("redacted mapping key collision")
            out[new_k] = _apply_redact(raw_v, redact_fn)
        return out
    if isinstance(value, (list, tuple)):
        if not isinstance(direct, (list, tuple)):
            raise _SanitizationError("redacted sequence is not a list or tuple")
        items = [_apply_redact(item, redact_fn) for item in direct]
        return tuple(items) if isinstance(value, tuple) else items
    if value is not None and direct is None:
        raise _SanitizationError("redacted scalar value is None")
    return direct


def load_safe_json_report(
    path: Path,
    *,
    redact_fn: Callable[[Any], Any] | None = None,
    max_bytes: int = MAX_SAFE_JSON_REPORT_BYTES,
) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    """Read a JSON object report with a pre-read size cap and raw-byte provenance."""
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive: {max_bytes}")
    try:
        if path.is_symlink():
            return None, _prov("symlink", 0, None, False), f"report is a symlink: {path.name}"
        st = path.lstat()
    except FileNotFoundError:
        return None, _prov("missing", 0, None, False), f"missing canonical report: {path.name}"
    except OSError as exc:
        return None, _prov("io_error", 0, None, False), f"cannot stat report {path.name}: {exc}"

    if not stat_mod.S_ISREG(st.st_mode):
        return (
            None,
            _prov("non_regular_file", 0, None, False),
            f"non-regular report path: {path.name}",
        )

    actual_size = int(st.st_size)
    if actual_size > max_bytes:
        return (
            None,
            _prov("oversize", actual_size, None, False, max_bytes=max_bytes),
            f"report {path.name} size {actual_size} exceeds maximum {max_bytes} bytes",
        )

    try:
        with path.open("rb") as handle:
            raw_bytes = handle.read(max_bytes + 1)
    except OSError as exc:
        return None, _prov("io_error", 0, None, False), f"cannot read report {path.name}: {exc}"

    nbytes = len(raw_bytes)
    if nbytes > max_bytes:
        return (
            None,
            _prov("oversize", nbytes, None, False, max_bytes=max_bytes),
            f"report {path.name} size {nbytes} exceeds maximum {max_bytes} bytes",
        )

    digest = hashlib.sha256(raw_bytes).hexdigest()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return (
            None,
            _prov("decode_error", nbytes, digest, False),
            f"report {path.name} is not valid UTF-8: {exc}",
        )

    try:
        parsed = json.loads(raw_text)
        _validate_parsed_tree(parsed)
    except (ValueError, RecursionError) as exc:
        return (
            None,
            _prov("malformed_json", nbytes, digest, False),
            f"malformed JSON in {path.name}: {exc}",
        )

    if not isinstance(parsed, dict):
        return (
            None,
            _prov("non_mapping_root", nbytes, digest, False),
            f"report {path.name} root is not an object",
        )

    if redact_fn is not None:
        try:
            sanitized = _apply_redact(parsed, redact_fn)
            if not isinstance(sanitized, dict):
                raise _SanitizationError("redacted report root is not a JSON object")
            json.dumps(sanitized, sort_keys=True, allow_nan=False)
        except Exception as exc:
            return (
                None,
                _prov("redaction_corrupted_json", nbytes, digest, True),
                f"redacted report {path.name} failed sanitization: {type(exc).__name__}",
            )
        if sanitized != parsed:
            return (
                sanitized,
                _prov("redacted_unqualified", nbytes, digest, True),
                f"privacy redaction modified {path.name}; redacted reports cannot qualify",
            )
        return sanitized, _prov("valid", nbytes, digest, False), None

    return parsed, _prov("valid", nbytes, digest, False), None


def _sanitize_stage(stage: object, redact_fn: Callable[[Any], Any] | None) -> str:
    try:
        raw_stage = str(stage).strip()
    except Exception:
        return "unknown"
    if not raw_stage:
        return "unknown"
    if redact_fn is None:
        return raw_stage
    try:
        redacted = _apply_redact(raw_stage, redact_fn)
    except Exception:
        redacted = None
    if isinstance(redacted, str) and redacted.strip():
        return redacted
    return "unknown"


def _sanitize_reason(reason: object, redact_fn: Callable[[Any], Any] | None) -> str:
    try:
        raw_reason = str(reason)
    except Exception:
        return REDACTED_REFUSAL_REASON
    if not raw_reason.strip():
        return REDACTED_REFUSAL_REASON
    if redact_fn is None:
        return raw_reason
    try:
        redacted = _apply_redact(raw_reason, redact_fn)
    except Exception:
        return REDACTED_REFUSAL_REASON
    if isinstance(redacted, str) and redacted.strip():
        return redacted
    return REDACTED_REFUSAL_REASON


def write_prepare_refusal_state(
    state_dir: Path,
    *,
    stage: str,
    reason: str,
    reached: Mapping[str, Any] | None = None,
    redact_fn: Callable[[Any], Any] | None = None,
) -> Path:
    """Persist a fail-safe prepare-refusal record containing only reached stage facts."""
    state_dir.mkdir(parents=True, exist_ok=True)
    safe_stage = _sanitize_stage(stage, redact_fn)
    safe_reason = _sanitize_reason(reason, redact_fn)
    safe_reached: dict[str, Any] = {}
    if isinstance(reached, Mapping):
        for key in REACHED_PREPARE_KEYS:
            try:
                val = reached.get(key)
                if not isinstance(val, Mapping):
                    continue
                raw_map = dict(val)
                _validate_parsed_tree(raw_map)
                redacted_val = _apply_redact(raw_map, redact_fn)
                if not isinstance(redacted_val, dict):
                    continue
                json.dumps(redacted_val, sort_keys=True, allow_nan=False)
            except Exception:
                continue
            safe_reached[key] = redacted_val
    payload: dict[str, Any] = {
        "schema": PREPARE_REFUSAL_SCHEMA,
        "result": "refused",
        "stage": safe_stage,
        "reason": safe_reason,
        "reasons": [safe_reason],
        "reached": safe_reached,
    }
    out_path = state_dir / PREPARE_REFUSAL_FILENAME
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def load_prepare_or_refusal_state(
    state_dir: Path,
    *,
    redact_fn: Callable[[Any], Any] | None = None,
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    """Load prepare-state.json if valid, or fall back to prepare-refusal.json."""
    state_path = state_dir / PREPARE_STATE_FILENAME
    state_err: str | None = None
    if state_path.exists() or state_path.is_symlink():
        state_data, _prov_map, state_err = load_safe_json_report(state_path, redact_fn=redact_fn)
        if state_data is not None and state_err is None:
            return state_data, None, None

    refusal_path = state_dir / PREPARE_REFUSAL_FILENAME
    if refusal_path.exists() or refusal_path.is_symlink():
        refusal_data, _r_prov, refusal_err = load_safe_json_report(
            refusal_path, redact_fn=redact_fn
        )
        if refusal_data is not None:
            partial_state: dict[str, Any] = {}
            reached = refusal_data.get("reached")
            if isinstance(reached, Mapping):
                for key in REACHED_PREPARE_KEYS:
                    val = reached.get(key)
                    if isinstance(val, Mapping):
                        partial_state[key] = dict(val)
            return partial_state, None, refusal_data
        return (
            {},
            f"prepare-state.json and prepare-refusal.json unavailable: {refusal_err}",
            None,
        )

    if state_err is not None:
        return {}, f"prepare-state.json unavailable: {state_err}", None
    return (
        {},
        "prepare-state.json unavailable: missing canonical report: prepare-state.json",
        None,
    )
