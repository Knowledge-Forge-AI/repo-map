"""Synthetic producer faults through real Rust canonicalization and PostgreSQL publication."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import pytest

from common_lore_index.canonicalization import rust_pilot_family
from common_lore_index.canonicalization.rust_pilot_family import canonicalize_rust_pilot
from common_lore_index.ops.rust_pilot_publication import (
    publish_rust_pilot_generation,
    rust_publication_generations,
)
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.staged_ingestion import (
    IngestionAuthority,
    new_direct_authority,
    stage_id_for_authority,
)
from common_lore_index.storage.staged_prepared_refresh import run_staged_prepared_refresh
from common_lore_index.storage.staged_rows import build_staged_rows
from common_lore_index.storage.canonical import query_canonical_edge_records, query_canonical_node_records
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot


LEGACY_EG = "eg1:" + "3" * 64
LEGACY_KG = "kg1:" + "4" * 64


def _authority(live: Any, seed: str = "1", *, before: Callable[[], None] | None = None) -> IngestionAuthority:
    extractor, canonicalizer = rust_publication_generations(
        legacy_extractor_generation=LEGACY_EG,
        legacy_canonicalizer_generation=LEGACY_KG,
        lock_sha256=live.witnessed.lock_sha256,
        helper_closure_sha256=live.witnessed.helper_closure_sha256,
    )
    return replace(
        new_direct_authority(
            source_generation="sg1:" + seed * 64,
            config_generation="cg1:" + seed * 64,
            extractor_generation=extractor,
            canonicalizer_generation=canonicalizer,
        ),
        before_publication=before,
    ).validate()


def _all_counts(postgres: Any) -> tuple[str, ...]:
    return tuple(
        postgres.psql_scalar(f"SELECT count(*) FROM {table}")
        for table in ("runs", "ingestion_stages", "raw_observations", "canonical_nodes", "canonical_edges")
    )


def _published_view(postgres: Any) -> tuple[Any, ...]:
    return (
        query_canonical_node_records(postgres.psql_args, root_path="synthetic-root"),
        query_canonical_edge_records(postgres.psql_args, root_path="synthetic-root"),
        postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'complete'"),
        postgres.psql_scalar(
            "SELECT COALESCE(string_agg(source_generation || '|' || config_generation || '|' || "
            "extractor_generation || '|' || canonicalizer_generation, ',' ORDER BY id), '') "
            "FROM runs WHERE status = 'complete'"
        ),
    )


def _fault_witness(live: Any, monkeypatch: pytest.MonkeyPatch, fault: str) -> Any:
    rows = list(live.controller.admit("src/lib.rs").observations)
    items = [row for row in rows if row.kind == "rust.item"]
    assert len(items) >= 2
    if fault == "invalid":
        bad = replace(items[0], metadata={**items[0].metadata, "pointer": "not-a-pointer"})
        target = items[0]
        expected = "rust_pilot_key_invalid"
    elif fault == "duplicate":
        bad = replace(items[1], metadata={**items[1].metadata, "pointer": items[0].metadata["pointer"]})
        target = items[1]
        expected = "rust_pilot_duplicate_key"
    else:
        child = next(item for item in items if item.metadata.get("parent_pointer") != "/")
        bad = replace(child, metadata={**child.metadata, "parent_pointer": "/mod:missing"})
        target = child
        expected = "rust_pilot_parent_missing"
    replacement = tuple(bad if row is target else row for row in rows)
    # Keep controller custody/live checks real; only the producer's admitted tuple is synthetic.
    mapping = {"src/lib.rs": replacement}
    monkeypatch.setattr(rust_pilot_family, "_admit", lambda _run: (mapping, ()))
    witness = canonicalize_rust_pilot(live.controller, live.legacy_observations, repository_scope="synthetic")
    assert expected in {diagnostic.category for diagnostic in witness.result.diagnostics}
    assert not witness.result.ok
    return witness


def test_valid_witness_rows_roundtrip_through_real_staging_and_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        prepared = build_staged_rows(
            live.witnessed.observations, repository_name="synthetic", stage_id="stage-rust-proposal",
            witnessed=live.witnessed,
        )
        try:
            assert prepared.row_counts["raw_observations"] == len(live.witnessed.observations)
        finally:
            prepared.close()
        summary = publish_rust_pilot_generation(
            postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
            source_generation="sg1:" + "1" * 64, config_generation="cg1:" + "2" * 64,
            legacy_extractor_generation=LEGACY_EG, legacy_canonicalizer_generation=LEGACY_KG,
        )
        assert summary.files == len(live.infos)
        nodes, edges, complete, _ = _published_view(postgres)
        assert complete == "1" and any(node.kind == "rust.function" for node in nodes)
        assert any(edge.edge_kind == "contains" for edge in edges)


@pytest.mark.parametrize("fault", ["invalid", "duplicate", "missing"])
def test_invalid_duplicate_or_missing_item_pointer_refuses_before_any_postgres_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        before = _all_counts(postgres)
        authority = _authority(live)
        witness = _fault_witness(live, monkeypatch, fault)
        with pytest.raises(StorageSchemaError, match="canonicalization failed"):
            run_staged_prepared_refresh(
                postgres.psql_args, witness, repository_name="synthetic", root_path="synthetic-root",
                authority=authority,
            )
        assert _all_counts(postgres) == before == ("0", "0", "0", "0", "0")
        assert _published_view(postgres)[0:2] == ((), ())


@pytest.mark.parametrize("mutation", ["closed", "changed"])
def test_closed_or_changed_witness_refuses_before_staging_and_preserves_empty_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        before = _all_counts(postgres)
        authority = _authority(live)
        if mutation == "closed":
            live.controller.close()
        else:
            metadata = live.witnessed.result.graph.nodes[0].metadata
            assert isinstance(metadata, dict)
            metadata["tamper"] = True
        with pytest.raises(StorageSchemaError, match="Rust pilot witness"):
            run_staged_prepared_refresh(
                postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
                authority=authority,
            )
        assert _all_counts(postgres) == before
        assert _published_view(postgres)[0:2] == ((), ())


def test_explicit_stage_and_non_direct_authority_or_nonpositive_ttl_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        owner = _authority(live, "1")
        publish_rust_pilot_generation(
            postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
            source_generation=owner.source_generation, config_generation=owner.config_generation,
            legacy_extractor_generation=LEGACY_EG, legacy_canonicalizer_generation=LEGACY_KG,
        )
        other = _authority(live, "2")
        run_staged_prepared_refresh(
            postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
            authority=other, stage_id=str(stage_id_for_authority(owner)),
        )
        before = _published_view(postgres)
        assert other.source_generation in before[3]
        with pytest.raises(ValueError, match="expiry must be positive"):
            run_staged_prepared_refresh(
                postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
                authority=_authority(live, "3"), stage_ttl=timedelta(0),
            )
        non_direct = replace(_authority(live, "4"), execution_mode="coordinator")
        with pytest.raises(StorageSchemaError, match="not live or direct"):
            run_staged_prepared_refresh(
                postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
                authority=non_direct,
            )
        assert _published_view(postgres) == before


def test_callback_closure_rolls_back_staged_rows_and_preserves_published_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        owner = _authority(live, "5")
        publish_rust_pilot_generation(
            postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
            source_generation=owner.source_generation, config_generation=owner.config_generation,
            legacy_extractor_generation=LEGACY_EG, legacy_canonicalizer_generation=LEGACY_KG,
        )
        before = _published_view(postgres)
        closing = _authority(live, "6", before=live.controller.close)
        with pytest.raises(StorageSchemaError, match="during publication callback"):
            run_staged_prepared_refresh(
                postgres.psql_args, live.witnessed, repository_name="synthetic", root_path="synthetic-root",
                authority=closing,
            )
        assert _published_view(postgres) == before
        assert postgres.psql_scalar("SELECT count(*) FROM runs WHERE status = 'failed'") == "1"
