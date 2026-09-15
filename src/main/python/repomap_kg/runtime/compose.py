"""Complete fresh-artifact Compose projection for the local release cluster."""

from __future__ import annotations

import json
from pathlib import Path

from repomap_kg.coordinator.limits import DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
from repomap_kg.runtime.plan import LocalRuntimePlan, resolve_runtime_source_root
from repomap_kg.runtime.release import PACKAGED_PSQL, POSTGRES_RELEASE_IMAGE


def render_compose_yaml(plan: LocalRuntimePlan) -> str:
    """Render the health-gated least-capability release cluster."""

    source_root = resolve_runtime_source_root()
    config_mounts = _config_mounts(plan)
    execution_mounts = _source_mounts(plan)
    postgres_ports = ""
    if plan.direct_db_host_port_enabled:
        postgres_ports = (
            "    ports:\n"
            f'      - "{plan.postgres_bind_host}:{plan.postgres_host_port}:5432"\n'
        )
    application = f"repomap-runtime:{plan.identity.home_hash}"
    return f"""\
x-repomap-application: &repomap-application
  image: {application}
  build:
    context: {_yaml(source_root)}
    dockerfile: {_yaml(plan.dockerfile)}

services:
  postgres:
    image: {POSTGRES_RELEASE_IMAGE}
    container_name: {plan.identity.postgres_container}
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: {plan.user}
      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD}}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
{postgres_ports}\
    volumes:
      - ./postgres-data:/var/lib/postgresql/data
    networks:
      - repomap-local
    healthcheck:
      test: ["CMD", "/usr/bin/pg_isready", "-U", "{plan.user}", "-d", "postgres"]
      interval: 2s
      timeout: 3s
      retries: 30
      start_period: 2s
    restart: unless-stopped
    labels:
{_labels(plan, "postgres")}

  init-upgrade:
    <<: *repomap-application
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      REPOMAP_HOME: /repo-map-home
      REPOMAP_ADMIN_ROOT: /repo-map-admin
      REPOMAP_CONTAINER_INTERNAL: "1"
      REPOMAP_RUNTIME_HOME_HASH: {plan.identity.home_hash}
      REPOMAP_PG_PASSWORD: ${{REPOMAP_PG_PASSWORD}}
      PGPASSWORD: ${{REPOMAP_PG_PASSWORD}}
      REPOMAP_READ_STATUS_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      REPOMAP_REFRESH_PUBLICATION_PASSWORD: ${{REPOMAP_REFRESH_PUBLICATION_PASSWORD}}
      REPOMAP_COORDINATOR_CONTROL_PASSWORD: ${{REPOMAP_COORDINATOR_CONTROL_PASSWORD}}
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:mode=1777
    volumes:
{config_mounts}\
{_runtime_env_mount(plan)}\
      - admin-state:/repo-map-admin
    networks:
      - repomap-local
    command: ["ops", "release-cluster-init", "--repo-map-home", "/repo-map-home", "--json"]
    restart: "no"
    labels:
{_labels(plan, "init-upgrade")}

  http:
    <<: *repomap-application
    container_name: {plan.identity.server_container}
    depends_on:
      init-upgrade:
        condition: service_completed_successfully
    environment:
      REPOMAP_HOME: /repo-map-home
      REPOMAP_PG_USER: repomap_read_status
      REPOMAP_READ_STATUS_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      REPOMAP_PG_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      PGPASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
    ports:
      - "{plan.bind_host}:{plan.server_host_port}:{plan.server_host_port}"
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:mode=1777
    volumes:
{config_mounts}\
    networks:
      - repomap-local
      - repomap-http
    command: ["server", "serve", "--repo-map-home", "/repo-map-home", "--host", "0.0.0.0", "--port", "{plan.server_host_port}", "--container-internal-bind"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{plan.server_host_port}/readyz', timeout=2).read()"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 5s
    restart: unless-stopped
    labels:
{_labels(plan, "http")}

  mcp:
    <<: *repomap-application
    depends_on:
      init-upgrade:
        condition: service_completed_successfully
    environment:
      REPOMAP_HOME: /repo-map-home
      REPOMAP_PG_USER: repomap_read_status
      REPOMAP_READ_STATUS_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      REPOMAP_PG_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      PGPASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:mode=1777
    volumes:
{config_mounts}\
    networks:
      - repomap-local
    command: ["mcp", "serve", "--repo-map-home", "/repo-map-home"]
    stdin_open: true
    restart: "no"
    profiles: ["integration"]
    labels:
{_labels(plan, "mcp")}

  coordinator:
    <<: *repomap-application
    depends_on:
      init-upgrade:
        condition: service_completed_successfully
    environment:
      REPOMAP_HOME: /repo-map-home
      REPOMAP_READ_STATUS_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      REPOMAP_REFRESH_PUBLICATION_PASSWORD: ${{REPOMAP_REFRESH_PUBLICATION_PASSWORD}}
      REPOMAP_COORDINATOR_CONTROL_PASSWORD: ${{REPOMAP_COORDINATOR_CONTROL_PASSWORD}}
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:mode=1777
    volumes:
{config_mounts}\
      - coordinator-state:/repo-map-home/coordinator
{execution_mounts}\
    networks:
      - repomap-local
    command: ["ops", "coordinator-serve", "--repo-map-home", "/repo-map-home", "--service-package-psql", "{PACKAGED_PSQL}", "--startup-wait-seconds", "{DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS}", "--json"]
    healthcheck:
      test: ["CMD", "python", "-m", "repomap_kg", "ops", "coordinator-health", "--repo-map-home", "/repo-map-home", "--json"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: {DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS}s
    restart: unless-stopped
    labels:
{_labels(plan, "coordinator")}

  lifecycle-admin:
    <<: *repomap-application
    depends_on:
      init-upgrade:
        condition: service_completed_successfully
    environment:
      REPOMAP_HOME: /repo-map-home
      REPOMAP_ADMIN_ROOT: /repo-map-admin
      REPOMAP_CONTAINER_INTERNAL: "1"
      REPOMAP_RUNTIME_HOME_HASH: {plan.identity.home_hash}
      REPOMAP_PG_PASSWORD: ${{REPOMAP_PG_PASSWORD}}
      PGPASSWORD: ${{REPOMAP_PG_PASSWORD}}
      REPOMAP_READ_STATUS_PASSWORD: ${{REPOMAP_READ_STATUS_PASSWORD}}
      REPOMAP_REFRESH_PUBLICATION_PASSWORD: ${{REPOMAP_REFRESH_PUBLICATION_PASSWORD}}
      REPOMAP_COORDINATOR_CONTROL_PASSWORD: ${{REPOMAP_COORDINATOR_CONTROL_PASSWORD}}
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:mode=1777
    volumes:
{config_mounts}\
{_runtime_env_mount(plan)}\
      - admin-state:/repo-map-admin
{execution_mounts}\
    networks:
      - repomap-local
    command: ["ops", "release-cluster-status", "--repo-map-home", "/repo-map-home", "--json"]
    restart: "no"
    profiles: ["admin"]
    labels:
{_labels(plan, "lifecycle-admin")}

networks:
  repomap-local:
    name: {plan.identity.network_name}
    internal: true
    labels:
{_labels(plan, "network")}
  repomap-http:
    name: {plan.identity.network_name}-http
    labels:
{_labels(plan, "http-network")}

volumes:
  coordinator-state:
    labels:
{_labels(plan, "coordinator-state")}
  admin-state:
    labels:
{_labels(plan, "admin-state")}
"""


