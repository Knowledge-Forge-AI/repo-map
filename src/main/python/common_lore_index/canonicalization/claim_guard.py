"""Pre-dispatch refusal of extractor capability claims in raw observations.

Raw schema 1 has no capability field, and this foundation has no parent
witness, so every capability claim found in raw input is refused before
family dispatch. The guard recognizes only explicit claims: metadata names
reserved by ADR 0154 (including the versioned receipt reference) and a Rust
language or dialect assertion. Ordinary legacy observations, including the
discovery ``file`` observation that classifies ``.rs`` paths as ``unknown``,
are untouched, and unsupported kinds keep their existing diagnostic. Legacy
kinds whose ``language`` describes embedded content rather than the observed
source (a Markdown fence info word, an HTML ``lang`` attribute) are not Rust
assertions; reserved metadata names are still refused on every kind.

Diagnostics carry categorical codes and never echo metadata values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from common_lore_index.canonicalization.diagnostics import CanonicalizationDiagnostic
from common_lore_index.extractors.contracts.vocabulary import (
    RECEIPT_REFERENCE_KEY_PREFIX,
    is_reserved_claim_metadata_key,
)
from common_lore_index.extractors.contracts.witness import refuse_capability_admission
from common_lore_index.observations.raw import RawObservation

CLAIM_REFUSED_CATEGORY = "extractor_capability_claim_refused"
LANGUAGE_CLAIM_KEYS = ("language", "dialect", "language_dialect")
CONTENT_LANGUAGE_KINDS = frozenset({"markdown.code_fence", "html.document"})
REASON_RECEIPT = "receipt_reference_metadata"
REASON_CAPABILITY = "capability_claim_metadata"
REASON_RUST = "rust_language_claim"


@dataclass(frozen=True)
class ClaimRefusal:
    ordinal: int
    reason: str
    path: str

    def diagnostic(self) -> CanonicalizationDiagnostic:
        refusal = refuse_capability_admission()
        return CanonicalizationDiagnostic(
            severity="warning",
            category=CLAIM_REFUSED_CATEGORY,
            message=f"extractor capability claim refused: {refusal.code}",
            raw_observation_ordinal=self.ordinal,
            path=self.path,
            field="metadata",
            value=self.reason,
        )


def _is_rust_assertion(value: object) -> bool:
    if not isinstance(value, str):
        return False
    folded = value.strip().casefold()
    return folded == "rust" or folded.startswith(("rust/", "rust-", "rust."))


def capability_claim_reason(observation: RawObservation) -> str | None:
    """Return the closed refusal reason for one observation, if any."""

    metadata: Mapping[str, object] = observation.metadata
    reserved = [key for key in metadata if is_reserved_claim_metadata_key(key)]
    if any(key.startswith(RECEIPT_REFERENCE_KEY_PREFIX) for key in reserved):
        return REASON_RECEIPT
    if reserved:
        return REASON_CAPABILITY
    if observation.kind in CONTENT_LANGUAGE_KINDS:
        return None
    if any(_is_rust_assertion(metadata.get(key)) for key in LANGUAGE_CLAIM_KEYS):
        return REASON_RUST
    return None


def find_claim_refusals(observations: Sequence[RawObservation]) -> tuple[ClaimRefusal, ...]:
    """Find every raw observation that asserts an unwitnessed capability claim."""

    refusals = []
    for ordinal, observation in enumerate(observations):
        reason = capability_claim_reason(observation)
        if reason is not None:
            refusals.append(ClaimRefusal(ordinal, reason, observation.path))
    return tuple(refusals)
