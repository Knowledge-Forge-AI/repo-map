"""Direct staged publication for externally supplied complete observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.generations import canonicalizer_generation, source_generation
from repomap_kg.storage import LoadSummary
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    new_direct_authority,
    run_staged_full_refresh,
)


def _prefixed_digest(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return prefix + hashlib.sha256(encoded).hexdigest()


def build_observation_publication_authority(
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
) -> IngestionAuthority:
    """Build direct authority for one externally supplied complete generation."""

    config = {
        "contract": "arch4a-observation-publication-v1",
        "repository_name": repository_name,
        "root_path": root_path,
    }
    extractors = sorted(
        {(item.extractor, item.extractor_version) for item in observations}
    )
    extractor_contract = {
        "contract": "arch4a-observation-extractors-v1",
        "extractors": extractors,
    }
    return new_direct_authority(
        source_generation=source_generation(observations),
        config_generation=_prefixed_digest("cg1:", config),
        extractor_generation=_prefixed_digest("eg1:", extractor_contract),
        canonicalizer_generation=canonicalizer_generation(),
    )


def publish_observation_generation(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    repository_identity: str | None = None,
    git_commit: str | None = None,
    psql_command: str = "psql",
) -> LoadSummary:
    """Publish a complete observation generation through staged ingestion.

    ``psql_command`` remains part of the compatibility contract for callers that
    already select a client binary. Staged publication uses the Psycopg backend.
    """

    if not isinstance(psql_command, str) or not psql_command:
        raise ValueError("psql command is invalid")
    authority = build_observation_publication_authority(
        observations,
        repository_name=repository_name,
        root_path=root_path,
    )
    return run_staged_full_refresh(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        authority=authority,
        repository_identity=repository_identity,
    )


__all__ = [
    "build_observation_publication_authority",
    "publish_observation_generation",
]
