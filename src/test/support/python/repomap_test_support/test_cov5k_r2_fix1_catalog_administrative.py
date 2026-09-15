"""Administrative and harness qualification catalog definitions for FIX1 (Group K, gates, selections)."""

from __future__ import annotations

from repomap_test_support.test_cov5k_r2_fix1_catalog_values import (
    CatalogEntry,
    _BASE_OBSERVATION,
    _OWNER_ROOT,
    _TOOL_ROOT,
    _entry,
    _numbered_group,
)


K_FIXED_ARGV_SHAPES: dict[str, tuple[str, ...]] = {
    "K01": (
        "repomap-kg",
        "local",
        "db",
        "dump",
        "--database",
        "{database}",
        "--dry-run",
        "--json",
    ),
    "K02": (
        "repomap-kg",
        "local",
        "db",
        "restore-all",
        "--from-dump",
        "{dump}",
        "--dry-run",
        "--json",
    ),
    "K03": (
        "repomap-kg",
        "local",
        "db",
        "upgrade-schema",
        "--database",
        "{database}",
        "--dry-run",
        "--json",
    ),
    "K04": (
        "repomap-kg",
        "local",
        "db",
        "init",
        "--database",
        "{database}",
        "--from-source",
        "--dry-run",
        "--json",
    ),
    "K05": (
        "repomap-kg",
        "local",
        "db",
        "drop",
        "--database",
        "{database}",
        "--dry-run",
        "--json",
    ),
    "K06": (
        "psql",
        "{connection}",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "{sql_file}",
    ),
    "K07": (
        "TestImageManager",
        "build_ephemeral_image",
        "{dockerfile}",
    ),
    "K08": ("docker", "start", "{container}"),
    "K09": ("docker", "stop", "--time", "{seconds}", "{container}"),
    "K10": ("docker", "rm", "--force", "{container}"),
    "K11": (
        "{python}",
        "tools/run_tests.py",
        "--suite",
        "{suite}",
        "--pg-container-port",
        "{port}",
        "--smoke-image-reference={image_reference}",
    ),
    "K12": ("docker", "stats", "--no-stream", "{container}"),
}

K_REHEARSAL_ARGV_SHAPES: dict[str, tuple[str, ...]] = {
    "K01": (
        "repomap-kg",
        "local",
        "db",
        "dump",
        "--database",
        "repomap_fix1_k01",
        "--dry-run",
        "--json",
    ),
    "K02": (
        "repomap-kg",
        "local",
        "db",
        "restore-all",
        "--from-dump",
        "missing.dump",
        "--dry-run",
        "--json",
    ),
    "K03": (
        "repomap-kg",
        "local",
        "db",
        "upgrade-schema",
        "--database",
        "repomap_fix1_k03",
        "--dry-run",
        "--json",
    ),
    "K04": (
        "repomap-kg",
        "local",
        "db",
        "init",
        "--database",
        "repomap_fix1_k04",
        "--from-source",
        "--dry-run",
        "--json",
    ),
    "K05": (
        "repomap-kg",
        "local",
        "db",
        "drop",
        "--database",
        "repomap_fix1_k05",
        "--dry-run",
        "--json",
    ),
    "K06": (
        "psql",
        "-h",
        "127.0.0.1",
        "-p",
        "{port}",
        "-U",
        "repo_map_test",
        "-d",
        "repomap_test",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "rows.sql",
    ),
    "K07": (
        "TestImageManager",
        "build_ephemeral_image",
        "dependency-only-dockerfile",
    ),
    "K08": ("docker", "start", "repomap-fix1-k08"),
    "K09": (
        "docker",
        "stop",
        "--time",
        "1",
        "repomap-fix1-k09",
    ),
    "K10": ("docker", "rm", "--force", "repomap-fix1-k10"),
    "K11": (
        "{python}",
        "tools/run_tests.py",
        "--suite",
        "smoke",
        "--pg-container-port",
        "{port}",
        "--smoke-image-reference=sha256:0000000000000000000000000000000000000000000000000000000000000000",
    ),
    "K12": (
        "docker",
        "stats",
        "--no-stream",
        "repomap-fix1-k12",
    ),
}


def _group_k() -> tuple[CatalogEntry, ...]:
    owners = (
        ("K01", "backup", f"{_OWNER_ROOT}/runtime/backup.py:dump_database"),
        (
            "K02",
            "restore",
            f"{_OWNER_ROOT}/runtime/backup_restore_sets.py:restore_coordinated_backup",
        ),
        (
            "K03",
            "schema_migration",
            f"{_OWNER_ROOT}/runtime/schema_upgrade.py:upgrade_graph_schema",
        ),
        (
            "K04",
            "database_initialization",
            f"{_OWNER_ROOT}/runtime/_backup_lifecycle.py:init_database_from_source",
        ),
        (
            "K05",
            "database_removal",
            f"{_OWNER_ROOT}/runtime/backup.py:drop_database",
        ),
        (
            "K06",
            "psql_native_load",
            f"{_OWNER_ROOT}/storage/psql.py:run_psql",
        ),
        (
            "K07",
            "container_build",
            "src/test/support/python/repomap_test_support/"
            "resource_test_images.py:TestImageManager.build_ephemeral_image",
        ),
        (
            "K08",
            "container_start",
            "tool:docker:start",
        ),
        (
            "K09",
            "container_stop",
            "tool:docker:stop",
        ),
        (
            "K10",
            "container_removal",
            "tool:docker:rm",
        ),
        ("K11", "test_harness", f"{_TOOL_ROOT}/run_tests.py:main"),
        (
            "K12",
            "docker_stats_diagnostic",
            "tool:docker:stats",
        ),
    )
    observation = _BASE_OBSERVATION + (
        "argv",
        "effective_argv",
        "argv_execution_digest",
        "shell",
        "timeout_seconds",
        "host_executable",
        "disposable_resource_owned",
        "execution_disposition",
        "returncode",
    )
    return tuple(
        _entry(
            "K",
            code,
            f"{code}-{operation}",
            owner,
            operation,
            (
                ("operation", operation),
                ("fixed_argv_shape", K_FIXED_ARGV_SHAPES[code]),
                (
                    "rehearsal_argv_shape",
                    K_REHEARSAL_ARGV_SHAPES[code],
                ),
                ("shell", False),
                ("timeout_seconds", 10),
            ),
            "owner_resolved",
            executor=f"fix1.executor.k.{code.lower()}",
            observation=observation,
            cleanup="disposable_resource_settled",
            process="fixed_argv_shell_false",
            fixed_argv_shape=K_FIXED_ARGV_SHAPES[code],
        )
        for code, operation, owner in owners
    )


def _gates_and_selections() -> tuple[CatalogEntry, ...]:
    return (
        *_numbered_group(
            "COMPLETE_GATE",
            "complete-gate",
            4,
            f"{_TOOL_ROOT}/run_tests.py:main",
            "complete_gate",
            "passed",
            condition_modulus=1,
        ),
        *_numbered_group(
            "FOCUSED_SELECTION",
            "focused-selection",
            10,
            f"{_TOOL_ROOT}/run_tests.py:main",
            "focused_selection",
            "passed",
            condition_modulus=1,
        ),
    )
