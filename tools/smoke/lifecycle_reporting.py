"""Reporting and fixture helpers for the bounded smoke lifecycle."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from repomap_kg.ops.readback import MISSING_DATABASE_MESSAGE
from repomap_kg.ops.refresh import MISSING_DATABASE_DIAGNOSTIC_CODE


_ALLOWLISTED_RESULTS = frozenset({"success", "failure"})
_ALLOWLISTED_SEVERITIES = frozenset({"error", "warning", "info"})
_ALLOWLISTED_DIAGNOSTIC_CODES = frozenset(
    {
        MISSING_DATABASE_DIAGNOSTIC_CODE,
        "storage-status-unavailable",
        "storage-schema-unavailable",
        "authentication-failed",
        "configuration-error",
    }
)


def _bounded_smoke_failure_summary(
    completed: subprocess.CompletedProcess[str],
    *,
    stage: str = "post-drop-readback",
) -> dict[str, Any]:
    """Summarize expected-failure mismatch without leaking raw output or secrets."""
    exit_code = completed.returncode
    exit_classification = (
        "failure"
        if exit_code == 1
        else ("success" if exit_code == 0 else f"code_{exit_code}")
    )
    valid_json = valid_document = valid_graph = valid_diagnostics = False
    document: Any
    graph: Any
    diagnostics: Any
    first_diag: Any
    document = graph = diagnostics = first_diag = None
    try:
        document = json.loads(completed.stdout)
        valid_json = True
    except (json.JSONDecodeError, TypeError):
        pass
    if isinstance(document, dict):
        valid_document = True
        graph = document.get("graph")
        if isinstance(graph, dict):
            valid_graph = True
            diagnostics = graph.get("diagnostics")
            if isinstance(diagnostics, list):
                valid_diagnostics = True
                if diagnostics and isinstance(diagnostics[0], dict):
                    first_diag = diagnostics[0]

    command_val = document.get("command") if valid_document else None
    result_val = document.get("result") if valid_document else None
    graph_result = graph.get("result") if valid_graph else None
    db_checked = graph.get("db_checked") if valid_graph else None
    repo_exists = graph.get("repository_exists") if valid_graph else None
    code_val = first_diag.get("code") if isinstance(first_diag, dict) else None
    severity_val = first_diag.get("severity") if isinstance(first_diag, dict) else None
    message_matches = (
        first_diag.get("message") == MISSING_DATABASE_MESSAGE
        if isinstance(first_diag, dict)
        else False
    )

    def allowlisted(value: Any, values: frozenset[str]) -> str | None:
        if isinstance(value, str) and value in values:
            return value
        return "unknown" if value is not None else None

    predicates = {
        "exit_1": exit_code == 1,
        "valid_json": valid_json,
        "valid_document": valid_document,
        "cmd_graph_summary": command_val == "graph-summary",
        "result_failure": result_val == "failure",
        "graph_failure": graph_result == "failure",
        "db_checked_true": db_checked is True,
        "repo_exists_false": repo_exists is False,
        "diag_len_1": len(diagnostics) == 1
        if valid_diagnostics and isinstance(diagnostics, list)
        else False,
        "diag_code_missing": code_val == MISSING_DATABASE_DIAGNOSTIC_CODE,
        "diag_severity_error": severity_val == "error",
        "diag_message_match": message_matches,
    }
    return {
        "stage": stage,
        "exit_classification": exit_classification,
        "valid_json": valid_json,
        "valid_graph": valid_graph,
        "result": allowlisted(result_val, _ALLOWLISTED_RESULTS),
        "graph_result": allowlisted(graph_result, _ALLOWLISTED_RESULTS),
        "db_checked": db_checked if isinstance(db_checked, bool) else None,
        "repository_exists": repo_exists if isinstance(repo_exists, bool) else None,
        "diagnostics_count": len(diagnostics) if valid_diagnostics else 0,
        "diagnostic_code": allowlisted(code_val, _ALLOWLISTED_DIAGNOSTIC_CODES),
        "diagnostic_severity": allowlisted(severity_val, _ALLOWLISTED_SEVERITIES),
        "diagnostic_message_matched": message_matches,
        "violated": [key for key, passed in predicates.items() if not passed],
    }


def validate_target_database_absent(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    """Require the exact public graph-summary result for an absent database."""
    try:
        document = json.loads(completed.stdout)
        graph = document["graph"]
        diagnostics = graph["diagnostics"]
        diagnostic = diagnostics[0]
        valid = (
            completed.returncode == 1
            and document["command"] == "graph-summary"
            and document["result"] == "failure"
            and graph["result"] == "failure"
            and graph["db_checked"] is True
            and graph["repository_exists"] is False
            and len(diagnostics) == 1
            and diagnostic["code"] == MISSING_DATABASE_DIAGNOSTIC_CODE
            and diagnostic["severity"] == "error"
            and diagnostic["message"] == MISSING_DATABASE_MESSAGE
        )
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        valid, document = False, {}
    if not valid:
        try:
            detail = f": {json.dumps(_bounded_smoke_failure_summary(completed), sort_keys=True)}"
        except Exception:
            detail = ""
        raise RuntimeError(f"product command did not prove typed target absence{detail}")
    return document


def validate_control_graph_readback(document: dict[str, Any] | None) -> None:
    graph = document.get("graph") if document else None
    if (
        document is None
        or not isinstance(graph, dict)
        or document.get("result") != "success"
        or graph.get("result") != "success"
        or graph.get("repository_exists") is not True
        or int(graph.get("files") or 0) <= 0
    ):
        raise RuntimeError("control graph was incoherent after target drop")


def _private_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            values[key] = value
    return values


def _write_fixture(path: Path, name: str) -> None:
    path.mkdir(parents=True)
    (path / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    (path / "module.py").write_text(
        f"def {name}_value() -> str:\n    return {name!r}\n", encoding="utf-8"
    )


def _write_config(home: Path, port: int, target: Path, control: Path) -> None:
    graph_blocks = [
        f'''[[graphs]]
id = "{graph_id}"
name = "Smoke {graph_id.title()}"
root_path = "{root}"
repository_name = "smoke-{graph_id}"
database = "{database}"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
'''
        for graph_id, database, root in (
            ("target", "repomap_smoke_target", target),
            ("control", "repomap_smoke_control", control),
        )
    ]
    text = f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "docker"
server_host_port = 8765
bind_host = "127.0.0.1"

[runtime.postgres]
direct_host_port_enabled = true
host_port = {port}
bind_host = "127.0.0.1"

[postgres]
host = "127.0.0.1"
port = {port}
database = "repomap_smoke_target"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"

{"".join(graph_blocks)}
[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
'''
    (home / "repomap.rpl.toml").write_text(text, encoding="utf-8")
