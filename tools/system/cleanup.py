"""Resource cleanup and residue reclamation for the main system gate."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.system.config import (
    LABEL_RUN_ID,
    SystemTestConfig,
)


def perform_system_cleanup(
    *,
    compose_dir: Path | None,
    candidate_image_id: str | None,
    config: SystemTestConfig,
    client: Any | None,
    env: dict[str, str] | None = None,
    timeout_seconds: float = 120.0,
    created_image_ids: tuple[str, ...] = (),
    created_volume_names: tuple[str, ...] = (),
    created_network_names: tuple[str, ...] = (),
    created_container_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Tear down only exact run-owned containers, volumes, networks, and candidate image."""
    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    errors: list[str] = []
    containers_removed = 0
    images_removed = 0
    volumes_removed = 0
    networks_removed = 0
    cleanup_deadline = time.monotonic() + timeout_seconds
    docker_api = getattr(client, "api", None) if client is not None else None
    api_timeout_missing = object()
    original_api_timeout = (
        getattr(docker_api, "timeout", api_timeout_missing)
        if docker_api is not None
        else api_timeout_missing
    )

    def remaining_timeout() -> float:
        remaining = cleanup_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("system cleanup deadline exhausted")
        return max(1.0, remaining)

    def is_not_found(error: BaseException) -> bool:
        try:
            from docker.errors import NotFound
        except ImportError:
            return False
        return isinstance(error, NotFound)

    def docker_call(action: Any, /, *args: Any, **kwargs: Any) -> Any:
        remaining = remaining_timeout()
        if docker_api is None:
            return action(*args, **kwargs)
        docker_api.timeout = remaining
        try:
            return action(*args, **kwargs)
        finally:
            if original_api_timeout is api_timeout_missing:
                try:
                    del docker_api.timeout
                except AttributeError:
                    pass
            else:
                docker_api.timeout = original_api_timeout

    # 1. Docker compose down for this exact compose project
    if compose_dir is not None and compose_dir.exists():
        try:
            res = subprocess.run(
                ["docker", "compose", "--profile", "*", "down", "-v", "--remove-orphans", "--timeout", "10"],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                env=run_env,
                timeout=remaining_timeout(),
                check=False,
            )
            if res.returncode != 0:
                errors.append(f"docker compose down returned exit {res.returncode}: {res.stderr.strip()}")
        except Exception as exc:
            errors.append(f"docker compose down failed: {exc}")

    # 2. Exact run-owned container cleanup (by label and recorded container ID)
    if client is not None:
        try:
            containers = docker_call(
                client.containers.list,
                all=True,
                filters={"label": f"{LABEL_RUN_ID}={config.run_id}"},
            )
            for container in containers:
                try:
                    docker_call(container.remove, force=True, v=True)
                    containers_removed += 1
                except Exception as exc:
                    errors.append(f"failed to remove run-labeled container {container.id[:12]}: {exc}")
        except Exception as exc:
            errors.append(f"listing run-labeled containers failed: {exc}")

        for cid in created_container_ids:
            try:
                c = docker_call(client.containers.get, cid)
                docker_call(c.remove, force=True, v=True)
                containers_removed += 1
            except Exception as exc:
                if not is_not_found(exc):
                    errors.append(
                        f"failed to remove recorded container {cid[:12]}: {exc}"
                    )

    # 3. Exact run-owned volume cleanup (by run label and recorded volume names only)
    if client is not None:
        try:
            for vol in docker_call(
                client.volumes.list,
                filters={"label": f"{LABEL_RUN_ID}={config.run_id}"},
            ):
                try:
                    docker_call(vol.remove, force=True)
                    volumes_removed += 1
                except Exception as exc:
                    errors.append(f"failed to remove run-labeled volume {getattr(vol, 'name', vol)}: {exc}")

            for vol_name in created_volume_names:
                try:
                    vol = docker_call(client.volumes.get, vol_name)
                    docker_call(vol.remove, force=True)
                    volumes_removed += 1
                except Exception as exc:
                    if not is_not_found(exc):
                        errors.append(f"failed to remove recorded volume {vol_name}: {exc}")
        except Exception as exc:
            errors.append(f"volume cleanup failed: {exc}")

    # 4. Exact rendered project network cleanup.
    if client is not None:
        for network_name in created_network_names:
            try:
                network = docker_call(client.networks.get, network_name)
                docker_call(network.remove)
                networks_removed += 1
            except Exception as exc:
                if not is_not_found(exc):
                    errors.append(
                        f"failed to remove recorded network {network_name}: {exc}"
                    )

    # 5. Remove candidate image tag, ID, and boundary-attributed intermediates.
    if client is not None:
        if config.candidate_tag:
            try:
                docker_call(
                    client.images.remove,
                    image=config.candidate_tag,
                    force=True,
                )
                images_removed += 1
            except Exception as exc:
                if not is_not_found(exc):
                    errors.append(f"failed to remove candidate image tag {config.candidate_tag}: {exc}")

        if candidate_image_id and candidate_image_id != "unavailable":
            try:
                docker_call(
                    client.images.remove,
                    image=candidate_image_id,
                    force=True,
                )
                images_removed += 1
            except Exception as exc:
                if not is_not_found(exc):
                    errors.append(f"failed to remove candidate image ID {candidate_image_id[:19]}: {exc}")

        for img_id in created_image_ids:
            try:
                docker_call(client.images.remove, image=img_id, force=True)
                images_removed += 1
            except Exception as exc:
                if not is_not_found(exc):
                    errors.append(
                        f"failed to remove attributed intermediate {img_id[:19]}: {exc}"
                    )

    # 6. Prove terminal absence of every exact run-owned resource
    terminal_absence_verified = client is not None
    if client is None:
        errors.append("Docker client unavailable; terminal absence not verified")
    if client is not None:
        try:
            # Check recorded container IDs
            for cid in created_container_ids:
                try:
                    c = docker_call(client.containers.get, cid)
                    terminal_absence_verified = False
                    errors.append(f"terminal absence failed: recorded container {cid[:12]} still exists ({getattr(c, 'name', '')})")
                except Exception as exc:
                    if not is_not_found(exc):
                        terminal_absence_verified = False
                        errors.append(
                            f"container absence check failed for {cid[:12]}: {exc}"
                        )

            # Check run-labeled containers
            remaining_containers = docker_call(
                client.containers.list,
                all=True,
                filters={"label": f"{LABEL_RUN_ID}={config.run_id}"},
            )
            if remaining_containers:
                terminal_absence_verified = False
                errors.append(
                    f"terminal absence failed: {len(remaining_containers)} run-labeled containers still exist"
                )

            # Check recorded named volumes
            for vol_name in created_volume_names:
                try:
                    docker_call(client.volumes.get, vol_name)
                    terminal_absence_verified = False
                    errors.append(f"terminal absence failed: recorded volume {vol_name} still exists")
                except Exception as exc:
                    if not is_not_found(exc):
                        terminal_absence_verified = False
                        errors.append(
                            f"volume absence check failed for {vol_name}: {exc}"
                        )

            # Check run-labeled volumes
            remaining_volumes = docker_call(
                client.volumes.list,
                filters={"label": f"{LABEL_RUN_ID}={config.run_id}"},
            )
            if remaining_volumes:
                terminal_absence_verified = False
                errors.append(
                    f"terminal absence failed: {len(remaining_volumes)} run-labeled volumes still exist"
                )

            for network_name in created_network_names:
                try:
                    docker_call(client.networks.get, network_name)
                    terminal_absence_verified = False
                    errors.append(
                        f"terminal absence failed: recorded network {network_name} still exists"
                    )
                except Exception as exc:
                    if not is_not_found(exc):
                        terminal_absence_verified = False
                        errors.append(
                            f"network absence check failed for {network_name}: {exc}"
                        )

            remaining_networks = docker_call(
                client.networks.list,
                filters={"label": f"{LABEL_RUN_ID}={config.run_id}"}
            )
            if remaining_networks:
                terminal_absence_verified = False
                errors.append(
                    f"terminal absence failed: {len(remaining_networks)} run-labeled networks still exist"
                )

            # Check candidate tag
            if config.candidate_tag:
                all_tags = [
                    tag
                    for img in docker_call(client.images.list)
                    for tag in (getattr(img, "tags", None) or [])
                ]
                if config.candidate_tag in all_tags:
                    terminal_absence_verified = False
                    errors.append(f"terminal absence failed: candidate tag {config.candidate_tag} still present")

            # Check candidate image ID
            if candidate_image_id and candidate_image_id != "unavailable":
                try:
                    docker_call(client.images.get, candidate_image_id)
                    terminal_absence_verified = False
                    errors.append(f"terminal absence failed: candidate image ID {candidate_image_id[:19]} still exists")
                except Exception as exc:
                    if not is_not_found(exc):
                        terminal_absence_verified = False
                        errors.append(
                            f"candidate image absence check failed: {exc}"
                        )

            # Check intermediate image IDs
            for img_id in created_image_ids:
                try:
                    docker_call(client.images.get, img_id)
                    terminal_absence_verified = False
                    errors.append(f"terminal absence failed: intermediate image ID {img_id[:19]} still exists")
                except Exception as exc:
                    if not is_not_found(exc):
                        terminal_absence_verified = False
                        errors.append(
                            f"intermediate image absence check failed: {exc}"
                        )

        except Exception as exc:
            terminal_absence_verified = False
            errors.append(f"terminal absence verification failed: {exc}")

    return {
        "success": len(errors) == 0 and terminal_absence_verified,
        "errors": errors,
        "containers_removed": containers_removed,
        "images_removed": images_removed,
        "volumes_removed": volumes_removed,
        "networks_removed": networks_removed,
        "terminal_absence_verified": terminal_absence_verified,
    }
