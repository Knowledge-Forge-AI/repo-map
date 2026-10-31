"""Real native-tool baseline adapter using git grep --no-index and caller-side handoff helpers (S3)."""

from __future__ import annotations

import os
import selectors
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.retrieval.projection_chunks import frame_digest
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    FallbackDisclosure,
    MatchSurface,
    OmissionRecord,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    refused_envelope,
    unavailable_envelope,
)
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
from portable_handoff import recheck as handoff_recheck
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_views import MaterializedNativeView
from source_navigation_consumer import navigate as consumer_navigate

DEFAULT_GIT_GREP_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_STDOUT_BYTES = 1024 * 1024


def resolve_git_executable() -> str:
    """Resolve the git executable in the current environment."""
    return shutil.which("git") or "/usr/bin/git"


def probe_git_version(git_executable: str | None = None) -> str:
    """Return the version string of the resolved git executable."""
    exe = git_executable or resolve_git_executable()
    try:
        completed = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=3.0, check=False
        )
        return completed.stdout.strip() or "git-unknown"
    except Exception:
        return "git-unavailable"


def build_git_grep_argv(
    pattern: str,
    selected_paths: Sequence[str],
    *,
    git_executable: str = "/usr/bin/git",
    fixed_strings: bool = True,
    ignore_case: bool = False,
) -> tuple[str, ...]:
    """Construct safe single-thread git grep --no-index argv with explicit -e terminator."""
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty string")
    if not selected_paths:
        raise ValueError("selected_paths must be non-empty")
    mode_flag = "-F" if fixed_strings else "-E"
    extra_flags: tuple[str, ...] = ("-i",) if ignore_case else ()
    return (
        git_executable, "--no-pager", "-c", "core.attributesFile=/dev/null",
        "grep", "--no-index", "--threads=1", mode_flag, "-n", "-I", "-z",
        "--no-color", "--no-textconv", *extra_flags, "-e", pattern, "--",
        *tuple(selected_paths),
    )


def classify_git_grep_exit(returncode: int, stderr_text: str) -> str:
    """Classify git grep exit code into completed_match, completed_no_match, or failed."""
    if returncode == 0:
        return "completed_match"
    if returncode == 1 and not stderr_text.strip():
        return "completed_no_match"
    return "failed"


def parse_git_grep_z_output(
    raw_stdout: bytes,
    *,
    path_to_binding: Mapping[str, tuple[str, str]],
) -> tuple[EvaluationLocator, ...]:
    """Parse NUL-delimited git grep -n -z output (path\\0line\\0text\\n) sequentially."""
    if not raw_stdout:
        return ()
    locators: list[EvaluationLocator] = []
    pos = 0
    total_len = len(raw_stdout)
    while pos < total_len:
        if raw_stdout[pos : pos + 1] == b"\n":
            pos += 1
            continue
        nul1 = raw_stdout.find(b"\x00", pos)
        if nul1 == -1:
            raise ValueError("malformed git grep -z output: missing path NUL delimiter")
        nul2 = raw_stdout.find(b"\x00", nul1 + 1)
        if nul2 == -1:
            raise ValueError("malformed git grep -z output: missing line-number NUL delimiter")
        nl = raw_stdout.find(b"\n", nul2 + 1)
        next_pos = total_len if nl == -1 else nl + 1

        rel_view_path = raw_stdout[pos:nul1].decode("utf-8", errors="strict")
        try:
            line_no = int(raw_stdout[nul1 + 1 : nul2].decode("ascii"))
        except ValueError as error:
            raise ValueError("malformed git grep -z output: non-integer line number") from error
        mapped = path_to_binding.get(rel_view_path)
        if mapped is None:
            raise ValueError(f"git grep output referenced unmapped path: {rel_view_path!r}")
        binding_id, source_rel_path = mapped
        locators.append(
            EvaluationLocator(
                binding_id=binding_id,
                source_relative_path=source_rel_path,
                start_line=line_no,
                end_line=line_no,
            ).validate()
        )
        pos = next_pos
    return tuple(locators)


@dataclass(frozen=True)
class GitGrepRunResult:
    """Result of one bounded git grep --no-index child process invocation."""

    status: str
    returncode: int
    stdout_bytes: bytes
    stderr_text: str
    elapsed_ns: int
    argv: tuple[str, ...]


