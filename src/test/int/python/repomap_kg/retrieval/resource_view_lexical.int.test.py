"""Real PostgreSQL lexical publication/readback boundaries for the resource view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
    revoke_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.lexical_driver import LexicalStorageError
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    MIXED_V1_BINDINGS,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.postgres_harness import temporary_postgres


def _setup(
    tmp_path: Path, postgres: Any, *, aliases: tuple[str, ...] = MIXED_V1_BINDINGS,
) -> tuple[Any, Path, str]:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home", working_copy,
        host=postgres.host, port=postgres.port, database=postgres.database,
        user=postgres.user, password=postgres.password,
        declared_aliases=aliases,
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    apply_migrations(
        default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
        psql_command=postgres.psql_command,
    )
    published = refresh_graph(config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command)
    assert published.result == "success" and published.publication_state == "committed"
    return config, home, postgres.password


def _metric(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in payload["metrics"] if item["name"] == name)


def test_published_lexical_report_matches_real_plan_aggregates(tmp_path: Path) -> None:
    with temporary_postgres() as postgres:
        config, home, password = _setup(tmp_path, postgres, aliases=("core", "companion"))
        observer = ResourceObserver()
        outcome = build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            selected_binding_ids=(binding_id_for_alias("core"), binding_id_for_alias("companion")),
            authorize_body=True, resource_observer=observer,
        )
        assert outcome.result == "published" and outcome.plan is not None
        payload = observer.report().to_payload()
        assert payload["operation"] == "lexical_build"
        assert payload["backend"] == "postgresql"
        assert payload["outcome"] == "published"
        assert payload["instrumentation"] == "complete"
        assert _metric(payload, "lexical_input_bytes")["value"] == outcome.plan.aggregate_input_bytes
        assert _metric(payload, "lexical_projected_bytes")["value"] == outcome.plan.aggregate_projected_bytes
        assert _metric(payload, "lexical_documents")["value"] == len(outcome.plan.documents)
        assert _metric(payload, "lexical_omissions")["value"] == len(outcome.plan.omissions)
        encoded = json.dumps(payload, sort_keys=True)
        assert_canary_free(payload)
        assert str(home) not in encoded and (not password or password not in encoded)
        assert "mixed-v1" not in encoded


def test_metadata_only_lexical_refusals_are_private_in_reports(tmp_path: Path) -> None:
    with temporary_postgres() as postgres:
        config, home, password = _setup(tmp_path, postgres)
        for alias in ("feeds", "mailbox"):
            observer = ResourceObserver()
            outcome = build_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                selected_binding_ids=(binding_id_for_alias(alias),),
                authorize_body=True, resource_observer=observer,
            )
            assert outcome.result == "refused"
            payload = observer.report().to_payload()
            assert payload["outcome"] == "refused"
            encoded = json.dumps(payload, sort_keys=True)
            assert_canary_free(payload)
            assert str(home) not in encoded and (not password or password not in encoded)
            assert binding_id_for_alias(alias) not in encoded
            if outcome.refusal_code:
                assert outcome.refusal_code not in encoded
            assert "TRUNCATABLE_PROSE_PREFIX_MARKER_V1" not in encoded


def test_lexical_build_without_accepted_publication_is_not_recorded(
    tmp_path: Path,
) -> None:
    """A missing accepted Server publication cannot produce a lexical report."""
    with temporary_postgres() as postgres:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(
            default_rdbms_root(),
            config.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        observer = ResourceObserver()
        with pytest.raises(LexicalStorageError) as raised:
            build_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(binding_id_for_alias("core"),),
                authorize_body=True,
                resource_observer=observer,
            )
        assert raised.value.code == "cloe_lexical_no_accepted_publication"
        payload: dict[str, Any] = observer.report().to_payload()
        assert payload["schema"] == "cloe-resource-view-v1"
        assert payload["operation"] == "lexical_build"
        assert payload["backend"] == "postgresql"
        assert payload["outcome"] == "not_recorded"
        assert payload["instrumentation"] == "incomplete"
        assert all(item["availability"] == "unavailable" for item in payload["metrics"])
        assert payload["limits"]
        assert all(item["applies_this_call"] is None for item in payload["limits"])
        encoded = json.dumps(payload, sort_keys=True)
        assert_canary_free(payload)
        assert str(home) not in encoded
        assert (not postgres.password) or postgres.password not in encoded
        assert "cloe_lexical_no_accepted_publication" not in encoded


def _observed(call: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
    observer = ResourceObserver()
    result = call(resource_observer=observer, **kwargs)
    payload = observer.report().to_payload()
    assert_canary_free(payload)
    assert "mixed-v1" not in json.dumps(payload, sort_keys=True)
    return result, payload


def test_query_and_revoke_views_follow_real_service_envelopes_and_effects(tmp_path: Path) -> None:
    with temporary_postgres() as postgres:
        config, _home, _password = _setup(tmp_path, postgres, aliases=("core", "companion"))
        core = binding_id_for_alias("core")
        build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID, selected_binding_ids=(core,), authorize_body=True,
        )
        envelope, sql_view = _observed(
            lambda **kw: query_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core,)),
                authorize_body=True, **kw,
            ),
        )
        assert sql_view["outcome"] == envelope.capability_state.value
        assert _metric(sql_view, "query_hits_returned")["value"] == len(envelope.hits)
        assert {item["applies_this_call"] for item in sql_view["limits"]} == {None}
        immediate, immediate_view = _observed(
            lambda **kw: query_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(query="x", selected_binding_ids=(binding_id_for_alias("feeds"),)),
                authorize_body=True, **kw,
            ),
        )
        assert immediate_view["outcome"] == immediate.capability_state.value == "refused"
        assert {item["applies_this_call"] for item in immediate_view["limits"]} == {False}

        preview, preview_view = _observed(
            lambda **kw: revoke_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID, dry_run=True, confirmed=False, **kw,
            ),
        )
        assert preview.revoked_generation_count >= 1 and preview_view["outcome"] == "preview"
        assert {item["reason"] for item in preview_view["metrics"][2:]} == {"not_selected"}
        kept, kept_view = _observed(
            lambda **kw: revoke_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID, purge_rows=False, confirmed=True, **kw,
            ),
        )
        assert _metric(kept_view, "revoked_generations")["value"] == kept.revoked_generation_count >= 1
        assert _metric(kept_view, "purged_documents")["reason"] == "not_selected"
        _again, again_view = _observed(
            lambda **kw: revoke_graph_lexical_generation(config, MIXED_V1_GRAPH_ID, confirmed=True, **kw),
        )
        assert _metric(again_view, "revoked_generations")["value"] == 0
        assert _metric(again_view, "purged_documents")["availability"] == "measured"
