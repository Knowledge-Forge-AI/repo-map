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

    dirs_to_check = [child_manifest_dir]
    if child_manifest_dir.parent.exists() and child_manifest_dir.parent != child_manifest_dir:
        dirs_to_check.append(child_manifest_dir.parent)

    for check_dir in dirs_to_check:
        for item in sorted(check_dir.iterdir(), key=lambda p: p.name):
            if not item.name.endswith(".registration_failure"):
                continue
            fail_data = _parse_marker(item)
            fail_pid_str = fail_data.get("pid")
            if not fail_pid_str or not fail_pid_str.isdigit():
                continue
            pid = int(fail_pid_str)
            fail_inv = fail_data.get("invocation")
            fail_suite = fail_data.get("suite")
            fail_rev = fail_data.get("revision")
            if expected_invocation and fail_inv != expected_invocation:
                raise RuntimeError("child invocation identity mismatch")
            if expected_suite and fail_suite != expected_suite:
                raise RuntimeError("child suite identity mismatch")
            if expected_revision and fail_rev != expected_revision:
                raise RuntimeError("child source identity mismatch")
            registered[pid] = {
                "registration_failure": True,
                "pid": pid,
                "ppid": int(fail_data["ppid"]) if fail_data.get("ppid", "").isdigit() else None,
                "invocation": fail_inv,
                "suite": fail_suite,
                "revision": fail_rev,
                "role": fail_data.get("role", "unknown"),
                "owner": fail_data.get("owner", ""),
                "launch_shape": fail_data.get("launch_shape", ""),
                "has_config": fail_data.get("has_config") == "1",
                "has_manifest": fail_data.get("has_manifest") == "1",
                "has_token": fail_data.get("has_token") == "1",
                "token_hash": fail_data.get("token_hash", ""),
                "bootstrap_stage": fail_data.get("bootstrap_stage", ""),
                "failure_class": fail_data.get("failure_class", "unknown_failure"),
                "failure_reason": fail_data.get("failure_reason", "unknown"),
                "exited": True,
                "cov_start": 0,
                "strict": True,
                "auxiliary": False,
                "victim_receipt": None,
            }

    for item in sorted(child_manifest_dir.iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".start") or not item.name.removesuffix(".start").isdigit():
            continue
        pid = int(item.name.removesuffix(".start"))
        if pid in registered and registered[pid].get("registration_failure"):
            continue
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
        cov_start_raw = start.get("cov_start", "0" if expected_invocation else "1")
        if cov_start_raw not in ("0", "1", "pending"):
            raise RuntimeError("invalid child bootstrap status")
        is_pending = (cov_start_raw == "pending")
        cov_start = 0 if is_pending else int(cov_start_raw)
        bootstrap_error = start.get("bootstrap_error", "") or ("registration_incomplete" if is_pending else "")
        is_aux = start.get("role") == "auxiliary-runtime"
        victim_path = child_manifest_dir / f"{pid}.victim"
        victim = _parse_marker(victim_path) if victim_path.exists() else {}
        victim_receipt = victim if victim.get("pid") == str(pid) else None
        registered[pid] = {
            "exited": exited, "cov_start": cov_start, "token": start.get("token"),
            "invocation": inv, "suite": suite, "revision": start.get("revision"),
            "role": start.get("role", "unknown"), "owner": start.get("owner", ""),
            "ppid": int(start["ppid"]) if start.get("ppid") and start["ppid"].isdigit() else None,
            "launch_shape": start.get("launch_shape", ""),
            "bootstrap_error": bootstrap_error,
            "terminal_error": terminal.get("error", ""),
            "measurement": terminal.get("measurement"),
            "shard": terminal.get("shard"),
            "strict": (expected_invocation is not None) and not is_aux,
            "auxiliary": is_aux,
            "victim_receipt": victim_receipt,
            "is_pending": is_pending,
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
