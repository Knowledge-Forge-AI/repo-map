import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.config_loading import load_ops_config_home
from repomap_kg.ops.config_records import OpsPostgresStatus
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.server.http import RepoMapLocalRequestHandler, RepoMapLocalServer, serve_local_http
from repomap_test_support.cli_integration import OPS_CONFIG_TEMPLATE


class _TestHandler(RepoMapLocalRequestHandler):
    wfile: io.BytesIO
    response_status: int
    header_entries: list[tuple[str, str]]

    def __init__(self, path: str, home: Path) -> None:
        self.path = path
        self.server = object.__new__(RepoMapLocalServer)
        self.server.repo_map_home = home
        self.wfile = io.BytesIO()
        self.response_status = 0
        self.header_entries = []

    def send_response(self, code: int, message: str | None = None) -> None:
        self.response_status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.header_entries.append((keyword, value))

    def end_headers(self) -> None:
        pass


class LocalServerUnitTests(unittest.TestCase):
    def test_health_and_status_payloads_are_bounded_and_read_only(self):
        from repomap_kg.server.http import (
            HTTP_RESPONSE_MAX_BYTES,
            build_health_payload,
            build_status_payload,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            with patch(
                "repomap_kg.server.http.check_ops_postgres_status",
                return_value=OpsPostgresStatus(
                    db_checked=True,
                    connected=True,
                    schema_available=True,
                    required_tables={"canonical_nodes": True},
                ),
            ):
                health = build_health_payload(home)
                status = build_status_payload(home)

        self.assertEqual(health["service"], "repomap")
        self.assertEqual(health["schema_version"], 1)
        self.assertEqual(health["check"], "configuration")
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["local_only"])
        self.assertEqual(health["graph_count"], 1)
        self.assertFalse(health["safety"]["graph_roots_read"])
        self.assertFalse(health["safety"]["server_memory_read"])
        self.assertFalse(health["safety"]["destructive_db_actions"])
        self.assertEqual(status["service"], "repomap")
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["checks"]["liveness"]["status"], "live")
        self.assertEqual(status["checks"]["configuration"]["status"], "healthy")
        self.assertEqual(status["checks"]["storage"]["status"], "ready")
        self.assertEqual(status["checks"]["schema"]["status"], "ready")
        rendered = json.dumps(status, sort_keys=True)
        self.assertNotIn(str(home), rendered)
        self.assertNotIn("repo-map", rendered)
        self.assertNotIn("repository_name", rendered)
        self.assertNotIn("database", rendered)
        self.assertNotIn("diagnostics", rendered)
        self.assertLessEqual(len(rendered.encode("utf-8")), HTTP_RESPONSE_MAX_BYTES)

    def test_public_bind_is_rejected_unless_container_internal(self):
        from repomap_kg.server.http import (
            LocalServerError,
            serve_local_http,
            validate_server_bind_host,
        )

        validate_server_bind_host("127.0.0.1")
        validate_server_bind_host("localhost")
        validate_server_bind_host("::1")
        validate_server_bind_host("0.0.0.0", allow_container_internal=True)
        with self.assertRaises(ValueError):
            validate_server_bind_host("0.0.0.0")
        with self.assertRaises(LocalServerError):
            serve_local_http(None, host="0.0.0.0", port=55880)

    def test_health_reports_config_error_without_reading_roots(self):
        from repomap_kg.server.http import build_health_payload, build_status_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()

            with patch(
                "repomap_kg.server.http.check_ops_postgres_status"
            ) as postgres_status:
                health = build_health_payload(home)
                status = build_status_payload(home)

        self.assertEqual(health["status"], "unhealthy")
        self.assertEqual(health["graph_count"], 0)
        self.assertGreaterEqual(health["diagnostic_count"], 1)
        self.assertNotIn("diagnostics", health)
        self.assertEqual(status["status"], "not_ready")
        self.assertEqual(status["checks"]["liveness"]["status"], "live")
        self.assertEqual(status["checks"]["storage"]["status"], "not_ready")
        self.assertEqual(status["checks"]["schema"]["status"], "not_ready")
        self.assertFalse(status["safety"]["graph_roots_read"])
        postgres_status.assert_not_called()

    def test_status_uses_one_configuration_snapshot(self):
        from repomap_kg.server.http import build_status_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            config = load_ops_config_home(home)

            with (
                patch(
                    "repomap_kg.server.http.load_config_for_server",
                    return_value=(config, 0, False),
                ) as load_config,
                patch(
                    "repomap_kg.server.http.check_ops_postgres_status",
                    return_value=OpsPostgresStatus(
                        db_checked=True,
                        connected=True,
                        schema_available=True,
                        required_tables={},
                    ),
                ),
            ):
                status = build_status_payload(home)

        self.assertEqual(status["status"], "ready")
        load_config.assert_called_once_with(home)

    def test_readiness_separates_storage_and_schema_failure(self):
        from repomap_kg.server.http import build_readiness_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            with patch(
                "repomap_kg.server.http.check_ops_postgres_status",
                return_value=OpsPostgresStatus(
                    db_checked=True,
                    connected=False,
                    schema_available=False,
                    required_tables={},
                    error=f"private failure at {home}",
                ),
            ):
                storage_down = build_readiness_payload(home)
            with patch(
                "repomap_kg.server.http.check_ops_postgres_status",
                return_value=OpsPostgresStatus(
                    db_checked=True,
                    connected=True,
                    schema_available=False,
                    required_tables={"canonical_nodes": False},
                    error="private schema detail",
                ),
            ):
                schema_down = build_readiness_payload(home)

        self.assertEqual(storage_down["storage"]["status"], "not_ready")
        self.assertEqual(storage_down["schema"]["status"], "not_ready")
        self.assertEqual(schema_down["storage"]["status"], "ready")
        self.assertEqual(schema_down["schema"]["status"], "not_ready")
        rendered = json.dumps((storage_down, schema_down), sort_keys=True)
        self.assertNotIn(str(home), rendered)
        self.assertNotIn("private schema detail", rendered)

    def test_readiness_caps_graph_probes(self):
        from repomap_kg.server.http import HTTP_GRAPH_COUNT_MAX, build_readiness_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            config = load_ops_config_home(home)
            graph = config.graphs[0]
            graphs = tuple(
                replace(
                    graph,
                    id=f"graph-{index}",
                    repository_name=f"repository-{index}",
                    database=f"graph_database_{index}",
                )
                for index in range(HTTP_GRAPH_COUNT_MAX + 7)
            )
            config = replace(config, graphs=graphs)

            with (
                patch(
                    "repomap_kg.server.http.load_config_for_server",
                    return_value=(config, 0, False),
                ),
                patch(
                    "repomap_kg.server.http.check_ops_postgres_status",
                    return_value=OpsPostgresStatus(
                        db_checked=True,
                        connected=True,
                        schema_available=True,
                        required_tables={},
                    ),
                ) as postgres_status,
            ):
                readiness = build_readiness_payload(home)

        self.assertEqual(postgres_status.call_count, HTTP_GRAPH_COUNT_MAX)
        self.assertEqual(readiness["status"], "not_ready")
        self.assertEqual(readiness["graph_count"], HTTP_GRAPH_COUNT_MAX)
        self.assertTrue(readiness["graph_count_truncated"])

    def test_request_handler_serves_health_status_and_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            with patch(
                "repomap_kg.server.http.check_ops_postgres_status",
                return_value=OpsPostgresStatus(
                    db_checked=True,
                    connected=True,
                    schema_available=True,
                    required_tables={},
                ),
            ):
                live_status, live = self.call_handler("/livez", home)
                health_status, health = self.call_handler("/healthz", home)
                ready_status, ready = self.call_handler("/readyz", home)
                status_status, status = self.call_handler("/status", home)
                missing_status, missing = self.call_handler("/missing", home)

        self.assertEqual(live_status, 200)
        self.assertEqual(live["status"], "live")
        self.assertEqual(health_status, 200)
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(ready_status, 200)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(status_status, 200)
        self.assertEqual(status["status"], "ready")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing["schema_version"], 1)
        self.assertEqual(missing["status"], "not_found")
        missing_safety = missing["safety"]
        assert isinstance(missing_safety, dict)
        self.assertFalse(missing_safety["destructive_db_actions"])

    def test_response_size_guard_replaces_oversized_payload(self):
        from repomap_kg.server.http import HTTP_RESPONSE_MAX_BYTES

        handler = self.new_handler("/missing", Path("/tmp/fixture"))
        handler.write_json({"value": "x" * HTTP_RESPONSE_MAX_BYTES}, status=200)

        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(handler.response_status, 500)
        self.assertEqual(payload["status"], "response_too_large")
        self.assertLessEqual(len(handler.wfile.getvalue()), HTTP_RESPONSE_MAX_BYTES)

    def test_serve_local_http_starts_and_closes_server(self):
        from repomap_kg.server.http import serve_local_http

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            calls: list[tuple[str, object]] = []

            class FakeServer:
                def __init__(self, address, repo_map_home):
                    calls.append(("init", (address, repo_map_home)))

                def serve_forever(self):
                    calls.append(("serve_forever", None))
                    raise KeyboardInterrupt

                def server_close(self):
                    calls.append(("server_close", None))

            with patch("repomap_kg.server.http.RepoMapLocalServer", FakeServer):
                result = serve_local_http(
                    home,
                    host="0.0.0.0",
                    port=55880,
                    allow_container_internal=True,
                )

        self.assertEqual(result, 0)
        self.assertEqual(calls[0][0], "init")
        self.assertEqual(calls[1][0], "serve_forever")
        self.assertEqual(calls[2][0], "server_close")

    def test_serve_local_http_handles_sigterm_gracefully(self):
        import signal
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"; home.mkdir()
            (home / "repomap.rpl.toml").write_text(OPS_CONFIG_TEMPLATE, encoding="utf-8")
            calls: list[tuple[str, object]] = []

            class FakeServer:
                def __init__(self, address, repo_map_home):
                    calls.append(("init", (address, repo_map_home)))

                def serve_forever(self):
                    calls.append(("serve_forever", None))
                    os.kill(os.getpid(), signal.SIGTERM)

                def server_close(self):
                    calls.append(("server_close", None))

            with patch("repomap_kg.server.http.RepoMapLocalServer", FakeServer):
                result = serve_local_http(home, host="127.0.0.1", port=55882)

        self.assertEqual(result, 0)
        self.assertEqual(calls[0][0], "init")
        self.assertEqual(calls[1][0], "serve_forever")
        self.assertEqual(calls[2][0], "server_close")

    def test_server_serve_http_child_coverage_settlement(self):
        import coverage, socket, subprocess, time, urllib.request
        from runner_coverage import ChildCoverageSession
        repo_root = Path(__file__).resolve().parents[6]
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"; home.mkdir()
            (home / "repomap.rpl.toml").write_text(OPS_CONFIG_TEMPLATE, encoding="utf-8")
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
            session = ChildCoverageSession(
                coverage_module=coverage, scratch_dir=Path(tmpdir) / "session",
                source_root=repo_root / "src" / "main" / "python", suite="staging",
            )
            with session:
                runner = session.create_coverage(coverage); runner.start()
                cmd = [sys.executable, "-m", "repomap_kg", "server", "serve",
                       "--repo-map-home", str(home), "--host", "127.0.0.1", "--port", str(port)]
                process = subprocess.Popen(
                    cmd, cwd=repo_root, env=os.environ.copy(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    ready = False
                    for _ in range(50):
                        time.sleep(0.1)
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=1) as resp:
                                if resp.status == 200: ready = True; break
                        except Exception: pass
                    self.assertTrue(ready, "server failed to become ready")
                finally:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                    runner.stop(); runner.save()

                self.assertEqual(process.returncode, 0)
                pid = process.pid
                self.assertTrue((session.child_manifest_dir / f"{pid}.start").is_file())
                self.assertTrue((session.child_manifest_dir / f"{pid}.exit").is_file())
                self.assertEqual(list(session.child_manifest_dir.glob("unsettled*")), [])
                combined = session.combine(runner)
                self.assertIsNotNone(combined)
                self.assertTrue(any("http.py" in f for f in combined.get_data().measured_files()))

    def call_handler(self, path: str, home: Path) -> tuple[int, dict[str, object]]:
        handler = self.new_handler(path, home)
        handler.do_GET()
        handler.log_message("ignored %s", "message")
        payload: dict[str, object] = json.loads(handler.wfile.getvalue().decode("utf-8"))
        return handler.response_status, payload

    def new_handler(self, path: str, home: Path) -> _TestHandler:
        return _TestHandler(path, home)


if __name__ == "__main__":
    unittest.main()
