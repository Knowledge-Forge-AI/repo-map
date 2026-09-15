"""Command, script, and output contracts for test image materialization."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from repomap_test_support.resource_test_image_base import TestImageError
from repomap_test_support.resource_test_image_types import MaterializationClaim

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_MATERIALIZATION_OWNER_PREFIX = "runtime-image-materializer:"
_DEFAULT_BRIDGE_OPTION = "com.docker.network.bridge.default_bridge"
MATERIALIZATION_NETWORK_MODE = "bridge"
MATERIALIZATION_NETWORK_POLICY = "dependency-acquisition-built-in-bridge-v1"


class _MaterializationValidationError(TestImageError):
    """Carry one closed authority or conformance predicate without daemon detail."""

    def __init__(self, message: str, predicate: str) -> None:
        self.validation_predicate = predicate
        super().__init__(message)


def exact_image_id(identity: str) -> str:
    identity = str(identity)
    if not _SHA256_ID.fullmatch(identity):
        raise TestImageError("Docker Engine image ID is not exact")
    return identity


def split_tag(tag: str) -> tuple[str, str]:
    repository, separator, tag_value = tag.rpartition(":")
    if not separator or not repository or not tag_value:
        raise TestImageError("runtime cache tag is invalid")
    return repository, tag_value


def commit_configuration(labels: Mapping[str, str]) -> dict[str, object]:
    committed_labels: dict[str, str] = {}
    for key, value in sorted(labels.items()):
        if not _LABEL_VALUE.fullmatch(key) or not _LABEL_VALUE.fullmatch(value):
            raise TestImageError("runtime image label is not commit-safe")
        committed_labels[key] = value
    return {
        "Cmd": ["python3"],
        "Entrypoint": None,
        "Labels": committed_labels,
    }


def install_and_probe_command(
    dependencies: Sequence[str], psycopg_release_version: str
) -> list[str]:
    dependency_json = json.dumps(tuple(dependencies), separators=(",", ":"))
    script = (
        "import importlib, importlib.metadata, json, subprocess, sys\n"
        f"dependencies = json.loads({dependency_json!r})\n"
        "subprocess.run([sys.executable, '-m', 'pip', 'install', "
        "'--no-cache-dir', *dependencies], check=True)\n"
        "importlib.invalidate_caches()\n"
        "import psycopg, typing_extensions\n"
        f"assert psycopg.__version__ == {psycopg_release_version!r}\n"
        "resolved = {name: importlib.metadata.version(name) for name in "
        "('psycopg', 'psycopg-binary', 'typing-extensions')}\n"
        "print('REPOMAP_DEPENDENCY_VERSIONS=' + "
        "json.dumps(resolved, sort_keys=True, separators=(',', ':')))\n"
    )
    return ["-c", script]


def container_output(container: Container, *, stdout: bool) -> str:
    output: object = container.logs(stdout=stdout, stderr=not stdout)
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output or "")


def exception_provenance(error: BaseException) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    nested = error.__cause__ or error.__context__
    if nested is not None and nested is not error:
        payload["cause"] = exception_provenance(nested)
    return payload


def require_builtin_bridge(client: DockerClient) -> str:
    try:
        network = client.networks.get("bridge")
        network.reload()
    except Exception as error:
        raise _MaterializationValidationError(
            "pre-existing built-in bridge is unavailable", "network_authority"
        ) from error
    attrs = network.attrs
    options = attrs.get("Options") or {}
    network_id = str(getattr(network, "id", "") or attrs.get("Id") or "")
    if not (
        str(attrs.get("Name") or "") == "bridge"
        and str(attrs.get("Driver") or "") == "bridge"
        and str(attrs.get("Scope") or "") == "local"
        and not bool(attrs.get("Internal", False))
        and str(options.get(_DEFAULT_BRIDGE_OPTION) or "").lower() == "true"
        and re.fullmatch(r"[0-9a-f]{64}", network_id)
    ):
        raise _MaterializationValidationError(
            "pre-existing built-in bridge identity differs", "network_authority"
        )
    return network_id


def validate_network_authority(
    client: DockerClient,
    attrs: Mapping[str, object],
    host_config: Mapping[str, object],
    claim: MaterializationClaim,
) -> None:
    raw_mode = str(host_config.get("NetworkMode") or "")
    network_settings = attrs.get("NetworkSettings")
    effective = (
        network_settings.get("Networks")
        if isinstance(network_settings, Mapping)
        else None
    )
    if not isinstance(effective, Mapping):
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    claimed_mode = str(claim["network_mode"])
    if claimed_mode == "none":
        if raw_mode != "none":
            raise _MaterializationValidationError(
                "materialization container network mode differs",
                "network_authority",
            )
        if set(effective).difference({"none"}):
            raise _MaterializationValidationError(
                "materialization container network authority differs",
                "network_authority",
            )
        return
    if claimed_mode != "bridge" or raw_mode not in {"bridge", "default"}:
        raise _MaterializationValidationError(
            "materialization container network mode differs",
            "network_authority",
        )
    if set(effective) != {"bridge"}:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    bridge_attachment = effective.get("bridge")
    if not isinstance(bridge_attachment, Mapping):
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    claimed_id = str(claim.get("network_id") or "")
    if require_builtin_bridge(client) != claimed_id:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    attached_id = str(bridge_attachment.get("NetworkID") or "")
    if attached_id and attached_id != claimed_id:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )


__all__ = [
    "MATERIALIZATION_NETWORK_MODE",
    "MATERIALIZATION_NETWORK_POLICY",
    "_DEFAULT_BRIDGE_OPTION",
    "_LABEL_VALUE",
    "_MATERIALIZATION_OWNER_PREFIX",
    "_MaterializationValidationError",
    "_SHA256_ID",
    "commit_configuration",
    "container_output",
    "exact_image_id",
    "exception_provenance",
    "install_and_probe_command",
    "require_builtin_bridge",
    "split_tag",
    "validate_network_authority",
]
