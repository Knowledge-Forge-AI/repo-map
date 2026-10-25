"""Unit tests for bounded JSON report I/O and prepare-refusal state persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ci import d12_hosted_state


def _state_mod() -> Any:
    return d12_hosted_state


def test_load_safe_json_report_constants_and_valid_mapping(tmp_path: Path) -> None:
    mod = _state_mod()
    assert mod.MAX_SAFE_JSON_REPORT_BYTES == 8 * 1024 * 1024
    assert mod.PREPARE_REFUSAL_SCHEMA == "repomap-d12-prepare-refusal-v1"

    report_path = tmp_path / "valid.json"
    raw = json.dumps({"mode": "exploration", "result": "observed"}, sort_keys=True).encode("utf-8")
    report_path.write_bytes(raw)

    data, prov, err = mod.load_safe_json_report(report_path)
    assert err is None
    assert data == {"mode": "exploration", "result": "observed"}
    assert prov == {
        "status": "valid",
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "redacted": False,
    }


def test_load_safe_json_report_missing_and_symlink_refusal(tmp_path: Path) -> None:
    mod = _state_mod()
    missing_path = tmp_path / "missing.json"
    data, prov, err = mod.load_safe_json_report(missing_path)
    assert data is None
    assert err is not None and "missing" in err
    assert prov["status"] == "missing"
    assert prov["byte_length"] == 0
    assert prov["sha256"] is None

    target = tmp_path / "target.json"
    target.write_text('{"ok": true}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    s_data, s_prov, s_err = mod.load_safe_json_report(link)
    assert s_data is None
    assert s_err is not None and "symlink" in s_err
    assert s_prov["status"] == "symlink"
    assert s_prov["byte_length"] == 0
    assert s_prov["sha256"] is None


def test_load_safe_json_report_rejects_oversize_file_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state_mod()
    oversize_path = tmp_path / "oversize.json"
    payload = b"{" + b"a" * 128 + b"}"
    oversize_path.write_bytes(payload)

    def _forbidden_open(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("oversize file must be rejected by stat size check before open()")

    monkeypatch.setattr(Path, "open", _forbidden_open)
    data, prov, err = mod.load_safe_json_report(oversize_path, max_bytes=64)
    assert data is None
    assert err is not None and "exceeds maximum" in err
    assert prov["status"] == "oversize"
    assert prov["byte_length"] == len(payload)
    assert prov["sha256"] is None
    assert prov["max_bytes"] == 64


def test_load_safe_json_report_decode_error_retains_raw_bytes_and_sha256(tmp_path: Path) -> None:
    mod = _state_mod()
    bad_utf8 = tmp_path / "bad-utf8.json"
    raw = b"\xff\xfe\xfd\x80non-utf8-bytes"
    bad_utf8.write_bytes(raw)

    data, prov, err = mod.load_safe_json_report(bad_utf8)
    assert data is None
    assert err is not None and "not valid UTF-8" in err
    assert prov == {
        "status": "decode_error",
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "redacted": False,
    }


def test_load_safe_json_report_malformed_non_mapping_and_redaction(tmp_path: Path) -> None:
    mod = _state_mod()
    malformed = tmp_path / "malformed.json"
    raw_bad = b'{"unterminated": '
    malformed.write_bytes(raw_bad)
    data, prov, err = mod.load_safe_json_report(malformed)
    assert data is None
    assert err is not None and "malformed JSON" in err
    assert prov["status"] == "malformed_json"
    assert prov["byte_length"] == len(raw_bad)
    assert prov["sha256"] == hashlib.sha256(raw_bad).hexdigest()

    list_root = tmp_path / "list.json"
    raw_list = b"[1, 2, 3]"
    list_root.write_bytes(raw_list)
    l_data, l_prov, l_err = mod.load_safe_json_report(list_root)
    assert l_data is None
    assert l_err is not None and "root is not an object" in l_err
    assert l_prov["status"] == "non_mapping_root"
    assert l_prov["byte_length"] == len(raw_list)
    assert l_prov["sha256"] == hashlib.sha256(raw_list).hexdigest()

    secret_path = tmp_path / "secret.json"
    raw_secret = json.dumps({"note": "/Users/alice/private"}).encode("utf-8")
    secret_path.write_bytes(raw_secret)
    r_data, r_prov, r_err = mod.load_safe_json_report(
        secret_path,
        redact_fn=lambda obj: {"note": "<redacted-private-path>"} if isinstance(obj, dict) else obj,
    )
    assert r_data == {"note": "<redacted-private-path>"}
    assert r_err is not None and "privacy redaction modified" in r_err
    assert r_prov["status"] == "redacted_unqualified"
    assert r_prov["redacted"] is True
    assert r_prov["byte_length"] == len(raw_secret)
    assert r_prov["sha256"] == hashlib.sha256(raw_secret).hexdigest()


def test_prepare_refusal_persistence_and_load_fallback(tmp_path: Path) -> None:
    mod = _state_mod()
    state_dir = tmp_path / "state"
    refusal_path = mod.write_prepare_refusal_state(
        state_dir,
        stage="sdk_materialization",
        reason="SDK inspect missing Architecture at /Users/alice/work",
        reached={
            "pr_binding": {"run_id": "9001", "run_attempt": 1},
            "identity_binding": {"source_sha256": "a" * 64},
            "native_environment": {"host_kernel": "Linux", "host_arch": "x86_64"},
            "entry_baseline": {
                "images": (
                    "sha256:" + "01" * 32,
                    "/Users/alice/work/tuple-item",
                    {"/Users/alice/work/tuple-key": "/Users/alice/work/tuple-val"},
                ),
                "containers": [],
                "volumes": [],
                "networks": [],
            },
        },
        redact_fn=lambda val: (
            val.replace("/Users/alice/work", "<redacted-private-path>") if isinstance(val, str) else val
        ),
    )
    assert refusal_path == state_dir / "prepare-refusal.json"
    assert refusal_path.is_file()

    state, load_err, refusal = mod.load_prepare_or_refusal_state(state_dir)
    assert load_err is None
    assert refusal is not None
    assert refusal["schema"] == mod.PREPARE_REFUSAL_SCHEMA
    assert refusal["stage"] == "sdk_materialization"
    assert "<redacted-private-path>" in refusal["reason"]
    assert "/Users/alice/work" not in json.dumps(refusal)
    assert state["pr_binding"] == {"run_id": "9001", "run_attempt": 1}
    assert state["identity_binding"] == {"source_sha256": "a" * 64}
    assert state["native_environment"] == {"host_kernel": "Linux", "host_arch": "x86_64"}
    assert state["entry_baseline"]["images"] == [
        "sha256:" + "01" * 32,
        "<redacted-private-path>/tuple-item",
        {"<redacted-private-path>/tuple-key": "<redacted-private-path>/tuple-val"},
    ]
    assert state.get("post_sdk_baseline") is None
    assert state.get("sdk_materialization") is None


def test_load_prepare_or_refusal_state_prefers_valid_prepare_state_and_reports_missing(
    tmp_path: Path,
) -> None:
    mod = _state_mod()
    empty_dir = tmp_path / "empty"
    state, err, refusal = mod.load_prepare_or_refusal_state(empty_dir)
    assert state == {}
    assert refusal is None
    assert err is not None and "prepare-state.json" in err

    populated_dir = tmp_path / "populated"
    populated_dir.mkdir(parents=True)
    (populated_dir / "prepare-state.json").write_text(
        json.dumps({"pr_binding": {"run_id": "42"}, "sdk_materialization": {"sdk_build_attempts": 0}}),
        encoding="utf-8",
    )
    p_state, p_err, p_refusal = mod.load_prepare_or_refusal_state(populated_dir)
    assert p_err is None
    assert p_refusal is None
    assert p_state["pr_binding"] == {"run_id": "42"}


def test_load_safe_json_report_deep_parse_and_sanitizer_failures_retain_provenance(tmp_path: Path) -> None:
    mod = _state_mod()
    deep_path = tmp_path / "deep.json"
    deep_raw = (b'{"a":' * 1500) + b"{}" + (b"}" * 1500)
    assert len(deep_raw) < mod.MAX_SAFE_JSON_REPORT_BYTES
    deep_path.write_bytes(deep_raw)

    data, prov, err = mod.load_safe_json_report(deep_path)
    assert data is None and err is not None and "malformed JSON" in err
    assert prov == {
        "status": "malformed_json", "byte_length": len(deep_raw),
        "sha256": hashlib.sha256(deep_raw).hexdigest(), "redacted": False,
    }

    san_path = tmp_path / "san-err.json"
    san_raw = json.dumps({"nested": {"key": "SYNTHETIC_SECRET_VALUE"}}).encode("utf-8")
    san_path.write_bytes(san_raw)
    for exc_to_raise in (
        RecursionError("synthetic sanitizer recursion overflow"),
        RuntimeError("sanitizer failed on SYNTHETIC_SECRET_VALUE"),
    ):
        def _failing_redact(_val: Any, _exc: Exception = exc_to_raise) -> Any:
            raise _exc

        s_data, s_prov, s_err = mod.load_safe_json_report(san_path, redact_fn=_failing_redact)
        assert s_data is None and s_err is not None and "SYNTHETIC_SECRET_VALUE" not in s_err
        assert s_prov == {
            "status": "redaction_corrupted_json", "byte_length": len(san_raw),
            "sha256": hashlib.sha256(san_raw).hexdigest(), "redacted": True,
        }

    def _interrupt_redact(_val: Any) -> Any:
        raise KeyboardInterrupt("deliberate operator cancel")

    with pytest.raises(KeyboardInterrupt, match="deliberate operator cancel"):
        mod.load_safe_json_report(san_path, redact_fn=_interrupt_redact)


def test_load_safe_json_report_recursive_key_sanitization_collision_and_unusable_keys(tmp_path: Path) -> None:
    mod = _state_mod()
    key_path = tmp_path / "private-keys.json"
    raw_keys = json.dumps(
        {
            "SYNTHETIC_PRIVATE_KEY_ROOT": "ok",
            "nested": {"items": [{"SYNTHETIC_PRIVATE_KEY_CHILD": "SYNTHETIC_PRIVATE_VAL"}]},
        },
        sort_keys=True,
    ).encode("utf-8")
    key_path.write_bytes(raw_keys)

    def _redact_keys_and_vals(val: Any) -> Any:
        if not isinstance(val, str):
            return val
        return (
            val.replace("SYNTHETIC_PRIVATE_KEY_ROOT", "<redacted-root-key>")
            .replace("SYNTHETIC_PRIVATE_KEY_CHILD", "<redacted-child-key>")
            .replace("SYNTHETIC_PRIVATE_VAL", "<redacted-val>")
        )

    k_data, k_prov, k_err = mod.load_safe_json_report(key_path, redact_fn=_redact_keys_and_vals)
    assert k_data == {
        "<redacted-root-key>": "ok",
        "nested": {"items": [{"<redacted-child-key>": "<redacted-val>"}]},
    }
    assert "SYNTHETIC_PRIVATE" not in json.dumps(k_data)
    assert k_err is not None and "cannot qualify" in k_err and "SYNTHETIC_PRIVATE" not in k_err
    assert k_prov == {
        "status": "redacted_unqualified", "byte_length": len(raw_keys),
        "sha256": hashlib.sha256(raw_keys).hexdigest(), "redacted": True,
    }

    coll_path = tmp_path / "colliding-keys.json"
    raw_coll = json.dumps(
        {"nested": {"SYNTHETIC_PRIVATE_KEY_1": "first", "SYNTHETIC_PRIVATE_KEY_2": "second"}}, sort_keys=True
    ).encode("utf-8")
    coll_path.write_bytes(raw_coll)
    c_data, c_prov, c_err = mod.load_safe_json_report(
        coll_path,
        redact_fn=lambda v: "<redacted-key>" if isinstance(v, str) and v.startswith("SYNTHETIC_PRIVATE_KEY_") else v,
    )
    assert c_data is None and c_err is not None and "SYNTHETIC_PRIVATE_KEY_" not in c_err
    assert c_prov == {
        "status": "redaction_corrupted_json", "byte_length": len(raw_coll),
        "sha256": hashlib.sha256(raw_coll).hexdigest(), "redacted": True,
    }

    unusable_path = tmp_path / "unusable-key.json"
    raw_unusable = json.dumps({"SYNTHETIC_PRIVATE_KEY_BAD": "value"}).encode("utf-8")
    unusable_path.write_bytes(raw_unusable)
    for bad_key in (None, "", "   ", 42, ["not-a-str"]):
        u_data, u_prov, u_err = mod.load_safe_json_report(
            unusable_path,
            redact_fn=lambda v, replacement=bad_key: replacement if v == "SYNTHETIC_PRIVATE_KEY_BAD" else v,
        )
        assert u_data is None and u_err is not None and "SYNTHETIC_PRIVATE_KEY_BAD" not in u_err
        assert u_prov == {
            "status": "redaction_corrupted_json", "byte_length": len(raw_unusable),
            "sha256": hashlib.sha256(raw_unusable).hexdigest(), "redacted": True,
        }

    unchanged_path = tmp_path / "unchanged.json"
    unchanged_doc = {"mode": "exploration", "steps": {"closure": {"elf_count": 42}}, "primary": None}
    raw_unchanged = json.dumps(unchanged_doc, sort_keys=True).encode("utf-8")
    unchanged_path.write_bytes(raw_unchanged)
    v_data, v_prov, v_err = mod.load_safe_json_report(unchanged_path, redact_fn=_redact_keys_and_vals)
    assert v_err is None and v_data == unchanged_doc
    assert v_prov == {
        "status": "valid", "byte_length": len(raw_unchanged),
        "sha256": hashlib.sha256(raw_unchanged).hexdigest(), "redacted": False,
    }


def test_write_prepare_refusal_state_none_reason_and_callback_failures(tmp_path: Path) -> None:
    mod = _state_mod()
    none_dir = tmp_path / "none-reason"
    mod.write_prepare_refusal_state(
        none_dir,
        stage="innocent_stage_identifier",
        reason="SDK inspect failed for SYNTHETIC_PRIVATE_REASON_TOKEN",
        reached={"pr_binding": {"run_id": "9001", "run_attempt": 1}},
        redact_fn=lambda v: (
            None
            if isinstance(v, str) and ("SYNTHETIC_PRIVATE_REASON_TOKEN" in v or v == "innocent_stage_identifier")
            else v
        ),
    )
    n_state, n_err, n_refusal = mod.load_prepare_or_refusal_state(none_dir)
    assert n_err is None and n_refusal is not None
    assert n_refusal["stage"] == "unknown"
    assert n_refusal["reason"] == mod.REDACTED_REFUSAL_REASON
    assert "SYNTHETIC_PRIVATE_REASON_TOKEN" not in json.dumps(n_refusal)
    assert "innocent_stage_identifier" not in json.dumps(n_refusal)
    assert n_refusal["reasons"] == [mod.REDACTED_REFUSAL_REASON]
    assert n_state == {"pr_binding": {"run_id": "9001", "run_attempt": 1}}

    cb_dir = tmp_path / "cb-failure"

    def _flaky_redact(val: Any) -> Any:
        if not isinstance(val, str):
            return val
        if "SYNTHETIC_EXPLODING_TOKEN" in val or val == "innocent_stage_identifier":
            raise RuntimeError("boom on SYNTHETIC_EXPLODING_TOKEN")
        if val == "SYNTHETIC_REDACTABLE_KEY":
            return "<redacted-key>"
        if val.startswith("SYNTHETIC_COLLIDE_"):
            return "<collided>"
        if val == "SYNTHETIC_UNUSABLE_KEY":
            return None
        return val

    mod.write_prepare_refusal_state(
        cb_dir,
        stage="innocent_stage_identifier",
        reason="Refused due to SYNTHETIC_EXPLODING_TOKEN",
        reached={
            "pr_binding": {"run_id": "9001", "run_attempt": 1, "SYNTHETIC_REDACTABLE_KEY": "ok"},
            "identity_binding": {"source_sha256": "a" * 64, "bad": "SYNTHETIC_EXPLODING_TOKEN"},
            "native_environment": {"SYNTHETIC_COLLIDE_1": "x", "SYNTHETIC_COLLIDE_2": "y"},
            "entry_baseline": {"SYNTHETIC_UNUSABLE_KEY": "z"},
        },
        redact_fn=_flaky_redact,
    )
    c_state, c_err, c_refusal = mod.load_prepare_or_refusal_state(cb_dir)
    assert c_err is None and c_refusal is not None
    assert c_refusal["stage"] == "unknown"
    assert c_refusal["reason"] == mod.REDACTED_REFUSAL_REASON
    assert c_refusal["reasons"] == [mod.REDACTED_REFUSAL_REASON]
    serialized = json.dumps(c_refusal)
    for forbidden in (
        "SYNTHETIC_EXPLODING_TOKEN",
        "SYNTHETIC_REDACTABLE_KEY",
        "SYNTHETIC_COLLIDE_",
        "SYNTHETIC_UNUSABLE_KEY",
        "innocent_stage_identifier",
    ):
        assert forbidden not in serialized
    assert c_state == {"pr_binding": {"run_id": "9001", "run_attempt": 1, "<redacted-key>": "ok"}}
    assert "identity_binding" not in c_state
    assert "native_environment" not in c_state
    assert "entry_baseline" not in c_state

    with pytest.raises(KeyboardInterrupt, match="stop persistence"):
        mod.write_prepare_refusal_state(
            tmp_path / "cancel-dir", stage="sdk_materialization", reason="cancelled",
            redact_fn=lambda _v: (_ for _ in ()).throw(KeyboardInterrupt("stop persistence")),
        )
