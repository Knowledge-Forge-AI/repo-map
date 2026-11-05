"""Explicit PostgreSQL publication boundary for the witnessed Rust pilot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any

from common_lore_index.canonicalization.rust_pilot_family import WitnessedCanonicalization


def _generation(prefix: str, payload: object) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return prefix + hashlib.sha256(data).hexdigest()


def rust_publication_generations(*, legacy_extractor_generation: str,
                                legacy_canonicalizer_generation: str,
                                lock_sha256: str, helper_closure_sha256: str) -> tuple[str, str]:
    return (
        _generation("eg1:", {
            "domain": "rust-pilot-extractor-v1", "legacy": legacy_extractor_generation,
            "lock": lock_sha256, "selection": "rust-pilot-selection-v1",
            "helper": helper_closure_sha256,
        }),
        _generation("kg1:", {
            "domain": "rust-pilot-canonicalizer-v1", "legacy": legacy_canonicalizer_generation,
            "family": "rust-pilot-family-v1", "lock": lock_sha256,
            "helper": helper_closure_sha256,
        }),
    )


def publish_rust_pilot_generation(
    psql_args: Sequence[str], witnessed: WitnessedCanonicalization, *,
    repository_name: str, root_path: str, source_generation: str, config_generation: str,
    legacy_extractor_generation: str, legacy_canonicalizer_generation: str,
    repository_identity: str | None = None, git_commit: str | None = None,
    connect: Callable[..., Any] | None = None, backend_telemetry: Any | None = None,
    staging_measurements: Any | None = None,
) -> Any:
    if type(witnessed) is not WitnessedCanonicalization or not witnessed.verify_live():
        raise ValueError("invalid Rust pilot witness")
    eg, kg = rust_publication_generations(
        legacy_extractor_generation=legacy_extractor_generation,
        legacy_canonicalizer_generation=legacy_canonicalizer_generation,
        lock_sha256=witnessed.lock_sha256,
        helper_closure_sha256=witnessed.helper_closure_sha256,
    )
    from common_lore_index.storage.staged_ingestion import new_direct_authority
    from common_lore_index.storage.staged_prepared_refresh import run_staged_prepared_refresh
    authority = new_direct_authority(
        source_generation=source_generation, config_generation=config_generation,
        extractor_generation=eg, canonicalizer_generation=kg,
    )
    return run_staged_prepared_refresh(
        psql_args, witnessed, repository_name=repository_name, root_path=root_path,
        authority=authority, repository_identity=repository_identity, git_commit=git_commit,
        connect=connect, backend_telemetry=backend_telemetry,
        staging_measurements=staging_measurements,
    )


__all__ = ("publish_rust_pilot_generation", "rust_publication_generations")
