"""Closed ADR 0050 capability, effect, provenance and lifecycle vocabularies.

Every value here is a declaration vocabulary. Validating a value proves only
that it is well formed; it never proves that an effect was enforced, that a
capability was achieved, or that a run was contained.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

CAPABILITY_VOCABULARY_VERSION = "cap-v1"
CAPABILITIES_V1 = frozenset(
    {
        "file.classification",
        "lexical.structure",
        "syntax.tree",
        "syntax.error_tolerant",
        "resolution.include_local",
        "resolution.symbol_local",
        "resolution.type",
        "metadata.package",
        "build.condition",
    }
)

EFFECT_DIMENSIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "target_code_evaluated": frozenset({"none", "evaluated"}),
        "execution_boundary": frozenset(
            {"pure-python", "in-process-native", "subprocess"}
        ),
        "filesystem_read_scope": frozenset(
            {"selected-input", "repository", "beyond-repository"}
        ),
        "filesystem_write_scope": frozenset(
            {"none", "scratch", "repository", "beyond-repository"}
        ),
        "network": frozenset({"none", "any"}),
    }
)

PROVENANCE_VALUES = frozenset(
    {
        "python-stdlib",
        "python-distribution",
        "repomap-built-helper",
        "operator-supplied-external",
    }
)

# Five distinct lifecycle facts (ADR 0050 D5). They have different subjects
# and are recorded in different fields; none is derived from another.
LIFECYCLE_STATES = ("installed", "admitted", "attempted", "exercised", "achieved")
LIFECYCLE_SUBJECTS: Mapping[str, str] = MappingProxyType(
    {
        "installed": "environment",
        "admitted": "run",
        "attempted": "attempt",
        "exercised": "attempt",
        "achieved": "attempt",
    }
)

UNDECLARED = "undeclared"
UNAVAILABLE = "unavailable"
INSTALLED_FACTS = frozenset({"installed", UNAVAILABLE, UNDECLARED})
ADMISSION_FACTS = frozenset({"admitted", "refused", UNDECLARED})

PIPELINE_STAGES = frozenset({"S1", "S2", "S3", "S4"})

# Raw observation metadata names reserved by this foundation. Canonicalization
# refuses observations that carry them because no witness can admit a claim.
RECEIPT_REFERENCE_METADATA_KEY = "extractor_receipt_ref_v1"
RECEIPT_REFERENCE_KEY_PREFIX = "extractor_receipt"
CAPABILITY_CLAIM_METADATA_KEYS = frozenset(
    {
        "capability_vocabulary",
        "declared_capabilities",
        "admitted_capabilities",
        "exercised_capabilities",
        "achieved_capabilities",
        "effect_vector",
        "parent_witness",
        "capability_witness",
    }
)

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]{0,63}")
DIALECT_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._+-]{0,31}(?:/[a-z0-9][a-z0-9._+-]{0,31})?"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ContractError(ValueError):
    """Categorical contract refusal; the message is the closed code only."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_str(value: object, *, code: str) -> str:
    """Accept an exact ``str``; subclasses and other types are refused."""

    if not isinstance(value, str) or type(value) is not str:
        raise ContractError(code)
    return value


def require_int(value: object, *, code: str, minimum: int, maximum: int) -> int:
    """Accept an exact ``int`` in range; ``bool`` is never an integer here."""

    if not isinstance(value, int) or type(value) is not int:
        raise ContractError(code)
    if not minimum <= value <= maximum:
        raise ContractError(code)
    return value


def require_member(value: object, allowed: frozenset[str], *, code: str) -> str:
    text = require_str(value, code=code)
    if text not in allowed:
        raise ContractError(code)
    return text


def require_pattern(value: object, pattern: re.Pattern[str], *, code: str) -> str:
    text = require_str(value, code=code)
    if pattern.fullmatch(text) is None:
        raise ContractError(code)
    return text


def require_token(value: object, *, code: str) -> str:
    return require_pattern(value, TOKEN_PATTERN, code=code)


def require_sha256(value: object, *, code: str) -> str:
    return require_pattern(value, SHA256_PATTERN, code=code)


def require_sequence(values: object, *, code: str, maximum: int) -> tuple[object, ...]:
    """Accept an exact list or tuple of bounded length (never str or bytes)."""

    if not isinstance(values, (list, tuple)) or type(values) not in (list, tuple):
        raise ContractError(code)
    if len(values) > maximum:
        raise ContractError(code)
    return tuple(values)


def require_sorted_members(
    values: object, allowed: frozenset[str], *, code: str
) -> tuple[str, ...]:
    """Validate a canonical (sorted, unique) list drawn from a closed set."""

    sequence = require_sequence(values, code=code, maximum=len(allowed))
    items = tuple(require_member(item, allowed, code=code) for item in sequence)
    if list(items) != sorted(set(items)):
        raise ContractError(code)
    return items


def require_capabilities(values: object, *, code: str) -> tuple[str, ...]:
    """Validate a cap-v1 set. No capability implies or adds another."""

    return require_sorted_members(values, CAPABILITIES_V1, code=code)


@dataclass(frozen=True)
class EffectVector:
    """One declared value per closed effect dimension (ADR 0050 D2).

    This is a declaration. Enforcement by the environment and observation by
    the parent boundary are separate facts that this value cannot supply.
    """

    target_code_evaluated: str
    execution_boundary: str
    filesystem_read_scope: str
    filesystem_write_scope: str
    network: str

    def __post_init__(self) -> None:
        for dimension, allowed in EFFECT_DIMENSIONS.items():
            require_member(getattr(self, dimension), allowed, code="invalid_effect")

    def to_dict(self) -> dict[str, str]:
        return {dimension: getattr(self, dimension) for dimension in EFFECT_DIMENSIONS}

    @classmethod
    def from_mapping(cls, payload: object) -> EffectVector:
        if not isinstance(payload, dict) or type(payload) is not dict:
            raise ContractError("invalid_effect")
        if set(payload) != set(EFFECT_DIMENSIONS):
            raise ContractError("invalid_effect")
        return cls(**{dimension: payload[dimension] for dimension in EFFECT_DIMENSIONS})

    def declares_extraction_admissible_shape(self) -> bool:
        """Report whether the *declared* shape lies inside ADR 0050 D3.

        A true result is not admission: D7 requires mechanical enforcement or
        parent witnessing for every dimension, and neither exists here.
        """

        return (
            self.target_code_evaluated == "none"
            and self.network == "none"
            and self.filesystem_write_scope in ("none", "scratch")
            and self.filesystem_read_scope in ("selected-input", "repository")
        )


def is_reserved_claim_metadata_key(key: object) -> bool:
    """Return whether a raw metadata key is reserved for capability claims."""

    if not isinstance(key, str):
        return False
    return key in CAPABILITY_CLAIM_METADATA_KEYS or key.startswith(
        RECEIPT_REFERENCE_KEY_PREFIX
    )
