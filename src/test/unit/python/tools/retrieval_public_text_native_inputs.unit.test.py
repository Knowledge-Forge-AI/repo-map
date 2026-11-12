"""Native input custody: fresh owned paths, exact worker-view copy, fixed argv and child env."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil

import pytest

import retrieval_semantic_generator_worker_contracts as contracts
from retrieval_public_text_native_inputs import (
    FUNCTIONAL_SELECTOR, LEARNED_SELECTOR, NativeInputRefusal, canonical_argv, child_environment, copy_worker_view,
    create_native_paths,
)
from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES

TOOLS = Path(contracts.__file__).resolve().parent
RUNTIME = "sha256:" + "d" * 64


def _scratch(tmp_path: Path) -> Path:
    root = tmp_path / "scratch"
    for path in (root, root / "tmp", root / "evidence"):
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    return root


def _expected(tools: Path = TOOLS) -> dict[str, str]:
    return {name: "sha256:" + hashlib.sha256((tools / name).read_bytes()).hexdigest() for name in WORKER_SOURCE_FILES}


def _tools_copy(tmp_path: Path) -> Path:
    tools = tmp_path / "tools-copy"
    tools.mkdir()
    for name in WORKER_SOURCE_FILES:
        shutil.copyfile(TOOLS / name, tools / name)
        (tools / name).chmod(0o644)
    return tools


def test_paths_are_fresh_owned_and_single_use(tmp_path: Path) -> None:
    root = _scratch(tmp_path)
    paths = create_native_paths(root)
    for path in (paths.run_root, paths.source_view, *paths.input_roots, *paths.output_roots):
        assert path.is_dir() and os.stat(path).st_mode & 0o777 == 0o700
    assert not paths.report_dir.exists() and "private" in repr(paths)
    with pytest.raises(NativeInputRefusal, match="already_used"):
        create_native_paths(root)


def test_paths_refuse_loose_or_missing_roots(tmp_path: Path) -> None:
    root = _scratch(tmp_path)
    (root / "tmp").chmod(0o755)
    with pytest.raises(NativeInputRefusal, match="custody"):
        create_native_paths(root)
    with pytest.raises(NativeInputRefusal):
        create_native_paths(Path("relative"))
    (tmp_path / "second").mkdir()
    report_root = _scratch(tmp_path / "second")
    (report_root / "evidence" / "publictext-cal1-native-report").mkdir()
    with pytest.raises(NativeInputRefusal, match="report_already_used"):
        create_native_paths(report_root)


def test_worker_view_copies_exactly_the_unchanged_flat_closure(tmp_path: Path) -> None:
    paths = create_native_paths(_scratch(tmp_path))
    expected = _expected()
    assert copy_worker_view(TOOLS, paths, expected) == expected
    copied = sorted(item.name for item in paths.source_view.iterdir())
    assert copied == sorted(WORKER_SOURCE_FILES) and len(copied) == 17
    for name in WORKER_SOURCE_FILES:
        assert (paths.source_view / name).read_bytes() == (TOOLS / name).read_bytes()
        assert os.stat(paths.source_view / name).st_mode & 0o777 == 0o600
    with pytest.raises(NativeInputRefusal, match="not_empty"):
        copy_worker_view(TOOLS, paths, expected)


def test_worker_view_refuses_wrong_population_even_with_seventeen_entries(tmp_path: Path) -> None:
    paths = create_native_paths(_scratch(tmp_path))
    expected = _expected()
    swapped = dict(expected)
    swapped.pop(WORKER_SOURCE_FILES[0])
    swapped["retrieval_semantic_fusion.py"] = expected[WORKER_SOURCE_FILES[1]]
    assert len(swapped) == 17
    for candidate in (swapped, {k: v for k, v in expected.items() if k != WORKER_SOURCE_FILES[0]},
                      {**expected, WORKER_SOURCE_FILES[0]: "sha256:short"}):
        with pytest.raises(NativeInputRefusal):
            copy_worker_view(TOOLS, paths, candidate)
    assert not any(paths.source_view.iterdir())


def test_worker_view_refuses_digest_symlink_and_writable_sources_before_any_copy(tmp_path: Path) -> None:
    tools = _tools_copy(tmp_path)
    expected = _expected(tools)
    paths = create_native_paths(_scratch(tmp_path))
    with pytest.raises(NativeInputRefusal, match="digest"):
        copy_worker_view(tools, paths, {**expected, WORKER_SOURCE_FILES[-1]: "sha256:" + "0" * 64})
    (tools / WORKER_SOURCE_FILES[-1]).chmod(0o666)
    with pytest.raises(NativeInputRefusal, match="custody"):
        copy_worker_view(tools, paths, expected)
    (tools / WORKER_SOURCE_FILES[-1]).chmod(0o644)
    target = tools / WORKER_SOURCE_FILES[-1]
    moved = tmp_path / "moved.py"
    target.rename(moved)
    target.symlink_to(moved)
    with pytest.raises(NativeInputRefusal, match="custody"):
        copy_worker_view(tools, paths, expected)
    assert not any(paths.source_view.iterdir())
    with pytest.raises(NativeInputRefusal, match="tools_root"):
        copy_worker_view(Path("tools"), paths, expected)


def test_argv_is_the_single_learned_selector_with_the_existing_runtime_override(tmp_path: Path) -> None:
    paths = create_native_paths(_scratch(tmp_path))
    interpreter = Path("/opt/venv/bin/python3")
    argv = canonical_argv(interpreter, paths, RUNTIME)
    assert argv[:4] == (str(interpreter), "-I", "-B", "tools/run_tests.py")
    assert argv[-3:] == ("--", LEARNED_SELECTOR, "-s")
    assert LEARNED_SELECTOR.startswith("src/test/int/python/tools/retrieval_public_text_study.int.test.py::")
    assert FUNCTIONAL_SELECTOR not in argv and "--pg-container-port" in argv and "55433" in argv
    assert argv[argv.index("--smoke-image-reference") + 1] == RUNTIME
    assert "--no-coverage" in argv and "--report" not in argv
    for bad in ((Path("python3"), RUNTIME), (Path("/usr/bin/bash"), RUNTIME), (interpreter, "latest")):
        with pytest.raises(NativeInputRefusal):
            canonical_argv(bad[0], paths, bad[1])


def test_child_environment_is_scoped_and_does_not_mutate_the_parent(tmp_path: Path) -> None:
    paths = create_native_paths(_scratch(tmp_path))
    before = dict(os.environ)
    base = {"PATH": "/usr/bin", "PYTHONPATH": "/leak", "COVERAGE_PROCESS_START": "x", "CLOE_HOME": "/home"}
    child = child_environment(paths, base)
    assert dict(os.environ) == before
    assert child["PATH"] == "/usr/bin" and not {"PYTHONPATH", "COVERAGE_PROCESS_START", "CLOE_HOME"} & set(child)
    assert child["TMPDIR"] == str(paths.run_root / "tmp") and child["PYTHONDONTWRITEBYTECODE"] == "1"
    assert child["REPOMAP_TEST_PHASE"].endswith("PUBLICTEXT-CAL1")
    (paths.run_root / "tmp").chmod(0o755)
    with pytest.raises(NativeInputRefusal):
        child_environment(paths, base)
