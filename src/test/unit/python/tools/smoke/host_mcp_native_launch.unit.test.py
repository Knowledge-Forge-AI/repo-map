"""PREPARE1 direct-console launch contracts for the host MCP native runner.

A tiny fake console script (a real subprocess, never the product) answers
JSON-RPC lines so launch, environment, EOF, failure, deadline and
classification behavior is exercised without PostgreSQL or Docker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from smoke.host_mcp_native_launch import (
    ALLOWED_CHILD_KEYS, ChildLayout, ChildTracker, Expectation, SessionRecord, child_environment, classify_session,
    console_entrypoint, import_probe, run_session,
)

POISON = {"PGPASSWORD": "poison-admin", "PGPASSFILE": "/poison/pgpass", "PGSERVICE": "poison",
          "PYTHONPATH": "/poison/path", "VIRTUAL_ENV": "/poison/venv", "DOCKER_HOST": "unix:///poison.sock",
          "REPOMAP_MCP_CONFIG": "/poison/mcp.json", "REPOMAP_READ_STATUS_PASSWORD": "poison-read",
          "REPOMAP_PG_PASSWORD": "poison-pg", "OPENAI_API_KEY": "poison-provider", "PYTHONSTARTUP": "/poison"}
INTERPRETER_ADDED = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE", "PYTHONNOUSERSITE"}
FAKE_CONSOLE = f"""#!{sys.executable}
import json, os, subprocess, sys, time
for line in sys.stdin:
    request = json.loads(line)
    mid, method = request.get("id"), request.get("method")
    name = (request.get("params") or {{}}).get("name")
    if method == "initialize":
        result = {{"protocolVersion": "2024-11-05"}}
    elif name == "env":
        result = {{"isError": False, "structuredContent": {{"keys": sorted(os.environ), "cwd": os.getcwd(),
                   "argv": sys.argv[1:]}}}}
    elif name == "refuse":
        result = {{"isError": True, "structuredContent": {{"error": "limit must be between 1 and 200"}}}}
    elif name == "topology":
        result = {{"isError": True, "structuredContent": {{"error": "docker exec into Postgres container failed"}}}}
    elif name == "empty":
        result = {{"isError": False, "structuredContent": {{"items": []}}}}
    elif name == "rpc_error":
        print(json.dumps({{"jsonrpc": "2.0", "id": mid, "error": {{"code": -32601, "message": "nope"}}}}), flush=True)
        continue
    elif name == "malformed":
        print("this is not json", flush=True)
        continue
    elif name == "fail":
        sys.exit(3)
    elif name == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        print(child.pid, file=sys.stderr, flush=True)
        time.sleep(120)
    else:
        result = {{"isError": False, "structuredContent": {{"items": [1]}}}}
    print(json.dumps({{"jsonrpc": "2.0", "id": mid, "result": result}}), flush=True)
