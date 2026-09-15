"""Records, bindings, and validation rules for portable snapshot manifests."""

from __future__ import annotations

from dataclasses import dataclass
import re

from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


_DIGEST = re.compile(r"[a-z][a-z0-9_-]*:[A-Za-z0-9._-]+\Z")
_GRAPH = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_SOURCE_KINDS = frozenset({"local-directory", "git-tree", "sealed-artifacts"})
_ACQUISITION_METHODS = frozenset(
    {"sealed-local-copy", "verified-object-read", "coordinator-capture"}
)
_PRIVACY_POLICIES = frozenset(
    {
        "public-dev",
        "private-ops",
        "private-memory",
        "private-config",
        "sensitive-local",
        "inherit",
    }
)
_PATH_SEGMENT = re.compile(r"[^/\x00-\x1f\x7f]+\Z")


@dataclass(frozen=True)
class ArtifactLimits:
    max_artifacts: int = 100_000
    max_total_bytes: int = 4 * 1024 * 1024 * 1024
    max_path_bytes: int = 1024
    max_manifest_bytes: int = 16 * 1024 * 1024
    max_diagnostics: int = 32
    max_diagnostic_bytes: int = 4096

    def __post_init__(self) -> None:
        for value in self.__dict__.values():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("artifact limits must be positive integers")


DEFAULT_ARTIFACT_LIMITS = ArtifactLimits()


@dataclass(frozen=True, order=True)
class ManifestBinding:
    binding_id: str
    revision: int
    snapshot_id: str
    source_definition_id: str
    source_kind: str
    acquisition_method: str
    selection_policy_id: str
    ignore_policy_id: str
    privacy_policy: str
    role: str
    input_name: str | None
    alias: str | None = None
    logical_root: str | None = None
    evidence_retention_policy: str | None = None
    extractor_profile: str | None = None
    resolution_policy: str | None = None
    repository_scope: str | None = None

    def __post_init__(self) -> None:
        for value, prefix, label in (
            (self.binding_id, "bind1:", "binding identity"),
            (self.snapshot_id, "snap1:", "snapshot identity"),
            (self.source_definition_id, "src1:", "source definition identity"),
            (self.selection_policy_id, "select1:", "selection policy identity"),
            (self.ignore_policy_id, "ignore1:", "ignore policy identity"),
        ):
            _identity(value, prefix, label)
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("binding revision is invalid")
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError("source kind is unsupported")
        if self.acquisition_method not in _ACQUISITION_METHODS:
            raise ValueError("acquisition method is unsupported")
        if self.privacy_policy not in _PRIVACY_POLICIES:
            raise ValueError("privacy policy is invalid")
        _bounded_token(self.role, "binding role")
        if self.input_name is not None:
            _bounded_token(self.input_name, "binding input name")
        semantic_fields = (
            self.alias,
            self.logical_root,
            self.evidence_retention_policy,
            self.extractor_profile,
            self.resolution_policy,
            self.repository_scope,
        )
        if any(value is not None for value in semantic_fields):
            if not all(isinstance(value, str) and value for value in semantic_fields):
                raise ValueError("binding semantic execution fields are incomplete")
            assert self.alias is not None
            assert self.evidence_retention_policy is not None
            assert self.extractor_profile is not None
            assert self.resolution_policy is not None
            assert self.repository_scope is not None
            _bounded_token(self.alias, "binding alias")
            _bounded_token(
                self.evidence_retention_policy, "evidence retention policy"
            )
            _bounded_token(self.extractor_profile, "extractor profile")
            _bounded_token(self.resolution_policy, "resolution policy")
            _bounded_token(self.repository_scope, "repository scope")
            if self.logical_root != ".":
                assert self.logical_root is not None
                _portable_path(self.logical_root)

    def mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "acquisition_method": self.acquisition_method,
            "binding_id": self.binding_id,
            "ignore_policy_id": self.ignore_policy_id,
            "input_name": self.input_name,
            "privacy_policy": self.privacy_policy,
            "revision": self.revision,
            "role": self.role,
            "selection_policy_id": self.selection_policy_id,
            "snapshot_id": self.snapshot_id,
            "source_definition_id": self.source_definition_id,
            "source_kind": self.source_kind,
        }
        if self.alias is not None:
            result["semantic_execution"] = {
                "alias": self.alias,
                "evidence_retention_policy": self.evidence_retention_policy,
                "extractor_profile": self.extractor_profile,
                "logical_root": self.logical_root,
                "repository_scope": self.repository_scope,
                "resolution_policy": self.resolution_policy,
            }
        return result


@dataclass(frozen=True, order=True)
class ManifestArtifact:
    binding_id: str
    source_relative_path: str
    reference: ArtifactReference
    executable: bool

    def __post_init__(self) -> None:
        _identity(self.binding_id, "bind1:", "binding identity")
        _portable_path(self.source_relative_path)
        if not isinstance(self.reference, ArtifactReference):
            raise ValueError("artifact reference is invalid")
        if not isinstance(self.executable, bool):
            raise ValueError("artifact executable mode is invalid")

    def semantic_mapping(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "executable": self.executable,
            "reference": self.reference.semantic_mapping(),
            "source_relative_path": self.source_relative_path,
        }


