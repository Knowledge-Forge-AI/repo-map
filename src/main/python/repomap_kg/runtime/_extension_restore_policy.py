"""Trusted artifact and capability policy contract for D9-B extension_v2 restore."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.runtime._backup_provenance import (
    BASELINE_EXTENSION_NAME,
    BASELINE_EXTENSION_SCHEMA,
)
from repomap_kg.runtime._extension_restore_qualification import (
    SAFE_VERSION_RE,
    SHA256_HEX_RE,
    TrustedArtifactQualification,
)

_ALLOWED_DATABASE_ROLES = frozenset({"graph", "control"})
_ALLOWED_OWNERSHIP_CLASSIFICATIONS = frozenset({"required", "unclassified"})
_ALLOWED_EXPERIMENTAL_CONTEXTS = frozenset({"none", "adr0077-disposable-pgvector"})
_ALLOWED_BASELINE_ORIGINS = frozenset({"non_baseline"})
DECLARATION_FORMAT = "repomap-extension-declaration-v1"
MAX_REPLAY_TIMEOUT_SECONDS = 86400.0
MAX_REPLAY_OUTPUT_BYTES = 64 * 1024 * 1024
DEFAULT_ALLOWED_DEPENDENT_CLASSES: tuple[str, ...] = (
    "table",
    "table column",
    "sequence",
    "index",
    "type",
    "domain",
    "domain constraint",
    "function",
    "operator",
    "operator class",
    "operator family",
    "operator of access method",
    "function of access method",
    "table constraint",
    "default value",
    "view",
    "materialized view",
    "pg_class",
    "pg_type",
    "pg_proc",
    "pg_index",
)


@dataclass(frozen=True)
class ExtensionReplayBounds:
    """Explicit caller-chosen whole-archive replay deadline and output ceiling; not capacity qualification."""

    timeout_seconds: float
    max_output_bytes: int

    def __post_init__(self) -> None:
        t, b = self.timeout_seconds, self.max_output_bytes
        if (
            isinstance(t, bool)
            or not isinstance(t, (int, float))
            or not math.isfinite(t)
            or not 0 < t <= MAX_REPLAY_TIMEOUT_SECONDS
        ):
            raise ValueError("replay timeout_seconds must be finite, positive and at most 86400")
        if isinstance(b, bool) or not isinstance(b, int) or not 0 < b <= MAX_REPLAY_OUTPUT_BYTES:
            raise ValueError("replay max_output_bytes must be a positive int of at most 64 MiB")


@dataclass(frozen=True)
class TrustedOptionalCapabilityContract:
    """Declared optional schema and least-privilege role contract (e.g. ADR 0077)."""

    capability_id: str
    experimental_context: str
    extension_schema: str
    application_schemas: tuple[str, ...] = ()
    enrichment_reader_role: str | None = None
    enrichment_writer_role: str | None = None
    require_distinct_principals: bool = True
    require_principals_before_create: bool = True

    def __post_init__(self) -> None:
        if (
            not self.capability_id
            or not self.extension_schema
            or self.experimental_context not in _ALLOWED_EXPERIMENTAL_CONTEXTS
        ):
            raise ValueError("invalid capability_id, extension_schema, or experimental_context")
        if self.require_distinct_principals and (
            not self.enrichment_reader_role
            or not self.enrichment_writer_role
            or self.enrichment_reader_role == self.enrichment_writer_role
        ):
            raise ValueError("optional capability requires distinct reader and writer roles")


@dataclass(frozen=True)
class TrustedExtensionRule:
    """Trusted admission rule for one non-baseline PostgreSQL extension."""

    name: str
    allowed_database_roles: tuple[str, ...]
    exact_versions: tuple[str, ...]
    required_schema: str
    allowed_owners: tuple[str, ...]
    declaration_identity: str
    ownership_classification: str = "required"
    experimental_context: str = "none"
    baseline_origin: str = "non_baseline"
    relocatable: bool | None = None
    prerequisites: tuple[str, ...] = ()
    allowed_dependent_schemas: tuple[str, ...] = ()
    allowed_dependent_classes: tuple[str, ...] = DEFAULT_ALLOWED_DEPENDENT_CLASSES
    control_sha256: str = ""
    script_sha256: str = ""
    library_sha256: str | None = None
    readiness_probe_sql: str = "SELECT 1;"
    optional_capability: TrustedOptionalCapabilityContract | None = None

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name == BASELINE_EXTENSION_NAME
            or not self.allowed_database_roles
            or not set(self.allowed_database_roles).issubset(_ALLOWED_DATABASE_ROLES)
        ):
            raise ValueError(
                "TrustedExtensionRule requires non-baseline name and valid allowed_database_roles"
            )
        if not self.exact_versions or any(
            not isinstance(v, str) or not SAFE_VERSION_RE.match(v) for v in self.exact_versions
        ):
            raise ValueError("exact_versions must be non-empty safe version strings")
        if (
            not self.required_schema
            or not self.allowed_owners
            or any(not o for o in self.allowed_owners)
            or not self.allowed_dependent_schemas
            or any(not s for s in self.allowed_dependent_schemas)
            or not self.allowed_dependent_classes
            or any(not c for c in self.allowed_dependent_classes)
        ):
            raise ValueError(
                "required_schema, allowed_owners, allowed_dependent_schemas, and allowed_dependent_classes must be non-empty"
            )
        if (
            not SHA256_HEX_RE.match(self.control_sha256)
            or not SHA256_HEX_RE.match(self.script_sha256)
            or (self.library_sha256 is not None and not SHA256_HEX_RE.match(self.library_sha256))
        ):
            raise ValueError(
                "control_sha256, script_sha256, and optional library_sha256 must be 64-char lowercase hex SHA-256 digests"
            )
        if (
            self.ownership_classification not in _ALLOWED_OWNERSHIP_CLASSIFICATIONS
            or self.experimental_context not in _ALLOWED_EXPERIMENTAL_CONTEXTS
            or self.baseline_origin not in _ALLOWED_BASELINE_ORIGINS
            or not self.declaration_identity
            or self.declaration_identity in {"unavailable", "undeclared"}
            or not self.readiness_probe_sql.strip()
            or (self.ownership_classification == "required" and self.experimental_context != "none")
            or (
                self.experimental_context != "none"
                and self.ownership_classification != "unclassified"
            )
        ):
            raise ValueError(
                "invalid extension classification, declaration_identity, or readiness_probe_sql"
            )


@dataclass(frozen=True)
class TrustedExtensionRestorePolicy:
    """Immutable caller-supplied trust root for D9-B extension_v2 backup and restore."""

    policy_id: str
    allow_extension_v2: bool = False
    artifact_qualification: TrustedArtifactQualification = TrustedArtifactQualification()
    extensions: tuple[TrustedExtensionRule, ...] = ()
    replay_bounds: ExtensionReplayBounds | None = None

    def __post_init__(self) -> None:
        if not self.policy_id or (
            not self.allow_extension_v2 and (self.extensions or self.replay_bounds is not None)
        ):
            raise ValueError(
                "policy_id must be non-empty and core-only policy cannot declare non-baseline extension rules or replay bounds"
            )
        qual = self.artifact_qualification
        if self.allow_extension_v2 and not (
            qual.allowed_server_versions
            and qual.allowed_os_arch_abis
            and qual.allowed_engine_image_ids
            and qual.allowed_client_versions
            and qual.require_exact_abi_match
        ):
            raise ValueError(
                "extension_v2 policy requires explicit server versions, OS/arch ABIs, Engine image IDs, exact client versions, and require_exact_abi_match=True"
            )
        if self.allow_extension_v2 and (
            not qual.template_baselines
            or any(img not in qual.allowed_engine_image_ids for img, _ in qual.template_baselines)
        ):
            raise ValueError(
                "extension_v2 policy requires template1 baselines bound to admitted Engine image IDs"
            )
        if self.allow_extension_v2 and not isinstance(self.replay_bounds, ExtensionReplayBounds):
            raise ValueError("extension_v2 policy requires explicit replay_bounds")
        seen: set[tuple[str, str]] = set()
        for r in self.extensions:
            for role in r.allowed_database_roles:
                if (r.name, role) in seen:
                    raise ValueError(f"duplicate TrustedExtensionRule for {(r.name, role)!r}")
                seen.add((r.name, role))

    def rule_for(
        self, name: str, *, database_role: str | None = None
    ) -> TrustedExtensionRule | None:
        return next(
            (
                r
                for r in self.extensions
                if r.name == name
                and (database_role is None or database_role in r.allowed_database_roles)
            ),
            None,
        )

    def declaration_record(self) -> dict[str, Any]:
        """Stable source capability declaration bound into a backup manifest.

        Current target qualification (admitted Engine IDs, server/client/platform sets,
        template references) and operational replay bounds are restore-time inputs and
        are deliberately excluded, so a later independently qualified target can be
        considered against the original backup.
        """
        rules = sorted(
            (asdict(rule) for rule in self.extensions),
            key=lambda rule: (rule["name"], rule["allowed_database_roles"]),
        )
        return {
            "allow_extension_v2": self.allow_extension_v2,
            "extensions": rules,
            "format": DECLARATION_FORMAT,
            "policy_id": self.policy_id,
        }

    def declaration_digest(self) -> str:
        canonical = json.dumps(
            self.declaration_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def policy_binding_record(self) -> dict[str, str]:
        base = {
            "d1_baseline": f"{BASELINE_EXTENSION_NAME}@{BASELINE_EXTENSION_SCHEMA}",
            "d3_policy": "allowlist-required",
        }
        if self.allow_extension_v2:
            base["policy_id"] = self.policy_id
            base["declaration_format"] = DECLARATION_FORMAT
            base["declaration_sha256"] = self.declaration_digest()
        return base


CORE_ONLY_EXTENSION_RESTORE_POLICY = TrustedExtensionRestorePolicy(
    policy_id="core-only-default-v1", allow_extension_v2=False
)


def resolve_extension_restore_policy(
    policy: TrustedExtensionRestorePolicy | None,
) -> TrustedExtensionRestorePolicy:
    return policy if policy is not None else CORE_ONLY_EXTENSION_RESTORE_POLICY


def project_policy_for_observation(
    policy: TrustedExtensionRestorePolicy | None, *, database_role: str
) -> dict[str, dict[str, Any]] | None:
    resolved = resolve_extension_restore_policy(policy)
    return (
        None
        if not resolved.allow_extension_v2
        else {
            r.name: {
                "allowed_owners": r.allowed_owners,
                "baseline_origin": r.baseline_origin,
                "declaration_identity": r.declaration_identity,
                "exact_versions": r.exact_versions,
                "experimental_context": r.experimental_context,
                "ownership_classification": r.ownership_classification,
                "prerequisites": tuple(sorted(r.prerequisites)),
                "relocatable": r.relocatable,
                "required_schema": r.required_schema,
            }
            for r in resolved.extensions
            if database_role in r.allowed_database_roles
        }
    )