"""


def _call(mid: int, name: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": {}}}


@pytest.fixture
def console(tmp_path: Path) -> Path:
    path = tmp_path / "console dir" / "repomap-kg"
    path.parent.mkdir()
    path.write_text(FAKE_CONSOLE, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def layout(tmp_path: Path) -> ChildLayout:
    return ChildLayout(tmp_path / "child").create()


def _run(console: Path, layout: ChildLayout, requests: list[dict], **kwargs) -> SessionRecord:
    env = child_environment(layout, sys.platform)
    return run_session("test", console, layout.root / "home", layout, env, requests, **kwargs)


def test_console_forms_are_classified_by_content_including_a_trampoline_with_spaces(tmp_path: Path) -> None:
    # A kernel shebang cannot carry a spaced path; installers then emit the sh trampoline instead.
    checkout, spaced = tmp_path / "checkout", tmp_path / "check out"
    venv_bin, spaced_bin = checkout / ".venv" / "bin", spaced / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    spaced_bin.mkdir(parents=True)
    body = "import sys\nfrom repomap_kg.cli import main\nif __name__ == '__main__':\n    sys.exit(main())\n"
    shebang = venv_bin / "shebang"
    shebang.write_text(f"#!{venv_bin}/python3\n# -*- coding: utf-8 -*-\n{body}", encoding="utf-8")
    trampoline = spaced_bin / "trampoline"
    trampoline.write_text(f"#!/bin/sh\n'''exec' \"{spaced_bin}/python\" \"$0\" \"$@\"\n' '''\n{body}", encoding="utf-8")
    wrapper = tmp_path / "wrapper"
    wrapper.write_text("#!/bin/sh\nPYTHONPATH=/w exec python3 -c 'from repomap_kg.cli import main; "
                       "raise SystemExit(main())' \"$@\"\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text(f"#!/usr/bin/python3\n{body}", encoding="utf-8")
    unsupported = tmp_path / "unsupported"
    unsupported.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

    first, second = console_entrypoint(shebang), console_entrypoint(trampoline)
    assert (first.form, first.interpreter) == ("absolute-shebang", f"{venv_bin}/python3")
    assert (second.form, second.interpreter) == ("sh-exec-trampoline", f"{spaced_bin}/python")
    assert first.native_refusal(checkout) is None and second.native_refusal(spaced) is None
    assert first.targets_cli_main and len(first.sha256) == 64 and first.shebang_lines[0].startswith("#!")
    assert console_entrypoint(wrapper).form == "runner-provisioned-wrapper"
    assert "not a checkout console" in str(console_entrypoint(wrapper).native_refusal(checkout))
    assert "inside <checkout>/.venv/bin" in str(console_entrypoint(elsewhere).native_refusal(checkout))
    assert console_entrypoint(unsupported).form == "unsupported"


def test_child_environment_is_built_from_scratch_and_blocks_injection(
        console: Path, layout: ChildLayout, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in POISON.items():
        monkeypatch.setenv(key, value)
    env = child_environment(layout, "darwin")
    assert tuple(sorted(env)) == ALLOWED_CHILD_KEYS
    assert env["PATH"].split(":")[0] == str(layout.shims) and env["LANG"] == "en_US.UTF-8"
    assert not any(value in "".join(env.values()) for value in POISON.values())
    assert child_environment(layout, "linux", test_extra_path=("/seam/bin",))["PATH"].split(":")[1] == "/seam/bin"

    record = _run(console, layout, [_call(1, "env")])
    received = set(record.responses[1]["result"]["structuredContent"]["keys"])
    assert not received & set(POISON), "a poisoned parent key reached the child"
    # The exec mapping is exact; an interpreter may add its own keys after exec (for example a Nix
    # Python wrapper sets PYTHONNOUSERSITE, macOS adds __CF_USER_TEXT_ENCODING). Those are not injection.
    assert received - INTERPRETER_ADDED == set(ALLOWED_CHILD_KEYS)
    assert record.jsonable()["exec_env_keys"] == list(ALLOWED_CHILD_KEYS)


def test_clean_eof_session_classifies_every_outcome(console: Path, layout: ChildLayout) -> None:
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                *(_call(mid, name) for mid, name in ((2, "ok"), (3, "refuse"), (4, "ok"), (5, "refuse"), (6, "ok"),
                                                     (7, "rpc_error"), (8, "empty"), (9, "topology"), (10, "refuse")))]
    record = _run(console, layout, requests)
    assert record.returncode == 0 and record.pid and not record.deadline_exceeded
    verdict = classify_session(record, {
        1: Expectation("protocol", "2024-11-05", lambda result: result["protocolVersion"]),
        2: Expectation("positive", {"items": [1]}), 3: Expectation("refusal", "limit must be between 1 and 200"),
        4: Expectation("positive", {"items": [2]}), 5: Expectation("positive", {"items": [1]}),
        6: Expectation("refusal", "x"), 7: Expectation("positive", {}),
        8: Expectation("positive", {"items": []}, nonempty=lambda payload: bool(payload["items"])),
        9: Expectation("bounded_refusal"), 10: Expectation("bounded_refusal"), 11: Expectation("positive", {}),
    })
    assert verdict["messages"] == {
        "1": "protocol_ok", "2": "positive_ok", "3": "expected_refusal_ok", "4": "mismatch",
        "5": "unexpected_refusal", "6": "unexpected_success", "7": "jsonrpc_error", "8": "empty_positive",
        "9": "unbounded_refusal", "10": "expected_refusal_ok", "11": "missing_response"}
    assert verdict["session"] == [] and verdict["ok"] is False


def test_failing_child_and_malformed_line_are_session_failures(console: Path, layout: ChildLayout) -> None:
    failed = _run(console, layout, [_call(1, "ok"), _call(2, "fail")])
    assert failed.returncode == 3
    assert classify_session(failed, {1: Expectation("positive", {"items": [1]})})["session"] == ["child_failed"]
    malformed = _run(console, layout, [_call(1, "malformed"), _call(2, "ok")])
    verdict = classify_session(malformed, {2: Expectation("positive", {"items": [1]})})
    assert malformed.malformed_lines == ["this is not json"] and verdict["session"] == ["malformed_line"]
    assert not verdict["ok"]
    extra = classify_session(malformed, {})
    assert "unexpected_response" in extra["session"]


def test_deadline_kills_only_the_child_group_and_reaps(console: Path, layout: ChildLayout) -> None:
    tracker = ChildTracker()
    record = _run(console, layout, [_call(1, "hang")], deadline=3, tracker=tracker)
    assert record.deadline_exceeded and record.returncode is not None and tracker.live is None
    grandchild = int(record.stderr.split()[0])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the child's own process group survived the deadline")
    assert classify_session(record, {1: Expectation("positive", {})})["session"][:2] == [
        "child_failed", "deadline_exceeded"]
    assert tracker.reap() == {"step": "reap-child", "ok": True, "detail": "no live child"}


def test_unrelated_cwd_contains_a_space_and_restart_is_a_fresh_process(console: Path, layout: ChildLayout) -> None:
    first, second = (_run(console, layout, [_call(1, "env")]) for _ in range(2))
    payload = first.responses[1]["result"]["structuredContent"]
    assert " " in Path(payload["cwd"]).name and Path(payload["cwd"]).resolve() == layout.cwd.resolve()
    assert payload["argv"] == ["mcp", "serve", "--repo-map-home", str(layout.root / "home")]
    assert first.pid != second.pid and first.argv[0] == str(console)


def test_tracker_reaps_a_live_child() -> None:
    tracker = ChildTracker()
    tracker.live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                                    text=True)
    step = tracker.reap()
    assert step["ok"] and tracker.live is None


def test_import_probe_records_success_and_refusal_without_installing(layout: ChildLayout) -> None:
    env = child_environment(layout, "darwin")
    seen: list[tuple] = []

    def runner(argv, **kwargs):
        seen.append((tuple(argv), kwargs["env"], kwargs["cwd"]))
        stdout = json.dumps({"repomap_kg_file": "/c/src/main/python/repomap_kg/__init__.py", "psycopg": "3.2"})
        return subprocess.CompletedProcess(argv, 0, stdout + "\n", "")

    ok = import_probe("/c/.venv/bin/python", layout, env, runner=runner)
    assert ok["ok"] and ok["role"] == "prerequisite-probe-not-acceptance" and seen[0][1] == env
    assert seen[0][2] == layout.cwd and "-I" not in seen[0][0]

    def missing(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "ModuleNotFoundError: No module named 'psycopg'")

    refused = import_probe("/c/.venv/bin/python", layout, env, runner=missing)
    assert refused["ok"] is False and "psycopg" in refused["stderr"]
