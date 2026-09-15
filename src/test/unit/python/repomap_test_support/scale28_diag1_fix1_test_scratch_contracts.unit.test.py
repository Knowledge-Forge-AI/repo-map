"""SCALE28-FIX12-DIAG1-FIX1: the repository-owned test scratch authority.

These tests were written before the owner existed. They pin the properties the
former environment failures needed: one selected root, one exclusively
allocated short run, a complete child environment that every subprocess
receives, a tempfile cache that cannot outrank the new root, socket paths
checked in encoded bytes, and a terminal state that cannot be quietly
reclassified.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support.test_scratch import (
    ENV_PHASE,
    ENV_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
    MAX_SOCKET_PATH_BYTES,
    TestScratchError,
    TestScratchLayout,
    socket_component_byte_capacity,
    establish_run,
    finalize_run,
    short_test_directory,
)

CHILD_ENVIRONMENT_KEYS = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONPYCACHEPREFIX",
    "GOTMPDIR",
    "GOCACHE",
    "GOLANGCI_LINT_CACHE",
    "PIP_CACHE_DIR",
    "BUILDX_CONFIG",
    "PYTHONDONTWRITEBYTECODE",
    ENV_SCRATCH_ROOT,
    ENV_RUN_ROOT,
    ENV_PROJECT,
    ENV_PHASE,
)


def _env(root: Path, **extra: str) -> dict[str, str]:
    env = {ENV_SCRATCH_ROOT: str(root)}
    env.update(extra)
    return env

def test_go_variables_are_present_before_any_child_starts(tmp_path):
    layout = establish_run(_env(tmp_path))
    env = layout.child_environment()

    for key in ("GOTMPDIR", "GOCACHE", "GOLANGCI_LINT_CACHE"):
        assert Path(env[key]).is_dir(), key

def test_pytest_basetemp_is_centralized(tmp_path):
    layout = establish_run(_env(tmp_path))

    assert layout.pytest_basetemp.is_dir()
    assert layout.pytest_basetemp.parent == layout.run_root

def test_short_socket_path_succeeds():
    """Uses the ambient run layout, as real callers do.

    Deliberately not parameterized on ``tmp_path``: pytest's basetemp now lives
    inside the run root, so rooting a second scratch tree there would measure a
    nested path far deeper than any real caller's and would test the fixture
    rather than the helper.
    """
    with short_test_directory("s-", "c.sock") as directory:
        socket_path = directory / "c.sock"
        assert len(os.fsencode(str(socket_path))) <= MAX_SOCKET_PATH_BYTES
        assert directory.is_dir()

    assert not directory.exists()

def test_longest_coordinator_path_fits_owned_short_directory():
    """Private phase roots still support the longest coordinator path."""
    layout = establish_run()
    with short_test_directory(
        "async10-", "incompatible/configured.rp.toml", layout=layout
    ) as directory:
        candidate = directory / "incompatible/configured.rp.toml"
        assert len(os.fsencode(str(candidate))) <= MAX_SOCKET_PATH_BYTES
        assert directory.parent == layout.socket_directories

    assert not directory.exists()

def test_safety3_former_104_byte_shape_has_a_fitting_owned_component() -> None:
    suffix = "incompatible/configured.rp.toml"
    fixed = Path("/private/tmp")
    one_character_shape = fixed / "r" / "a000" / suffix
    padding = "r" * (
        1 + 104 - len(os.fsencode(str(one_character_shape)))
    )
    run_root = fixed / padding
    old_shape = run_root / "a000" / suffix

    assert len(os.fsencode(str(old_shape))) == 104
    assert socket_component_byte_capacity(
        run_root / "s", suffix, maximum_path_bytes=103
    ) == 1

@pytest.mark.parametrize("root_delta", [-1, 0, 1])
def test_safety3_socket_budget_owns_adjacent_root_lengths(root_delta: int) -> None:
    suffix = "coordinator/coordinator.sock"
    fixed = Path("/private/tmp")
    one_character_shape = fixed / "r" / "s" / "x" / suffix
    target = 1 + 103 - len(os.fsencode(str(one_character_shape)))
    run_root = fixed / ("r" * (target + root_delta))

    if root_delta == 1:
        with pytest.raises(TestScratchError, match="mathematically impossible"):
            socket_component_byte_capacity(
                run_root / "s", suffix, maximum_path_bytes=103
            )
    else:
        capacity = socket_component_byte_capacity(
            run_root / "s", suffix, maximum_path_bytes=103
        )
        assert capacity == 1 - root_delta

def test_safety3_socket_budget_counts_multibyte_root_bytes() -> None:
    suffix = "coordinator.sock"
    ascii_root = Path("/private/tmp") / ("e" * 20)
    utf8_root = Path("/private/tmp") / ("é" * 20)

    ascii_capacity = socket_component_byte_capacity(
        ascii_root / "s", suffix, maximum_path_bytes=103
    )
    utf8_capacity = socket_component_byte_capacity(
        utf8_root / "s", suffix, maximum_path_bytes=103
    )

    assert ascii_capacity - utf8_capacity == 20

def test_safety3_impossible_socket_budget_refuses_before_workload() -> None:
    with pytest.raises(TestScratchError, match="mathematically impossible"):
        socket_component_byte_capacity(
            Path("/private/tmp/too-long"),
            "nested/coordinator.sock",
            maximum_path_bytes=20,
        )

@pytest.mark.parametrize(
    "suffix",
    ["coordinator/coordinator.sock", "incompatible/configured.rp.toml"],
)
def test_safety3_unit_and_integration_layouts_share_budget_owner(
    tmp_path: Path,
    suffix: str,
) -> None:
    run_root = tmp_path / "run"
    layout = TestScratchLayout(run_root=run_root, scratch_root=tmp_path).create()
    maximum = len(os.fsencode(str(layout.socket_directories / "x" / suffix)))

    with short_test_directory(
        "phase-name-is-not-load-bearing-",
        suffix,
        layout=layout,
        maximum_path_bytes=maximum,
    ) as directory:
        assert directory.parent == layout.socket_directories
        assert len(os.fsencode(str(directory / suffix))) <= maximum

def test_nested_scratch_root_overflow_is_reported_not_silently_truncated(
    tmp_path,
):
    """An impossible socket-directory owner must fail before yielding."""
    shortest_shape = tmp_path / "r" / "s" / "x" / "c.sock"
    run_component_length = max(
        1,
        MAX_SOCKET_PATH_BYTES + 2 - len(os.fsencode(str(shortest_shape))),
    )
    run_root = tmp_path / ("r" * run_component_length)
    layout = TestScratchLayout(run_root=run_root, scratch_root=tmp_path)
    minimum_socket_shape = layout.socket_directories / "x" / "c.sock"

    assert len(os.fsencode(str(minimum_socket_shape))) > MAX_SOCKET_PATH_BYTES
    with pytest.raises(TestScratchError, match="mathematically impossible"):
        with short_test_directory("s-", "c.sock", layout=layout):
            pytest.fail("the helper must refuse an overlong nested root")

def test_socket_path_overflow_is_refused_before_execution(tmp_path):
    layout = establish_run(_env(tmp_path))
    overlong = "n" * 200 + ".sock"

    with pytest.raises(TestScratchError) as excinfo:
        with short_test_directory("s-", overlong, layout=layout):
            pytest.fail("the helper must refuse before yielding")

    assert "encoded bytes" in str(excinfo.value)

def test_socket_path_limit_counts_encoded_bytes_not_characters(tmp_path):
    layout = establish_run(_env(tmp_path))
    multibyte = "é" * 60 + ".sock"

    assert len(multibyte) < MAX_SOCKET_PATH_BYTES
    assert len(os.fsencode(multibyte)) > len(multibyte)
    with pytest.raises(TestScratchError):
        with short_test_directory("s-", multibyte, layout=layout):
            pytest.fail("the helper must measure encoded bytes")

def test_terminal_manifest_is_idempotent(tmp_path):
    layout = establish_run(_env(tmp_path))

    finalize_run(layout, "passed", exit_status=0)
    finalize_run(layout, "passed", exit_status=0)

    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    assert manifest["state"] == "passed"
    assert manifest["exit_status"] == 0
    assert manifest["live_runtime_residue"] is False

def test_conflicting_terminal_state_fails_closed(tmp_path):
    layout = establish_run(_env(tmp_path))
    finalize_run(layout, "passed", exit_status=0)

    with pytest.raises(TestScratchError):
        finalize_run(layout, "failed", exit_status=1)

def test_an_inherited_run_is_not_finalized_by_the_borrower(tmp_path):
    """Only the allocating process owns the terminal state.

    The runner's own tests invoke main() repeatedly inside one outer run. If a
    borrower finalized the inherited root, the second invocation would collide
    with the first and fail closed on a state it does not own.
    """
    owner = establish_run(_env(tmp_path))
    borrower = establish_run(
        _env(tmp_path, **{ENV_RUN_ROOT: str(owner.run_root)})
    )

    assert owner.allocated is True
    assert borrower.allocated is False

    finalize_run(borrower, "failed", exit_status=1)
    assert json.loads(owner.manifest.read_text(encoding="utf-8"))["state"] == (
        "running"
    )

    finalize_run(owner, "passed", exit_status=0)
    assert json.loads(owner.manifest.read_text(encoding="utf-8"))["state"] == (
        "passed"
    )

def test_unknown_terminal_result_is_rejected(tmp_path):
    layout = establish_run(_env(tmp_path))

    with pytest.raises(TestScratchError):
        finalize_run(layout, "mostly-fine", exit_status=0)

def test_layout_directories_are_owner_only(tmp_path):
    layout = establish_run(_env(tmp_path))

    for directory in layout.directories():
        assert directory.is_dir()
        assert directory.stat().st_mode & 0o077 == 0

