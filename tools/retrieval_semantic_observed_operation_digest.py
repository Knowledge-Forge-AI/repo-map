"""Canonical digest and size guard for one observed-operation record."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from retrieval_semantic_experiment_contracts import ExperimentRefusal, canonical_json_bytes


MAX_OBSERVED_OPERATION_BYTES = 12_000


def observed_operation_digest(value: Mapping[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "record_sha256"}
    encoded = canonical_json_bytes(payload)
    if len(encoded) > MAX_OBSERVED_OPERATION_BYTES:
        raise ExperimentRefusal("observed_operation_record_bytes")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["MAX_OBSERVED_OPERATION_BYTES", "observed_operation_digest"]
