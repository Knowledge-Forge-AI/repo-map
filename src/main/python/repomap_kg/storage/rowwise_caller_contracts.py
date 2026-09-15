"""Executable ARCH3E contracts for receiptless row-wise mutation callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FutureBehavior = Literal[
    "complete staged publication",
    "acquisition-only non-mutating input",
    "announced retirement",
]
CallerKind = Literal[
    "public command",
    "programmatic API",
    "production compatibility path",
    "repository tool",
]
BindingKind = Literal["call", "default"]


@dataclass(frozen=True)
class RowwiseCallerContract:
    """Required ARCH4 disposition for one supported receiptless surface."""

    caller_id: str
    caller_kind: CallerKind
    current_symbol: str
    future_behavior: FutureBehavior
    migration_phase: Literal["ARCH4A", "ARCH4B", "ARCH4C"]
    replacement_contract: str
    compatibility_boundary: str
    direct_relevance: bool
    coordinator_relevance: bool
    current_receiptless_mutation: bool = True


@dataclass(frozen=True)
class ReceiptlessBinding:
    """One source binding to a receiptless row-wise loader."""

    source_path: str
    owner: str
    binding_kind: BindingKind
    loader: Literal["load_canonical_observations", "load_file_observations"]
    occurrences: int
    contract_id: str


_ACQUISITION_REPLACEMENT = (
    "retain public-safe acquisition artifacts and observations without invoking "
    "storage or changing graph freshness"
)
_ACQUISITION_BOUNDARY = (
    "ARCH4B keeps the command name and acquisition fields, replaces load_summary "
    "with an explicit non-publication result, and rejects mutation-only storage "
    "selectors after the announced boundary"
)


ROWWISE_CALLER_CONTRACTS = (
    RowwiseCallerContract(
        caller_id="storage.load-files",
        caller_kind="public command",
        current_symbol="repomap_kg.cli.dispatch.dispatch_command",
        future_behavior="complete staged publication",
        migration_phase="ARCH4A",
        replacement_contract=(
            "treat the supplied observation set as one complete repository generation "
            "and publish it through run_staged_full_refresh with a validated receipt"
        ),
        compatibility_boundary=(
            "preserve command arguments, success payload, handled errors, and direct "
            "execution while adding staged commit-unknown semantics"
        ),
        direct_relevance=True,
        coordinator_relevance=True,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="storage.load-canonical",
        caller_kind="public command",
        current_symbol="retired in ARCH4B; rejected by the storage parser",
        future_behavior="announced retirement",
        migration_phase="ARCH4B",
        replacement_contract=(
            "use storage load-files for an explicit complete generation or configured "
            "ops refresh for normal publication"
        ),
        compatibility_boundary=(
            "announce and test the removal version before deleting the canonical-only "
            "fixture command; do not silently widen it into full publication"
        ),
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="sources.ingest-feed",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.source.ingest_feed_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="sources.import-archive",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.source_archive.import_archive_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="sources.import-warc",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.source.import_warc_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="bulk.import",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.bulk.import_bulk_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="api.acquire",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.api.acquire_api_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="github.acquire",
        caller_kind="public command",
        current_symbol="repomap_kg.ops.ingestion.github_api.acquire_github_api_source",
        future_behavior="acquisition-only non-mutating input",
        migration_phase="ARCH4B",
        replacement_contract=_ACQUISITION_REPLACEMENT,
        compatibility_boundary=_ACQUISITION_BOUNDARY,
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="programmatic.load-file-observations",
        caller_kind="programmatic API",
        current_symbol="removed in ARCH4C",
        future_behavior="announced retirement",
        migration_phase="ARCH4C",
        replacement_contract=(
            "complete callers use run_staged_full_refresh; partial callers return "
            "acquisition input without storage mutation"
        ),
        compatibility_boundary=(
            "announce removal of the storage facade export before deleting the final-"
            "table mutation implementation; no receiptless forwarding remains"
        ),
        direct_relevance=True,
        coordinator_relevance=True,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="programmatic.load-canonical-observations",
        caller_kind="programmatic API",
        current_symbol="removed in ARCH4C",
        future_behavior="announced retirement",
        migration_phase="ARCH4C",
        replacement_contract=(
            "use run_staged_full_refresh for a complete generation; canonical-only "
            "fixture mutation has no final-state replacement"
        ),
        compatibility_boundary=(
            "announce removal of the storage facade export before deleting the "
            "canonical-only row-wise implementation"
        ),
        direct_relevance=True,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="programmatic.refresh-graph-rowwise",
        caller_kind="production compatibility path",
        current_symbol="repomap_kg.ops.refresh.refresh_graph",
        future_behavior="complete staged publication",
        migration_phase="ARCH4A",
        replacement_contract=(
            "make staged ingestion the only refresh_graph mode and preserve shared "
            "direct/coordinator generation, fencing, cancellation, and reconciliation"
        ),
        compatibility_boundary=(
            "reject the rowwise ingestion_mode value after the announced boundary; "
            "default and public CLI execution use staged publication"
        ),
        direct_relevance=True,
        coordinator_relevance=True,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="tool.compare-pg-connectors-seed",
        caller_kind="repository tool",
        current_symbol="tools.compare_pg_connectors.run_connector_comparison",
        future_behavior="complete staged publication",
        migration_phase="ARCH4A",
        replacement_contract=(
            "seed the complete synthetic connector fixture through staged publication"
        ),
        compatibility_boundary=(
            "preserve connector operations, report fields, privacy checks, and exact "
            "psql/Psycopg payload parity"
        ),
        direct_relevance=False,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
    RowwiseCallerContract(
        caller_id="tool.scale7-rowwise-baseline",
        caller_kind="repository tool",
        current_symbol="tools.scale7_measure_ingestion._run_current",
        future_behavior="announced retirement",
        migration_phase="ARCH4B",
        replacement_contract=(
            "retain staged ingestion measurement and remove the obsolete receiptless "
            "row-wise baseline"
        ),
        compatibility_boundary=(
            "version the measurement report before removing the current-mode result; "
            "historical reports remain unchanged"
        ),
        direct_relevance=False,
        coordinator_relevance=False,
        current_receiptless_mutation=False,
    ),
)


RECEIPTLESS_BINDINGS: tuple[ReceiptlessBinding, ...] = ()


__all__ = (
    "RECEIPTLESS_BINDINGS",
    "ROWWISE_CALLER_CONTRACTS",
    "ReceiptlessBinding",
    "RowwiseCallerContract",
)
