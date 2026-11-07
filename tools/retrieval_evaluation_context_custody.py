"""Immutable W4 evaluation source/input custody and sanitized failure records."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_V1_FIXTURE_ROOT = REPO_ROOT / "src/test/fixtures/retrieval_evaluation/context-v1"


def _collect_tree(root: Path, *, include: Any) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"evaluation closure root is not a directory: {root.name}")
    collected: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if (
            any(part in {"__pycache__", ".git"} for part in relative_parts)
            or path.name in {".DS_Store"}
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if path.is_symlink():
            raise ValueError("evaluation closure contains a symlink")
        if path.is_file() and include(path):
            collected[str(path.relative_to(REPO_ROOT))] = path.read_bytes()
    return collected


def context_candidate_source_files(repo_root: Path = REPO_ROOT) -> dict[str, bytes]:
    """Snapshot all product Python/resources and maintained W4 support dependencies."""
    if repo_root.resolve() != REPO_ROOT.resolve():
        raise ValueError("W4 source closure must use the candidate repository root")
    out: dict[str, bytes] = {}
    out.update(
        _collect_tree(
            repo_root / "src/main/python",
            include=lambda p: p.suffix in {".py", ".pyi"} or p.name == "py.typed",
        )
    )
    out.update(_collect_tree(repo_root / "src/main/resources", include=lambda _p: True))
    out.update(
        _collect_tree(
            repo_root / "src/test/support/python/repomap_test_support",
            include=lambda p: p.suffix == ".py",
        )
    )
    for test_root in (
        repo_root / "src/test/unit/python/tools",
        repo_root / "src/test/int/python/repomap_kg/retrieval",
    ):
        if test_root.exists():
            out.update(
                _collect_tree(
                    test_root,
                    include=lambda p: p.name.startswith("retrieval_evaluation_context")
                    or p.name.startswith("context_evaluation"),
                )
            )
    out.update(
        _collect_tree(repo_root / "tools", include=lambda p: p.suffix == ".py")
    )
    for name in (
        "pyproject.toml", "requirements.txt", "requirements-dev.txt", "uv.lock",
        "poetry.lock", "Pipfile.lock", "tools/ci/pre_review_python.in",
        "tools/ci/pre_review_python.lock",
    ):
        path = repo_root / name
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"dependency manifest is not a regular file: {name}")
            out[str(path.relative_to(repo_root))] = path.read_bytes()
    return dict(sorted(out.items()))


def context_input_files(
    context_fixture_root: Path = CONTEXT_V1_FIXTURE_ROOT,
    mixed_fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
    *,
    extra_files: Mapping[str, bytes] | None = None,
) -> dict[str, bytes]:
    """Snapshot frozen corpora plus caller-supplied generated native inputs."""
    out: dict[str, bytes] = {}
    for root, prefix in ((context_fixture_root, "context-v1"), (mixed_fixture_root, "mixed-v1")):
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"evaluation fixture root is not a directory: {prefix}")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("evaluation fixture contains a symlink")
            if path.is_file():
                out[f"{prefix}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    for raw_name, data in (extra_files or {}).items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or raw_name.startswith(("/", "\\"))
            or "\\" in raw_name
            or ":" in raw_name
            or any(part in {"", ".", ".."} for part in raw_name.split("/"))
            or not isinstance(data, bytes)
        ):
            raise ValueError("generated evaluation input has an unsafe name or type")
        if raw_name in out:
            raise ValueError(f"generated evaluation input collides with frozen input: {raw_name}")
        out[raw_name] = data
    return dict(sorted(out.items()))


def sanitized_failure_record(*, phase: str, error: BaseException) -> dict[str, str]:
    """Return a public-safe failure record without exception text or filesystem paths."""
    error_type = type(error).__name__
    safe_type = error_type if error_type.isidentifier() else "EvaluationError"
    return {
        "record_type": "failure",
        "phase": phase,
        "error_type": safe_type,
        "error_code": "evaluation_failed",
    }


def sanitized_failure_report(*, phase: str, error: BaseException) -> dict[str, Any]:
    record = sanitized_failure_record(phase=phase, error=error)
    return {
        "schema_version": "cloe-context-evaluation-failure-v1",
        "status": "failed",
        "failure": record,
    }


__all__ = [
    "CONTEXT_V1_FIXTURE_ROOT",
    "REPO_ROOT",
    "context_candidate_source_files",
    "context_input_files",
    "sanitized_failure_record",
    "sanitized_failure_report",
]
