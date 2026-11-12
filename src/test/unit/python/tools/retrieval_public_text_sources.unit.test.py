"""Evaluator versus flat worker closures: explicit members, fresh reads and change refusal."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from retrieval_public_text_sources import (
    PUBLIC_TEXT_EVALUATOR_PATHS, SourceClosureRefusal, evaluator_closure, require_unchanged, worker_closure,
)
from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES

REPO = Path(__file__).resolve().parents[5]


def _base(root: Path) -> dict[str, bytes]:
    names = [f"tools/{name}" for name in WORKER_SOURCE_FILES] + ["tools/retrieval_semantic_fusion.py"]
    return {name: (root / name).read_bytes() for name in names}


def _copy(tmp_path: Path) -> Path:
    root = (tmp_path / "repo").resolve()
    names = list(PUBLIC_TEXT_EVALUATOR_PATHS) + list(_base(REPO))
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, target)
    return root


def test_worker_closure_is_the_exact_flat_seventeen_file_closure() -> None:
    closure = worker_closure(REPO)
    assert closure.name == "worker" and sorted(closure.digests) == sorted(WORKER_SOURCE_FILES)
    assert len(closure.digests) == 17 and "retrieval_semantic_generator_pins.json" in closure.digests
    assert all("/" not in name for name in closure.digests)
    assert worker_closure(REPO).identity == closure.identity


def test_evaluator_closure_adds_explicit_owners_and_is_distinct_from_the_worker_closure() -> None:
    closure = evaluator_closure(REPO, _base(REPO))
    assert set(PUBLIC_TEXT_EVALUATOR_PATHS) <= set(closure.digests)
    assert {f"tools/{name}" for name in WORKER_SOURCE_FILES} <= set(closure.digests)
    assert closure.identity != worker_closure(REPO).identity
    assert not any("__pycache__" in name or name.startswith("/") for name in closure.digests)
    assert "src/test/int/python/tools/retrieval_public_text_study.int.test.py" in closure.digests


def test_evaluator_closure_refuses_missing_worker_members_or_changed_base_bytes() -> None:
    base = _base(REPO)
    with pytest.raises(SourceClosureRefusal, match="worker_members"):
        evaluator_closure(REPO, {"tools/retrieval_semantic_fusion.py": base["tools/retrieval_semantic_fusion.py"]})
    with pytest.raises(SourceClosureRefusal, match="base_closure_changed"):
        evaluator_closure(REPO, {**base, "tools/retrieval_semantic_fusion.py": b"stale"})
    with pytest.raises(SourceClosureRefusal):
        evaluator_closure(REPO, {})


@pytest.mark.parametrize("name", ["../escape.py", "/abs.py", "tools/__pycache__/x.pyc", "tools\\x.py", "./tools/x.py"])
def test_member_names_are_closed_relative_paths(name: str) -> None:
    with pytest.raises(SourceClosureRefusal, match="source_path_invalid"):
        evaluator_closure(REPO, {**_base(REPO), name: b""})


def test_root_symlink_missing_member_and_frozen_boundary_changes_refuse(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    worker = worker_closure(root)
    evaluator = evaluator_closure(root, _base(root))
    require_unchanged(root, worker)
    require_unchanged(root, evaluator)
    with pytest.raises(SourceClosureRefusal, match="source_root_invalid"):
        worker_closure(Path("relative"))
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(SourceClosureRefusal, match="source_root_invalid"):
        worker_closure(link)
    support = root / PUBLIC_TEXT_EVALUATOR_PATHS[-3]
    support.write_bytes(support.read_bytes() + b"\n")
    with pytest.raises(SourceClosureRefusal, match="evaluator_source_closure_changed"):
        require_unchanged(root, evaluator)
    pins = root / "tools" / "retrieval_semantic_generator_pins.json"
    pins.write_bytes(pins.read_bytes() + b" ")
    with pytest.raises(SourceClosureRefusal, match="worker_source_closure_changed"):
        require_unchanged(root, worker)
    moved = tmp_path / "moved.py"
    target = root / PUBLIC_TEXT_EVALUATOR_PATHS[0]
    target.rename(moved)
    with pytest.raises(SourceClosureRefusal, match="missing"):
        evaluator_closure(root, _base(root))
    target.symlink_to(moved)
    with pytest.raises(SourceClosureRefusal, match="symlink"):
        evaluator_closure(root, _base(root))
