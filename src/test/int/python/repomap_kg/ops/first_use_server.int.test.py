"""First-use delta for a PostgreSQL Server mixed-v1 home."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
    revoke_graph_lexical_generation,
)
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.resource_view._projections import project_compact_context
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import CapabilityState
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.first_use_workflow import (
    first_use_expectations,
    guard_first_use_root,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.postgres_harness import temporary_postgres


def _resource_payload(
    observer: ResourceObserver,
    *,
    operation: str,
    backend: str,
    outcome: str,
) -> dict[str, Any]:
    payload = observer.report().to_payload()
    assert payload["schema"] == "cloe-resource-view-v1"
    assert payload["operation"] == operation
    assert payload["backend"] == backend
    assert payload["outcome"] == outcome
    assert payload["instrumentation"] == "complete"
    assert "mixed-v1" not in json.dumps(payload, sort_keys=True)
    assert_canary_free(payload)
    return payload


def _invoke(argv: list[str], capsys: Any) -> tuple[int, dict[str, Any], str]:
    rc = cli_main(argv)
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    assert_canary_free(payload)
    return rc, payload, captured.out


def _pack(
    home: Path,
    selection: Path,
    capsys: Any,
    *,
    mode: str = "ranked_discovery",
    query: str | None = "RetrievalExecutionPipeline",
    intent: str | None = "implementation",
    canonical_key: str | None = None,
    fallback: str | None = None,
) -> dict[str, Any]:
    args = [
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--mode", mode, "--selection", str(selection),
    ]
    if query is not None:
        args.extend(["--query", query])
    if intent is not None:
        args.extend(["--intent", intent])
    if canonical_key is not None:
        args.extend(["--canonical-key", canonical_key])
    if fallback is not None:
        args.extend(["--fallback-to", fallback])
    rc, packet, _raw = _invoke(args, capsys)
    assert rc in {0, 1, 3}
    assert_valid_context_packet(packet)
    view = project_compact_context(packet).to_payload()
    assert view["schema"] == "cloe-resource-view-v1"
    assert view["operation"] == "compact_context"
    assert view["backend"] == "postgresql"
    assert view["outcome"] == packet["status"]
    assert view["instrumentation"] == "complete"
    assert "mixed-v1" not in json.dumps(view, sort_keys=True)
    return packet


def _select(
    home: Path,
    output: Path,
    capsys: Any,
    *,
    pin: bool,
) -> dict[str, Any]:
    args = [
        "ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--binding", binding_id_for_alias("core"), "--binding", binding_id_for_alias("companion"),
    ]
    if pin:
        args.append("--pin-publication")
    args.extend(["--output", str(output)])
    rc, payload, _raw = _invoke(args, capsys)
    assert rc == 0
    assert payload["schema"] == "cloe-source-selection-v1"
    assert payload["backend"] == "postgresql"
    assert {item["binding_id"] for item in payload["bindings"]} == {
        binding_id_for_alias("core"), binding_id_for_alias("companion"),
    }
    if pin:
        assert payload["expected_publication"]["generation"] == 1
        assert all(item["snapshot_id"] for item in payload["bindings"])
    else:
        assert payload["expected_publication"] is None
    return payload


def test_first_use_server_context_and_native_fts_lifecycle(
    tmp_path: Path,
    capsys: Any,
) -> None:
    expectations = {item.alias: item for item in first_use_expectations(("core", "companion"))}
    assert {item.lexical_treatment for item in expectations.values()} == {"eligible"}

    work_root = tmp_path / "workflow"
    work_root.mkdir()
    working_copy = guard_first_use_root(work_root / "working-copy", work_root)
    materialize_mixed_v1_working_copy(working_copy, generation=1)

    with temporary_postgres() as postgres:
        home = guard_first_use_root(work_root / "postgres-home", work_root)
        write_mixed_v1_postgres_home(
            home,
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

        refresh_observer = ResourceObserver()
        first_refresh = refresh_graph(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=postgres.psql_command,
            resource_observer=refresh_observer,
        )
        assert first_refresh.result == "success"
        assert first_refresh.publication_state == "committed"
        _resource_payload(
            refresh_observer, operation="server_refresh", backend="postgresql", outcome="committed"
        )

        pinned = work_root / "selection-v1.json"
        pinned_record = _select(home, pinned, capsys, pin=True)
        assert pinned_record["expected_publication"]["generation"] == 1
        _pack(home, pinned, capsys)

        guard_first_use_root(working_copy, work_root)
        materialize_mixed_v1_working_copy(working_copy, generation=2)
        second_refresh_observer = ResourceObserver()
        second_refresh = refresh_graph(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=postgres.psql_command,
            resource_observer=second_refresh_observer,
        )
        assert second_refresh.result == "success"
        assert second_refresh.publication_state == "committed"
        _resource_payload(
            second_refresh_observer,
            operation="server_refresh",
            backend="postgresql",
            outcome="committed",
        )
        stale = _pack(home, pinned, capsys)
        assert stale["status"] == "stale"
        assert stale["reason"] == "selection_publication_advanced"

        current = work_root / "selection-current.json"
        _select(home, current, capsys, pin=False)
        unsupported = _pack(
            home,
            current,
            capsys,
            mode="graph_investigation",
            query=None,
            intent=None,
            canonical_key="py:pkg.pipeline.RetrievalExecutionPipeline",
        )
        assert unsupported["status"] == "unavailable"
        assert unsupported["reason"] == "backend_unsupported"
        fallback = _pack(
            home,
            current,
            capsys,
            mode="graph_investigation",
            query="RetrievalExecutionPipeline",
            intent=None,
            canonical_key="py:pkg.pipeline.RetrievalExecutionPipeline",
            fallback="ranked_discovery",
        )
        assert fallback["effective_mode"] == "ranked_discovery"
        assert fallback["fallback"]["reason"] == "backend_unsupported"

        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        lexical_observer = ResourceObserver()
        built = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
            resource_observer=lexical_observer,
        )
        assert built.result == "published"
        assert built.plan is not None
        _resource_payload(
            lexical_observer, operation="lexical_build", backend="postgresql", outcome="published"
        )

        query_observer = ResourceObserver()
        query = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                query_style="ranked_terms",
                selected_binding_ids=(core_id,),
            ),
            authorize_body=True,
            resource_observer=query_observer,
        )
        assert query.capability_state in {CapabilityState.AVAILABLE, CapabilityState.PARTIAL}
        assert any(hit.locator.source_relative_path == "pkg/pipeline.py" for hit in query.hits)
        query_view = _resource_payload(
            query_observer, operation="lexical_query", backend="postgresql",
            outcome=query.capability_state.value,
        )
        hits_metric = next(item for item in query_view["metrics"] if item["name"] == "query_hits_returned")
        assert hits_metric["value"] == len(query.hits)
        assert "RetrievalExecutionPipeline" not in json.dumps(query_view)
        revoke_observer = ResourceObserver()
        revoked = revoke_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID, reason="first_use_server", confirmed=True,
            resource_observer=revoke_observer,
        )
        assert revoked.revoked_generation_count >= 1
        revoke_view = _resource_payload(
            revoke_observer, operation="lexical_revoke", backend="postgresql", outcome="revoked",
        )
        generations = next(item for item in revoke_view["metrics"] if item["name"] == "revoked_generations")
        assert generations["value"] == revoked.revoked_generation_count
        after_revoke = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert after_revoke.capability_state == CapabilityState.UNAVAILABLE
        assert after_revoke.unavailable_reason == "projection_absent"
