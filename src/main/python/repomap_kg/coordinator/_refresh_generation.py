"""Generation-fence terminal construction for pre-launch refresh rejection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Mapping, Protocol

from repomap_kg.coordinator._refresh_contracts import (
    RefreshConfigurationError,
    RefreshSourceError,
)
if TYPE_CHECKING:
    from repomap_kg.ops.config_records import OpsConfig


class GenerationClaim(Protocol):
    @property
    def job_id(self) -> str: ...
    @property
    def attempt(self) -> int: ...
    @property
    def graph_id(self) -> str: ...
    @property
    def source_generation(self) -> str: ...
    @property
    def config_generation(self) -> str: ...
    @property
    def extractor_generation(self) -> str: ...
    @property
    def canonicalizer_generation(self) -> str: ...


class ConfiguredGenerationChanged(ValueError):
    """Execution-relevant configured generations no longer match the claim."""


def validate_configured_generations(config: OpsConfig, claim: GenerationClaim) -> None:
    """Recompute execution-relevant generations in the worker before discovery."""

    from repomap_kg.ops.generations import (
        canonicalizer_generation,
        configured_graph,
        extractor_generation,
    )
    graph = configured_graph(config, claim.graph_id)
    if graph.refresh_unsupported_classification is not None:
        raise RefreshConfigurationError(graph.refresh_unsupported_classification)
    from repomap_kg.graph.multi_source_pipeline import (
        MultiSourceCaptureError,
        scan_multi_source_generations,
    )
    try:
        scan = scan_multi_source_generations(graph)
    except MultiSourceCaptureError as error:
        category = (
            "source_unavailable"
            if error.category == "source_unavailable"
            else "source_capture"
        )
        raise RefreshSourceError(category) from error
    current_source_generation = scan.source_generation
    current_config_generation = scan.config_generation
    actual = (
        current_source_generation,
        current_config_generation,
        extractor_generation(graph),
        canonicalizer_generation(),
    )
    expected = (
        claim.source_generation,
        claim.config_generation,
        claim.extractor_generation,
        claim.canonicalizer_generation,
    )
    if actual != expected:
        raise ConfiguredGenerationChanged("refresh generation changed")


def generation_changed_terminal(claim: GenerationClaim) -> Mapping[str, object]:
    """Return a proven not-started terminal without worker or transaction ownership."""

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "message_type": "error",
        "job_id": claim.job_id,
        "attempt": claim.attempt,
        "job_kind": "refresh_graph",
        "graph_id": claim.graph_id,
        "status": "failed",
        "started_at": now,
        "finished_at": now,
        "phase": "preflight",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": ["generation_changed:identity_mismatch"],
        "publication_state": "not_started",
        "latest_run_identity": None,
        "source_generation": claim.source_generation,
        "config_generation": claim.config_generation,
        "extractor_generation": claim.extractor_generation,
        "canonicalizer_generation": claim.canonicalizer_generation,
        "retryable": False,
        "error_category": "generation_changed",
        "_termination_proved": True,
        "_error_category": "generation_changed",
        "_diagnostic_summary": "generation_changed:identity_mismatch",
    }


def psql_configuration_terminal(claim: GenerationClaim) -> Mapping[str, object]:
    """Return a sanitized terminal for rejected pre-launch psql authority."""

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "message_type": "error",
        "job_id": claim.job_id,
        "attempt": claim.attempt,
        "job_kind": "refresh_graph",
        "graph_id": claim.graph_id,
        "status": "failed",
        "started_at": now,
        "finished_at": now,
        "phase": "preflight",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": ["psql_authority_invalid"],
        "publication_state": "not_started",
        "latest_run_identity": None,
        "source_generation": claim.source_generation,
        "config_generation": claim.config_generation,
        "extractor_generation": claim.extractor_generation,
        "canonicalizer_generation": claim.canonicalizer_generation,
        "retryable": False,
        "error_category": "configuration",
        "_termination_proved": True,
        "_error_category": "configuration",
        "_diagnostic_summary": "psql_authority_invalid",
    }
