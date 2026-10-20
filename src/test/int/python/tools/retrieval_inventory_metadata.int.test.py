"""Integration tests for tools/retrieval_inventory_metadata.py over real loopback HTTP."""

from __future__ import annotations

from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Iterator

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_TOOLS_DIR = str(_REPO_ROOT / "tools")
_SCRIPT_PATH = str(_REPO_ROOT / "tools" / "retrieval_inventory_metadata.py")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from retrieval_inventory_metadata import (
    ROSTER,
    InventoryError,
    TransportExchange,
    _TestTransportSeam,
    execute_candidate_inventory,
    main,
)

BLOB_1 = "1111111111111111111111111111111111111111"
BLOB_2 = "2222222222222222222222222222222222222222"
BLOB_3 = "3333333333333333333333333333333333333333"
PARENT_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class _RouteSpec:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        send_content_length: bool = True,
        chunked: bool = False,
        truncate_chunked: bool = False,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = dict(headers or {})
        self.send_content_length = send_content_length
        self.chunked = chunked
        self.truncate_chunked = truncate_chunked


class _LoopbackServerState:
    def __init__(self) -> None:
        self.routes: dict[str, _RouteSpec] = {}
        self.requests: list[dict[str, Any]] = []


def _make_handler(state: _LoopbackServerState) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            state.requests.append({
                "method": self.command,
                "path": self.path,
                "accept_encoding": self.headers.get("Accept-Encoding"),
                "authorization": self.headers.get("Authorization"),
                "connection": self.headers.get("Connection"),
            })
            route = state.routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.send_header("Content-Length", "2")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(route.status)
            for k, v in route.headers.items():
                self.send_header(k, v)
            if route.chunked:
                self.send_header("Transfer-Encoding", "chunked")
            elif route.send_content_length and "Content-Length" not in route.headers:
                self.send_header("Content-Length", str(len(route.body)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                if route.chunked:
                    for idx in range(0, len(route.body), 37):
                        part = route.body[idx : idx + 37]
                        self.wfile.write(f"{len(part):x}\r\n".encode("ascii") + part + b"\r\n")
                    if not route.truncate_chunked:
                        self.wfile.write(b"0\r\n\r\n")
                else:
                    self.wfile.write(route.body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return _Handler


@contextmanager
def _running_loopback_server(state: _LoopbackServerState) -> Iterator[str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _make_handler(state))
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _populate_candidate_routes(state: _LoopbackServerState, candidate: str) -> dict[str, str]:
    spec = ROSTER[candidate]
    origin_path = spec.origin_review_paths[0]
    paths = {
        "ref": f"/repos/{spec.repository}/git/ref/tags/{spec.tag}",
        "tag": f"/repos/{spec.repository}/git/tags/{spec.annotated_tag_sha}",
        "commit": f"/repos/{spec.repository}/git/commits/{spec.commit_sha}",
        "tree": f"/repos/{spec.repository}/git/trees/{spec.tree_sha}?recursive=1",
    }
    state.routes[paths["ref"]] = _RouteSpec(json.dumps({
        "ref": spec.ref,
        "object": {"type": "tag", "sha": spec.annotated_tag_sha},
    }).encode("utf-8"))
    state.routes[paths["tag"]] = _RouteSpec(json.dumps({
        "tag": spec.tag,
        "sha": spec.annotated_tag_sha,
        "message": "Annotated release tag\nMulti-line body\r\n",
        "tagger": {"name": "Private Tagger", "email": "tagger@example.org"},
        "verification": {"verified": True, "signature": "-----BEGIN PGP SIGNATURE-----\nline\n", "payload": "signed\ntag\n"},
        "object": {"type": "commit", "sha": spec.commit_sha},
    }).encode("utf-8"))
    state.routes[paths["commit"]] = _RouteSpec(json.dumps({
        "sha": spec.commit_sha,
        "message": "Commit subject\n\nCommit body\n",
        "author": {"name": "Private Author", "email": "author@example.org"},
        "tree": {"sha": spec.tree_sha},
        "parents": [{"sha": PARENT_SHA}],
    }).encode("utf-8"))
    state.routes[paths["tree"]] = _RouteSpec(json.dumps({
        "sha": spec.tree_sha,
        "truncated": False,
        "tree": [
            {"path": spec.package_root, "mode": "040000", "type": "tree", "sha": BLOB_1},
            {"path": f"{spec.package_root}/__init__.py", "mode": "100644", "type": "blob", "sha": BLOB_1, "size": 64},
            {"path": origin_path, "mode": "100644", "type": "blob", "sha": BLOB_2, "size": 512},
            {"path": "tests/tmp/test_secret_mod.py", "mode": "100644", "type": "blob", "sha": BLOB_3, "size": 128},
            {"path": "scripts/dev_link", "mode": "120000", "type": "blob", "sha": BLOB_2, "size": 10},
            {"path": "external/sub", "mode": "160000", "type": "commit", "sha": BLOB_3},
        ],
    }).encode("utf-8"))
    return paths


def test_loopback_http_dry_plan_and_verified_execution_a_and_b(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _LoopbackServerState()
    _populate_candidate_routes(state, "A")
    _populate_candidate_routes(state, "B")

    with _running_loopback_server(state) as base_url:
        proc = subprocess.run(
            [sys.executable, _SCRIPT_PATH],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0
        plan = json.loads(proc.stdout)
        assert plan["mode"] == "dry_plan" and plan["network_operations_performed"] == 0
        assert len(state.requests) == 0

        seam = _TestTransportSeam(base_url=base_url)
        for cand, concern, origin_path in (
            ("A", "platform_helper_origin_review", "src/click/_winconsole.py"),
            ("B", "spdx_license_data_origin_review", "src/packaging/licenses/_spdx.py"),
        ):
            out_path = tmp_path / f"verified_{cand}.json"
            intent_path = tmp_path / f"verified_{cand}.intent.json"
            rc = main(
                ["--execute", "--candidate", cand, "--output", str(out_path), "--intent", str(intent_path)],
                _seam=seam,
            )
            captured = capsys.readouterr()
            assert rc == 0 and captured.err == ""
            summary = json.loads(captured.out)
            assert summary["status"] == "verified" and summary["candidate"] == cand
            assert summary["corpus_admitted"] is False and summary["production_pgvector_admitted"] is False

            saved = json.loads(out_path.read_text(encoding="utf-8"))
            assert saved["identity_verification"]["verified"] is True
            assert saved["identity_verification"]["independent_cryptographic_authentication"] is False
            raw_text = out_path.read_text(encoding="utf-8")
            assert "Private Tagger" not in raw_text and "Private Author" not in raw_text
            assert "PGP SIGNATURE" not in raw_text and "127.0.0.1" not in raw_text

            telem = saved["transport_telemetry"]
            assert len(telem) == 4
            for ex in telem:
                assert ex["status_code"] == 200
                assert ex["response_closed"] is True
                assert ex["max_single_read_request"] == 1
                assert ex["bytes_read"] > 0 and ex["bytes_requested"] >= ex["bytes_read"]

            inv = saved["tree_inventory"]
            assert inv["entry_count"] == 6 and inv["per_entry_urls_requested"] == 0
            rev = inv["exclusion_and_review_buckets"]
            assert rev["origin_review_required"] == [
                {"path": origin_path, "concern": concern, "held_from_eligibility": True, "content_interpreted": False}
            ]
            assert rev["path_candidates_only"] == [f"{ROSTER[cand].package_root}/__init__.py"]
            assert rev["ineligible_symlinks"] == ["scripts/dev_link"]
            assert rev["ineligible_gitlinks"] == ["external/sub"]

        assert len(state.requests) == 8
        assert all(
            r["method"] == "GET" and r["accept_encoding"] == "identity" and r["authorization"] is None
            for r in state.requests
        )


def test_loopback_http_byte_cap_and_entry_cap_refusals_and_response_closure(tmp_path: Path) -> None:
    state = _LoopbackServerState()
    paths_a = _populate_candidate_routes(state, "A")
    spec_a = ROSTER["A"]

    with _running_loopback_server(state) as base_url:
        tree_bytes = state.routes[paths_a["tree"]].body
        tight_cap = len(tree_bytes) - 5

        telem_cl: list[TransportExchange] = []
        with pytest.raises(InventoryError, match="byte_cap_exceeded"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "cl_cap.json",
                _seam=_TestTransportSeam(base_url=base_url, tree_byte_cap=tight_cap),
                _telemetry_out=telem_cl,
            )
        assert len(telem_cl) == 4 and all(ex.response_closed for ex in telem_cl)
        assert telem_cl[-1].bytes_requested == 0 and telem_cl[-1].bytes_read == 0

        state.routes[paths_a["tree"]] = _RouteSpec(tree_bytes, send_content_length=False)
        telem_stream_cap: list[TransportExchange] = []
        with pytest.raises(InventoryError, match="byte_cap_exceeded"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "stream_cap.json",
                _seam=_TestTransportSeam(base_url=base_url, tree_byte_cap=tight_cap),
                _telemetry_out=telem_stream_cap,
            )
        assert len(telem_stream_cap) == 4 and all(ex.response_closed for ex in telem_stream_cap)
        assert telem_stream_cap[-1].bytes_requested == tight_cap
        assert telem_stream_cap[-1].bytes_read == tight_cap
        assert telem_stream_cap[-1].max_single_read_request == 1

        e1 = '{"path":"src/click/a.py","mode":"100644","type":"blob","sha":"' + BLOB_1 + '","size":1}'
        e2 = '{"path":"src/click/b.py","mode":"100644","type":"blob","sha":"' + BLOB_2 + '","size":2}'
        e3 = '{"path":"src/click/c.py","mode":"100644","type":"blob","sha":"' + BLOB_3 + '","size":3}'
        prefix = f'{{"sha":"{spec_a.tree_sha}","truncated":false,"tree":[{e1},{e2},'.encode("utf-8")
        state.routes[paths_a["tree"]] = _RouteSpec(prefix + e3.encode("utf-8") + b"]}", chunked=True)

        telem_entry: list[TransportExchange] = []
        intent_entry = tmp_path / "entry_cap.intent.json"
        with pytest.raises(InventoryError, match="tree_entry_cap_exceeded"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "entry_cap.json",
                intent_path=intent_entry,
                _seam=_TestTransportSeam(base_url=base_url, tree_entry_cap=2),
                _telemetry_out=telem_entry,
            )
        assert len(telem_entry) == 4 and all(ex.response_closed for ex in telem_entry)
        assert telem_entry[-1].bytes_requested == len(prefix)
        assert telem_entry[-1].bytes_read == len(prefix)

        state.routes[paths_a["tree"]] = _RouteSpec(prefix, chunked=True, truncate_chunked=True)
        telem_trunc: list[TransportExchange] = []
        with pytest.raises(InventoryError, match="incomplete_body"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "chunk_trunc.json",
                _seam=_TestTransportSeam(base_url=base_url),
                _telemetry_out=telem_trunc,
            )
        assert len(telem_trunc) == 4 and all(ex.response_closed for ex in telem_trunc)

        req_count_before = len(state.requests)
        with pytest.raises(InventoryError, match="intent_already_exists"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "entry_cap_retry.json",
                intent_path=intent_entry,
                _seam=_TestTransportSeam(base_url=base_url, tree_entry_cap=2),
            )
        assert len(state.requests) == req_count_before

        state.routes[paths_a["ref"]] = _RouteSpec(b"{}", status=302, headers={"Location": f"{base_url}/other"})
        telem_red: list[TransportExchange] = []
        with pytest.raises(InventoryError, match="redirect_refused"):
            execute_candidate_inventory(
                "A",
                output_path=tmp_path / "redir.json",
                _seam=_TestTransportSeam(base_url=base_url),
                _telemetry_out=telem_red,
            )
        assert len(telem_red) == 1 and telem_red[0].response_closed is True
