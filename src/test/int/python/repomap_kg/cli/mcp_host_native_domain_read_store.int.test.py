"""Host-native stdio MCP reads for the twelve READSTORE3 domain tools.

A real PostgreSQL publication (a tiny mixed-language graph and one RSS
acquisition) is read by a real ``repomap-kg mcp serve`` subprocess that has no
Docker access, no inherited database password, and no source roots. The five
language summaries, six ingested-source reads and legacy ``repomap_status``
must equal the maintained query owners and serializers run as the fixture
admin on the same published records.

Inside the authenticated test sandbox the child is the runner-provisioned
``repomap-kg`` wrapper (recorded as ``launch_mode``). Observed environment keys
are those the harness passed to that wrapper, not the final Python child's
environment. This is neither the operator's macOS checkout console script nor
native host proof.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import shutil
import socket
import sys
import time
import uuid

import pytest

from repomap_kg.runtime.database_roles import READ_STATUS_ROLE
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_test_support.host_mcp_domain_publication import (
    ABSENT_DATABASE, FEED_URL, domain_snapshot, publish_domain_fixture, write_domain_config,
)
from repomap_test_support.host_mcp_domain_reads import build_domain_plan, twelve_tool_requests, verify_domain_plan
from repomap_test_support.host_mcp_publication import (
    RESTORE_LOGIN_SQL, assert_least_privilege, await_no_read_role_backends,
)
from repomap_test_support.host_mcp_stdio import (
    HostMcpHarness, forbidden_env_keys, initialize_request, tool_request, tools_list_request,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres

CATALOG_SHA256 = "c38abd4f5e4da60a3ad3031e4476ff0c0e95552fc7dff149f6a920120a232dde"  # unchanged 27 tools
CANARY_KEY = "REPOMAP_ENV_CANARY_PASSWORD_PROBE"
BAD_ITEM = "python.module:not-a-feed-item"


def test_host_native_stdio_mcp_reads_twelve_domain_tools_without_docker_or_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    for name in ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_READ_STATUS_PASSWORD",
                 "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psycopg")
    with temporary_postgres() as postgres:
        feed_name = f"host_feed_{uuid.uuid4().hex[:10]}"
        feed_db = postgres.create_database(feed_name)
        try:
            _run_proof(tmp_path, postgres, feed_db)
        finally:
            postgres.psql_scalar(RESTORE_LOGIN_SQL)
            postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{feed_name}" WITH (FORCE);')


def _run_proof(tmp_path: Path, postgres, feed_db) -> None:
    publication = publish_domain_fixture(tmp_path, postgres, feed_db)
    assert publication.fetches == (FEED_URL,)  # the only acquisition happened during fixture setup
    assert not (tmp_path / "sources").exists()
    before = domain_snapshot(publication)
    catalog_sha256 = hashlib.sha256(json.dumps(tool_definitions(), sort_keys=True).encode()).hexdigest()
    assert catalog_sha256 == CATALOG_SHA256

    harness = HostMcpHarness(tmp_path / "mcp", publication.home)
    plan = build_domain_plan(publication)
    item_key = plan.chain["item_key"]
    feed = {"project": "host-feed", "source_id": "example-rss-feed"}
    refusals: dict[int, tuple[str, dict[str, object], str]] = {
        900: ("repomap_source_summary", {**feed, "project": "no-such-graph"},
              "unknown legacy MCP project or graph-registry graph_id: no-such-graph"),
        901: ("repomap_python_summary", {"graph_id": "no-such-graph"}, "unknown graph_id: no-such-graph"),
        902: ("repomap_nix_summary", {"graph_id": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        903: ("repomap_ingested_sources", {"project": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        904: ("repomap_status", {"project": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        905: ("repomap_source_runs", {**feed, "source_id": "   "}, "source_id is required"),
        906: ("repomap_source_feed_items", {**feed, "limit": 0}, "limit must be between 1 and 500"),
        907: ("repomap_explain_source_feed_item", {"project": "host-feed", "item_key": BAD_ITEM},
              "item_key must use the feed.item namespace"),
        908: ("repomap_source_references", {**feed, "target_kind": "https://example.invalid"},
              "target_kind must not be a URL"),
        # Absent database: bounded generic Psycopg label on read_configured_graph (disclosed change).
        910: ("repomap_python_summary", {"graph_id": "host-absent"}, "psycopg readback failed for python summary"),
        911: ("repomap_ingested_sources", {"project": "host-absent"},
              "psycopg readback failed for ingested source records"),
        912: ("repomap_status", {"project": "host-absent"}, "psycopg readback failed for canonical storage summary"),
    }
    requests = [initialize_request(1), tools_list_request(2),
                *(tool_request(mid, name, args) for mid, (name, args) in plan.requests.items()),
                *(tool_request(mid, name, args) for mid, (name, args, _text) in refusals.items())]
    session = harness.run(requests)
    assert session.returncode == 0, session.stderr
    assert forbidden_env_keys(session.observed_env_keys) == (), session.observed_env_keys
    assert session.result(1)["protocolVersion"] == "2024-11-05"
    listed = {tool["name"]: tool for tool in session.result(2)["tools"]}
    assert listed == {tool["name"]: tool for tool in tool_definitions()} and len(listed) == 27
    proof = verify_domain_plan(plan, session.structured)
    for message_id, (_name, _args, text) in refusals.items():
        assert session.refusal(message_id) == text, message_id

    assert_least_privilege(postgres, publication.secrets.read_status)
    assert_least_privilege(feed_db, publication.secrets.read_status)
    postgres.psql_scalar(f'ALTER ROLE "{READ_STATUS_ROLE}" NOLOGIN;')
    try:
        denied = harness.run([initialize_request(1), tool_request(2, "repomap_list_graphs", {}),
                              *_requests(twelve_tool_requests(10, summary_graph="host-mixed",
                                                              feed_project="host-feed", item_key=item_key))])
    finally:
        postgres.psql_scalar(f'ALTER ROLE "{READ_STATUS_ROLE}" LOGIN;')
    assert denied.returncode == 0
    assert [g["graph_id"] for g in denied.structured(2)["graphs"]] == ["host-mixed", "host-feed", "host-absent"]
    nologin = _bounded(denied, 10)
    assert set(nologin.values()) <= {f"psycopg readback failed for {label}" for label in _LABELS}, nologin

    restarted = harness.run([initialize_request(1), *_requests({2: plan.requests[420], 3: plan.requests[400],
                                                                4: plan.requests[411]})])
    assert restarted.returncode == 0
    for mid, source in ((2, 420), (3, 400), (4, 411)):
        assert restarted.structured(mid) == session.structured(source), mid
    canary = harness.run([initialize_request(1), tool_request(2, "repomap_list_graphs", {})],
                         extra_env={CANARY_KEY: "synthetic"})
    assert canary.returncode == 0 and CANARY_KEY in canary.observed_env_keys
    assert forbidden_env_keys(canary.observed_env_keys) == (CANARY_KEY,)
    await_no_read_role_backends(postgres)
    assert domain_snapshot(publication) == before
    wrong_password = _wrong_password_session(tmp_path, harness, publication.home, item_key)
    assert domain_snapshot(publication) == before
    absent = _postgres_absent_sessions(tmp_path, harness, item_key)
    assert harness.shim_invocations() == ""
    _emit_evidence(session, denied, restarted, canary, absent, before, catalog_sha256, proof, nologin, refusals,
                   wrong_password)


_LABELS = ("python summary", "terraform summary", "openapi summary", "js framework summary", "nix summary",
           "ingested source records", "source summary", "source run records", "source feed item records",
           "source feed item explanation", "source reference records", "canonical storage summary")


def _requests(calls: dict[int, tuple[str, dict]]) -> list[dict]:
    return [tool_request(mid, name, args) for mid, (name, args) in calls.items()]


def _bounded(session, start: int) -> dict[str, str]:
    """Every one of the twelve reads is a bounded refusal without topology."""

    outcomes: dict[str, str] = {}
    for offset, label in enumerate(_LABELS):
        text = session.refusal(start + offset)
        assert 0 < len(text) <= 300 and "docker" not in text and "Postgres container" not in text, (label, text)
        outcomes[label] = text
    return outcomes


def _wrong_password_session(tmp_path: Path, harness: HostMcpHarness, home: Path, item_key: str) -> dict:
    """A copied home whose read/status secret is wrong: every read is refused."""

    wrong_home = tmp_path / "wrong-password-home"
    shutil.copytree(home, wrong_home)
    env_file = wrong_home / "runtime" / ".env"
    wrong = "wrong-" + secrets.token_hex(8)
    env_file.write_text("".join(
        f"REPOMAP_READ_STATUS_PASSWORD={wrong}\n" if line.startswith("REPOMAP_READ_STATUS_PASSWORD=") else line
        for line in env_file.read_text(encoding="utf-8").splitlines(keepends=True)), encoding="utf-8")
    session = harness.run([initialize_request(1), *_requests(twelve_tool_requests(
        10, summary_graph="host-mixed", feed_project="host-feed", item_key=item_key))], home=wrong_home)
    assert session.returncode == 0
    outcomes = _bounded(session, 10)
    assert all(wrong not in text for text in outcomes.values())
    assert set(outcomes.values()) <= {f"psycopg {phase} failed for {label}" for label in _LABELS
                                      for phase in ("authentication", "connection", "readback")}, outcomes
    shutil.rmtree(wrong_home)
    return {"exit": session.returncode, "outcomes": outcomes}


def _postgres_absent_sessions(tmp_path: Path, harness: HostMcpHarness, item_key: str) -> dict[str, dict]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    outcomes = {}
    for label, direct, port, env in (
        ("closed-host-port", "true", closed_port, {}),
        ("container-internal-psql", "false", 55439, {"REPOMAP_STORAGE_READBACK_DRIVER": "psql"}),
    ):
        home = tmp_path / f"absent-{label}"
        setup_local_runtime(home)
        write_domain_config(home, port, "repomap_absent_mixed", "repomap_absent_feed", tmp_path / "missing-sources")
        config = home / "repomap.rpl.toml"
        config.write_text(config.read_text(encoding="utf-8").replace(
            "direct_host_port_enabled = true", f"direct_host_port_enabled = {direct}"), encoding="utf-8")
        started = time.monotonic()
        absent = harness.run([initialize_request(1), *_requests(twelve_tool_requests(
            10, summary_graph="host-mixed", feed_project="host-feed", item_key=item_key))], home=home, extra_env=env)
        assert absent.returncode == 0, label
        outcomes[label] = {"exit": absent.returncode, "outcomes": _bounded(absent, 10),
                           "bounded_seconds": round(time.monotonic() - started, 1)}
        assert harness.shim_invocations() == "", label
    return outcomes


def _emit_evidence(session, denied, restarted, canary, absent, before, catalog, proof, nologin, refusals,
                   wrong_password) -> None:
    payload = {
        "argv_tail": list(session.argv[1:4]), "launched_executable": Path(session.argv[0]).name,
        "launch_mode": session.launch_mode, "launch_sha256": session.launch_sha256,
        "observed_env_keys": list(session.observed_env_keys),
        "observed_env_scope": "keys passed to the launched executable at the observer final-exec seam; a "
                              "runner-provisioned wrapper adds PYTHONPATH before exec'ing python3",
        "canary_observed_forbidden_keys": list(forbidden_env_keys(canary.observed_env_keys)),
        "catalog_sha256": catalog, "main_exit": session.returncode, "main_responses": len(session.responses),
        "proof": proof, "refusals": {str(mid): session.refusal(mid) for mid in refusals},
        "nologin_exit": denied.returncode, "nologin_outcomes": nologin,
        "restart_exit": restarted.returncode, "canary_exit": canary.returncode, "postgres_absent": absent,
        "wrong_read_password": wrong_password,
        "absent_graph_database": ABSENT_DATABASE, "counts_unchanged": before[1],
        "home_files_unchanged": len(before[0]), "shim_invocations": "",
    }
    stream = getattr(sys, "__stdout__", None)
    if stream is not None:
        stream.write("HOST_MCP_DOMAIN_READSTORE_EVIDENCE=" + json.dumps(payload, sort_keys=True, default=list) + "\n")
        stream.flush()
