"""Closed qualification records, schemas, and static resolution for TEST-COV5K-R2-FIX1."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Iterable, Mapping, TypeAlias

from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry,
    ParameterTuple,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    SOURCE_MANIFEST_DIGEST,
    verify_source_freeze,
)

ObservedTuple: TypeAlias = tuple[tuple[str, object], ...]
THRESHOLDS = (
    ("request_deadline_ms", 300),
    ("operation_classification_ms", 900),
    ("terminal_read_ms", 500),
    ("cleanup_attempt_ms", 5_000),
)
TOLERANCES = (
    ("process_rss_page_bytes", 4_096),
    ("container_rss_value_bytes", 33_554_432),
    ("container_sampling_skew_ms", 250),
)
PROTOCOL_DIGEST = hashlib.sha256(b"ADR-0046-observer-protocol").hexdigest()


def _runtime_identity_digest() -> str:
    payload = {
        "python": (sys.implementation.name, sys.version_info[:3]),
        "platform": (platform.system(), platform.machine()),
        "packages": tuple(
            (n, version(n)) for n in ("docker", "psutil", "psycopg", "pytest")
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


RUNTIME_IDENTITY_DIGEST = _runtime_identity_digest()
_EXPECTED_FIELDS = {"expected", "expected_value", "expected_contract_category"}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


class IntegrityError(ValueError):
    """A deterministic qualification-integrity rejection."""


class LifecycleState(str, Enum):
    """Closed pre-registration and observation lifecycle."""

    DRAFT = "draft"
    VALIDATED = "validated"
    FROZEN = "frozen"
    OBSERVATION_OPEN = "observation-open"
    SEALED = "sealed"


@dataclass(frozen=True, slots=True)
class DraftManifest:
    registration_id: str
    entries: tuple[CatalogEntry, ...]
    thresholds: tuple[tuple[str, int], ...]
    tolerances: tuple[tuple[str, int], ...]
    state: LifecycleState = LifecycleState.DRAFT


@dataclass(frozen=True, slots=True)
class ValidatedManifest:
    registration_id: str
    entries: tuple[CatalogEntry, ...]
    thresholds: tuple[tuple[str, int], ...]
    tolerances: tuple[tuple[str, int], ...]
    state: LifecycleState = LifecycleState.VALIDATED


@dataclass(frozen=True, slots=True)
class FrozenManifest:
    registration_id: str
    entries: tuple[CatalogEntry, ...]
    thresholds: tuple[tuple[str, int], ...]
    tolerances: tuple[tuple[str, int], ...]
    source_manifest_digest: str
    policy_digest: str
    protocol_digest: str
    runtime_identity_digest: str
    preregistration_digest: str
    state: LifecycleState = LifecycleState.FROZEN


@dataclass(frozen=True, slots=True)
class ObservationSession:
    registration_id: str
    preregistration_digest: str
    state: LifecycleState = LifecycleState.OBSERVATION_OPEN


@dataclass(frozen=True, slots=True)
class ResultArtifact:
    schema: str
    authority_id: str
    case_id: str
    condition_id: str
    semantic_group: str
    product_owner_id: str
    evidence_executor_id: str
    parameter_values: ParameterTuple
    enacted_parameters: ParameterTuple
    parameter_digest: str
    runtime_identity_digest: str
    source_manifest_digest: str
    policy_digest: str
    protocol_digest: str
    preregistration_digest: str
    observed_fields: ObservedTuple
    started_monotonic_ns: int
    completed_monotonic_ns: int
    purpose: str
    qualification_status: str
    model_rehearsal_only: bool
    result_digest: str


@dataclass(frozen=True, slots=True)
class SealedRehearsal:
    registration_id: str
    preregistration_digest: str
    result_digests: tuple[str, ...]
    qualification_status: str = "unqualified"
    model_rehearsal_only: bool = True
    state: LifecycleState = LifecycleState.SEALED


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_digest(value: object) -> str:
    """Return a deterministic public-safe SHA-256 digest."""
    encoded = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parameter_digest(entry: CatalogEntry) -> str:
    return canonical_digest(
        {
            "case_id": entry.case_id,
            "parameter_schema": entry.parameter_schema,
            "parameter_values": entry.parameter_values,
        }
    )


def closed_source_manifest_digest(entries: tuple[CatalogEntry, ...]) -> str:
    verify_source_freeze(_REPOSITORY_ROOT)
    paths = sorted(
        {
            entry.product_entrypoint.partition(":")[0]
            for entry in entries
            if not entry.product_entrypoint.startswith("tool:")
        }
    )
    owner_sources = tuple(
        (p, hashlib.sha256((_REPOSITORY_ROOT / p).read_bytes()).hexdigest())
        for p in paths
    )
    executor_paths = {
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_catalog.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executors.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_catalog_administrative.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_catalog_runtime.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_catalog_storage.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_catalog_values.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executor_administrative.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executor_preparation.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executor_runtime.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_qualification.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_qualification_records.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_qualification_groups.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_rehearsal.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_group_k_container.py",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_image_route.py",
    }
    executor_paths.update(
        entry.pytest_node_id.partition("::")[0]
        for entry in entries
        if entry.pytest_node_id is not None
    )
    executor_sources = tuple(
        (p, hashlib.sha256((_REPOSITORY_ROOT / p).read_bytes()).hexdigest())
        for p in sorted(executor_paths)
    )
    return canonical_digest(
        {
            "observer_source_manifest": SOURCE_MANIFEST_DIGEST,
            "product_owner_sources": owner_sources,
            "test_owned_executor_sources": executor_sources,
        }
    )


def _duplicate(values: Iterable[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def build_result(
    manifest: FrozenManifest,
    session: ObservationSession,
    entry: CatalogEntry,
    observed_fields: ObservedTuple,
    *,
    enacted_parameters: ParameterTuple,
    started_monotonic_ns: int,
    completed_monotonic_ns: int,
) -> ResultArtifact:
    """Build a canonical rehearsal result from executor-observed facts only."""
    if _duplicate(field for field, _ in observed_fields):
        raise IntegrityError("duplicate observed field")
    if session.preregistration_digest != manifest.preregistration_digest:
        raise IntegrityError("observation is not bound to frozen manifest")
    if (
        session.state is not LifecycleState.OBSERVATION_OPEN
        or session.registration_id != manifest.registration_id
    ):
        raise IntegrityError("observation lifecycle is not open")
    if enacted_parameters != entry.parameter_values:
        raise IntegrityError("parameter tuple changed")
    fields = dict(observed_fields)
    if _EXPECTED_FIELDS.intersection(fields):
        raise IntegrityError("expected value inserted as observation")
    artifact = ResultArtifact(
        schema="repomap.test-cov5k-r2-fix1.result.v1",
        authority_id=entry.authority_id,
        case_id=entry.case_id,
        condition_id=entry.condition_id,
        semantic_group=entry.semantic_group,
        product_owner_id=entry.product_owner_id,
        evidence_executor_id=entry.evidence_executor_id,
        parameter_values=entry.parameter_values,
        enacted_parameters=enacted_parameters,
        parameter_digest=parameter_digest(entry),
        runtime_identity_digest=manifest.runtime_identity_digest,
        source_manifest_digest=manifest.source_manifest_digest,
        policy_digest=manifest.policy_digest,
        protocol_digest=manifest.protocol_digest,
        preregistration_digest=manifest.preregistration_digest,
        observed_fields=observed_fields,
        started_monotonic_ns=started_monotonic_ns,
        completed_monotonic_ns=completed_monotonic_ns,
        purpose="qualification_model_rehearsal",
        qualification_status="unqualified",
        model_rehearsal_only=True,
        result_digest="",
    )
    return ResultArtifact(
        **{**asdict(artifact), "result_digest": canonical_digest(artifact)}
    )


def predecessor_accepts_p0(finding: str, artifacts: tuple[ResultArtifact, ...]) -> bool:
    """Model the rejected record's four permissive integrity behaviors."""
    if finding == "P0-1":
        return any(
            item.product_owner_id == item.evidence_executor_id for item in artifacts
        )
    if finding == "P0-2":
        return len({item.result_digest for item in artifacts}) < len(artifacts) or any(
            "caller_ordinal" in dict(item.observed_fields)
            or "aggregate_count" in dict(item.observed_fields)
            for item in artifacts
        )
    if finding == "P0-3":
        return any(
            dict(item.observed_fields).get("cleanup_disposition") == "complete"
            for item in artifacts
        )
    if finding == "P0-4":
        groups = {item.semantic_group for item in artifacts}
        unrelated = any(
            item.semantic_group in {"D", "H", "K"}
            and "final_release" in item.evidence_executor_id
            for item in artifacts
        )
        aggregate_zero = any(
            item.semantic_group == "H"
            and dict(item.observed_fields).get("aggregate") is True
            for item in artifacts
        )
        return unrelated or aggregate_zero or not {"D", "H", "K"} <= groups
    raise ValueError(f"unknown predecessor finding: {finding}")


