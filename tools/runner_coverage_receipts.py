"""Invocation-bound child start and terminal receipt readback."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_registered_children(
    child_manifest_dir: Path,
    expected_invocation: str | None = None,
    expected_suite: str | None = None,
    expected_revision: str | None = None,
) -> dict[int, dict[str, Any]]:
    from runner_coverage_capability import _parse_marker

    registered: dict[int, dict[str, Any]] = {}
    if not child_manifest_dir.exists():
        return registered
    for item in sorted(child_manifest_dir.iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".start") or not item.name.removesuffix(".start").isdigit():
            continue
        pid = int(item.name.removesuffix(".start"))
        start = _parse_marker(item)
        inv, suite = start.get("invocation"), start.get("suite")
        if expected_invocation and inv != expected_invocation:
            raise RuntimeError("child invocation identity mismatch")
        if expected_suite and suite != expected_suite:
            raise RuntimeError("child suite identity mismatch")
        if expected_revision and start.get("revision") != expected_revision:
            raise RuntimeError("child source identity mismatch")
        if start.get("pid") != str(pid):
            raise RuntimeError("child start PID identity mismatch")
        terminal_path = child_manifest_dir / f"{pid}.exit"
        terminal = _parse_marker(terminal_path) if terminal_path.exists() else {}
        exited = terminal.get("pid") == str(pid)
        if expected_invocation:
            exited = exited and terminal.get("complete") == "1"
            if exited and any(terminal.get(key) != start.get(key)
                              for key in ("invocation", "suite", "revision", "token", "role", "owner", "ppid", "launch_shape")
                              if key in start or key in terminal):
                raise RuntimeError("child terminal identity mismatch")
        cov_start = start.get("cov_start", "0" if expected_invocation else "1")
        if cov_start not in ("0", "1"):
            raise RuntimeError("invalid child bootstrap status")
        is_aux = start.get("role") == "auxiliary-runtime"
        victim_path = child_manifest_dir / f"{pid}.victim"
        victim = _parse_marker(victim_path) if victim_path.exists() else {}
        victim_receipt = victim if victim.get("pid") == str(pid) else None
        registered[pid] = {
            "exited": exited, "cov_start": int(cov_start), "token": start.get("token"),
            "invocation": inv, "suite": suite,
            "role": start.get("role", "unknown"), "owner": start.get("owner", ""),
            "ppid": int(start["ppid"]) if start.get("ppid") and start["ppid"].isdigit() else None,
            "launch_shape": start.get("launch_shape", ""),
            "bootstrap_error": start.get("bootstrap_error", ""),
            "terminal_error": terminal.get("error", ""),
            "measurement": terminal.get("measurement"),
            "shard": terminal.get("shard"),
            "strict": (expected_invocation is not None) and not is_aux,
            "auxiliary": is_aux,
            "victim_receipt": victim_receipt,
        }
    return registered


def verify_intentional_victim(
    pid: int,
    child_info: dict[str, Any],
    victim_counts: dict[str, int],
) -> bool:
    """Validate intentional non-cooperative victim receipt against maintained obligations."""
    import os
    from runner_integration_obligations import find_intentional_victim_declaration

    victim = child_info.get("victim_receipt")
    decl = find_intentional_victim_declaration(child_info.get("owner"))
    if not (
        decl is not None
        and child_info.get("role") == decl.role
        and victim is not None
        and victim.get("owner") == decl.owner_sha256
        and victim.get("owner") == child_info.get("owner")
        and victim.get("pid") == str(pid)
        and (not child_info.get("ppid") or victim.get("ppid") == str(child_info.get("ppid")))
        and (not child_info.get("invocation") or victim.get("invocation") == child_info.get("invocation"))
        and victim.get("backend_disappeared") == "1"
        and victim.get("descriptor_closed") == "1"
        and victim.get("process_cleaned") == "1"
    ):
        return False
    try:
        exitcode = int(victim.get("exitcode", "0"))
    except ValueError:
        exitcode = 0
    if exitcode not in decl.permitted_exitcodes:
        return False
    try:
        os.kill(pid, 0)
        return False
    except OSError:
        pass
    cur_count = victim_counts.get(decl.owner_sha256, 0)
    if cur_count >= decl.max_victims:
        return False
    victim_counts[decl.owner_sha256] = cur_count + 1
    return True
