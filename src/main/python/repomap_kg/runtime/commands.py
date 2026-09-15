"""Local runtime file rendering and table projection helpers."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from pathlib import Path

from repomap_kg.runtime.compose import render_compose_yaml as _render_release_compose
from repomap_kg.runtime.plan import (
    LocalRuntimeDiagnostic,
    LocalRuntimeError,
    LocalRuntimePlan,
    LocalRuntimeResult,
)
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE,
    GO_RELEASE_VERSION,
    PACKAGED_PG_DUMP,
    PACKAGED_PG_RESTORE,
    PACKAGED_PSQL,
    POSTGRES_RELEASE_IMAGE,
    POSTGRES_RELEASE_VERSION,
    PSYCOPG_LIBPQ_VERSION,
    PSYCOPG_RELEASE_VERSION,
    PYTHON_RELEASE_IMAGE,
    PYTHON_RELEASE_VERSION,
    SETUPTOOLS_RELEASE_VERSION,
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


def render_server_dockerfile() -> str:
    return f"""\
FROM {GO_RELEASE_IMAGE} AS go-helper
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src/main/go
COPY src/main/go/ ./
RUN test "${{TARGETOS}}" = "linux" \\
    && case "${{TARGETARCH}}" in amd64|arm64) ;; *) exit 1 ;; esac \\
    && mkdir -p /out \\
    && CGO_ENABLED=0 GOOS="${{TARGETOS}}" GOARCH="${{TARGETARCH}}" \\
       go build -trimpath -o /out/repomap-go-extract ./cmd/repomap-go-extract

FROM {PYTHON_RELEASE_IMAGE} AS python-runtime
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/main/python ./src/main/python
COPY src/main/resources ./src/main/resources
RUN python -m pip install --no-cache-dir setuptools=={SETUPTOOLS_RELEASE_VERSION} \\
    && python -m pip install --no-cache-dir --no-build-isolation .

RUN python -c "from pathlib import Path; from repomap_kg.storage import discover_migrations; from repomap_kg.coordinator._control_schema import discover_control_migrations; encode=lambda items: tuple((item.relative_path,item.changeset_id,item.checksum) for item in items); installed_graph=encode(discover_migrations()); source_graph=encode(discover_migrations(Path('/build/src/main/resources/rdbms'))); installed_control=encode(discover_control_migrations()); source_control=encode(discover_control_migrations(Path('/build/src/main/resources/coordinator-rdbms'))); assert installed_graph == source_graph; assert installed_control == source_control"
RUN python -m pip uninstall -y pip setuptools \\
    && rm -rf /usr/local/lib/python3.12/ensurepip \\
    && python -c "from importlib.util import find_spec; assert find_spec('pip') is None; assert find_spec('setuptools') is None"

FROM {POSTGRES_RELEASE_IMAGE} AS runtime
ARG TARGETARCH
COPY --from=python-runtime /usr/local /usr/local
COPY --from=python-runtime /usr/lib /usr/lib
COPY --from=go-helper /out/repomap-go-extract /tmp/repomap-go-extract
COPY --from=go-helper /usr/local/go/LICENSE /usr/share/doc/repomap-kg/go/LICENSE
RUN install -d -m 0700 /repo-map-home /repo-map-home/runtime /repo-map-home/coordinator /repo-map-admin \
    && install -m 0444 /dev/null /etc/repomap-release-container \
    && chmod 1777 /tmp
RUN package_root="$(python -c 'import pathlib, repomap_kg; print(pathlib.Path(repomap_kg.__file__).parent)')" \\
    && install -D -m 0755 /tmp/repomap-go-extract \\
       "${{package_root}}/_bin/linux-${{TARGETARCH}}/repomap-go-extract" \\
    && rm /tmp/repomap-go-extract
ENV REPOMAP_PACKAGED_PSQL={PACKAGED_PSQL} \\
    REPOMAP_PACKAGED_PG_DUMP={PACKAGED_PG_DUMP} \\
    REPOMAP_PACKAGED_PG_RESTORE={PACKAGED_PG_RESTORE}
LABEL io.repomap.release.postgresql="{POSTGRES_RELEASE_VERSION}" \\
      io.repomap.release.python="{PYTHON_RELEASE_VERSION}" \\
      io.repomap.release.go="{GO_RELEASE_VERSION}" \\
      io.repomap.release.psycopg="{PSYCOPG_RELEASE_VERSION}" \\
      io.repomap.release.libpq="{PSYCOPG_LIBPQ_VERSION}"
RUN python -c "import psycopg; from psycopg import pq; assert psycopg.__version__ == '{PSYCOPG_RELEASE_VERSION}'; assert pq.version() == {PSYCOPG_LIBPQ_VERSION}"
RUN python -c "from repomap_kg.storage import discover_migrations; from repomap_kg.coordinator._control_schema import discover_control_migrations; assert discover_migrations(); assert discover_control_migrations()"
RUN python -c "from importlib.util import find_spec; assert find_spec('pip') is None; assert find_spec('setuptools') is None" \\
    && test ! -e /usr/local/lib/python3.12/ensurepip \\
    && test -s /usr/share/doc/repomap-kg/go/LICENSE \\
    && test -s /usr/local/lib/python3.12/LICENSE.txt
RUN case "$(psql --version)" in "psql (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac \\
    && case "$(pg_dump --version)" in "pg_dump (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac \\
    && case "$(pg_restore --version)" in "pg_restore (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac
RUN ! command -v go
ENTRYPOINT [\"python\", \"-m\", \"repomap_kg\"]
CMD [\"server\", \"serve\", \"--repo-map-home\", \"/repo-map-home\"]
"""

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
