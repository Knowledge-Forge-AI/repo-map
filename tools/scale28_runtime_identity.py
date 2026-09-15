"""Public-safe exact-stack identity capture for SCALE28 qualification."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import platform
from typing import Mapping, TypeGuard, TypedDict

import docker
import psutil
import psycopg

from scale12_resource_sampling import (
    _DOCKER_READ_ERRORS,
    _container_stats_memory_bytes,
    _create_docker_api_client,
)


_STATS_FIELD_SHAPE = "memory_stats.usage+memory_stats.stats.inactive_file"
_OPERATION_SHAPE = "one_shot_stats_no_subprocess"
SCALE_QUALIFICATION_STATUS = "Q2"
_QUALIFICATION_PHASE = "TEST-COV5K-R2"


class _EnginePayloadValues(TypedDict):
    docker_api_version: str
    engine_server_version: str
    engine_operating_system: str
    engine_os_type: str
    engine_architecture: str
    cgroup_version: str
    container_image_digest: str


@dataclass(frozen=True, slots=True)
class EngineComponentIdentity:
    """One engine component with public fields and digest-bound details."""

    name: str
    version: str
    detail_fields: tuple[str, ...]
    details_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "detail_fields": list(self.detail_fields),
            "details_digest": self.details_digest,
        }


@dataclass(frozen=True, slots=True)
class Scale28RuntimeIdentity:
    """One unqualified, public-safe identity for the post-R1 runtime stack."""

    python_implementation: str
    python_version: str
    repomap_commit: str
    psycopg_version: str
    libpq_version: str
    postgresql_server_version: str
    psutil_version: str
    host_operating_system: str
    host_kernel: str
    docker_sdk_version: str
    docker_api_version: str
    engine_server_version: str
    engine_components: tuple[EngineComponentIdentity, ...]
    engine_operating_system: str
    engine_os_type: str
    engine_architecture: str
    cgroup_version: str
    container_image_digest: str
    container_stats_field_shape: str
    transport_class: str
    operation_shape: str = _OPERATION_SHAPE
    qualification_status: str = "unqualified"
    schema_version: int = 1

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "repomap_commit": self.repomap_commit,
            "psycopg_version": self.psycopg_version,
            "libpq_version": self.libpq_version,
            "postgresql_server_version": self.postgresql_server_version,
            "psutil_version": self.psutil_version,
            "host_operating_system": self.host_operating_system,
            "host_kernel": self.host_kernel,
            "docker_sdk_version": self.docker_sdk_version,
            "docker_api_version": self.docker_api_version,
            "engine_server_version": self.engine_server_version,
            "engine_components": [
                component.to_mapping() for component in self.engine_components
            ],
            "engine_operating_system": self.engine_operating_system,
            "engine_os_type": self.engine_os_type,
            "engine_architecture": self.engine_architecture,
            "cgroup_version": self.cgroup_version,
            "container_image_digest": self.container_image_digest,
            "container_stats_field_shape": self.container_stats_field_shape,
            "transport_class": self.transport_class,
            "operation_shape": self.operation_shape,
            "qualification_status": self.qualification_status,
        }


def runtime_identity_matches_qualification_receipt(
    identity: Scale28RuntimeIdentity,
    receipt: Mapping[str, object] | None,
) -> bool:
    """Require one exact Outcome-A successor receipt for SCALE qualification."""

    if not isinstance(identity, Scale28RuntimeIdentity) or not isinstance(
        receipt,
        Mapping,
    ):
        return False
    if (
        receipt.get("phase_id") != _QUALIFICATION_PHASE
        or receipt.get("outcome") != "A"
        or receipt.get("runtime_identity") != identity.to_mapping()
    ):
        return False
    return identity.qualification_status == "unqualified"


def capture_runtime_identity(
    *,
    runtime: str,
    container_name: str,
    repomap_commit: str,
    postgresql_server_version: str,
) -> Scale28RuntimeIdentity | None:
    """Capture identity without granting timing qualification."""

    if (
        runtime not in {"docker", "podman"}
        or not container_name
        or not _is_public_identity(repomap_commit)
        or not _is_public_identity(postgresql_server_version)
    ):
        raise ValueError("runtime identity input is invalid")
    opened = _create_docker_api_client(runtime)
    if opened is None:
        return None
    client, transport_class = opened
    result: Scale28RuntimeIdentity | None = None
    try:
        version = client.version()
        info = client.info()
        container = client.inspect_container(container_name)
        stats = client.stats(container_name, stream=False, one_shot=True)
        if _container_stats_memory_bytes(stats) is None:
            return None
        result = _identity_from_payloads(
            version=version,
            info=info,
            container=container,
            repomap_commit=repomap_commit,
            postgresql_server_version=postgresql_server_version,
            docker_api_version=client.api_version,
            transport_class=transport_class,
        )
    except _DOCKER_READ_ERRORS:
        result = None
    finally:
        try:
            client.close()
        except _DOCKER_READ_ERRORS:
            result = None
    return result


def _identity_from_payloads(
    *,
    version: object,
    info: object,
    container: object,
    repomap_commit: str,
    postgresql_server_version: str,
    docker_api_version: object,
    transport_class: str,
) -> Scale28RuntimeIdentity | None:
    if not all(isinstance(value, Mapping) for value in (version, info, container)):
        return None
    assert isinstance(version, Mapping)
    assert isinstance(info, Mapping)
    assert isinstance(container, Mapping)
    components = _components(version.get("Components"))
    docker_api_ver = docker_api_version
    server_ver = version.get("Version")
    op_sys = info.get("OperatingSystem")
    os_type = info.get("OSType")
    arch = info.get("Architecture")
    cg_ver = info.get("CgroupVersion")
    img_digest = container.get("Image")
    if (
        components is None
        or not _is_public_identity(docker_api_ver)
        or not _is_public_identity(server_ver)
        or not _is_public_identity(op_sys)
        or not _is_public_identity(os_type)
        or not _is_public_identity(arch)
        or not _is_public_identity(cg_ver)
        or not _is_public_identity(img_digest)
    ):
        return None
    values: _EnginePayloadValues = {
        "docker_api_version": docker_api_ver,
        "engine_server_version": server_ver,
        "engine_operating_system": op_sys,
        "engine_os_type": os_type,
        "engine_architecture": arch,
        "cgroup_version": cg_ver,
        "container_image_digest": img_digest,
    }
    return Scale28RuntimeIdentity(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        repomap_commit=repomap_commit,
        psycopg_version=psycopg.__version__,
        libpq_version=str(psycopg.pq.version()),
        postgresql_server_version=postgresql_server_version,
        psutil_version=psutil.__version__,
        host_operating_system=platform.system(),
        host_kernel=platform.release(),
        docker_sdk_version=docker.__version__,
        engine_components=components,
        container_stats_field_shape=_STATS_FIELD_SHAPE,
        transport_class=transport_class,
        **values,
    )


def _components(value: object) -> tuple[EngineComponentIdentity, ...] | None:
    if not isinstance(value, list) or not value:
        return None
    components: list[EngineComponentIdentity] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        name = item.get("Name")
        version = item.get("Version")
        details = item.get("Details")
        if (
            not _is_public_identity(name)
            or not _is_public_identity(version)
            or not isinstance(details, Mapping)
            or not all(isinstance(key, str) for key in details)
        ):
            return None
        encoded = json.dumps(
            details,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        components.append(
            EngineComponentIdentity(
                name=name,
                version=version,
                detail_fields=tuple(sorted(details)),
                details_digest=hashlib.sha256(encoded).hexdigest(),
            )
        )
    return tuple(components)


def _is_public_identity(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and "\n" not in value
        and "\r" not in value
        and len(value) <= 512
    )
