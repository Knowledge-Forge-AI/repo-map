"""Real PostgreSQL CLI children: v2 refresh reports, budget refusal and v1 default.

Each command is an observed canonical ``-m common_lore_index`` child. CLI JSON
remains the authority for publication state; no report value is copied from it.
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
from repomap_test_support.retrieval_evaluation_publication import read_postgres_accepted_publication
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


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


def _refresh(home: Path, postgres: Any, tmp_path: Path, *extra: str, codes=frozenset({0})) -> dict[str, Any]:
    completed = run_cloe(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--psql-command", postgres.psql_command, "--json", *extra, cwd=tmp_path,
    )
    assert completed.returncode in codes, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def test_server_v2_committed_refused_and_v1_default_reports(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    with temporary_postgres() as postgres:
        home, working_copy = _home(tmp_path, postgres)
        forbidden = (home, working_copy, postgres.password, MIXED_V1_GRAPH_ID)

        committed = _refresh(home, postgres, tmp_path, "--resource-report", str(reports / "v2.json"),
                             "--resource-report-schema", "2")
        assert committed["result"] == "success"
        v2 = report_payload(reports / "v2.json", operation="server_refresh", backend="postgresql",
                            outcome="committed", forbidden=forbidden)
        assert v2["schema"] == "cloe-resource-view-v2" and len(v2["metrics"]) == 30
        sealed = metric(v2, "sealed_manifest_bytes")["value"]
        assert metric(v2, "sealing_copy_read_bytes")["value"] == sealed
        assert metric(v2, "sealing_read_bytes")["value"] > 4 * sealed
        assert metric(v2, "sealing_read_bytes")["basis"] == "call_meter_exact"
        assert metric(v2, "worker_launches")["value"] == 1
        for name in ("worker_cpu", "worker_user_cpu", "worker_system_cpu", "worker_peak_rss"):
            row = metric(v2, name)
            assert row["availability"] == "measured" and row["value"] >= 0
        assert metric(v2, "worker_cpu")["value"] > 0 and metric(v2, "worker_peak_rss")["value"] > 0
        assert metric(v2, "worker_cpu")["value"] == (
            metric(v2, "worker_user_cpu")["value"] + metric(v2, "worker_system_cpu")["value"]
        )
        group = metric(v2, "worker_group_members_after_reap")
        assert group["availability"] == "measured" and group["value"] in (0, 1)
        assert group["basis"] == "process_group_probe"
        assert metric(v2, "publication_elapsed")["availability"] == "measured"

        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        accepted_before = read_postgres_accepted_publication(
            config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command,
        )

        refused = _refresh(
            home, postgres, tmp_path, "--sealing-max-write-bytes", "1", "--resource-report",
            str(reports / "refused.json"), "--resource-report-schema", "2", codes=frozenset({1}),
        )
        result = refused["graphs"][0] if "graphs" in refused else refused
        assert result["result"] == "failure"
        assert (result["publication_state"], result["error_category"]) == ("not_started", "resource_budget_exceeded")
        codes = [item["code"] for item in result["diagnostics"]]
        assert codes == ["sealing-budget-exceeded"]
        assert result["diagnostics"][0]["message"] == "sealing budget exceeded: planned_write_bytes"
        refusal = report_payload(reports / "refused.json", operation="server_refresh", backend="postgresql",
                                 outcome="refused", instrumentation="incomplete", forbidden=forbidden)
        assert metric(refusal, "worker_launches")["value"] == 0
        assert limit(refusal, "sealing_max_write_bytes")["value"] == 1

        assert read_postgres_accepted_publication(
            config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command,
        ) == accepted_before
        following = _refresh(home, postgres, tmp_path, "--resource-report", str(reports / "v1.json"))
        assert following["result"] == "success"
        v1 = report_payload(reports / "v1.json", operation="server_refresh", backend="postgresql",
                            outcome="committed", forbidden=forbidden)
        assert v1["schema"] == "cloe-resource-view-v1" and len(v1["metrics"]) == 11
        assert v1["limits"][-1]["name"] == "sealing_io_limit"

        plain = _refresh(home, postgres, tmp_path)
        assert set(plain) == set(following)
    assert report_leftovers(reports) == []