def resolve_owner(repository_root: Path, entry: CatalogEntry) -> None:
    """Prove the configured owner path and top-level symbol exist."""
    if entry.product_entrypoint.startswith("tool:"):
        _, executable, subcommand = entry.product_entrypoint.split(":", 2)
        if shutil.which(executable) is None:
            raise IntegrityError("product tool executable does not exist")
        if entry.fixed_argv_shape[:2] != (executable, subcommand):
            raise IntegrityError("product tool argv does not match owner")
        return
    path_text, separator, symbol = entry.product_entrypoint.partition(":")
    if not separator or not symbol:
        raise IntegrityError("product owner entrypoint is malformed")
    path = repository_root / path_text
    if not path.is_file():
        raise IntegrityError("product owner path does not exist")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbol_parts = symbol.split(".")
    owner = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == symbol_parts[0]
        ),
        None,
    )
    if owner is None:
        raise IntegrityError("product owner symbol does not exist")
    for nested_name in symbol_parts[1:]:
        if not isinstance(owner, ast.ClassDef):
            raise IntegrityError("product owner callgraph symbol does not exist")
        owner = next(
            (
                n
                for n in owner.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == nested_name
            ),
            None,
        )
        if owner is None:
            raise IntegrityError("product owner callgraph symbol does not exist")
