"""Owner-private execution capability for one portable semantic attempt."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat

from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.coordinator._refresh_capability_io import validate_private_directory
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    apply_owner_private_acl,
    reject_reparse_path,
    validate_owner_private_acl,
)


_GRAPH_ID = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_GENERATION = re.compile(r"(?:sg1|cg1|eg1|kg1):[A-Za-z0-9._-]+\Z")
_MAX_CAPABILITY_BYTES = 8192
_FIELDS = frozenset(
    {
        "schema_version",
        "job_id",
        "attempt",
        "graph_id",
        "store_root",
        "workspace_root",
        "manifest_reference",
        "source_generation",
        "config_generation",
        "extractor_generation",
        "canonicalizer_generation",
        "max_artifact_bytes",
        "max_bundle_bytes",
    }
)


@dataclass(frozen=True)
class PortableExecutionCapability:
    """Physical store/workspace authority sealed to one semantic attempt."""

    schema_version: int
    job_id: str
    attempt: int
    graph_id: str
    store_root: Path
    workspace_root: Path
    manifest_reference: ArtifactReference
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    max_artifact_bytes: int
    max_bundle_bytes: int

    def validate(self) -> "PortableExecutionCapability":
        valid = (
            self.schema_version == 1
            and not isinstance(self.schema_version, bool)
            and isinstance(self.job_id, str)
            and 0 < len(self.job_id) <= 128
            and isinstance(self.attempt, int)
            and not isinstance(self.attempt, bool)
            and self.attempt > 0
            and isinstance(self.graph_id, str)
            and _GRAPH_ID.fullmatch(self.graph_id) is not None
            and isinstance(self.store_root, Path)
            and self.store_root.is_absolute()
            and isinstance(self.workspace_root, Path)
            and self.workspace_root.is_absolute()
            and isinstance(self.manifest_reference, ArtifactReference)
            and self.manifest_reference.store_version is not None
            and self.manifest_reference.media_type
            == "application/x-repomap-snapshot-manifest-v1+json"
            and self.manifest_reference.record_format == "canonical-json-v1"
            and all(
                isinstance(value, str) and _GENERATION.fullmatch(value) is not None
                for value in (
                    self.source_generation,
                    self.config_generation,
                    self.extractor_generation,
                    self.canonicalizer_generation,
                )
            )
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 < value <= 4 * 1024 * 1024 * 1024
                for value in (self.max_artifact_bytes, self.max_bundle_bytes)
            )
        )
        if not valid:
            raise ValueError("invalid portable capability")
        validate_private_directory(self.store_root)
        validate_private_directory(self.workspace_root)
        return self


def create_portable_capability(
    directory: Path, capability: PortableExecutionCapability
) -> Path:
    capability.validate()
    validate_private_directory(directory)
    payload = asdict(capability)
    payload["store_root"] = str(capability.store_root)
    payload["workspace_root"] = str(capability.workspace_root)
    payload["manifest_reference"] = capability.manifest_reference.to_mapping()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > _MAX_CAPABILITY_BYTES:
        raise ValueError("invalid portable capability")
    path = directory / f"portable-{secrets.token_hex(16)}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
    except OSError:
        path.unlink(missing_ok=True)
        raise ValueError("invalid portable capability") from None
    finally:
        os.close(descriptor)
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            apply_owner_private_acl(path)
            validate_owner_private_acl(path)
        except WindowsSecurityError:
            path.unlink(missing_ok=True)
            raise ValueError("invalid portable capability") from None
    return path


def load_portable_capability(path: Path) -> PortableExecutionCapability:
    descriptor: int | None = None
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
            descriptor = os.open(path, os.O_RDONLY)
            validate_owner_private_acl(path)
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_size <= 0
            or details.st_size > _MAX_CAPABILITY_BYTES
            or (
                os.name != "nt"
                and (
                    details.st_uid != os.getuid()
                    or stat.S_IMODE(details.st_mode) != 0o600
                )
            )
        ):
            raise ValueError
        payload = json.loads(os.read(descriptor, _MAX_CAPABILITY_BYTES + 1))
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError
        return PortableExecutionCapability(
            schema_version=payload["schema_version"],
            job_id=payload["job_id"],
            attempt=payload["attempt"],
            graph_id=payload["graph_id"],
            store_root=Path(payload["store_root"]),
            workspace_root=Path(payload["workspace_root"]),
            manifest_reference=ArtifactReference.from_mapping(
                payload["manifest_reference"]
            ),
            source_generation=payload["source_generation"],
            config_generation=payload["config_generation"],
            extractor_generation=payload["extractor_generation"],
            canonicalizer_generation=payload["canonicalizer_generation"],
            max_artifact_bytes=payload["max_artifact_bytes"],
            max_bundle_bytes=payload["max_bundle_bytes"],
        ).validate()
    except (
        OSError,
        UnicodeError,
        WindowsSecurityError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise ValueError("invalid portable capability") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def remove_portable_capability(path: Path) -> None:
    path.unlink(missing_ok=True)


__all__ = [
    "PortableExecutionCapability",
    "create_portable_capability",
    "load_portable_capability",
    "remove_portable_capability",
]
