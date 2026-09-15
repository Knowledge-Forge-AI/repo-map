"""Refresh capability record creation, deserialization, and validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat

from repomap_kg.coordinator._refresh_capability_io import (
    validate_config_file,
    validate_private_directory,
    validate_psql,
    validate_psql_lexical,
    validate_search_path,
)
from repomap_kg.coordinator._refresh_contracts import RefreshConfigurationError
from repomap_kg.coordinator.contracts import is_public_safe_text
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    apply_owner_private_acl,
    reject_reparse_path,
    validate_owner_private_acl,
)
from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)

_CAPABILITY_FIELDS = frozenset({
    "schema_version",
    "job_id",
    "attempt",
    "graph_id",
    "config_path",
    "psql_path",
    "postgres_user",
    "postgres_password",
    "executable_search_path",
    "source_generation",
    "config_generation",
    "extractor_generation",
    "canonicalizer_generation",
    "coordinator_instance_id",
    "singleton_fencing_epoch",
    "graph_lease_fencing_epoch",
})
_GRAPH_ID = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_MAX_CAPABILITY_BYTES = 4096


@dataclass(frozen=True)
class ResolvedRefreshAuthority:
    """Coordinator-resolved private execution values, never client input."""

    graph_id: str
    config_path: Path
    psql_path: Path
    postgres_user: str
    postgres_password: str
    executable_search_path: tuple[Path, ...]
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str


@dataclass(frozen=True)
class RefreshCapability:
    """Minimum internally resolved authority for one refresh attempt."""

    schema_version: int
    job_id: str
    attempt: int
    graph_id: str
    config_path: Path
    psql_path: Path
    postgres_user: str
    postgres_password: str
    executable_search_path: tuple[Path, ...]
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    coordinator_instance_id: str | None = None
    singleton_fencing_epoch: int = 0
    graph_lease_fencing_epoch: int = 0

    def publication_generations(self) -> RunPublicationGenerations:
        return RunPublicationGenerations(
            source_generation=self.source_generation,
            config_generation=self.config_generation,
            extractor_generation=self.extractor_generation,
            canonicalizer_generation=self.canonicalizer_generation,
        ).validate()

    def publication_receipt(self) -> RunPublicationReceipt:
        return RunPublicationReceipt(
            attempt=RunPublicationAttempt(
                JobId(self.job_id), AttemptNumber(self.attempt)
            ),
            generations=self.publication_generations(),
        ).validate()

    def validate(self) -> "RefreshCapability":
        validate_psql_lexical(self.psql_path)
        try:
            valid = (
                self.schema_version == 1
                and not isinstance(self.schema_version, bool)
                and isinstance(self.attempt, int)
                and not isinstance(self.attempt, bool)
                and self.attempt > 0
                and is_public_safe_text(self.job_id, maximum=128)
                and isinstance(self.graph_id, str)
                and _GRAPH_ID.fullmatch(self.graph_id) is not None
                and isinstance(self.config_path, Path)
                and self.config_path.is_absolute()
                and isinstance(self.postgres_user, str)
                and _GRAPH_ID.fullmatch(self.postgres_user.replace("_", "-"))
                is not None
                and isinstance(self.postgres_password, str)
                and 0 < len(self.postgres_password) <= 256
                and isinstance(self.executable_search_path, tuple)
                and 0 < len(self.executable_search_path) <= 32
                and all(
                    isinstance(path, Path) and path.is_absolute()
                    for path in self.executable_search_path
                )
                and is_public_safe_text(
                    self.coordinator_instance_id,
                    maximum=128,
                )
                and isinstance(self.singleton_fencing_epoch, int)
                and not isinstance(self.singleton_fencing_epoch, bool)
                and self.singleton_fencing_epoch > 0
                and isinstance(self.graph_lease_fencing_epoch, int)
                and not isinstance(self.graph_lease_fencing_epoch, bool)
                and self.graph_lease_fencing_epoch > 0
            )
            self.publication_generations()
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("invalid refresh capability")
        return self


def create_refresh_capability(
    directory: Path, capability: RefreshCapability
) -> Path:
    """Write one private capability file owned and later removed by the parent."""

    capability.validate()
    validate_private_directory(directory)
    validate_config_file(capability.config_path)
    validate_psql(capability.psql_path)
    validate_search_path(capability.executable_search_path)
    payload = asdict(capability)
    payload["config_path"] = str(capability.config_path)
    payload["psql_path"] = str(capability.psql_path)
    payload["executable_search_path"] = [
        str(path) for path in capability.executable_search_path
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > _MAX_CAPABILITY_BYTES:
        raise ValueError("invalid refresh capability")
    path = directory / f"refresh-{secrets.token_hex(16)}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("capability write failed")
            remaining = remaining[written:]
    except OSError:
        path.unlink(missing_ok=True)
        raise ValueError("invalid refresh capability") from None
    finally:
        os.close(descriptor)
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            apply_owner_private_acl(path)
            validate_owner_private_acl(path)
        except WindowsSecurityError:
            path.unlink(missing_ok=True)
            raise ValueError("invalid refresh capability") from None
    return path


def load_refresh_capability(path: Path) -> RefreshCapability:
    """Read one exact owner-only capability without accepting authority extensions."""

    descriptor: int | None = None
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
            descriptor = os.open(path, os.O_RDONLY)
            validate_owner_private_acl(path)
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        details = os.fstat(descriptor)
        unsafe = not stat.S_ISREG(details.st_mode) or details.st_size <= 0
        if os.name != "nt":
            unsafe = unsafe or (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            )
        if unsafe or details.st_size > _MAX_CAPABILITY_BYTES:
            raise ValueError
        payload = json.loads(os.read(descriptor, _MAX_CAPABILITY_BYTES + 1))
        if not isinstance(payload, dict) or set(payload) != _CAPABILITY_FIELDS:
            raise ValueError
        capability = RefreshCapability(
            schema_version=payload["schema_version"],
            job_id=payload["job_id"],
            attempt=payload["attempt"],
            graph_id=payload["graph_id"],
            config_path=Path(payload["config_path"]),
            psql_path=Path(payload["psql_path"]),
            postgres_user=payload["postgres_user"],
            postgres_password=payload["postgres_password"],
            executable_search_path=tuple(
                Path(value) for value in payload["executable_search_path"]
            ),
            source_generation=payload["source_generation"],
            config_generation=payload["config_generation"],
            extractor_generation=payload["extractor_generation"],
            canonicalizer_generation=payload["canonicalizer_generation"],
            coordinator_instance_id=payload.get("coordinator_instance_id"),
            singleton_fencing_epoch=payload.get("singleton_fencing_epoch", 0),
            graph_lease_fencing_epoch=payload.get("graph_lease_fencing_epoch", 0),
        ).validate()
        validate_config_file(capability.config_path)
        validate_psql(capability.psql_path)
        validate_search_path(capability.executable_search_path)
        return capability
    except RefreshConfigurationError:
        raise
    except (
        OSError,
        UnicodeError,
        WindowsSecurityError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise ValueError("invalid refresh capability") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def remove_refresh_capability(path: Path) -> None:
    """Remove only an owner-controlled regular capability file."""

    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
            validate_owner_private_acl(path)
        details = path.lstat()
        unsafe = not stat.S_ISREG(details.st_mode)
        if os.name != "nt":
            unsafe = unsafe or (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            )
        if unsafe:
            raise ValueError
        path.unlink()
    except FileNotFoundError:
        return
    except (OSError, ValueError, WindowsSecurityError):
        raise ValueError("invalid refresh capability") from None
