"""Installed pure-Local workflow from the exact candidate wheel (ADR 0181, rows L01-L11).

Every child runs from the pure environment's own wrappers or interpreter in an
owned unrelated cwd with a closed environment; there is no editable or source
fallback. The guarded refresh is the only route through the stdlib-only guard.
Facts are witnessed from child outputs, MCP replies and the filesystem, then
reconciled against the frozen intent into one bounded diagnostic bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from common_lore_index.entrypoints import LEGACY_COMMAND_NOTICE
from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.context_contracts import DEFAULT_BUDGET_BYTES
from common_lore_index.server._mcp_dispatch import MCP_PROTOCOL_VERSION
from installed_experience_pins import CODE_KIND, GRAPH_ID
from repomap_kg.server.mcp import LEGACY_MCP_NOTICE
from repomap_test_support.installed_candidate import ROOT, candidate_wheel
from repomap_test_support.installed_environment import ChildResult, run_child
from repomap_test_support.installed_experience_driver import (
    Observed, OwnerRun, blocker_probe, guard_events, guard_extra, guarded_argv, intent_for,
    json_object, observed_code, preparation, pure_environment,
)
from repomap_test_support.installed_experience_fixture import (
    current_config_name, driverless_postgres_home, expectations, message_is_reviewed_public,
    tiny_home, write_tiny_material,
)
from repomap_test_support.installed_mcp_session import McpSession, stderr_class, structured, useful_question
from repomap_test_support.installed_origin import observe_origin
from repomap_test_support.installed_experience_witnesses import origin_source_values, pure_local_origin_witness

OUT, EXIT, FS, MCP, GUARD = "child-stdout", "child-exit", "filesystem", "mcp-reply", "guard-log"


def _stderr(result: ChildResult) -> str:
    return stderr_class(result.stderr, module_notice=LEGACY_MCP_NOTICE, command_notice=LEGACY_COMMAND_NOTICE)


def _absolute_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("/") else []
    if isinstance(value, dict):
        return [item for child in value.values() for item in _absolute_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _absolute_strings(child)]
    return []


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _graph_row(payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = (payload or {}).get("graphs") or []
    return next((row for row in rows if row.get("graph_id", row.get("id")) == GRAPH_ID), {})


def _status(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("storage_status")
    return status if isinstance(status, dict) else {}


def test_installed_local_workflow(tmp_path_factory, tmp_path: Path) -> None:
    candidate = candidate_wheel(tmp_path_factory)
    owned = tmp_path / "owned root"
    env = pure_environment(owned / "pure env", candidate)
    material = write_tiny_material(owned / "owned material" / "tiny")
    home = tiny_home(owned / "owned homes" / "local home", material, config_name=current_config_name())
    backups = owned / "owned backups"
    backups.mkdir(mode=0o700)
    assert message_is_reviewed_public()
    expect = expectations()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    scripts = project["scripts"]
    source = {"L00": origin_source_values(ROOT),
              "L01": {f"{key}_stdout": f"{name} {version}\n" for key, name in (
                  ("cloe", "cloe"), ("long", "common-lore-index"), ("legacy", "repomap-kg"))},
              "L05": {"code_line": expect.code_line}}
    run = OwnerRun("local", intent_for("local", preparation(candidate), source))
    run.registry.own(owned)
    run.step("L00", lambda: pure_local_origin_witness(env, ROOT, scripts))
    cloe = str(env.wrapper("cloe"))
    log = owned / "guard.log"
    database = home / "state" / "sqlite-local" / "graphs" / f"{GRAPH_ID}.sqlite3"
    answers: dict[str, list[str | None]] = {}

    def cli(*args: str) -> ChildResult:
        return run_child(env, (cloe, *args))

    def l01() -> Observed:
        facts: dict[str, tuple[Any, str]] = {}
        for key, name in (("cloe", "cloe"), ("long", "common-lore-index"), ("legacy", "repomap-kg")):
            result = run_child(env, (str(env.wrapper(name)), "--version"))
            if result.returncode != 0:
                return Observed(exit=result.exit, failure_code="child-exit-nonzero")
            facts[f"{key}_stdout"] = (result.stdout, OUT)
            facts[f"{key}_stderr"] = (_stderr(result), OUT)
        return Observed(facts)

    def l02() -> Observed:
        checked = cli("ops", "config-check", "--repo-map-home", str(home), "--json")
        graphs = cli("ops", "graphs", "--repo-map-home", str(home), "--json")
        if checked.returncode != 0 or graphs.returncode != 0:
            return Observed(failure_code="child-exit-nonzero")
        config, listing = json_object(checked.stdout) or {}, json_object(graphs.stdout) or {}
        rows = listing.get("graphs") or []
        paths = _absolute_strings(config) + _absolute_strings(listing)
        owned_paths = bool(paths) and all(Path(item).resolve().is_relative_to(owned.resolve())
                                          for item in paths)
        return Observed({"valid": (config.get("valid"), OUT),
                         "graph_ids": (",".join(str(row.get("graph_id", row.get("id"))) for row in rows), OUT),
                         "storage_backend": ((config.get("storage") or {}).get("backend"), OUT),
                         "public_paths_owned": (owned_paths, OUT)}, exit=checked.exit)

    def l03() -> Observed:
        init = cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH_ID, "--json")
        graphs = cli("ops", "graphs", "--repo-map-home", str(home), "--check-db", "--json")
        if graphs.returncode != 0:
            return Observed(exit=graphs.exit, failure_code="child-exit-nonzero")
        status = _status(_graph_row(json_object(graphs.stdout)))
        return Observed({"init_exit": (init.exit, EXIT), "db_state": (status.get("state"), OUT),
                         "published": (status.get("published"), OUT)}, exit=init.exit)

    def l04() -> Observed:
        preflight = cli("ops", "refresh-preflight", "--repo-map-home", str(home), "--graph", GRAPH_ID, "--json")
        witness = observe_origin(env, ROOT, isolated=False, extra=guard_extra(log))
        refresh = run_child(env, guarded_argv(env, "ops", "refresh-graph", "--repo-map-home", str(home),
                                              "--graph", GRAPH_ID, "--json"), extra=guard_extra(log))
        events = guard_events(log)
        if not log.is_file() or not any(event.get("kind") == "import-info" for event in events):
            return Observed(failure_code="witness-failed")
        forbidden = [event for event in events if event.get("kind") != "import-info"]
        payload = witness.payload or {}
        return Observed({
            "preflight_exit": (preflight.exit, EXIT),
            "accepted_generation": ((json_object(refresh.stdout) or {}).get("accepted_generation"), OUT),
            "forbidden_events": (len(forbidden), GUARD),
            "blocker_probe": ("import-blocked" if blocker_probe(env, owned / "blocker.log")
                              == "import-blocked" else "absent", GUARD),
            "probe_checkout_root_absent": (payload.get("probe_checkout_root_present") is False, OUT),
            "probe_python_path_absent": (payload.get("python_path_set") is False, OUT),
        }, exit=refresh.exit)

    def ask(label: str) -> Observed:
        answer = useful_question(env, (cloe, "mcp", "serve", "--repo-map-home", str(home)),
                                 graph_id=GRAPH_ID, code_query=expect.code_query, code_kind=CODE_KIND,
                                 docs_query=expect.docs_query, protocol=MCP_PROTOCOL_VERSION)
        if not answer.complete:
            return Observed(failure_code="protocol-violation")
        answers[label] = answer.digests
        facts = dict(answer.facts)
        session = McpSession(env, (cloe, "mcp", "serve", "--repo-map-home", str(home)))
        session.request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": "installed-experience", "version": "1"}})
        session.notify("notifications/initialized")
        message = session.call("repomap_search_nodes", {"graph_id": GRAPH_ID,
                                "query": "email.message", "kind": "email.message"})
        transcript = session.close()
        rows = (structured(transcript, message) or {}).get("results") or []
        facts["message_metadata_present"] = (transcript.outcome == "complete" and any(
            row.get("kind") == "email.message" and (row.get("metadata") or {}).get("subject_present") is True
            for row in rows), MCP)
        return Observed(facts, stderr_class=_stderr(ChildResult(0, "", answer.stderr_text)))

    def l06() -> Observed:
        selection = owned / "selection.json"
        bindings = [arg for alias in ("code", "docs")
                    for arg in ("--binding", graph_source_binding_id(GRAPH_ID, alias))]
        selected = cli("ops", "context-select", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                       *bindings, "--pin-publication", "--output", str(selection))
        pin = ((json_object(selected.stdout) or {}).get("expected_publication") or {}).get("generation")
        if selected.returncode != 0:
            return Observed(exit=selected.exit, failure_code="child-exit-nonzero")
        pack = cli("ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                   "--mode", "ranked_discovery", "--query", expect.code_query, "--intent", "implementation",
                   "--selection", str(selection))
        packet = json_object(pack.stdout) or {}
        locations = [loc for item in packet.get("items") or [] for loc in item.get("locations") or []]
        return Observed({
            "pin_generation": (pin, OUT),
            "pack_within_bound": (pack.exit in (0, 3) and len(pack.stdout.encode()) <= DEFAULT_BUDGET_BYTES, OUT),
            "pack_has_code_location": (any(loc.get("source_relative_path") == expect.code_path
                                           for loc in locations), OUT)}, exit=pack.exit)

    def l07() -> Observed:
        target = backups / "b1"
        created = cli("ops", "sqlite-backup", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                      "--output", str(target), "--json")
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8")) if (
            target / "manifest.json").is_file() else {}
        return Observed({"backup_result": ((json_object(created.stdout) or {}).get("result"), OUT),
                         "backup_files": (len(os.listdir(target)) if target.is_dir() else 0, FS),
                         "manifest_graph": ((manifest.get("graph") or {}).get("graph_id"), FS),
                         "manifest_generation": ((manifest.get("publication") or {}).get("generation"), FS)},
                        exit=created.exit)

    def readback(label: str) -> tuple[bool, bool]:
        observed = ask(label)
        same = observed.failure_code is None and answers.get(label) == answers.get("L05")
        return same, not os.path.lexists(material)

    def l08() -> Observed:
        material.rename(material.parent / "hidden tiny")
        same, absent = readback("L08")
        return Observed({"digests_equal": (same, MCP), "material_absent": (absent, FS)})

    def l09() -> Observed:
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)
        restored = cli("ops", "sqlite-restore", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                       "--backup", str(backups / "b1"), "--json")
        if restored.returncode != 0:
            return Observed(exit=restored.exit, failure_code="child-exit-nonzero")
        graphs = cli("ops", "graphs", "--repo-map-home", str(home), "--check-db", "--json")
        if graphs.returncode != 0:
            return Observed(exit=graphs.exit, failure_code="child-exit-nonzero")
        payload = json_object(restored.stdout) or {}
        status = _status(_graph_row(json_object(graphs.stdout)))
        same, absent = readback("L09")
        return Observed({"restore_result": (payload.get("result"), OUT),
                         "schema_state": (payload.get("schema_state"), OUT),
                         "generation": (status.get("accepted_generation"), OUT),
                         "digests_equal": (same, MCP), "material_absent": (absent, FS)}, exit=restored.exit)

    def l10() -> Observed:
        before = _sha(database)
        again = cli("ops", "sqlite-restore", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                    "--backup", str(backups / "b1"), "--json")
        return Observed({"exit": (again.exit, EXIT),
                         "refusal": (observed_code(again.stdout, again.stderr, ("sqlite-restore-target-exists",)), OUT),
                         "database_unchanged": (_sha(database) == before, FS)}, exit=again.exit)

    def l11() -> Observed:
        postgres_home = driverless_postgres_home(owned / "owned homes" / "postgres home", material)
        checked = cli("ops", "config-check", "--repo-map-home", str(postgres_home), "--check-db", "--json")
        probe = run_child(env, (str(env.python), "-I", "-c",
                                "import importlib.util; print(importlib.util.find_spec('psycopg') is None)"))
        if probe.returncode != 0:
            return Observed(exit=probe.exit, failure_code="child-exit-nonzero")
        return Observed({"exit": (checked.exit, EXIT),
                         "refusal": (observed_code(checked.stdout, checked.stderr, ("postgresql-driver-unavailable",)), OUT),
                         "psycopg_absent": (probe.stdout.strip() == "True", OUT)}, exit=checked.exit)

    for scenario, action in (("L01", l01), ("L02", l02), ("L03", l03), ("L04", l04),
                             ("L05", lambda: ask("L05")), ("L06", l06), ("L07", l07), ("L08", l08),
                             ("L09", l09), ("L10", l10), ("L11", l11)):
        run.step(scenario, action)
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted", (verdict.categories, run.mismatches, [
        (row["scenario"], row["outcome"], row["failure_code"]) for row in verdict.rows])
    assert root.is_dir()