def _config_mounts(plan: LocalRuntimePlan) -> str:
    files = plan.config.config_files if plan.config is not None else ()
    return "".join(
        _bind_mount(plan.repo_map_home / name, Path("/repo-map-home") / name)
        for name in files
    )


def _source_mounts(plan: LocalRuntimePlan) -> str:
    if plan.config is None:
        return ""
    roots = sorted(
        {
            Path(binding.root_path_expanded).resolve(strict=False)
            for graph in plan.config.graphs
            if graph.enabled
            for binding in graph.effective_source_bindings
            if binding.enabled
        },
        key=str,
    )
    return "".join(_bind_mount(root, root) for root in roots)


def _bind_mount(source: Path, target: Path) -> str:
    return (
        "      - type: bind\n"
        f"        source: {_yaml(source.resolve(strict=False))}\n"
        f"        target: {_yaml(target)}\n"
        "        read_only: true\n"
    )


def _runtime_env_mount(plan: LocalRuntimePlan) -> str:
    return _bind_mount(plan.env_file, Path("/repo-map-home/runtime/.env"))


def _labels(plan: LocalRuntimePlan, component: str) -> str:
    prefix = " " * 6
    return "\n".join(
        f'{prefix}{key}: "{value}"'
        for key, value in plan.identity.labels(component).items()
    )


def _yaml(value: Path | str) -> str:
    return json.dumps(str(value))


__all__ = ["render_compose_yaml"]
