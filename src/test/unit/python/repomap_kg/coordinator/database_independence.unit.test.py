from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from repomap_kg.coordinator._portable_authority import _validate_audit_event
from repomap_kg.coordinator._worker_environment import build_portable_worker_environment


def test_coverage_instrumentation_introduces_sqlite3_positive_control(tmp_path: Path) -> None:
    """Positive control proving coverage instrumentation introduces sqlite3 at process startup."""
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import coverage\ncoverage.process_startup()\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    env["COVERAGE_PROCESS_START"] = "/dev/null"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps(sorted(sys.modules)))",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = set(json.loads(probe.stdout))
    assert "sqlite3" in loaded, "Expected sqlite3 in sys.modules when coverage process startup is active"


def test_portable_environment_is_closed_against_database_credentials_and_proxies(tmp_path) -> None:
    environment = build_portable_worker_environment(
        workspace_root=tmp_path,
        python_path=Path("/opt/repomap/python"),
    )

    prohibited_prefixes = (
        "PG",
        "DATABASE",
        "PSQL",
        "GIT",
        "SSH",
        "AWS",
        "GOOGLE",
        "AZURE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    )
    assert not any(key.upper().startswith(prohibited_prefixes) for key in environment)
    assert environment["PATH"] == ""
    assert set(environment) <= {
        "HOME", "LANG", "LC_ALL", "PATH", "PYTHONPATH", "TMPDIR", "SystemRoot"
    }


def test_portable_worker_import_graph_does_not_reach_database_modules() -> None:
    prohibited_modules = {
        "psycopg",
        "psycopg2",
        "sqlite3",
        "repomap_kg.coordinator._control_client",
        "repomap_kg.coordinator._control_schema",
        "repomap_kg.storage.staged_ingestion",
        "repomap_kg.storage.staging_copy",
        "repomap_kg.storage.staging_resource_observability",
    }
    clean_env = os.environ.copy()
    cov_config = clean_env.pop("COVERAGE_PROCESS_START", None)
    session_dir = Path(cov_config).parent.resolve() if cov_config else None
    orig_pythonpath = clean_env.get("PYTHONPATH", "")
    if orig_pythonpath:
        filtered_parts = []
        for p in orig_pythonpath.split(os.pathsep):
            try:
                resolved_p = Path(p).resolve()
            except OSError:
                resolved_p = None
            if session_dir is not None and resolved_p == session_dir:
                continue
            if "repomap-coverage-session-" in p:
                continue
            filtered_parts.append(p)
        if filtered_parts:
            clean_env["PYTHONPATH"] = os.pathsep.join(filtered_parts)
        else:
            clean_env.pop("PYTHONPATH", None)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; "
            "import repomap_kg.coordinator.portable_worker; "
            "import repomap_kg.coordinator._portable_semantic_adapter; "
            "import repomap_kg.coordinator._portable_materialization; "
            "print(json.dumps(sorted(sys.modules)))",
        ],
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = set(json.loads(probe.stdout))
    assert not (loaded & prohibited_modules), f"Prohibited modules imported: {loaded & prohibited_modules}"


@pytest.mark.parametrize(
    ("event", "args"),
    (
        ("import", ("psycopg",)),
        ("import", ("repomap_kg.storage.staged_publication",)),
        ("import", ("repomap_kg.coordinator.local_lifecycle",)),
        ("import", ("repomap_kg.registry",)),
        ("socket.__new__", (object(),)),
        ("socket.connect", (object(), ("127.0.0.1", 5432))),
        ("subprocess.Popen", ("git",)),
        ("os.posix_spawn", ("nix",)),
        ("os.fork", ()),
        ("os.forkpty", ()),
        ("os.system", ("nix build",)),
        ("open", ("/unowned/source.py", "r", 0)),
        ("open", ("/unowned/output", "w", 0)),
    ),
)
def test_runtime_authority_guard_denies_unowned_operations(event, args, tmp_path) -> None:
    with pytest.raises(PermissionError):
        _validate_audit_event(
            event,
            args,
            (tmp_path / "store", tmp_path / "workspace", tmp_path / "code"),
            (tmp_path / "store", tmp_path / "workspace"),
        )


def test_runtime_authority_guard_allows_only_owned_store_workspace_and_code_reads(tmp_path) -> None:
    store = tmp_path / "store"
    workspace = tmp_path / "workspace"
    code = tmp_path / "code"
    for root in (store, workspace, code):
        root.mkdir()

    _validate_audit_event("open", (store / "object", "r", 0), (store, workspace, code), (store, workspace))
    _validate_audit_event("open", (workspace / "output", "w", 0), (store, workspace, code), (store, workspace))
    _validate_audit_event("open", (code / "module.py", "r", 0), (store, workspace, code), (store, workspace))
