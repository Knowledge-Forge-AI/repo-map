"""Public-safe receipt builders for ADR 0154 contract owners.

These builders produce contract-logic fixtures only. They are not native
component evidence and no fixture here represents parent verification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from common_lore_index.extractors.contracts.receipt_schema import (
    Attempt,
    Declaration,
    ObservedFacts,
    Receipt,
)
from common_lore_index.extractors.contracts.vocabulary import EffectVector


def digest_of(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def contained_effects() -> EffectVector:
    return EffectVector(
        target_code_evaluated="none",
        execution_boundary="subprocess",
        filesystem_read_scope="selected-input",
        filesystem_write_scope="scratch",
        network="none",
    )


def declaration(**changes: Any) -> Declaration:
    base = Declaration(
        stage="S3",
        language_dialect="example/dialect-1",
        runtime_identity="example-runtime-1",
        capabilities=("lexical.structure", "syntax.error_tolerant", "syntax.tree"),
        effects=contained_effects(),
        provenance="repomap-built-helper",
        invocation_mode="parse-only",
        dependency_sha256=digest_of("dependency"),
        profile_sha256=digest_of("profile"),
    )
    return replace(base, **changes)


def attempt(label: str = "input-1", **changes: Any) -> Attempt:
    base = Attempt(
        input_sha256=digest_of(label),
        outcome="succeeded",
        exercised=("lexical.structure", "syntax.tree"),
        achieved=("syntax.tree",),
        completeness="complete",
    )
    return replace(base, **changes)


def observed(**changes: Any) -> ObservedFacts:
    base = ObservedFacts(
        installed="installed",
        admitted="admitted",
        artifact_sha256=digest_of("artifact"),
        invocation_mode="parse-only",
        attempts=(attempt(),),
        resource_events=(),
        exit_status=0,
        cleanup="proven",
        verification="unverified",
    )
    return replace(base, **changes)


def receipt(**changes: Any) -> Receipt:
    base = Receipt(
        state="complete",
        producer="example-producer",
        consumer_boundary="example-parent",
        run_id="run-0001",
        source_sha256=digest_of("source"),
        declared=declaration(),
        observed=observed(),
        refusal=None,
    )
    return replace(base, **changes)


def declared_receipt() -> Receipt:
    return receipt(state="declared", observed=None)


def canonical(payload: dict[str, Any]) -> bytes:
    """Encode an arbitrary payload the way the codec canonicalizes receipts."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
