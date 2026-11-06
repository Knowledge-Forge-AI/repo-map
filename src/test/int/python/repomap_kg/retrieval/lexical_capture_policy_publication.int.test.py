"""Real retained-publication capture and lexical policy integration proofs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import resolve_ops_graph
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def _write_public_fixture(tmp_path: Path, pg_db: Any) -> tuple[Path, Path, str, str]:
    """Write the maintained two-binding all-public home without publishing it."""
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home",
        working_copy,
        host=pg_db.host,
        port=pg_db.port,
        database=pg_db.database,
        user=pg_db.user,
        password=pg_db.password,
        declared_aliases=("core", "companion"),
    )
    return home, working_copy, binding_id_for_alias("core"), binding_id_for_alias("companion")


def _public_fixture(tmp_path: Path, pg_db: Any) -> tuple[Path, OpsConfig, str, str]:
    """Publish the maintained two-binding all-public fixture through PostgreSQL."""
    home, _working_copy, core_id, companion_id = _write_public_fixture(tmp_path, pg_db)
    publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    return home, config, core_id, companion_id


def _companion_privacy_edit(text: str) -> str:
    """Reclassify only the temporary companion binding in repomap.rpl.toml."""
    header, *blocks = text.split("[[graphs.source_bindings]]")
    for index, block in enumerate(blocks):
        if 'alias = "companion"' in block:
            assert 'privacy = "public-dev"' in block
            blocks[index] = block.replace(
                'privacy = "public-dev"', 'privacy = "private-memory"', 1
            )
            break
    else:
        raise AssertionError("maintained companion binding block was not found")
    return "[[graphs.source_bindings]]".join((header, *blocks))


def test_real_retained_capture_records_edge_omissions_and_survives_root_deletion(
    tmp_path: Path,
) -> None:
    """Accepted bytes, strict decoding, and truncation remain queryable after roots vanish."""
    with temporary_postgres() as pg_db:
        _, config, core_id, companion_id = _public_fixture(tmp_path, pg_db)
        working_copy = tmp_path / "working-copy"
        shutil.rmtree(working_copy / "core")
        shutil.rmtree(working_copy / "companion")
        built = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert built.result == "published"
        assert built.published is not None
        assert built.published.projected_document_count > 0
        assert built.published.projected_chunk_count > 0
        omissions = {
            (omission.binding_id, omission.source_relative_path): omission.reason_code
            for omission in built.omissions
        }
        assert omissions[(companion_id, "generated/invalid_utf8.txt")] == ExclusionReason.INVALID_UTF8.value
        assert omissions[(companion_id, "generated/binary_nul.txt")] == ExclusionReason.NUL_BYTE_REJECTED.value
        assert omissions[(companion_id, "generated/oversized_dump.txt")] == ExclusionReason.ARTIFACT_OVERSIZED.value
        assert omissions[(companion_id, "generated/truncatable_prose.md")] == "oversize_projected_file_truncated"

        prefix_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="TRUNCATABLE_PROSE_PREFIX_MARKER_V1",
                query_style="literal_captured_text",
                selected_binding_ids=(companion_id,),
                path_prefixes=("generated/truncatable_prose.md",),
            ),
            authorize_body=True,
        )
        assert prefix_env.capability_state == CapabilityState.PARTIAL
        assert prefix_env.scope_complete is False
        assert any(
            hit.locator.source_relative_path == "generated/truncatable_prose.md"
            for hit in prefix_env.hits
        )
        assert any(
            omission.source_relative_path == "generated/truncatable_prose.md"
            and omission.reason_code == "oversize_projected_file_truncated"
            for omission in prefix_env.omissions
        )

        beyond_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1",
                query_style="literal_captured_text",
                selected_binding_ids=(companion_id,),
                path_prefixes=("generated/truncatable_prose.md",),
            ),
            authorize_body=True,
        )
        assert beyond_env.hits == ()
        assert beyond_env.capability_state == CapabilityState.PARTIAL
        assert beyond_env.scope_complete is False
        assert any(
            omission.source_relative_path == "generated/truncatable_prose.md"
            and omission.reason_code == "oversize_projected_file_truncated"
            for omission in beyond_env.omissions
        )

        normalized_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="CRLF_NORMALIZED_CITATION_MARKER_V1",
                query_style="literal_captured_text",
                selected_binding_ids=(companion_id,),
                source_path_prefix="generated/crlf_notes.txt",
            ),
            authorize_body=True,
        )
        assert any(
            hit.locator.source_relative_path == "generated/crlf_notes.txt"
            for hit in normalized_env.hits
        )

        core_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
                path_prefixes=("pkg",),
            ),
            authorize_body=True,
        )
        assert core_env.capability_state == CapabilityState.AVAILABLE
        assert core_env.scope_complete is True
        assert any(hit.locator.source_relative_path == "pkg/pipeline.py" for hit in core_env.hits)


def test_real_aggregate_refusal_preserves_prior_published_authority(tmp_path: Path) -> None:
    """A retained aggregate-byte refusal cannot replace a useful prior generation."""
    with temporary_postgres() as pg_db:
        home, working_copy, core_id, _ = _write_public_fixture(tmp_path, pg_db)
        marker = b"# aggregate budget marker\n" + (b"x" * 600)
        (working_copy / "core" / "000-budget-a.py").write_bytes(marker)
        (working_copy / "core" / "000-budget-b.py").write_bytes(marker)
        # The maintained publication must include the test-owned files before capture.
        publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)

        prior = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id,),
            authorize_body=True,
        )
        assert prior.result == "published"
        assert prior.published is not None
        prior_generation_id = prior.published.lexical_generation_id

        refusal_observer = ResourceObserver()
        refused = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id,),
            authorize_body=True,
            max_input_artifact_bytes=1024,
            max_aggregate_input_bytes=1024,
            resource_observer=refusal_observer,
        )
        assert refused.result == "refused"
        assert refused.refusal_code == ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value
        assert refused.published is None
        refusal_report: dict[str, Any] = refusal_observer.report().to_payload()
        assert refusal_report["schema"] == "cloe-resource-view-v1"
        assert refusal_report["operation"] == "lexical_build"
        assert refusal_report["backend"] == "postgresql"
        assert refusal_report["outcome"] == "refused"
        assert refusal_report["instrumentation"] == "complete"
        lexical_metrics = {
            item["name"]: item
            for item in refusal_report["metrics"]
            if item["name"].startswith("lexical_")
        }
        assert set(lexical_metrics) == {
            "lexical_input_bytes",
            "lexical_projected_bytes",
            "lexical_documents",
            "lexical_omissions",
        }
        assert all(
            item["availability"] == "unavailable"
            and item["value"] is None
            and item["reason"] == "not_reached"
            for item in lexical_metrics.values()
        )
        assert refusal_report["limits"]
        assert all(item["applies_this_call"] is None for item in refusal_report["limits"])
        encoded_refusal = json.dumps(refusal_report, sort_keys=True)
        assert_canary_free(refusal_report)
        assert str(home) not in encoded_refusal
        assert core_id not in encoded_refusal
        assert refused.refusal_code not in encoded_refusal

        after_refusal = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
            ),
            authorize_body=True,
        )
        assert after_refusal.capability_state == CapabilityState.AVAILABLE
        assert after_refusal.scope_complete is True
        assert after_refusal.provenance["lexical_generation_id"] == prior_generation_id
        assert any(hit.locator.source_relative_path == "pkg/pipeline.py" for hit in after_refusal.hits)


def test_real_binding_privacy_reclassification_refuses_body_scope(tmp_path: Path) -> None:
    """A binding privacy edit reclassifies its composed graph and refuses all body scope."""
    with temporary_postgres() as pg_db:
        home, config, core_id, companion_id = _public_fixture(tmp_path, pg_db)
        assert resolve_ops_graph(config, MIXED_V1_GRAPH_ID).privacy == "public-dev"
        built = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert built.result == "published"
        assert built.published is not None
        config_path = home / "repomap.rpl.toml"
        original = config_path.read_text(encoding="utf-8")
        try:
            config_path.write_text(_companion_privacy_edit(original), encoding="utf-8")
            reclassified = load_graph_registry_config_home(home)
            assert isinstance(reclassified, OpsConfig)
            graph = resolve_ops_graph(reclassified, MIXED_V1_GRAPH_ID)
            assert graph.privacy == "private-ops"
            companion = next(binding for binding in graph.source_bindings if binding.binding_id == companion_id)
            assert companion.privacy == "private-memory"
            refused = query_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(
                    query="RetrievalExecutionPipeline",
                    selected_binding_ids=(core_id, companion_id),
                ),
                authorize_body=True,
            )
            assert refused.capability_state == CapabilityState.REFUSED
            assert refused.refusal_code == ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value
            assert refused.hits == ()
            assert refused.scope_complete is False
            assert refused.omissions == ()
        finally:
            config_path.write_text(original, encoding="utf-8")
        recovered = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert recovered.capability_state == CapabilityState.AVAILABLE
        assert recovered.hits
        assert recovered.provenance["lexical_generation_id"] == built.published.lexical_generation_id
