"""Source-derived identities and owner intent assembly for the installed proof.

``candidate_census_sha256`` reuses the first-use, runner-equivalent
``candidate_census`` unchanged (``src/main``, ``src/test``, ``tools`` and
``pyproject.toml``). ``fixture_census_sha256`` binds the tiny public fixture
tree. ``owner_intent`` freezes one owner's intent after shared wheel
preparation and before its first scenario child (section 10.2): every expected
value is a recipe constant or a source-computed value, never a run result.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_source_identity import Lister, candidate_census, git_listed
from installed_experience_domains import SCHEMA_INTENT, STORAGE_SCENARIO, InstalledError
from installed_experience_pins import MESSAGE_PATH, MESSAGE_SHA256, TE_MODULE_SHA256, TE_RECORD_SHA256
from installed_experience_records import encode_intent
from installed_experience_recipe import owner_scenarios, recipe_digest, resolve_expected

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_RELATIVE = Path("src/test/fixtures/installed_experience/tiny-v1")
MAX_FIXTURE_FILES = 16
MAX_FIXTURE_BYTES = 16 * 1024


@dataclass(frozen=True)
class Preparation:
    """Shared wheel preparation bindings, observed before any owner intent."""

    candidate_input_sha256: str
    candidate_input_count: int
    wheel_sha256: str
    wheel_bytes: int
    wheel_member_count: int
    inventory_sha256: str
    incumbent_wheel_sha256: str | None = None


def candidate_census_sha256(repo_root: Path = REPO_ROOT, *, lister: Lister = git_listed) -> str:
    return candidate_census(repo_root, lister=lister)


def fixture_rows(fixture_root: Path) -> list[list[Any]]:
    """Sorted ``[relative, sha256, size]`` of every regular fixture file; no symlinks."""
    rows: list[list[Any]] = []
    total = 0
    for current, dirnames, filenames in os.walk(fixture_root, followlinks=False):
        dirnames.sort()
        for name in dirnames:
            if os.path.islink(os.path.join(current, name)):
                raise InstalledError("unsafe-member")
        for name in sorted(filenames):
            path = Path(current) / name
            details = os.lstat(path)
            if not stat.S_ISREG(details.st_mode):
                raise InstalledError("unsafe-member")
            body = path.read_bytes()
            total += len(body)
            rows.append([path.relative_to(fixture_root).as_posix(),
                         hashlib.sha256(body).hexdigest(), len(body)])
    if not rows or len(rows) > MAX_FIXTURE_FILES or total > MAX_FIXTURE_BYTES:
        raise InstalledError("bound-exceeded")
    return sorted(rows)


def fixture_census_sha256(fixture_root: Path | None = None) -> str:
    root = REPO_ROOT / FIXTURE_RELATIVE if fixture_root is None else fixture_root
    return hashlib.sha256(canonical_bytes(fixture_rows(root), 64 * 1024) + b"\n").hexdigest()


def owner_intent(
    owner: str,
    preparation: Preparation,
    source_values: Mapping[str, Mapping[str, Any]],
    *,
    fixture_digest: str,
    candidate_census: str,
    python: str,
    platform: str,
) -> bytes:
    """Encode one owner's intent; ``source_values`` maps scenario id to source facts."""
    rows = owner_scenarios(owner)
    scenarios = [{
        "id": row.id, "action": row.action, "env_class": row.env_class, "family": row.family,
        "expectation": row.expectation,
        "expected": resolve_expected(row, source_values.get(row.id, {})),
    } for row in rows]
    incumbent = preparation.incumbent_wheel_sha256 if owner == "migration" else None
    if owner == "migration" and incumbent is None:
        raise InstalledError("witness-missing")
    payload = {
        "schema": SCHEMA_INTENT, "owner": owner, "storage_scenario": STORAGE_SCENARIO[owner],
        "recipe_digest": recipe_digest(),
        "candidate_input_sha256": preparation.candidate_input_sha256,
        "candidate_input_count": preparation.candidate_input_count,
        "wheel_sha256": preparation.wheel_sha256, "wheel_bytes": preparation.wheel_bytes,
        "wheel_member_count": preparation.wheel_member_count,
        "inventory_sha256": preparation.inventory_sha256,
        "incumbent_wheel_sha256": incumbent,
        "projection": {"module_sha256": TE_MODULE_SHA256, "record_sha256": TE_RECORD_SHA256},
        "fixture_census_sha256": fixture_digest, "candidate_census_sha256": candidate_census,
        "message_path": MESSAGE_PATH, "message_sha256": MESSAGE_SHA256,
        "python": python, "platform": platform,
        "env_classes": sorted({row.env_class for row in rows}),
        "scenarios": scenarios,
    }
    return encode_intent(payload)


__all__ = [
    "FIXTURE_RELATIVE", "Preparation", "REPO_ROOT", "candidate_census_sha256",
    "fixture_census_sha256", "fixture_rows", "owner_intent",
]