def _validate_inventory(
    bindings: tuple[ManifestBinding, ...],
    entries: tuple[ManifestArtifact, ...],
    limits: ArtifactLimits,
) -> None:
    if not bindings:
        raise ValueError("snapshot manifest requires a binding")
    binding_ids = [item.binding_id for item in bindings]
    if len(binding_ids) != len(set(binding_ids)):
        raise ValueError("duplicate snapshot binding")
    if len(entries) > limits.max_artifacts:
        raise ValueError("artifact count bounds exceeded")
    known = set(binding_ids)
    keys = [(item.binding_id, item.source_relative_path) for item in entries]
    if any(item.binding_id not in known for item in entries):
        raise ValueError("artifact binding is absent")
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate artifact path")
    folded = [(binding, path.casefold()) for binding, path in keys]
    if len(folded) != len(set(folded)):
        raise ValueError("case-ambiguous artifact path")
    if any(len(item.source_relative_path.encode("utf-8")) > limits.max_path_bytes for item in entries):
        raise ValueError("artifact path bounds exceeded")
    total = sum(item.reference.size_bytes for item in entries)
    if total > limits.max_total_bytes:
        raise ValueError("artifact byte bounds exceeded")


_PRIVACY_RANK = {
    PrivacyClassification.PUBLIC: 0,
    PrivacyClassification.SOURCE_INDEX: 1,
    PrivacyClassification.LEGACY_GRAPH: 2,
    PrivacyClassification.RAW_SOURCE: 3,
    PrivacyClassification.CANONICAL_GRAPH: 4,
    PrivacyClassification.CANONICAL_PROVENANCE: 5,
}


def _privacy_rank(value: PrivacyClassification) -> int:
    return _PRIVACY_RANK.get(value, 0)


def _effective_privacy(
    bindings: tuple[ManifestBinding, ...], entries: tuple[ManifestArtifact, ...]
) -> PrivacyClassification:
    expected = PrivacyClassification.PUBLIC
    if any(item.privacy_policy != "public-dev" for item in bindings):
        expected = PrivacyClassification.RAW_SOURCE
    for item in entries:
        if _privacy_rank(item.reference.privacy) > _privacy_rank(expected):
            expected = item.reference.privacy
    return expected


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or value.startswith("/") or "\\" in value:
        raise ValueError("artifact path is not portable")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or _PATH_SEGMENT.fullmatch(part) is None for part in parts):
        raise ValueError("artifact path is not portable")
    return value


def _identity(value: object, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _bounded_token(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128 or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"{label} is invalid")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"manifest {label} is invalid")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("manifest field type is invalid")
    return value


def _binding_from_mapping(value: object) -> ManifestBinding:
    if not isinstance(value, dict):
        raise ValueError("manifest binding is invalid")
    try:
        base_fields = {
            "acquisition_method", "binding_id", "ignore_policy_id", "input_name",
            "privacy_policy", "revision", "role", "selection_policy_id",
            "snapshot_id", "source_definition_id", "source_kind",
        }
        if set(value) not in {frozenset(base_fields), frozenset(base_fields | {"semantic_execution"})}:
            raise ValueError("manifest binding is invalid")
        revision = value["revision"]
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError("manifest binding is invalid")
        semantic = value.get("semantic_execution")
        if semantic is None:
            semantic_values: tuple[str | None, ...] = (None,) * 6
        else:
            if not isinstance(semantic, dict) or set(semantic) != {
                "alias", "evidence_retention_policy", "extractor_profile",
                "logical_root", "repository_scope", "resolution_policy",
            }:
                raise ValueError("manifest binding is invalid")
            semantic_values = tuple(
                _str(semantic[field])
                for field in (
                    "alias", "logical_root", "evidence_retention_policy",
                    "extractor_profile", "resolution_policy", "repository_scope",
                )
            )
        return ManifestBinding(
            _str(value["binding_id"]), revision, _str(value["snapshot_id"]),
            _str(value["source_definition_id"]), _str(value["source_kind"]),
            _str(value["acquisition_method"]), _str(value["selection_policy_id"]),
            _str(value["ignore_policy_id"]), _str(value["privacy_policy"]),
            _str(value["role"]), None if value["input_name"] is None else _str(value["input_name"]),
            *semantic_values,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("manifest binding is invalid") from error


def _entry_from_mapping(value: object) -> ManifestArtifact:
    if not isinstance(value, dict):
        raise ValueError("manifest entry is invalid")
    try:
        if set(value) != {
            "binding_id", "executable", "reference", "source_relative_path",
        }:
            raise ValueError("manifest entry is invalid")
        reference = ArtifactReference.from_semantic_mapping(value["reference"])
        executable = value["executable"]
        if not isinstance(executable, bool):
            raise ValueError("artifact executable mode is invalid")
        return ManifestArtifact(_str(value["binding_id"]), _str(value["source_relative_path"]), reference, executable)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("manifest entry is invalid") from error


__all__ = [
    "ArtifactLimits",
    "DEFAULT_ARTIFACT_LIMITS",
    "ManifestArtifact",
    "ManifestBinding",
    "_ACQUISITION_METHODS",
    "_DIGEST",
    "_GRAPH",
    "_PATH_SEGMENT",
    "_PRIVACY_POLICIES",
    "_SOURCE_KINDS",
    "_binding_from_mapping",
    "_bounded_token",
    "_effective_privacy",
    "_entry_from_mapping",
    "_identity",
    "_list",
    "_portable_path",
    "_str",
    "_validate_inventory",
]
