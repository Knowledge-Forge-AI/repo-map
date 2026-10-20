"""Unit tests for tools/retrieval_inventory_metadata.py bounded metadata transport."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import urllib.request

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_TOOLS_DIR = str(_REPO_ROOT / "tools")
_SCRIPT_PATH = str(_REPO_ROOT / "tools" / "retrieval_inventory_metadata.py")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from retrieval_inventory_metadata import (
    IDENTITY_BYTE_CAP, LIVE_API_ORIGIN, ROSTER, TREE_BYTE_CAP, TREE_ENTRY_CAP,
    InventoryError, TransportExchange, _TestTransportSeam, build_dry_plan,
    execute_candidate_inventory, main, parse_strict_json_object,
    read_bounded_response, validate_and_classify_tree,
)

BLOB_SHA_1 = "1111111111111111111111111111111111111111"
BLOB_SHA_2 = "2222222222222222222222222222222222222222"
BLOB_SHA_3 = "3333333333333333333333333333333333333333"
PARENT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class _FakeResponse:
    def __init__(
        self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None,
        url: str = "", max_allowed_reads: int | None = None,
    ) -> None:
        self._body, self.status, self._url, self._pos, self.closed = body, status, url, 0, False
        self.headers = headers if headers is not None else {"Content-Length": str(len(body))}
        self.read_sizes: list[int] = []
        self.max_allowed_reads = max_allowed_reads

    def read(self, amt: int = -1) -> bytes:
        assert not self.closed and amt == 1
        self.read_sizes.append(amt)
        assert self.max_allowed_reads is None or len(self.read_sizes) <= self.max_allowed_reads
        if self._pos >= len(self._body):
            return b""
        self._pos += 1
        return self._body[self._pos - 1 : self._pos]

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


def _valid_payloads(candidate: str, extra_entries: list[dict[str, Any]] | None = None) -> dict[str, bytes]:
    spec = ROSTER[candidate]
    eps = spec.endpoints(LIVE_API_ORIGIN)
    ref_doc = {"ref": spec.ref, "node_id": "REF_NODE", "object": {"type": "tag", "sha": spec.annotated_tag_sha, "url": eps["tag"]}}
    tag_doc = {
        "tag": spec.tag, "sha": spec.annotated_tag_sha,
        "message": "Release signed by Maintainer <maintainer@example.org>\nSecond line\twith tab\r\n",
        "tagger": {"name": "Maintainer Name", "email": "maintainer@example.org"},
        "verification": {
            "verified": True, "payload": f"object {spec.commit_sha}\ntype commit\ntag {spec.tag}\n",
            "signature": "-----BEGIN PGP SIGNATURE-----\nVersion: GnuPG\n\niQIzBAABCAAdFiEE\n-----END PGP SIGNATURE-----\n",
        },
        "object": {"type": "commit", "sha": spec.commit_sha, "url": eps["commit"]},
    }
    commit_doc = {
        "sha": spec.commit_sha, "author": {"name": "Author Name", "email": "author@example.org"},
        "committer": {"name": "Committer Name", "email": "committer@example.org"},
        "message": "Commit message with contact@example.org\n\nDetailed body line.\n",
        "verification": {"verified": True, "signature": "sig-line-1\nsig-line-2\n", "payload": "commit-payload\nline2\n"},
        "tree": {"sha": spec.tree_sha, "url": eps["tree"]}, "parents": [{"sha": PARENT_SHA}],
    }
    origin_path = spec.origin_review_paths[0]
    entries: list[dict[str, Any]] = [
        {"path": spec.package_root, "mode": "040000", "type": "tree", "sha": BLOB_SHA_1},
        {"path": f"{spec.package_root}/__init__.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 120, "url": "https://api.github.com/repos/x/y/git/blobs/" + BLOB_SHA_1},
        {"path": f"{spec.package_root}/password_prompt.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 210},
        {"path": origin_path, "mode": "100644", "type": "blob", "sha": BLOB_SHA_2, "size": 450},
        {"path": f"{spec.package_root}/py.typed", "mode": "100644", "type": "blob", "sha": BLOB_SHA_3, "size": 0},
        {"path": "tests/tmp/secret_fixture.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 80},
        {"path": "docs/localhost_notes.rst", "mode": "100644", "type": "blob", "sha": BLOB_SHA_2, "size": 64},
        {"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "sha": BLOB_SHA_3, "size": 96},
        {"path": "README.md", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 200},
        {"path": "scripts/link_helper", "mode": "120000", "type": "blob", "sha": BLOB_SHA_2, "size": 12},
        {"path": "vendor/submod", "mode": "160000", "type": "commit", "sha": BLOB_SHA_3},
    ]
    if extra_entries:
        entries.extend(extra_entries)
    tree_doc = {"sha": spec.tree_sha, "truncated": False, "tree": entries}
    return {k: json.dumps(v).encode("utf-8") for k, v in ((eps["ref"], ref_doc), (eps["tag"], tag_doc), (eps["commit"], commit_doc), (eps["tree"], tree_doc))}


def test_dry_plan_default_and_cli_stdlib_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert IDENTITY_BYTE_CAP == 32_768
    assert TREE_BYTE_CAP == 2_097_152
    assert TREE_ENTRY_CAP == 10_000
    assert ROSTER["A"].origin_review_paths == ("src/click/_winconsole.py", "src/click/_compat.py", "src/click/_termui_impl.py")

    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0 and captured.err == ""
    plan = json.loads(captured.out)
    assert plan["mode"] == "dry_plan" and plan["network_operations_performed"] == 0
    assert [c["candidate"] for c in plan["selected_candidates"]] == ["A", "B"]
    for gate in ("corpus_admitted", "labels_collected", "learned_utility_measured", "production_pgvector_admitted", "rights_cleared", "independent_cryptographic_authentication"):
        assert plan[gate] is False

    plan_a = build_dry_plan("A")
    assert len(plan_a["selected_candidates"]) == 1
    assert plan_a["selected_candidates"][0]["repository"] == "pallets/click"
    assert plan_a["selected_candidates"][0]["tree_sha"] == "48a3e9893840b8ad002fc31b14be47a31dfd96ed"

    for bad_argv, expected_reason in (
        (["--candidate", "C"], "invalid_candidate"),
        (["--output", "out.json"], "output_requires_execute"),
        (["--execute", "--candidate", "A"], "missing_output_path"),
        (["--unknown-flag"], "invalid_cli_arguments"),
    ):
        rc_bad = main(bad_argv)
        err_doc = json.loads(capsys.readouterr().err)
        assert rc_bad == 2 and err_doc["status"] == "refused" and err_doc["reason"] == expected_reason
        assert err_doc["corpus_admitted"] is False and err_doc["transport_telemetry"] == []

    proc = subprocess.run(
        [sys.executable, "-S", _SCRIPT_PATH, "--candidate", "B"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    sub_plan = json.loads(proc.stdout)
    assert sub_plan["selected_candidates"][0]["repository"] == "pypa/packaging"


@pytest.mark.parametrize(
    ("candidate", "expected_concern", "expected_origin_path"),
    [
        ("A", "platform_helper_origin_review", "src/click/_winconsole.py"),
        ("B", "spdx_license_data_origin_review", "src/packaging/licenses/_spdx.py"),
    ],
)
def test_verified_execution_sanitization_manifest_and_origin_review(
    tmp_path: Path, candidate: str, expected_concern: str, expected_origin_path: str
) -> None:
    bodies = _valid_payloads(candidate)
    responses: list[_FakeResponse] = []
    requested_urls: list[str] = []

    def open_url(req: urllib.request.Request, timeout: float) -> _FakeResponse:
        assert req.get_method() == "GET"
        assert req.get_header("Accept-encoding") == "identity"
        assert not req.has_header("Authorization")
        assert timeout == 15.0
        requested_urls.append(req.full_url)
        resp = _FakeResponse(bodies[req.full_url], url=req.full_url)
        responses.append(resp)
        return resp

    out_file = tmp_path / f"cand_{candidate}.json"
    intent_file = tmp_path / f"cand_{candidate}.intent.json"
    res = execute_candidate_inventory(
        candidate, output_path=out_file, intent_path=intent_file, _seam=_TestTransportSeam(open_url=open_url)
    )
    assert out_file.is_file() and intent_file.is_file()
    assert len(requested_urls) == 4 and all(r.closed for r in responses)
    assert all(ex["response_closed"] is True and ex["max_single_read_request"] == 1 for ex in res["transport_telemetry"])

    raw_saved = out_file.read_text(encoding="utf-8")
    for forbidden_leak in ("Maintainer", "Author Name", "example.org", "PGP SIGNATURE", "sig-line-1", "commit-payload", str(tmp_path)):
        assert forbidden_leak not in raw_saved

    inv = res["tree_inventory"]
    assert inv["per_entry_urls_requested"] == 0 and inv["entry_count"] == 11
    buckets = inv["exclusion_and_review_buckets"]
    assert buckets["ineligible_symlinks"] == ["scripts/link_helper"]
    assert buckets["ineligible_gitlinks"] == ["vendor/submod"]
    assert buckets["origin_review_required"] == [
        {"path": expected_origin_path, "concern": expected_concern, "held_from_eligibility": True, "content_interpreted": False}
    ]
    pkg_root = ROSTER[candidate].package_root
    assert set(buckets["path_candidates_only"]) == {f"{pkg_root}/__init__.py", f"{pkg_root}/password_prompt.py"}
    assert buckets["excluded_non_python_package_blobs"] == [f"{pkg_root}/py.typed"]
    by_path = {item["path"]: item for item in inv["manifest"]}
    assert by_path[expected_origin_path]["eligible_path_candidate"] is False
    assert by_path[expected_origin_path]["classification"] == "origin_review_hold"
    assert by_path[f"{pkg_root}/__init__.py"]["eligible_path_candidate"] is True
    for item in inv["manifest"]:
        assert item["rights_cleared"] is False and item["followed"] is False


@pytest.mark.parametrize(("drift_step", "expected_reason", "expected_calls"), [
    ("ref", "identity_drift_ref", 1),
    ("tag", "identity_drift_tag", 2),
    ("commit", "identity_drift_commit", 3),
])
def test_identity_drift_refused_before_tree_request(
    tmp_path: Path, drift_step: str, expected_reason: str, expected_calls: int
) -> None:
    spec = ROSTER["A"]
    eps = spec.endpoints(LIVE_API_ORIGIN)
    bodies = _valid_payloads("A")
    bad_doc = json.loads(bodies[eps[drift_step]].decode("utf-8"))
    if drift_step in ("ref", "tag"):
        bad_doc["object"]["sha"] = BLOB_SHA_1
    else:
        bad_doc["tree"]["sha"] = BLOB_SHA_1
    bodies[eps[drift_step]] = json.dumps(bad_doc).encode("utf-8")

    calls: list[str] = []
    responses: list[_FakeResponse] = []

    def open_url(req: urllib.request.Request, _timeout: float) -> _FakeResponse:
        calls.append(req.full_url)
        resp = _FakeResponse(bodies[req.full_url], url=req.full_url)
        responses.append(resp)
        return resp

    out_path = tmp_path / f"drift_{drift_step}.json"
    with pytest.raises(InventoryError) as exc_info:
        execute_candidate_inventory("A", output_path=out_path, _seam=_TestTransportSeam(open_url=open_url))
    assert exc_info.value.reason == expected_reason
    assert len(calls) == expected_calls and eps["tree"] not in calls
    assert all(r.closed for r in responses) and not out_path.exists()


def test_boundary_byte_and_entry_caps_never_read_past_limit() -> None:
    exact_body = b'{"sha":"' + ROSTER["A"].tree_sha.encode() + b'","truncated":false,"tree":[]}'
    cap = len(exact_body)

    ex_ok = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    resp_ok = _FakeResponse(exact_body, headers={"Content-Length": str(cap)}, max_allowed_reads=cap)
    raw = read_bounded_response(resp_ok, byte_cap=cap, entry_cap=0, exchange=ex_ok)
    assert raw == exact_body and ex_ok.bytes_requested == cap and ex_ok.bytes_read == cap

    ex_cl = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    resp_cl = _FakeResponse(exact_body + b" ", headers={"Content-Length": str(cap + 1)}, max_allowed_reads=0)
    with pytest.raises(InventoryError, match="byte_cap_exceeded"):
        read_bounded_response(resp_cl, byte_cap=cap, entry_cap=0, exchange=ex_cl)
    assert ex_cl.bytes_requested == 0 and ex_cl.bytes_read == 0

    ex_unk = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    resp_unk = _FakeResponse(exact_body + b"   ", headers={}, max_allowed_reads=cap)
    with pytest.raises(InventoryError, match="byte_cap_exceeded"):
        read_bounded_response(resp_unk, byte_cap=cap, entry_cap=0, exchange=ex_unk)
    assert ex_unk.bytes_requested == cap and ex_unk.bytes_read == cap

    e1 = '{"path":"a.py","mode":"100644","type":"blob","sha":"' + BLOB_SHA_1 + '","size":1}'
    e2 = '{"path":"b.py","mode":"100644","type":"blob","sha":"' + BLOB_SHA_2 + '","size":2}'
    e3 = '{"path":"c.py","mode":"100644","type":"blob","sha":"' + BLOB_SHA_3 + '","size":3}'
    prefix = f'{{"sha":"{ROSTER["A"].tree_sha}","truncated":false,"tree":[{e1},{e2},'.encode("utf-8")
    three_body = prefix + e3.encode("utf-8") + b"]}"
    ex_ent = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    resp_ent = _FakeResponse(three_body, headers={}, max_allowed_reads=len(prefix))
    with pytest.raises(InventoryError, match="tree_entry_cap_exceeded"):
        read_bounded_response(resp_ent, byte_cap=TREE_BYTE_CAP, entry_cap=2, exchange=ex_ent)
    assert ex_ent.bytes_requested == len(prefix) and ex_ent.bytes_read == len(prefix)


    ex_unclosed = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    unclosed_body = exact_body[:-1] + b" "
    resp_unclosed = _FakeResponse(unclosed_body, headers={"Content-Length": str(cap)}, max_allowed_reads=cap)
    with pytest.raises(InventoryError, match="malformed_json"):
        read_bounded_response(resp_unclosed, byte_cap=cap, entry_cap=0, exchange=ex_unclosed)

    ex_deadline = TransportExchange("tree", "https://api.github.com/x", "GET", "2026-10-20T00:00:00Z")
    resp_deadline = _FakeResponse(exact_body, headers={"Content-Length": str(cap)}, max_allowed_reads=0)
    with pytest.raises(InventoryError, match="request_timeout"):
        read_bounded_response(resp_deadline, byte_cap=cap, entry_cap=0, exchange=ex_deadline, deadline=time.monotonic() - 0.01)


def test_json_and_tree_validation_corner_cases() -> None:
    assert parse_strict_json_object(b'{"msg":"line1\\nline2\\tindent\\r\\n"}')["msg"] == "line1\nline2\tindent\r\n"
    for raw_bad, expected in (
        (b'{"a":1,"a":2}', "duplicate_json_key"),
        (b'{"a":{"k":1,"k":2}}', "duplicate_json_key"),
        (b'{"a":NaN}', "nonfinite_json_number"),
        (b'{"a":Infinity}', "nonfinite_json_number"),
        (b'{"a":1e309}', "nonfinite_json_number"),
        (b'{"a":"bad\x01ctrl"}', "malformed_json"),
        (b'{"a":"bad\\u0000nul"}', "malformed_json"),
        (b'{"bad\\nkey":1}', "malformed_json"),
        (b'[1,2,3]', "invalid_json_object"),
        (b'{"a":1', "malformed_json"),
    ):
        with pytest.raises(InventoryError, match=expected):
            parse_strict_json_object(raw_bad)

    spec = ROSTER["A"]
    base_tree = {"sha": spec.tree_sha, "truncated": False, "tree": []}
    with pytest.raises(InventoryError, match="tree_sha_mismatch"):
        validate_and_classify_tree(spec, {**base_tree, "sha": BLOB_SHA_1}, raw_bytes=10, raw_sha256="sha256:00", request_utc="2026-10-20T00:00:00Z")
    for bad_trunc, reason in ((None, "invalid_truncated_flag"), (1, "invalid_truncated_flag"), ("false", "invalid_truncated_flag"), (True, "tree_truncated")):
        with pytest.raises(InventoryError, match=reason):
            validate_and_classify_tree(spec, {**base_tree, "truncated": bad_trunc}, raw_bytes=10, raw_sha256="sha256:00", request_utc="2026-10-20T00:00:00Z")

    for bad_entry, reason in (
        ({"path": "../evil.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 1}, "unsafe_tree_path"),
        ({"path": "/abs.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 1}, "unsafe_tree_path"),
        ({"path": "a//b.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 1}, "unsafe_tree_path"),
        ({"path": "a\\b.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 1}, "unsafe_tree_path"),
        ({"path": "a.py", "mode": "100644", "type": "tree", "sha": BLOB_SHA_1}, "invalid_tree_mode_or_type"),
        ({"path": "a.py", "mode": "120000", "type": "tree", "sha": BLOB_SHA_1}, "invalid_tree_mode_or_type"),
        ({"path": "a.py", "mode": "160000", "type": "blob", "sha": BLOB_SHA_1, "size": 1}, "invalid_tree_mode_or_type"),
        ({"path": "a.py", "mode": "100644", "type": "blob", "sha": "badsha", "size": 1}, "invalid_entry_sha"),
        ({"path": "a.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": -1}, "invalid_entry_size"),
        ({"path": "a.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": True}, "invalid_entry_size"),
        ({"path": "dir", "mode": "040000", "type": "tree", "sha": BLOB_SHA_1, "size": 10}, "invalid_entry_size"),
    ):
        with pytest.raises(InventoryError, match=reason):
            validate_and_classify_tree(spec, {**base_tree, "tree": [bad_entry]}, raw_bytes=10, raw_sha256="sha256:00", request_utc="2026-10-20T00:00:00Z")

    dup_entry = {"path": "a.py", "mode": "100644", "type": "blob", "sha": BLOB_SHA_1, "size": 1}
    with pytest.raises(InventoryError, match="duplicate_tree_path"):
        validate_and_classify_tree(spec, {**base_tree, "tree": [dup_entry, dup_entry]}, raw_bytes=10, raw_sha256="sha256:00", request_utc="2026-10-20T00:00:00Z")


def test_redirect_encoding_timeout_exclusive_files_and_no_retry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for bad_seam, reason in (
        (_TestTransportSeam(base_url="https://evil.example.com"), "invalid_endpoint_origin"),
        (_TestTransportSeam(identity_byte_cap=IDENTITY_BYTE_CAP + 1), "invalid_cap_configuration"),
        (_TestTransportSeam(tree_byte_cap=TREE_BYTE_CAP + 1), "invalid_cap_configuration"),
        (_TestTransportSeam(tree_entry_cap=TREE_ENTRY_CAP + 1), "invalid_cap_configuration"),
        (_TestTransportSeam(timeout_seconds=20.0), "invalid_timeout"),
    ):
        with pytest.raises(InventoryError, match=reason):
            bad_seam.validate()

    calls = 0

    def fail_redirect(req: urllib.request.Request, _t: float) -> Any:
        nonlocal calls
        calls += 1
        return _FakeResponse(b"{}", status=302, headers={"Location": "https://example.com"}, url=req.full_url)

    intent_1 = tmp_path / "attempt1.intent.json"
    out_1 = tmp_path / "attempt1.json"
    with pytest.raises(InventoryError, match="redirect_refused"):
        execute_candidate_inventory("A", output_path=out_1, intent_path=intent_1, _seam=_TestTransportSeam(open_url=fail_redirect))
    assert calls == 1 and intent_1.is_file() and not out_1.exists()

    with pytest.raises(InventoryError, match="intent_already_exists"):
        execute_candidate_inventory("A", output_path=out_1, intent_path=intent_1, _seam=_TestTransportSeam(open_url=fail_redirect))
    assert calls == 1

    def fail_gzip(req: urllib.request.Request, _t: float) -> _FakeResponse:
        return _FakeResponse(b"{}", headers={"Content-Encoding": "gzip"}, url=req.full_url)

    with pytest.raises(InventoryError, match="nonidentity_encoding_refused"):
        execute_candidate_inventory("A", output_path=tmp_path / "gz.json", _seam=_TestTransportSeam(open_url=fail_gzip))

    def fail_unicode_cl(req: urllib.request.Request, _t: float) -> _FakeResponse:
        return _FakeResponse(b"{}", headers={"Content-Length": "\u00b2"}, url=req.full_url)

    with pytest.raises(InventoryError, match="invalid_content_length"):
        execute_candidate_inventory("A", output_path=tmp_path / "ucl.json", _seam=_TestTransportSeam(open_url=fail_unicode_cl))

    for exc_to_raise, expected_code in (
        (socket.timeout("timed out"), "request_timeout"),
        (http.client.BadStatusLine("bad"), "http_protocol_error"),
        (http.client.IncompleteRead(b"{"), "incomplete_body"),
    ):
        def _fail_exc(_req: urllib.request.Request, _t: float, _e: Exception = exc_to_raise) -> Any:
            raise _e

        rc_exc = main(
            ["--execute", "--candidate", "A", "--output", str(tmp_path / f"err_{expected_code}.json")],
            _seam=_TestTransportSeam(open_url=_fail_exc),
        )
        err_payload = json.loads(capsys.readouterr().err)
        assert rc_exc == 2 and err_payload["reason"] == expected_code
        assert len(err_payload["transport_telemetry"]) == 1

    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(InventoryError, match="output_already_exists"):
        execute_candidate_inventory("A", output_path=existing, _seam=_TestTransportSeam(open_url=fail_gzip))

    sym_out = tmp_path / "sym.json"
    sym_out.symlink_to(existing)
    rc = main(["--execute", "--candidate", "A", "--output", str(sym_out)], _seam=_TestTransportSeam(open_url=fail_gzip))
    err_text = capsys.readouterr().err
    assert rc == 2 and json.loads(err_text)["reason"] == "unsafe_output_symlink"
    assert str(tmp_path) not in err_text and "/Users/" not in err_text
