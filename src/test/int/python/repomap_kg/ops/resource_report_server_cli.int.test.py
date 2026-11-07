"""Real PostgreSQL CLI children attach reports to refresh, lexical and context seams.

Each command is an observed canonical ``-m common_lore_index`` child registered
under the shared ``cli_module`` measurement family. Reports are read back
through the product reader; CLI JSON remains the authority for graph and
publication identity, and no report value is copied from it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_lore_index.coordinator.local_lifecycle import initialize_coordinator_control
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.resource_report_cli_files import (
    limit, metric, private_directory, report_leftovers, report_payload, run_cloe,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)

QUERY = "RetrievalExecutionPipeline"


def _json(completed: Any, *, codes: frozenset[int] = frozenset({0})) -> dict[str, Any]:
    assert completed.returncode in codes, completed.stderr
    assert "resource-report" not in completed.stderr, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _home(tmp_path: Path, postgres: Any) -> tuple[Path, Path]:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home", working_copy,
        host=postgres.host, port=postgres.port, database=postgres.database,
        user=postgres.user, password=postgres.password, declared_aliases=("core", "companion"),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    apply_migrations(
        default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
        psql_command=postgres.psql_command,
    )
    assert initialize_coordinator_control(home)["result"] == "ready"
    return home, working_copy


def test_server_cli_children_attach_reports_across_the_lexical_lifecycle(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    core, companion = binding_id_for_alias("core"), binding_id_for_alias("companion")
    with temporary_postgres() as postgres:
        home, working_copy = _home(tmp_path, postgres)
        forbidden = (home, working_copy, postgres.password, MIXED_V1_GRAPH_ID, core, companion, QUERY)
        base = ("--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID)

        def child(command: str, name: str, *extra: str, codes: frozenset[int] = frozenset({0})) -> Any:
            completed = run_cloe(
                "ops", command, *base, *extra, "--json", "--resource-report", str(reports / name),
                cwd=tmp_path,
            )
            return _json(completed, codes=codes)

        refreshed = child("refresh-graph", "refresh.json", "--psql-command", postgres.psql_command)
        assert refreshed["result"] == "success"
        refresh = report_payload(reports / "refresh.json", operation="server_refresh",
                                 backend="postgresql", outcome="committed", forbidden=forbidden)
        assert metric(refresh, "publication_elapsed")["availability"] == "measured"

        built = child("lexical-build", "build.json", "--authorize-body", "--binding", core, "--binding", companion)
        assert built["status"] == "ready"
        build = report_payload(reports / "build.json", operation="lexical_build", backend="postgresql",
                               outcome="published", forbidden=forbidden)
        assert metric(build, "lexical_documents")["value"] == built["document_count"]

        queried = child("lexical-query", "query.json", "--authorize-body", "--binding", core, "--query", QUERY,
                        codes=frozenset({0, 1}))
        assert queried["status"] in {"available", "partial"}
        # Only this small fixture's unshortened presentation can be an envelope oracle.
        assert queried["reason"] != "output_budget_exceeded"
        assert queried["hit_count"] == len(queried["envelope"]["hits"])
        query = report_payload(reports / "query.json", operation="lexical_query", backend="postgresql",
                               outcome=queried["status"], forbidden=forbidden)
        assert metric(query, "query_hits_returned")["value"] == queried["hit_count"] >= 1
        assert limit(query, "query_result_limit")["value"] == 20
        assert limit(query, "lexical_query_statement_timeout")["applies_this_call"] is None

        preview_json = child("lexical-revoke", "preview.json", "--dry-run")
        assert preview_json["status"] == "dry_run"
        preview = report_payload(reports / "preview.json", operation="lexical_revoke",
                                 backend="postgresql", outcome="preview", forbidden=forbidden)
        assert {item["reason"] for item in preview["metrics"][2:]} == {"not_selected"}

        revoked_json = child("lexical-revoke", "revoke.json", "--yes")
        assert revoked_json["status"] == "revoked"
        revoked = report_payload(reports / "revoke.json", operation="lexical_revoke",
                                 backend="postgresql", outcome="revoked", forbidden=forbidden)
        assert metric(revoked, "revoked_generations")["value"] >= 1
        assert metric(revoked, "purged_documents")["availability"] == "measured"

        after = child("lexical-query", "after.json", "--authorize-body", "--binding", core,
                      "--query", QUERY, codes=frozenset({1}))
        report_payload(reports / "after.json", operation="lexical_query", backend="postgresql",
                       outcome=after["status"], forbidden=forbidden)
        assert after["status"] == "unavailable"

        packed = run_cloe(
            "ops", "context-pack", *base, "--mode", "ranked_discovery", "--query", QUERY,
            "--intent", "implementation", "--resource-report", str(reports / "context.json"), cwd=tmp_path,
        )
        assert packed.returncode in {0, 1, 3}, packed.stderr
        packet = json.loads(packed.stdout)
        assert_canary_free(packet)
        context = report_payload(reports / "context.json", operation="compact_context",
                                 backend="postgresql", outcome=packet["status"], forbidden=forbidden)
        assert metric(context, "sqlite_progress_callbacks")["reason"] == "backend_not_applicable"
    assert report_leftovers(reports) == []


def test_server_refusals_precede_admission_and_coordinator_is_refused(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    existing = reports / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    with temporary_postgres() as postgres:
        home, working_copy = _home(tmp_path, postgres)
        base = ("--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID)
        unauthorized = run_cloe("ops", "lexical-query", *base, "--query", QUERY,
                                "--resource-report", str(existing), cwd=tmp_path)
        assert unauthorized.returncode == 1 and "body-authorization-required" in unauthorized.stderr
        assert "resource-report" not in unauthorized.stderr
        unconfirmed = run_cloe("ops", "lexical-revoke", *base, "--resource-report", str(existing), cwd=tmp_path)
        assert "revoke-confirmation-required" in unconfirmed.stderr
        coordinator = run_cloe("ops", "refresh-graph", *base, "--mode", "coordinator",
                               "--idempotency-key", "report-key", "--resource-report",
                               str(reports / "c.json"), cwd=tmp_path)
        assert coordinator.returncode == 1
        assert "resource-report-refused: coordinator_mode_unsupported" in coordinator.stderr
        config = load_graph_registry_config_home(home)
        graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
        source_root = Path(graph.effective_source_bindings[0].root_path_expanded)
        inside = private_directory(source_root / "reports")
        overlap = run_cloe("ops", "lexical-revoke", *base, "--dry-run",
                           "--resource-report", str(inside / "r.json"), cwd=tmp_path)
        assert overlap.returncode == 1 and "protected_root_overlap" in overlap.stderr
        store = private_directory(tmp_path / "explicit-store")
        stored = run_cloe("ops", "lexical-build", *base, "--authorize-body", "--binding",
                          binding_id_for_alias("core"), "--portable-store-root", str(store),
                          "--resource-report", str(store / "r.json"), cwd=tmp_path)
        assert stored.returncode == 1 and "protected_root_overlap" in stored.stderr
    assert existing.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in reports.iterdir()) == ["existing.json"]