def _kill_and_reap_process_group(proc: subprocess.Popen[bytes]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        except OSError:
            try:
                proc.kill()
            except OSError:
                break
        try:
            proc.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()


def run_git_grep_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float = DEFAULT_GIT_GREP_TIMEOUT_SECONDS,
    max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
) -> GitGrepRunResult:
    """Execute git grep in a new process group with streaming stdout cap and timeout cleanup."""
    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
        "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
    }
    t0, deadline = time.perf_counter_ns(), time.monotonic() + timeout_seconds
    proc = subprocess.Popen(
        list(argv), cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean_env, start_new_session=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    stdout_buf, stderr_buf = bytearray(), bytearray()
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout, selectors.EVENT_READ, "stdout")
            sel.register(proc.stderr, selectors.EVENT_READ, "stderr")
            while sel.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_and_reap_process_group(proc)
                    return GitGrepRunResult("failed_timeout", -1, bytes(stdout_buf), "timeout expired", time.perf_counter_ns() - t0, tuple(argv))
                for key, _ in sel.select(timeout=min(0.1, remaining)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                    elif key.data == "stdout":
                        stdout_buf.extend(chunk)
                        if len(stdout_buf) > max_stdout_bytes:
                            _kill_and_reap_process_group(proc)
                            return GitGrepRunResult(
                                "failed_stdout_overflow", -2, bytes(stdout_buf[:max_stdout_bytes]),
                                "stdout cap exceeded", time.perf_counter_ns() - t0, tuple(argv),
                            )
                    elif len(stderr_buf) < 262144:
                        stderr_buf.extend(chunk[: 262144 - len(stderr_buf)])
        try:
            proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill_and_reap_process_group(proc)
            return GitGrepRunResult("failed_timeout", -1, bytes(stdout_buf), "timeout expired", time.perf_counter_ns() - t0, tuple(argv))
    except BaseException:
        _kill_and_reap_process_group(proc)
        raise
    finally:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
    rc = proc.returncode if proc.returncode is not None else -1
    stderr_text = bytes(stderr_buf).decode("utf-8", errors="replace")
    return GitGrepRunResult(classify_git_grep_exit(rc, stderr_text), rc, bytes(stdout_buf), stderr_text, time.perf_counter_ns() - t0, tuple(argv))


def _execute_direct_handoff_native(
    task: EvaluationTask, view: MaterializedNativeView, scope: QueryScope, requested_mode: QueryMode,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    t0, plan = time.perf_counter_ns(), task.permitted_query_plan
    binding_id, alias, rel_path = str(plan["binding_id"]), str(plan["binding_alias"]), str(plan["source_relative_path"])
    start_line, end_line, expected_sub = int(plan["start_line"]), int(plan["end_line"]), str(plan["expected_substring"])
    repo_id = f"repo:{task.graph_id}"
    nav_res = consumer_navigate(
        graph_id=task.graph_id, repository_identity=repo_id, bindings={binding_id: view.view_root / alias},
        source_check=lambda text: expected_sub in text,
        handoff={"repository_identity": repo_id, "binding_id": binding_id, "source_relative_path": rel_path, "start_line": start_line, "end_line": end_line},
        tool_call=None,
    )
    handoff_record = {
        "version": 1, "task": task.question,
        "references": [{"id": f"ref-{task.task_id}", "repository_identity": repo_id, "root": {"key": alias, "origin": "caller_mapping"}, "source_relative_path": rel_path, "range": [start_line, end_line], "origin": "native", "selection": "direct"}],
        "findings": [], "questions": [], "next_checks": [], "negative_searches": [],
    }
    rechecked = handoff_recheck(
        handoff_record, [f"ref-{task.task_id}"], {(repo_id, "caller_mapping", alias): view.view_root / alias},
        source_check=lambda _ref, text: expected_sub in text,
    )
    elapsed = time.perf_counter_ns() - t0
    verified = nav_res.get("outcome") == "verified" and nav_res.get("graph_calls") == 0 and len(rechecked) == 1 and rechecked[0].get("source_check") is True
    hits = (
        (QueryHit(locator=EvaluationLocator(binding_id, rel_path, start_line, end_line), match_surface=MatchSurface.DIRECT_HANDOFF, rank=1, score=1.0, snippet_digest=frame_digest("sha256", (expected_sub,))),)
        if verified else ()
    )
    env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode, effective_mode=requested_mode,
        match_surface=MatchSurface.DIRECT_HANDOFF, scope=scope, ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE, hits=hits, scope_complete=True,
        provenance={"adapter_id": "native_tools_baseline", "backend": "native_filesystem"},
    ).validate()
    return ExecutionState.COMPLETED, env, elapsed, ByteLayerAccounting(observed_output_payload_bytes=len(expected_sub.encode("utf-8")))


def execute_native_baseline_task(
    task: EvaluationTask,
    view: MaterializedNativeView,
    *,
    git_executable: str | None = None,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    """Execute one evaluation task using real git grep --no-index over the authorized view."""
    requested_mode = QueryMode(task.requested_mode)
    selected_b_ids = tuple(
        sorted(binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings)
    )
    scope = QueryScope(
        graph_id=task.graph_id, backend="native_filesystem",
        selected_binding_ids=selected_b_ids, source_path_prefix=task.source_path_prefix,
    )
    if requested_mode == QueryMode.GRAPH_INVESTIGATION:
        return (
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(requested_mode=requested_mode, scope=scope, reason="native_filesystem_has_no_typed_graph_relationships"),
            0, ByteLayerAccounting(observed_output_payload_bytes=0),
        )
    unauthorized_reasons = [
        view.excluded_bindings[b_id] for b_id in selected_b_ids
        if b_id in view.excluded_bindings and view.excluded_bindings[b_id] != "binding_not_selected"
    ]
    if selected_b_ids and len(unauthorized_reasons) == len(selected_b_ids) and task.intended_match_surface == "captured_text":
        code = unauthorized_reasons[0]
        return (
            ExecutionState.REFUSED,
            refused_envelope(
                requested_mode=requested_mode, scope=scope, refusal_code=code,
                omissions=(OmissionRecord(binding_id=selected_b_ids[0], source_relative_path=None, reason_code=code, detail=f"native view excludes unauthorized body scope ({code})"),),
            ),
            0, ByteLayerAccounting(observed_output_payload_bytes=0),
        )
    plan = task.permitted_query_plan
    if str(plan.get("workflow") or "") == "direct_handoff" or task.intended_match_surface == "direct_handoff":
        return _execute_direct_handoff_native(task, view, scope, requested_mode)

    scoped_paths = [
        p for p in view.selected_relative_paths
        if view.path_to_binding[p][0] in set(selected_b_ids)
        and (task.source_path_prefix is None or view.path_to_binding[p][1].startswith(task.source_path_prefix))
    ]
    surf_actual = (
        MatchSurface.STORED_METADATA
        if (scoped_paths and all(view.path_to_surface.get(p) == MatchSurface.STORED_METADATA for p in scoped_paths))
        or (not scoped_paths and task.intended_match_surface == "extracted_metadata")
        else MatchSurface.CAPTURED_TEXT
    )
    eff_mode = QueryMode.CURRENT_LITERAL_ENUMERATION if surf_actual == MatchSurface.STORED_METADATA else QueryMode.LITERAL_CAPTURED_TEXT
    fb = (
        FallbackDisclosure(caller_selected=True, from_mode=requested_mode, to_mode=eff_mode, reason_code="native_git_grep_fixed_string_scan")
        if requested_mode != eff_mode
        else None
    )
    if not scoped_paths:
        env = QueryEnvelope(
            contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode,
            effective_mode=eff_mode, match_surface=surf_actual, scope=scope,
            ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
            capability_state=CapabilityState.AVAILABLE, hits=(), scope_complete=True, fallback=fb,
        ).validate()
        return ExecutionState.COMPLETED, env, 0, ByteLayerAccounting(0)

    exe = git_executable or resolve_git_executable()
    patterns: list[str] = list(plan.get("patterns") or [str(plan["query"])])
    fixed_strings = bool(plan.get("fixed_strings", True))
    ignore_case = bool(plan.get("ignore_case", False))
    limit = int(plan.get("limit", 10))

    total_elapsed, total_stdout = 0, 0
    scored: dict[tuple[str, str, int], tuple[EvaluationLocator, int]] = {}
    for pat in patterns:
        argv = build_git_grep_argv(
            pat, scoped_paths, git_executable=exe, fixed_strings=fixed_strings, ignore_case=ignore_case
        )
        res = run_git_grep_process(argv, cwd=view.view_root)
        total_elapsed += res.elapsed_ns
        total_stdout += len(res.stdout_bytes)
        if res.status.startswith("failed"):
            failed_env = QueryEnvelope(
                contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode,
                effective_mode=requested_mode, match_surface=MatchSurface.NONE, scope=scope,
                ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
                capability_state=CapabilityState.FAILED,
                provenance={"adapter_id": "native_tools_baseline", "failure_reason": res.status},
            ).validate()
            return (
                ExecutionState.FAILED, failed_env, total_elapsed,
                ByteLayerAccounting(observed_output_payload_bytes=total_stdout),
            )
        for loc in parse_git_grep_z_output(res.stdout_bytes, path_to_binding=view.path_to_binding):
            key = (loc.binding_id, loc.source_relative_path, ((loc.start_line or 1) - 1) // 25)
            prev = scored.get(key)
            scored[key] = (loc, 1) if prev is None else (prev[0], prev[1] + 1)

    ordered = sorted(
        scored.values(),
        key=lambda item: (-item[1], item[0].binding_id, item[0].source_relative_path, item[0].start_line or 0),
    )[:limit]
    hits = tuple(
        QueryHit(locator=loc, match_surface=surf_actual, rank=idx, score=float(score))
        for idx, (loc, score) in enumerate(ordered, start=1)
    )
    env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode,
        effective_mode=eff_mode, match_surface=surf_actual, scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE, hits=hits, scope_complete=True, fallback=fb,
        provenance={
            "adapter_id": "native_tools_baseline",
            "backend": "native_filesystem",
            "binary_files_policy": "-I (binary files skipped)",
        },
    ).validate()
    return (
        ExecutionState.COMPLETED, env, total_elapsed,
        ByteLayerAccounting(observed_output_payload_bytes=total_stdout),
    )
