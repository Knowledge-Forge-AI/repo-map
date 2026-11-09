"""Git-free product digest, runner-equivalent candidate census, and the intent.

``product_digest`` binds every regular file under ``src/main`` plus
``pyproject.toml`` (bytecode and tool caches excluded) without Git.
``candidate_census`` is byte-for-byte the algorithm of the runner's
``candidate_identity.source_sha256``: Git-listed cached and non-ignored files
under ``src/main``, ``src/test``, ``tools`` and ``pyproject.toml``, sorted by raw
relative name, each followed by NUL and the binary SHA-256 of its bytes. Task,
gold or held-out bytes may enter only as opaque integrity input there.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from first_use_workload_census import FIXTURE_RELATIVE, REPO_ROOT, load_census, verify_fixture
from first_use_workload_domains import HEX40, WorkloadError
from first_use_workload_records import encode_intent, intent_payload
from first_use_workload_recipe import RECIPE, recipe_digest
from first_use_workload_recipe_shapes import Recipe

CANDIDATE_PATHS = ("src/main", "src/test", "tools", "pyproject.toml")
PRODUCT_ROOTS = ("src/main", "pyproject.toml")
CACHE_DIRECTORIES = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})
BYTECODE_SUFFIXES = (".pyc", ".pyo")
GIT_TIMEOUT_SECONDS = 120

Lister = Callable[[Path], bytes]


class SourceIdentityError(RuntimeError):
    """The checkout could not be bound; never a partial digest."""


def git_listed(repo_root: Path) -> bytes:
    """NUL-separated names exactly as the runner's candidate identity lists them."""
    try:
        return subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
             "--", *CANDIDATE_PATHS],
            cwd=repo_root, timeout=GIT_TIMEOUT_SECONDS, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SourceIdentityError("candidate listing unavailable") from error


def candidate_census(repo_root: Path = REPO_ROOT, *, lister: Lister = git_listed) -> str:
    digest = hashlib.sha256()
    for name in sorted(set(lister(repo_root).split(b"\0")) - {b""}):
        path = repo_root / os.fsdecode(name)
        try:
            if not path.is_file():
                raise SourceIdentityError("candidate source file disappeared")
            body = path.read_bytes()
        except SourceIdentityError:
            raise
        except OSError:
            raise SourceIdentityError("candidate source unreadable") from None
        digest.update(name + b"\0" + hashlib.sha256(body).digest())
    return digest.hexdigest()


def _product_names(repo_root: Path) -> list[bytes]:
    def walk_error(_error: OSError) -> None:
        raise SourceIdentityError("product source unreadable") from None

    names: list[bytes] = []
    for top in PRODUCT_ROOTS:
        root = repo_root / top
        details = os.lstat(root)
        if stat.S_ISREG(details.st_mode):
            names.append(os.fsencode(top))
            continue
        if not stat.S_ISDIR(details.st_mode):
            raise SourceIdentityError("product root is not a regular tree")
        for current, dirnames, filenames in os.walk(root, followlinks=False, onerror=walk_error):
            dirnames[:] = sorted(name for name in dirnames if name not in CACHE_DIRECTORIES)
            for name in dirnames:
                if (Path(current) / name).is_symlink():
                    raise SourceIdentityError("product tree holds a symlink")
            for name in filenames:
                if name.endswith(BYTECODE_SUFFIXES):
                    continue
                path = Path(current) / name
                if not stat.S_ISREG(os.lstat(path).st_mode):
                    raise SourceIdentityError("product tree holds a non-regular file")
                names.append(os.fsencode(path.relative_to(repo_root).as_posix()))
    return sorted(names)


def product_digest(repo_root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256()
    try:
        for name in _product_names(repo_root):
            body = (repo_root / os.fsdecode(name)).read_bytes()
            digest.update(name + b"\0" + hashlib.sha256(body).digest())
    except OSError as error:
        raise SourceIdentityError("product source unreadable") from error
    return digest.hexdigest()


def current_intent(
    repo_root: Path = REPO_ROOT,
    *,
    declared_source_parent: str | None = None,
    lister: Lister = git_listed,
    recipe: Recipe = RECIPE,
) -> bytes:
    """Recompute the canonical intent of the current checkout."""
    if declared_source_parent is not None and HEX40.fullmatch(declared_source_parent) is None:
        raise WorkloadError("invalid_domain")
    census = load_census(repo_root)
    verify_fixture(census, repo_root / FIXTURE_RELATIVE)
    payload = intent_payload(
        recipe=recipe,
        recipe_digest=recipe_digest(recipe),
        census_digest=census.digest,
        fixture_digest=census.fixture_digest,
        product_digest=product_digest(repo_root),
        candidate_census=candidate_census(repo_root, lister=lister),
        declared_source_parent=declared_source_parent,
    )
    return encode_intent(payload)


__all__ = [
    "CANDIDATE_PATHS", "Lister", "SourceIdentityError", "candidate_census", "current_intent",
    "git_listed", "product_digest",
]
