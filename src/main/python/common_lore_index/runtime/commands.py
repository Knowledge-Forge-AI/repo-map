"""Local runtime file rendering and table projection helpers."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from pathlib import Path

from common_lore_index.runtime.compose import render_compose_yaml as _render_release_compose
from common_lore_index.runtime.plan import (
    LocalRuntimeDiagnostic,
    LocalRuntimeError,
    LocalRuntimePlan,
    LocalRuntimeResult,
)
from common_lore_index.runtime.release import (
    DYNAMIC_PACKAGE_MANIFEST as DYNAMIC_PACKAGE_MANIFEST,
    GO_RELEASE_IMAGE as GO_RELEASE_IMAGE,
    GO_RELEASE_VERSION as GO_RELEASE_VERSION,
    PACKAGED_PG_DUMP as PACKAGED_PG_DUMP,
    PACKAGED_PG_RESTORE as PACKAGED_PG_RESTORE,
    PACKAGED_PSQL as PACKAGED_PSQL,
    POSTGRES_RELEASE_IMAGE as POSTGRES_RELEASE_IMAGE,
    POSTGRES_RELEASE_VERSION as POSTGRES_RELEASE_VERSION,
    PSYCOPG_C_GENERATED_SOURCES as PSYCOPG_C_GENERATED_SOURCES,
    PSYCOPG_C_SDIST_MEMBERS as PSYCOPG_C_SDIST_MEMBERS,
    PSYCOPG_C_SDIST_SHA256 as PSYCOPG_C_SDIST_SHA256,
    PSYCOPG_C_SDIST_SIZE as PSYCOPG_C_SDIST_SIZE,
    PSYCOPG_C_SDIST_URL as PSYCOPG_C_SDIST_URL,
    PSYCOPG_LIBPQ_VERSION as PSYCOPG_LIBPQ_VERSION,
    PSYCOPG_RELEASE_VERSION as PSYCOPG_RELEASE_VERSION,
    PRODUCT_MINIMUM_LIBPQ_VERSION as PRODUCT_MINIMUM_LIBPQ_VERSION,
    PSYCOPG_TAG_COMMIT as PSYCOPG_TAG_COMMIT,
    PYTHON_RELEASE_IMAGE as PYTHON_RELEASE_IMAGE,
    PYTHON_RELEASE_VERSION as PYTHON_RELEASE_VERSION,
    RELEASE_BUILD_LINKAGE_PY as RELEASE_BUILD_LINKAGE_PY,
    RELEASE_BUILD_ONLY_MODULES as RELEASE_BUILD_ONLY_MODULES,
    RELEASE_FINAL_PROBE_PY as RELEASE_FINAL_PROBE_PY,
    RELEASE_SDIST_INSPECTION_PY as RELEASE_SDIST_INSPECTION_PY,
    RELEASE_WHEEL_REQUIREMENTS as RELEASE_WHEEL_REQUIREMENTS,
    PlatformPackages as PlatformPackages,
    render_apt_steps as render_apt_steps,
    validate_package_manifest as validate_package_manifest,
)

from common_lore_index.runtime.release_dockerfile import (
    PYTHON_PAYLOAD_SOURCE as PYTHON_PAYLOAD_SOURCE,
    render_server_dockerfile as render_server_dockerfile,
    _platform_case as _platform_case,
    _expected_identity as _expected_identity,
)


def ensure_runtime_files_exist(plan: LocalRuntimePlan) -> None:
    missing = [
        path for path in (plan.compose_file, plan.env_file, plan.dockerfile) if not path.exists()
    ]
    if missing:
        raise LocalRuntimeError(
            tuple(
                LocalRuntimeDiagnostic(
                    "error",
                    "runtime-files-missing",
                    str(path),
                    "runtime file is missing; run repomap-kg local setup",
                )
                for path in missing
            )
        )


def render_local_runtime_files(plan: LocalRuntimePlan) -> dict[Path, str]:
    return {
        plan.compose_file: render_compose_yaml(plan),
        plan.dockerfile: render_server_dockerfile(),
    }


def render_compose_yaml(plan: LocalRuntimePlan) -> str:
    return _render_release_compose(plan)


RUNTIME_HOME_HASH_ENV = "REPOMAP_RUNTIME_HOME_HASH"
_RUNTIME_HOME_HASH_RE = re.compile(r"[0-9a-f]{12}\Z")


def default_env_text(runtime_home_hash: str | None = None) -> str:
    password = secrets.token_urlsafe(32)
    read_password = secrets.token_urlsafe(32)
    refresh_password = secrets.token_urlsafe(32)
    control_password = secrets.token_urlsafe(32)
    text = (
        f"POSTGRES_PASSWORD={password}\n"
        f"REPOMAP_PG_PASSWORD={password}\n"
        f"PGPASSWORD={password}\n"
        f"REPOMAP_READ_STATUS_PASSWORD={read_password}\n"
        f"REPOMAP_REFRESH_PUBLICATION_PASSWORD={refresh_password}\n"
        f"REPOMAP_COORDINATOR_CONTROL_PASSWORD={control_password}\n"
    )
    if runtime_home_hash is not None:
        _validate_runtime_home_hash(runtime_home_hash)
        text += f"{RUNTIME_HOME_HASH_ENV}={runtime_home_hash}\n"
    return text


def ensure_runtime_home_hash(env_file: Path, runtime_home_hash: str) -> bool:
    """Atomically align the private runtime identity authority without changing secrets."""

    _validate_runtime_home_hash(runtime_home_hash)
    text = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    expected = f"{RUNTIME_HOME_HASH_ENV}={runtime_home_hash}"
    lines = text.splitlines()
    if sum(line == expected for line in lines) == 1 and not any(
        line.startswith(f"{RUNTIME_HOME_HASH_ENV}=") and line != expected
        for line in lines
    ):
        env_file.chmod(0o600)
        return False
    retained = [
        line for line in lines if not line.startswith(f"{RUNTIME_HOME_HASH_ENV}=")
    ]
    retained.append(expected)
    replacement = "\n".join(retained) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=env_file.parent,
            prefix=f".{env_file.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            os.chmod(stream.name, 0o600)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, env_file)
        env_file.chmod(0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return True


def _validate_runtime_home_hash(runtime_home_hash: str) -> None:
    if _RUNTIME_HOME_HASH_RE.fullmatch(runtime_home_hash) is None:
        raise ValueError("runtime home hash is invalid")


def format_local_runtime_table(result: LocalRuntimeResult) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap local runtime {payload['command']}",
        f"result: {payload['result']}",
        (
            "runtime: "
            f"container_runtime={payload['runtime']['container_runtime']} "
            f"direct_db={'enabled' if payload['runtime']['direct_db_host_port_enabled'] else 'disabled'} "
            f"postgres_host_port_published={str(payload['runtime']['postgres_host_port_published']).lower()} "
            f"postgres_internal={payload['runtime']['postgres_internal_host']}:{payload['runtime']['postgres_internal_port']} "
            f"server={payload['runtime']['bind_host']}:{payload['runtime']['server_host_port']} "
            f"containers_started={str(payload['runtime']['containers_started']).lower()}"
        ),
        (
            "safety: "
            f"graph_roots_read={str(payload['graph_roots_read']).lower()} "
            f"server_memory_read={str(payload['server_memory_read']).lower()} "
            f"destructive_db_actions={str(payload['destructive_db_actions']).lower()} "
            f"persistent_volume_deleted={str(payload['persistent_volume_deleted']).lower()} "
            f"remote_postgres={str(payload['network_exposure']['remote_postgres']).lower()}"
        ),
        f"created_file_count={payload['created_file_count']}",
    ]
    if payload["dbeaver"]["enabled"]:
        lines.insert(
            4,
            (
                "dbeaver: "
                f"host={payload['dbeaver']['host']} "
                f"port={payload['dbeaver']['port']} "
                f"database={payload['dbeaver']['database']} "
                f"user={payload['dbeaver']['user']} "
                f"password={payload['dbeaver']['password']} "
                f"ssl={payload['dbeaver']['ssl']}"
            ),
        )
    else:
        lines.insert(4, f"dbeaver: disabled; {payload['dbeaver']['message']}")
    if payload["containers"]:
        for component in ("server", "postgres"):
            container = payload["containers"].get(component)
            if not container:
                continue
            lines.append(
                "container: "
                f"component={component} "
                f"status={container['status']} "
                f"owned={str(container['owned']).lower()} "
                f"health={container.get('health', 'n/a')}"
            )
    if payload["server_health"]["checked"]:
        lines.append(
            "server_health: "
            f"status={payload['server_health']['status']} "
            f"reachable={str(payload['server_health']['reachable']).lower()} "
            f"url={payload['server_health'].get('url', '')}"
        )
    for diagnostic in payload["diagnostics"]:
        lines.append(
            f"{diagnostic['severity']}: {diagnostic['code']}: {diagnostic['message']}"
        )
    return "\n".join(lines)
