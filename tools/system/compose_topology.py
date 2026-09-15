"""Compose topology rendering and source-mount inspection for the system gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from repomap_kg.runtime.compose import render_compose_yaml
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import LocalRuntimePlan
from tools.system.config import SystemTestConfig, SystemTestError

APPLICATION_SERVICES = frozenset(
    {"init-upgrade", "http", "mcp", "coordinator", "lifecycle-admin"}
)


def prepare_system_compose_topology(
    *,
    compose_dir: Path,
    repo_map_home: Path,
    fixture_repo: Path,
    repo_root: Path,
    config: SystemTestConfig,
    server_port: int = 58180,
    postgres_port: int = 55434,
) -> tuple[LocalRuntimePlan, Path, Path, dict[str, Any]]:
    """Prepare runtime plan, write compose definitions and override, and inspect topology."""
    compose_dir = Path(compose_dir).resolve()
    compose_dir.mkdir(parents=True, exist_ok=True)
    repo_map_home = Path(repo_map_home).resolve()
    repo_map_home.mkdir(parents=True, exist_ok=True)

    config_content = f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "docker"
server_host_port = {server_port}
bind_host = "127.0.0.1"

[runtime.postgres]
direct_host_port_enabled = true
host_port = {postgres_port}
bind_host = "127.0.0.1"

[postgres]
host = "postgres"
port = 5432
database = "repomap"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "fixture"
name = "fixture"
root_path = "{fixture_repo.resolve()}"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
exclude_paths = [
  ".git",
  ".venv",
  "__pycache__",
]

[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
"""
    config_file = repo_map_home / "repomap.rpl.toml"
    config_file.write_text(config_content, encoding="utf-8")

    # Initialize runtime structure
    init_res = setup_local_runtime(repo_map_home)
    plan = init_res.plan

    base_compose_content = render_compose_yaml(plan)
    base_compose_path = compose_dir / "docker-compose.yml"
    base_compose_path.write_text(base_compose_content, encoding="utf-8")

    # Generate system override mapping all application services to candidate image tag
    from repomap_kg.runtime.release import POSTGRES_RELEASE_IMAGE
    override_yaml_lines = [
        "services:",
        "  postgres:",
        f"    image: {POSTGRES_RELEASE_IMAGE}",
    ]
    for svc in sorted(APPLICATION_SERVICES):
        override_yaml_lines.append(f"  {svc}:")
        override_yaml_lines.append(f"    image: {config.candidate_tag}")
        if svc == "coordinator":
            override_yaml_lines.append("    environment:")
            override_yaml_lines.append("      _REPOMAP_SYSTEM_TEST_PAUSE_PATH: /tmp/system_pause_trigger")
            override_yaml_lines.append("      REPOMAP_PG_PASSWORD: ${REPOMAP_PG_PASSWORD}")
            override_yaml_lines.append("      PGPASSWORD: ${REPOMAP_PG_PASSWORD}")
    override_yaml_lines.append("")
    override_path = compose_dir / "docker-compose.override.yml"
    override_path.write_text("\n".join(override_yaml_lines), encoding="utf-8")

    # Read env vars from generated .env and mirror into compose_dir
    env_vars: dict[str, str] = {}
    if plan.env_file.exists():
        env_content = plan.env_file.read_text(encoding="utf-8")
        env_content += f"COMPOSE_PROJECT_NAME={config.compose_project_name}\n"
        (compose_dir / ".env").write_text(env_content, encoding="utf-8")
        for line in env_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()

    # Verify compose topology via docker compose config --format json
    topology = inspect_and_verify_topology(
        compose_dir=compose_dir,
        repo_root=repo_root,
        candidate_tag=config.candidate_tag,
        env=env_vars,
    )

    return plan, base_compose_path, override_path, topology


def inspect_and_verify_topology(
    *,
    compose_dir: Path,
    repo_root: Path,
    candidate_tag: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute docker compose config --format json and verify no repo source mounts exist."""
    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    result = subprocess.run(
        ["docker", "compose", "--profile", "*", "config", "--format", "json"],
        cwd=compose_dir,
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
    )
    if result.returncode != 0:
        raise SystemTestError(
            f"docker compose config failed: {result.stderr.strip()}"
        )

    try:
        config_data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemTestError(f"invalid JSON from docker compose config: {error}") from error

    if not isinstance(config_data, dict) or not isinstance(config_data.get("services"), dict):
        raise SystemTestError("malformed compose topology: 'services' dictionary is missing")

    services: dict[str, Any] = config_data["services"]
    resolved_repo_root = repo_root.resolve()

    # 1. Require every application service to exist and use the exact candidate tag
    for svc_name in APPLICATION_SERVICES:
        if svc_name not in services:
            raise SystemTestError(
                f"expected application service {svc_name!r} is missing from compose topology"
            )
        svc = services[svc_name]
        if not isinstance(svc, dict):
            raise SystemTestError(f"malformed compose service definition for {svc_name!r}")
        image = svc.get("image")
        if image != candidate_tag:
            raise SystemTestError(
                f"service {svc_name!r} has image {image!r}, expected candidate tag {candidate_tag!r}"
            )

    # 2. Strictly reject any bind mount from repo root or any descendant of repo root across ALL services
    for s_name, s_data in services.items():
        if not isinstance(s_data, dict):
            raise SystemTestError(f"malformed service record for {s_name!r}")
        volumes = s_data.get("volumes", [])
        if not isinstance(volumes, list):
            raise SystemTestError(f"malformed volumes section in service {s_name!r}")
        for vol in volumes:
            if isinstance(vol, str):
                raise SystemTestError(
                    f"malformed string volume record in service {s_name!r}: {vol!r}"
                )
            if not isinstance(vol, dict):
                raise SystemTestError(f"malformed volume record in service {s_name!r}: {vol!r}")
            vol_type = vol.get("type")
            if vol_type == "volume":
                source = vol.get("source")
                if not isinstance(source, str) or not source:
                    raise SystemTestError(
                        f"malformed named volume in service {s_name!r}: {vol!r}"
                    )
                continue
            if vol_type == "tmpfs":
                continue
            if vol_type == "bind":
                source_str = vol.get("source")
                if not source_str or not isinstance(source_str, str):
                    raise SystemTestError(f"malformed bind volume in service {s_name!r}: {vol!r}")
                source_path = Path(source_str).resolve()
                if source_path == resolved_repo_root or resolved_repo_root in source_path.parents:
                    raise SystemTestError(
                        f"service {s_name!r} contains forbidden repository source mount: {source_path}"
                    )
            elif vol_type is None:
                raise SystemTestError(f"malformed volume record (missing type) in service {s_name!r}: {vol!r}")
            else:
                raise SystemTestError(f"unsupported volume type {vol_type!r} in service {s_name!r}: {vol!r}")

    return config_data
