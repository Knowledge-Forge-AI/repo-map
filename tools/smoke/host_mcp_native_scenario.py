"""The ordered host MCP native scenario: fixture, oracles, sessions, state, outage.

Passed to ``host_mcp_native_run.execute_run``, which owns cleanup and
evidence finalization. Every MCP process here is the selected console script
launched directly; expected refusals are classified separately from
unexpected failures, and a check that cannot be evaluated is a failure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any

from repomap_test_support.host_mcp_publication import assert_least_privilege, await_no_read_role_backends

from .host_mcp_native_checks import (
    OUTAGE_READS, RESTART_IDS, build_native_plan, catalog_digest, chain_checks, requests_for,
)
from .host_mcp_native_fixture import (
    FEED_URL, SECRET_FILE, VISIBLE_GRAPHS, fixture_inputs, fixture_state, public_state, publish_native_fixture,
    route_record,
)
from .host_mcp_native_launch import (
    ChildLayout, ChildTracker, Expectation, SessionRecord, classify_session, run_session,
)
from .host_mcp_native_run import RunContext, RunInterrupted, write_pgpass

COMPLETED = "completed_pending_manager_review"


def run_scenario(context: RunContext, backend: Any, console: Path, layout: ChildLayout, env: Mapping[str, str],
                 tracker: ChildTracker, summary: dict[str, Any]) -> str:
    evidence, checks = context.evidence, dict[str, bool]()
    admin = backend.start()
    evidence.add_secret(getattr(admin, "password", None))
    write_pgpass(context.work, admin)
    token = secrets.token_hex(4)
    databases = {"host-multi": backend.create_database(f"native_multi_{token}"),
                 "host-feed": backend.create_database(f"native_feed_{token}")}
    fixture = publish_native_fixture(context.work, admin.user, databases, admin.port)
    evidence.add_env_file_secrets(fixture.home / SECRET_FILE)
    route = {**route_record(fixture.home, admin.port), "backend": backend.route_evidence()}
    before = fixture_state(fixture)
    evidence.write_json("fixture.json", {
        "graphs": {"visible": list(VISIBLE_GRAPHS), "hidden": ["host-hidden"]},
        "databases": {graph_id: database.database for graph_id, database in databases.items()},
        "home": str(fixture.home), "publication_roots": fixture.roots, "setup_fetches": list(fixture.fetches),
        "inputs": {name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                   for name, path in fixture_inputs().items()},
        "route": route, "state_before_mcp": public_state(before),
    })
    checks.update(route_agrees=bool(route["agrees"]), only_setup_fetch=fixture.fetches == (FEED_URL,),
                  sources_absent_before_mcp=before["sources_absent"])
    plan = build_native_plan(fixture)
    evidence.write_json("oracle.json", {"chain": plan.chain, "messages": plan.oracle()})

    def session(label: str, requests: list[dict[str, Any]], expectations: Mapping[int, Expectation]) -> SessionRecord:
        record = run_session(label, console, fixture.home, layout, env, requests, tracker=tracker)
        verdict = classify_session(record, expectations)
        evidence.write_json(f"session-{label}.json", {**record.jsonable(), "classification": verdict})
        checks[f"session_{label}"] = verdict["ok"]
        return record

    main = session("main", requests_for(plan), plan.expectations)
    tools = (main.responses.get(2, {}).get("result") or {}).get("tools") or []
    summary["catalog"] = {"mcp_tools": len(tools), "mcp_list_sha256": catalog_digest(tools),
                          "tool_definitions_sha256": plan.chain["catalog_sha256"]}
    checks.update({f"chain_{name}": ok for name, ok in chain_checks(plan, main.responses).items()})
    failures: dict[str, str] = {}
    for graph_id, database in databases.items():
        name = f"write_denied_{graph_id}"
        checks[name] = _probe(partial(assert_least_privilege, database, fixture.secrets.read_status), failures,
                              name)
    checks["read_role_backends_ended_main"] = _probe(lambda: await_no_read_role_backends(admin), failures,
                                                     "read_role_backends_ended_main")

    restart_expect = {1: plan.expectations[1], **{mid: Expectation("positive", _payload(main, mid))
                                                  for mid in RESTART_IDS}}
    restart = session("restart", requests_for(plan, RESTART_IDS), restart_expect)
    checks["restart_fresh_process"] = restart.pid is not None and restart.pid != main.pid
    checks["read_role_backends_ended_restart"] = _probe(lambda: await_no_read_role_backends(admin), failures,
                                                        "read_role_backends_ended_restart")
    after = fixture_state(fixture)
    checks["state_unchanged"] = after == before
    checks["sources_still_absent"] = after["sources_absent"]
    checks["no_shim_invocations_before_outage"] = layout.shim_invocations() == ""
    evidence.write_json("state-after-mcp.json", {"state": public_state(after), "unchanged": after == before})

    stopped = backend.stop_for_outage()
    outage_expect = {1: plan.expectations[1], 10: plan.expectations[10],
                     **{mid: Expectation("bounded_refusal") for mid in OUTAGE_READS}}
    session("outage", requests_for(plan, (10, *OUTAGE_READS)), outage_expect)
    checks["outage_still_in_effect"] = backend.outage_active()
    checks["no_shim_invocations"] = layout.shim_invocations() == ""
    evidence.write_json("outage.json", {"stop": stopped, "families": OUTAGE_READS,
                                        "still_in_effect_after_mcp": checks["outage_still_in_effect"],
                                        "shim_invocations": layout.shim_invocations()})
    summary.update(checks=checks, probe_failures=failures, pids={"main": main.pid, "restart": restart.pid},
                   chain=plan.chain)
    evidence.write_json("checks.json", {"checks": checks, "probe_failures": failures})
    return COMPLETED if checks and all(checks.values()) else "checks_failed"


def _payload(record: SessionRecord, mid: int) -> Any:
    response = record.responses.get(mid, {})
    return json.loads(json.dumps((response.get("result") or {}).get("structuredContent"), sort_keys=True))


def _probe(check: Callable[[], Any], failures: dict[str, str], name: str) -> bool:
    """Run a maintained assertion helper; any failure (including pytest outcomes) is ``False``."""
    try:
        check()
    except (RunInterrupted, KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:
        failures[name] = f"{type(error).__name__}: {error}"[:500]
        return False
    return True
