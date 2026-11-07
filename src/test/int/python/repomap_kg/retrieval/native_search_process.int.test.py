"""Integration tests for real native git-grep process execution, timeout cleanup, and caps (S3)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    EvaluationLocator,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_sqlite_corpus,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_native import (
    build_git_grep_argv,
    execute_native_baseline_task,
    probe_git_version,
    resolve_git_executable,
    run_git_grep_process,
)
from retrieval_evaluation_schema import EvaluationTask, GoldTarget
from retrieval_evaluation_views import materialize_native_search_view


def test_real_git_grep_execution_match_no_match_error_and_beyond_cap_advantage(
    tmp_path: Path,
) -> None:
    """Real git grep --no-index executes over materialized native view and finds markers beyond the 262 KiB cap."""
    git_exe = resolve_git_executable()
    version = probe_git_version(git_exe)
    assert "git version" in version.lower()

    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq", wc)
    sq_state = publish_and_load_sqlite_corpus(sq_home)

    view = materialize_native_search_view(
        tmp_path / "native_view",
        manifest=sq_state.manifest,
        bundle=sq_state.bundle,
        store=sq_state.store,
        policy=sq_state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )

    # Exit 0: real match
    argv_match = build_git_grep_argv(
        "ERR_CLOE_MANIFEST_SEAL_MISMATCH_409",
        view.selected_relative_paths,
        git_executable=git_exe,
        fixed_strings=True,
    )
    res_match = run_git_grep_process(argv_match, cwd=view.view_root)
    assert res_match.returncode == 0
    assert res_match.status == "completed_match"
    assert b"core/pkg/pipeline.py" in res_match.stdout_bytes

    # Exit 1: clean no-match
    argv_nomatch = build_git_grep_argv(
        "NONEXISTENT_TOKEN_XYZ_987654321",
        view.selected_relative_paths,
        git_executable=git_exe,
        fixed_strings=True,
    )
    res_nomatch = run_git_grep_process(argv_nomatch, cwd=view.view_root)
    assert res_nomatch.returncode == 1
    assert res_nomatch.status == "completed_no_match"
    assert res_nomatch.stdout_bytes == b""

    # Exit > 1: invalid regex error classification
    argv_err = build_git_grep_argv(
        "[unclosed_regex_group",
        view.selected_relative_paths,
        git_executable=git_exe,
        fixed_strings=False,
    )
    res_err = run_git_grep_process(argv_err, cwd=view.view_root)
    assert res_err.returncode > 1
    assert res_err.status == "failed"

    # stdout overflow cap proof
    argv_overflow = build_git_grep_argv(
        "line",
        view.selected_relative_paths,
        git_executable=git_exe,
        fixed_strings=True,
    )
    res_overflow = run_git_grep_process(
        argv_overflow, cwd=view.view_root, max_stdout_bytes=64
    )
    assert res_overflow.status == "failed_stdout_overflow"

    # Native full-file search finds TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1 beyond 262 KiB cap,
    # whereas captured_projection_reference omits the tail past 262,144 bytes.
    beyond_cap_task = EvaluationTask(
        task_id="int-beyond-cap",
        family="duplicate_paths_quotations_long_unicode",
        split="calibration",
        question="Locate TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1 beyond the 262 KiB projection cap.",
        permitted_query_plan={
            "mode": "literal_captured_text",
            "query": "TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1",
            "fixed_strings": True,
            "limit": 5,
        },
        graph_id=MIXED_V1_GRAPH_ID,
        generation=1,
        selected_bindings=("core", "companion"),
        source_path_prefix=None,
        requested_mode="literal_captured_text",
        intended_match_surface="captured_text",
        comparability_stratum="body",
        comparator_exposure={
            "native_tools_baseline": "full_file_bytes",
            "captured_projection_reference": "bounded_262kib_prefix",
        },
        gold_targets=(
            GoldTarget(
                locator=EvaluationLocator(
                    binding_id=binding_id_for_alias("companion"),
                    source_relative_path="generated/truncatable_prose.md",
                ),
                relevance_grade=3,
                rationale="Marker beyond 262 KiB cap in truncatable_prose.md",
            ),
        ),
        expected_capability_state="available",
        expected_refusal_code=None,
        grading_rule="ranked_positive",
    )
    exec_state, native_env, _el, _bytes = execute_native_baseline_task(
        beyond_cap_task, view, git_executable=git_exe
    )
    assert exec_state == ExecutionState.COMPLETED
    assert native_env.capability_state == CapabilityState.AVAILABLE
    assert any(
        h.locator.source_relative_path == "generated/truncatable_prose.md"
        for h in native_env.hits
    )
    assert_canary_free(native_env.to_dict())

    proj = build_captured_text_projection(sq_state.projection_inputs(), sq_state.policy)
    proj_env = query_captured_text(
        proj,
        CapturedTextQueryRequest(
            query="TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1",
            selected_binding_ids=(
                binding_id_for_alias("core"),
                binding_id_for_alias("companion"),
            ),
            limit=5,
        ),
        current_accepted_reference=sq_state.accepted_reference,
    )
    assert len(proj_env.hits) == 0
    assert proj_env.scope_complete is False


def test_git_grep_timeout_process_group_cleanup_and_cli_validate_subprocess(
    tmp_path: Path,
) -> None:
    """Real slow child process group is killed/reaped on timeout, and CLI validate runs as observed child."""
    pid_file = tmp_path / "grandchild.pid"
    slow_git = tmp_path / "slow_git.sh"
    slow_git.write_text(
        "#!/bin/sh\n"
        "sleep 60 &\n"
        f"echo \"$!\" > '{pid_file}'\n"
        "printf 'partial_line_without_eof'\n"
        "sleep 60\n",
        encoding="utf-8",
    )
    os.chmod(slow_git, 0o755)

    f = tmp_path / "sample.txt"
    f.write_text("hello world\n", encoding="utf-8")
    argv = build_git_grep_argv(
        "hello", ("sample.txt",), git_executable=str(slow_git), fixed_strings=True
    )
    res = run_git_grep_process(argv, cwd=tmp_path, timeout_seconds=0.35)
    assert res.status == "failed_timeout"
    assert res.returncode == -1
    assert res.stdout_bytes == b"partial_line_without_eof"
    assert pid_file.is_file()
    gc_pid = int(pid_file.read_text(encoding="utf-8").strip())
    with pytest.raises(ProcessLookupError):
        os.kill(gc_pid, 0)

    # Also verify real CLI subprocess execution via launch_observed_process with owned timeout cleanup
    from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
    from runner_coverage_observer import launch_observed_process

    repo_root = MIXED_V1_FIXTURE_ROOT.parents[4]
    cli_script = repo_root / "tools" / "retrieval_evaluation.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{repo_root / 'src/main/python'}:"
        f"{repo_root / 'src/test/support/python'}:"
        f"{repo_root / 'tools'}"
    )
    completed = launch_observed_process(
        [
            sys.executable,
            str(cli_script),
            "validate",
            "--catalog",
            str(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"),
            "--freeze",
            str(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"),
        ],
        family="cli_module",
        pid_namespace_relation="shared",
        cwd=repo_root,
        env=env,
        timeout=30.0,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "valid"' in completed.stdout


def test_retrieval_mcp_navigation_session_and_post_deletion_projection_separation(
    tmp_path: Path,
) -> None:
    """Guarded SQLite MCP navigation session over mixed-v1 and post-working-copy-deletion projection build."""
    import shutil

    from repomap_test_support.sqlite_local_harness import (
        LocalHarness,
        initialize,
        structured,
        tool,
    )

    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq", wc)
    sq_state = publish_and_load_sqlite_corpus(sq_home)
    shutil.rmtree(wc)

    proj = build_captured_text_projection(sq_state.projection_inputs(), sq_state.policy)
    assert len(proj.projected_files) > 0
    assert any(f.source_relative_path == "pkg/pipeline.py" for f in proj.projected_files)

    scratch = tmp_path / "mcp-nav-scratch"
    harness = LocalHarness(scratch, block_psycopg=True)
    args = {
        "graph_id": MIXED_V1_GRAPH_ID,
        "query": "pipeline",
        "scope": "code",
        "grouping": "none",
        "limit": 1,
    }
    requests = [
        initialize(1),
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        tool(2, "repomap_navigation_search", args),
        tool(3, "repomap_navigation_search", {**args, "offset": 1}),
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        tool(
            5,
            "repomap_navigation_search",
            {
                **args,
                "source_binding_id": binding_id_for_alias("core"),
                "source_path_prefix": "pkg/pipeline.py",
            },
        ),
    ]
    responses = harness.mcp(sq_home, requests)
    assert_canary_free(responses)
    assert set(responses.keys()) == {1, 2, 3, 4, 5}
    first = structured(responses, 2)
    assert first["schema"] == "repomap.navigation_search" and first["status"] == "ok"
    scoped = structured(responses, 5)
    assert scoped["status"] == "ok" and len(scoped["results"]) >= 1
    assert harness.forbidden_events() == []
    assert list(scratch.glob(".mcp-stdin-*.jsonl")) == []
    assert list(scratch.glob("mcp-stdin-*.jsonl")) == []
