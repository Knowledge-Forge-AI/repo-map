"""Historical migration-root fixtures for compatibility-phase tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from repomap_kg.storage import default_rdbms_root, discover_migrations


ARCH5D_REMOVAL_MIGRATION = (
    "2026/07/16-002-arch5d-drop-legacy-graph-schema.sql"
)


def pre_arch5d_rdbms_root(base: Path) -> Path:
    """Copy the migration tree at the exact pre-ARCH5D schema boundary."""

    current_root = default_rdbms_root()
    current = discover_migrations(current_root)
    removal = next(
        migration
        for migration in current
        if migration.relative_path == ARCH5D_REMOVAL_MIGRATION
    )
    historical = base / "pre-arch5d-rdbms"
    shutil.copytree(current_root, historical)
    for migration in current[removal.ordinal - 1 :]:
        (historical / migration.relative_path).unlink()
    assert len(discover_migrations(historical)) == removal.ordinal - 1
    return historical
