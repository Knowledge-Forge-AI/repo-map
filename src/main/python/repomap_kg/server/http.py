"""Long-running local read-only server mode for RepoMap runtime containers."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.ops.config import (
    OpsConfig,
    OpsConfigError,
    check_ops_postgres_status,
    graph_database,
    load_ops_config_home,
    resolve_repo_map_home,
)
from repomap_kg.runtime.database_role_contract import project_read_status_config

LOCAL_BIND_HOSTS = frozenset(("127.0.0.1", "localhost", "::1"))
CONTAINER_INTERNAL_BIND_HOST = "0.0.0.0"
HTTP_RESULT_SCHEMA_VERSION = 1
HTTP_GRAPH_COUNT_MAX = 200
HTTP_DIAGNOSTIC_COUNT_MAX = 100
HTTP_RESPONSE_MAX_BYTES = 8 * 1024
HTTP_ENDPOINTS = ("/livez", "/healthz", "/readyz", "/status")


class LocalServerError(ValueError):
    """Raised when the local server cannot start safely."""


def validate_server_bind_host(
    host: str,
    *,
    allow_container_internal: bool = False,
) -> None:
    """Validate server bind host for local-only operation."""

    if host in LOCAL_BIND_HOSTS:
        return
    if allow_container_internal and host == CONTAINER_INTERNAL_BIND_HOST:
        return
    raise ValueError("server host must be localhost-only")


def _base_http_payload() -> dict[str, Any]:
    return {
        "schema_version": HTTP_RESULT_SCHEMA_VERSION,
        "service": "repomap",
        "version": __version__,
        "local_only": True,
        "endpoints": list(HTTP_ENDPOINTS),
        "safety": read_only_safety_payload(),
    }


def build_liveness_payload() -> dict[str, Any]:
    return {
        **_base_http_payload(),
        "check": "liveness",
        "status": "live",
    }


def build_health_payload(repo_map_home: str | Path | None) -> dict[str, Any]:
    home = resolve_repo_map_home(repo_map_home)
    _, configuration = _load_configuration_check(home)
    return {
        **_base_http_payload(),
        "check": "configuration",
        **configuration,
    }


def build_readiness_payload(repo_map_home: str | Path | None) -> dict[str, Any]:
    home = resolve_repo_map_home(repo_map_home)
    config, configuration = _load_configuration_check(home)
    readiness = _readiness_check(config, configuration=configuration)
    return {
        **_base_http_payload(),
        "check": "readiness",
        **readiness,
        "graph_count": readiness["storage"]["checked_graph_count"],
        "graph_count_limit": HTTP_GRAPH_COUNT_MAX,
        "graph_count_truncated": configuration["graph_count_truncated"],
        "configuration": configuration,
    }


def build_status_payload(repo_map_home: str | Path | None) -> dict[str, Any]:
    home = resolve_repo_map_home(repo_map_home)
    config, configuration = _load_configuration_check(home)
    readiness = _readiness_check(config, configuration=configuration)
    graph_count = readiness["storage"]["checked_graph_count"]
    return {
        **_base_http_payload(),
        "status": readiness["status"],
        "graph_count": graph_count,
        "graph_count_limit": HTTP_GRAPH_COUNT_MAX,
        "graph_count_truncated": configuration["graph_count_truncated"],
        "checks": {
            "liveness": {"status": "live"},
            "configuration": {
                key: configuration[key]
                for key in (
                    "status",
                    "graph_count",
                    "graph_count_limit",
                    "graph_count_truncated",
                    "diagnostic_count",
                    "diagnostic_count_limit",
                    "diagnostic_count_truncated",
                )
            },
            "storage": readiness["storage"],
            "schema": readiness["schema"],
        },
    }


def _load_configuration_check(
    repo_map_home: Path,
) -> tuple[OpsConfig | None, dict[str, Any]]:
    config, diagnostic_count, diagnostic_count_truncated = load_config_for_server(
        repo_map_home
    )
    return config, _configuration_check(
        config,
        diagnostic_count=diagnostic_count,
        diagnostic_count_truncated=diagnostic_count_truncated,
    )


def load_config_for_server(
    repo_map_home: Path,
) -> tuple[OpsConfig | None, int, bool]:
    try:
        config = project_read_status_config(load_ops_config_home(repo_map_home))
    except OpsConfigError as error:
        diagnostic_count, truncated = _bounded_count(
            len(error.diagnostics),
            HTTP_DIAGNOSTIC_COUNT_MAX,
        )
        return None, diagnostic_count, truncated
    diagnostic_count, truncated = _bounded_count(
        len(config.diagnostics),
        HTTP_DIAGNOSTIC_COUNT_MAX,
    )
    return config, diagnostic_count, truncated


def _configuration_check(
    config: OpsConfig | None,
    *,
    diagnostic_count: int,
    diagnostic_count_truncated: bool,
) -> dict[str, Any]:
    total_graph_count = len(config.graphs) if config else 0
    graph_count, graph_count_truncated = _bounded_count(
        total_graph_count,
        HTTP_GRAPH_COUNT_MAX,
    )
    return {
        "status": (
            "healthy" if config is not None and not graph_count_truncated else "unhealthy"
        ),
        "graph_count": graph_count,
        "graph_count_limit": HTTP_GRAPH_COUNT_MAX,
        "graph_count_truncated": graph_count_truncated,
        "diagnostic_count": diagnostic_count,
        "diagnostic_count_limit": HTTP_DIAGNOSTIC_COUNT_MAX,
        "diagnostic_count_truncated": diagnostic_count_truncated,
    }


def _readiness_check(
    config: OpsConfig | None,
    *,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    graphs = tuple(config.graphs) if config else ()
    selected_graphs = graphs[:HTTP_GRAPH_COUNT_MAX]
    statuses = (
        tuple(
            check_ops_postgres_status(
                config,
                database=graph_database(config, graph),
            )
            for graph in selected_graphs
        )
        if config is not None
        else ()
    )
    checked_graph_count = len(statuses)
    storage_ready_graph_count = sum(status.connected is True for status in statuses)
    schema_ready_graph_count = sum(
        status.connected is True and status.schema_available is True
        for status in statuses
    )
    config_available = (
        config is not None and not configuration["graph_count_truncated"]
    )
    storage_ready = config_available and storage_ready_graph_count == checked_graph_count
    schema_ready = config_available and schema_ready_graph_count == checked_graph_count
    storage = {
        "status": "ready" if storage_ready else "not_ready",
        "checked_graph_count": checked_graph_count,
        "ready_graph_count": storage_ready_graph_count,
    }
    schema = {
        "status": "ready" if schema_ready else "not_ready",
        "checked_graph_count": checked_graph_count,
        "ready_graph_count": schema_ready_graph_count,
    }
    ready = (
        configuration["status"] == "healthy"
        and storage_ready
        and schema_ready
    )
    return {
        "status": "ready" if ready else "not_ready",
        "storage": storage,
        "schema": schema,
    }


def _bounded_count(value: int, limit: int) -> tuple[int, bool]:
    return min(value, limit), value > limit


def read_only_safety_payload() -> dict[str, bool]:
    return {
        "graph_roots_read": False,
        "server_memory_read": False,
        "server_memory_mutated": False,
        "source_trees_mutated": False,
        "destructive_db_actions": False,
        "source_acquisition": False,
        "public_tunnel": False,
        "remote_postgres": False,
    }


class RepoMapLocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        repo_map_home: Path,
    ) -> None:
        super().__init__(server_address, RepoMapLocalRequestHandler)
        self.repo_map_home = repo_map_home


class RepoMapLocalRequestHandler(BaseHTTPRequestHandler):
    server: RepoMapLocalServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path == "/livez":
            self.write_json(build_liveness_payload(), status=200)
            return
        if path == "/healthz":
            payload = build_health_payload(self.server.repo_map_home)
            self.write_json(
                payload,
                status=200 if payload["status"] == "healthy" else 503,
            )
            return
        if path == "/readyz":
            payload = build_readiness_payload(self.server.repo_map_home)
            self.write_json(
                payload,
                status=200 if payload["status"] == "ready" else 503,
            )
            return
        if path == "/status":
            payload = build_status_payload(self.server.repo_map_home)
            self.write_json(payload, status=200)
            return
        self.write_json(
            {
                **_base_http_payload(),
                "status": "not_found",
                "error": "unknown endpoint",
            },
            status=404,
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def write_json(self, payload: dict[str, Any], *, status: int) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(body) > HTTP_RESPONSE_MAX_BYTES:
            status = 500
            body = json.dumps(
                {
                    **_base_http_payload(),
                    "status": "response_too_large",
                },
                sort_keys=True,
            ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_local_http(
    repo_map_home: str | Path | None,
    *,
    host: str,
    port: int,
    allow_container_internal: bool = False,
) -> int:
    try:
        validate_server_bind_host(
            host,
            allow_container_internal=allow_container_internal,
        )
    except ValueError as error:
        raise LocalServerError(str(error)) from error
    home = resolve_repo_map_home(repo_map_home)
    server = RepoMapLocalServer((host, port), home)
    print(
        f"RepoMap local server listening on {host}:{port}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
