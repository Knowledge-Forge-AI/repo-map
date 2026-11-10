"""Installed canonical and finite legacy stdio MCP over a published tiny graph (rows M01-M07).

Every server is the pure environment's own wrapper or ``python -m`` module in an
owned unrelated cwd, read through a bounded session with its own deadline,
stream caps and kill/reap. Protocol version, ``tools/list`` digest and legacy
notices are source constants computed in this process before any child runs.
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any

from common_lore_index.entrypoints import LEGACY_COMMAND_NOTICE
from common_lore_index.server._mcp_dispatch import MCP_PROTOCOL_VERSION
from common_lore_index.server.mcp_schemas import tool_definitions
from installed_experience_pins import CODE_KIND, GRAPH_ID
from repomap_kg.server.mcp import LEGACY_MCP_NOTICE
from repomap_test_support.installed_candidate import ROOT, candidate_wheel
from repomap_test_support.installed_environment import run_child
from repomap_test_support.installed_experience_driver import (
    Observed, OwnerRun, intent_for, preparation, publish_tiny, pure_environment,
)
from repomap_test_support.installed_experience_fixture import (
    current_config_name, expectations, tiny_home, write_tiny_material,
)
from repomap_test_support.installed_mcp_session import (
    McpSession, result_digest, stderr_class, useful_question,
)
from repomap_test_support.installed_experience_witnesses import origin_source_values, pure_local_origin_witness

OUT, MCP, FS = "child-stdout", "mcp-reply", "filesystem"


def _line(text: str) -> str:
    """The single stderr line, or ``other`` when stderr is not exactly one line."""
    return text[:-1] if text.endswith("\n") and text.count("\n") == 1 else "other"


def _klass(text: str) -> str:
    return stderr_class(text, module_notice=LEGACY_MCP_NOTICE, command_notice=LEGACY_COMMAND_NOTICE)


def _snapshot(home: Path, database: Path) -> tuple[str, list[str]]:
    attempts = home / "state" / "portable-publication" / "sqlite-local" / GRAPH_ID / "attempts"
    listing = sorted(os.listdir(attempts)) if attempts.is_dir() else []
    return hashlib.sha256(database.read_bytes()).hexdigest(), listing


def test_installed_mcp_canonical_and_legacy_servers(tmp_path_factory, tmp_path: Path) -> None:
    candidate = candidate_wheel(tmp_path_factory)
    owned = tmp_path / "owned root"
    env = pure_environment(owned / "pure env", candidate)
    material = write_tiny_material(owned / "owned material" / "tiny")
    home = tiny_home(owned / "owned homes" / "mcp home", material, config_name=current_config_name())
    expect = expectations()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    scripts = project["scripts"]
    tools_sha = result_digest({"tools": tool_definitions()})
    source = {"M00": origin_source_values(ROOT),
              "M01": {"protocol_version": MCP_PROTOCOL_VERSION, "tools_sha256": tools_sha},
              "M02": {"tools_sha256": tools_sha}, "M03": {"stderr_line": LEGACY_MCP_NOTICE},
              "M04": {"stderr_line": LEGACY_COMMAND_NOTICE},
              "M05": {"stdout": f"repomap-kg {version}\n", "stderr_line": LEGACY_COMMAND_NOTICE}}
    run = OwnerRun("mcp", intent_for("mcp", preparation(candidate), source))
    run.registry.own(owned)
    run.step("M00", lambda: pure_local_origin_witness(env, ROOT, scripts))
    database = home / "state" / "sqlite-local" / "graphs" / f"{GRAPH_ID}.sqlite3"
    selector = {"CLOE_HOME": str(home)}
    state: dict[str, Any] = {}

    def ask(argv: tuple[str, ...], extra: dict[str, str] | None = None) -> Any:
        return useful_question(env, argv, graph_id=GRAPH_ID, code_query=expect.code_query,
                               code_kind=CODE_KIND, docs_query=expect.docs_query,
                               protocol=MCP_PROTOCOL_VERSION, extra=extra)

    def found(answer: Any) -> bool:
        facts = answer.facts
        return (facts.get("code_kind", (None,))[0] == CODE_KIND
                and facts.get("code_path", (None,))[0] == expect.code_path
                and facts.get("code_line", (None,))[0] == expect.code_line
                and facts.get("docs_path", (None,))[0] == expect.docs_path)

    def m01() -> Observed:
        if publish_tiny(env, home, owned / "guard.log", GRAPH_ID) != 1:
            return Observed(failure_code="prerequisite-failed")
        state["before"] = _snapshot(home, database)
        answer = ask((str(env.wrapper("cloe")), "mcp", "serve", "--repo-map-home", str(home)))
        if not answer.complete:
            return Observed(failure_code="protocol-violation")
        state["digests"] = answer.digests
        return Observed({"protocol_version": (answer.protocol_version, MCP),
                         "tools_sha256": (answer.tools_sha256, MCP),
                         "stderr_class": (_klass(answer.stderr_text), OUT),
                         "useful_member_found": (found(answer), MCP)})

    def m02() -> Observed:
        answer = ask((str(env.python), "-m", "common_lore_index.server.mcp"), selector)
        return Observed({"tools_sha256": (answer.tools_sha256, MCP),
                         "digests_equal": (answer.complete and answer.digests == state.get("digests"), MCP),
                         "stderr_class": (_klass(answer.stderr_text), OUT)})

    def legacy(argv: tuple[str, ...], extra: dict[str, str] | None) -> Observed:
        answer = ask(argv, extra)
        return Observed({"stderr_line": (_line(answer.stderr_text), OUT),
                         "digests_equal": (answer.complete and answer.digests == state.get("digests"), MCP)})

    def m05() -> Observed:
        result = run_child(env, (str(env.python), "-m", "repomap_kg", "--version"))
        return Observed({"stdout": (result.stdout, OUT), "stderr_line": (_line(result.stderr), OUT)},
                        exit=result.exit)

    def m06() -> Observed:
        session = McpSession(env, (str(env.wrapper("cloe")), "mcp", "serve", "--repo-map-home", str(home)))
        session.request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": "installed-experience", "version": "1"}})
        session.notify("notifications/initialized")
        unknown = session.call("repomap_installed_experience_absent", {})
        invalid = session.call("repomap_navigation_search",
                               {"graph_id": GRAPH_ID, "query": expect.code_query, "limit": 0})
        session.malformed()
        valid = session.call("repomap_navigation_search",
                             {"graph_id": GRAPH_ID, "query": expect.code_query, "scope": "code"})
        transcript = session.close()
        if transcript.outcome != "complete":
            return Observed(failure_code="protocol-violation")
        replies = transcript.replies
        malformed = replies.get(None) or {}
        return Observed({
            "unknown_tool_error": ((replies.get(unknown) or {}).get("is_error"), MCP),
            "invalid_limit_error": ((replies.get(invalid) or {}).get("is_error"), MCP),
            "malformed_code": (str(malformed.get("error_code")), MCP),
            "malformed_id_null": (None in replies, MCP),
            "valid_call_ok": ((replies.get(valid) or {}).get("is_error") is False, MCP)})

    def m07() -> Observed:
        sha, listing = _snapshot(home, database)
        before_sha, before_listing = state.get("before", (None, None))
        return Observed({"database_unchanged": (sha == before_sha, FS),
                         "attempts_unchanged": (listing == before_listing, FS)})

    steps = (("M01", m01), ("M02", m02),
             ("M03", lambda: legacy((str(env.python), "-m", "repomap_kg.server.mcp"), selector)),
             ("M04", lambda: legacy((str(env.wrapper("repomap-kg")), "mcp", "serve", "--repo-map-home",
                                     str(home)), None)),
             ("M05", m05), ("M06", m06), ("M07", m07))
    for scenario, action in steps:
        run.step(scenario, action)
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted", (verdict.categories, run.mismatches, [
        (row["scenario"], row["outcome"], row["failure_code"]) for row in verdict.rows])
    assert root.is_dir()
