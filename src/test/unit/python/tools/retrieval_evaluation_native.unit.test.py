"""Unit tests for native git-grep argv construction, NUL-delimited framing, and exit semantics (S3)."""

from __future__ import annotations

import pytest

from retrieval_evaluation_native import (
    build_git_grep_argv,
    classify_git_grep_exit,
    parse_git_grep_z_output,
)


def test_git_grep_argv_enforces_safe_single_thread_fixed_string_flags() -> None:
    """build_git_grep_argv constructs an argv vector with -F -n -I -z --threads=1 and -e terminator."""
    argv = build_git_grep_argv(
        "--malicious-looking-pattern",
        ("core/pkg/pipeline.py", "companion/docs/architecture.md"),
        git_executable="/usr/bin/git",
    )
    assert argv == (
        "/usr/bin/git",
        "--no-pager",
        "-c",
        "core.attributesFile=/dev/null",
        "grep",
        "--no-index",
        "--threads=1",
        "-F",
        "-n",
        "-I",
        "-z",
        "--no-color",
        "--no-textconv",
        "-e",
        "--malicious-looking-pattern",
        "--",
        "core/pkg/pipeline.py",
        "companion/docs/architecture.md",
    )

    with pytest.raises(ValueError, match="non-empty"):
        build_git_grep_argv("", ("core/pkg/pipeline.py",))
    with pytest.raises(ValueError, match="selected_paths"):
        build_git_grep_argv("token", ())


def test_parse_git_grep_z_output_handles_colons_newlines_and_rejects_malformed_framing() -> None:
    """NUL-delimited git grep -z -n output parses path\\0line\\0text\\n and fails closed on bad framing."""
    raw = (
        b"core/pkg/colon:name.py\x0042\x00def key: value = 'a:b:c'\n"
        b"companion/docs/line\nbreak.md\x007\x00Heading: overview\n"
    )
    mapping = {
        "core/pkg/colon:name.py": ("bind1:core", "pkg/colon:name.py"),
        "companion/docs/line\nbreak.md": ("bind1:companion", "docs/line\nbreak.md"),
    }
    locators = parse_git_grep_z_output(raw, path_to_binding=mapping)
    assert len(locators) == 2
    assert locators[0].binding_id == "bind1:core"
    assert locators[0].source_relative_path == "pkg/colon:name.py"
    assert locators[0].start_line == 42 and locators[0].end_line == 42
    assert locators[1].binding_id == "bind1:companion"
    assert locators[1].source_relative_path == "docs/line\nbreak.md"
    assert locators[1].start_line == 7 and locators[1].end_line == 7

    for bad_raw in (
        b"no_nul_delimiter_at_all\n",
        b"core/pkg/colon:name.py\x00missing_second_nul\n",
        b"core/pkg/colon:name.py\x00not_an_int\x00text\n",
        b"unmapped/file.py\x0010\x00text\n",
    ):
        with pytest.raises(ValueError):
            parse_git_grep_z_output(bad_raw, path_to_binding=mapping)


def test_git_grep_exit_code_classification_distinguishes_no_match_from_failure() -> None:
    """Exit code 0 is match, 1 with empty stderr is no-match, and >1 or error stderr is failure."""
    assert classify_git_grep_exit(0, "") == "completed_match"
    assert classify_git_grep_exit(1, "") == "completed_no_match"
    assert classify_git_grep_exit(1, "fatal: bad flag") == "failed"
    assert classify_git_grep_exit(2, "fatal: error") == "failed"
    assert classify_git_grep_exit(128, "fatal: error") == "failed"
