"""First-use delta for mixed-v1 privacy and alias-qualified context scope."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config import OpsConfig, OpsConfigError
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.resource_view._projections import project_compact_context
from common_lore_index.retrieval.context_contracts import CONTEXT_LOCATION_KEYS
from common_lore_index.retrieval.projection_policy import ExclusionReason
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.governance3_first_use_sealing import assert_mixed_snapshot_equivalence
from repomap_test_support.first_use_workflow import (
    first_use_expectations,
    guard_first_use_root,
)
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)
from repomap_test_support.sqlite_local_harness import LocalHarness


def _invoke(argv: list[str], capsys: Any) -> tuple[int, dict[str, Any]]:
    rc = cli_main(argv)
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    assert_canary_free(payload)
    return rc, payload


def _select_local(
    harness: LocalHarness,
    home: Path,
    output: Path,
    *,
    aliases: tuple[str, ...],
    expected_generation: int | None = None,
) -> dict[str, Any]:
    args = [
        "ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
    ]
    for alias in aliases:
        args.extend(["--binding", binding_id_for_alias(alias)])
    if expected_generation is not None:
        args.append("--pin-publication")
    args.extend(["--output", str(output)])
    completed = harness.run(*args)
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout)
    assert record["schema"] == "cloe-source-selection-v1"
    assert {row["binding_id"] for row in record["bindings"]} == {
        binding_id_for_alias(alias) for alias in aliases
    }
    if expected_generation is not None:
        assert record["expected_publication"]["generation"] == expected_generation
    assert_canary_free(record)
    return record


def _select_all_local(harness: LocalHarness, home: Path, output: Path) -> None:
    _select_local(harness, home, output, aliases=MIXED_V1_BINDINGS)


def _pack_local(
    harness: LocalHarness,
    home: Path,
    selection: Path,
    *,
    query: str,
    intent: str,
) -> dict[str, Any]:
    completed = harness.run(
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--mode", "ranked_discovery", "--query", query, "--intent", intent,
        "--selection", str(selection),
    )
    assert completed.returncode in {0, 3}, completed.stderr
    packet = json.loads(completed.stdout)
    assert_valid_context_packet(packet)
    view = project_compact_context(packet).to_payload()
    assert view["schema"] == "cloe-resource-view-v1"
    assert view["operation"] == "compact_context"
    assert view["backend"] == "sqlite"
    assert view["outcome"] == packet["status"]
    assert view["instrumentation"] == "complete"
    assert_canary_free(packet)
    assert_canary_free(view)
    return packet


def _assert_lexical_refusal_report(observer: ResourceObserver) -> None:
    report = observer.report().to_payload()
    assert report["schema"] == "cloe-resource-view-v1"
    assert report["operation"] == "lexical_build"
    assert report["backend"] == "postgresql"
    assert report["outcome"] == "refused"
    assert report["instrumentation"] == "complete"
    assert "mixed-v1" not in json.dumps(report, sort_keys=True)
    assert_canary_free(report)


def test_first_use_mixed_context_is_alias_qualified_and_body_blind(
    tmp_path: Path,
    capsys: Any,
) -> None:
    expectations = {item.alias: item for item in first_use_expectations(MIXED_V1_BINDINGS)}
    assert expectations["core"].body_treatment == "full-authorized"
    assert expectations["companion"].body_treatment == "full-authorized"
    assert expectations["feeds"].body_treatment == "metadata-only"
    assert expectations["mailbox"].body_treatment == "metadata-only"
    assert {item.lexical_treatment for item in expectations.values()} == {"eligible", "refused"}

    work_root = tmp_path / "workflow"
    work_root.mkdir()
    working_copy = guard_first_use_root(work_root / "working-copy", work_root)
    materialize_mixed_v1_working_copy(working_copy)
    home = guard_first_use_root(work_root / "sqlite-home", work_root)
    write_mixed_v1_sqlite_home(home, working_copy)
    harness = LocalHarness(work_root / "guarded", block_psycopg=True)
    for command in ("sqlite-init", "refresh-graph"):
        completed = harness.run(
            "ops", command, "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--json",
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert isinstance(payload, dict)
        assert_canary_free(payload)
    selection = work_root / "selection.json"
    record = _select_local(harness, home, selection, aliases=MIXED_V1_BINDINGS, expected_generation=1)
    assert_mixed_snapshot_equivalence(home, working_copy, record["expected_publication"])

    packets = {
        "core": _pack_local(
            harness, home, selection, query="RetrievalExecutionPipeline", intent="implementation"
        ),
        "companion": _pack_local(harness, home, selection, query="architecture", intent="docs"),
        "feeds": _pack_local(harness, home, selection, query="release", intent="messages"),
        "mailbox": _pack_local(harness, home, selection, query="incident", intent="messages"),
    }
    alias_by_id = {binding_id_for_alias(alias): alias for alias in MIXED_V1_BINDINGS}
    seen_aliases: set[str] = set()
    for packet in packets.values():
        for item in packet["items"]:
            for location in item["locations"]:
                binding_id = location["source_binding_id"]
                assert binding_id in alias_by_id
                seen_aliases.add(alias_by_id[binding_id])
                assert tuple(location) == CONTEXT_LOCATION_KEYS
    assert seen_aliases == set(MIXED_V1_BINDINGS)
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()


def test_first_use_mixed_lexical_refuses_metadata_only_bindings_before_body_capture(
    tmp_path: Path,
) -> None:
    work_root = tmp_path / "workflow"
    work_root.mkdir()
    working_copy = guard_first_use_root(work_root / "working-copy", work_root)
    materialize_mixed_v1_working_copy(working_copy)

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
        )
        state = publish_and_load_postgres_corpus(
            home,
            selected_aliases=MIXED_V1_BINDINGS,
            psql_command=postgres.psql_command,
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)

        # The refusal must be decided from the accepted policy before body
        # capture.  Remove the synthetic metadata-only roots so an accidental
        # filesystem read cannot make this proof pass.
        for alias in ("feeds", "mailbox"):
            shutil.rmtree(working_copy / alias)

        for alias in ("feeds", "mailbox"):
            refusal_observer = ResourceObserver()
            refused = build_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(binding_id_for_alias(alias),),
                authorize_body=True,
                resource_observer=refusal_observer,
            )
            assert refused.result == "refused"
            assert refused.refusal_code in {
                ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value,
                ExclusionReason.RETENTION_NOT_AUTHORIZED.value,
            }
            assert refused.published is None
            assert refused.plan is None
            assert_canary_free(refused.to_dict())
            _assert_lexical_refusal_report(refusal_observer)

        empty_observer = ResourceObserver()
        with pytest.raises(ValueError, match="binding-selection-required"):
            build_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(),
                authorize_body=True,
                resource_observer=empty_observer,
            )
        empty_report = empty_observer.report().to_payload()
        assert empty_report["operation"] == "lexical_build"
        assert empty_report["outcome"] == "not_recorded"
        assert empty_report["instrumentation"] == "incomplete"
        assert_canary_free(empty_report)
        assert state.accepted_reference.accepted_generation == 1


def test_first_use_mixed_declared_alias_sets_publish_read_and_refuse_empty(
    tmp_path: Path,
) -> None:
    work_root = tmp_path / "workflow"
    work_root.mkdir()
    working_copy = guard_first_use_root(work_root / "working-copy", work_root)
    materialize_mixed_v1_working_copy(working_copy)
    home = guard_first_use_root(work_root / "sqlite-home", work_root)
    harness = LocalHarness(work_root / "guarded", block_psycopg=True)

    one = ("core",)
    write_mixed_v1_sqlite_home(home, working_copy, declared_aliases=one)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    assert graph.explicit_source_bindings
    assert tuple(binding.alias for binding in graph.effective_source_bindings) == one

    initialized = harness.run(
        "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--json",
    )
    assert initialized.returncode == 0, initialized.stderr
    first_refresh = harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--json",
    )
    assert first_refresh.returncode == 0, first_refresh.stderr
    first_payload = json.loads(first_refresh.stdout)
    assert first_payload["accepted_generation"] == 1
    assert_canary_free(first_payload)
    first_selection = _select_local(
        harness, home, work_root / "selection-one.json", aliases=one, expected_generation=1
    )
    assert first_selection["bindings"][0]["binding_id"] == binding_id_for_alias("core")
    first_packet = _pack_local(
        harness, home, work_root / "selection-one.json",
        query="RetrievalExecutionPipeline", intent="implementation",
    )
    first_locations = [
        location for item in first_packet["items"] for location in item["locations"]
    ]
    assert first_locations
    assert {location["source_binding_id"] for location in first_locations} == {
        binding_id_for_alias("core")
    }
    assert all(tuple(location) == CONTEXT_LOCATION_KEYS for location in first_locations)
    assert_canary_free(first_packet)

    several = ("core", "companion", "feeds")
    write_mixed_v1_sqlite_home(home, working_copy, declared_aliases=several)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    assert tuple(binding.alias for binding in graph.effective_source_bindings) == tuple(
        sorted(several, key=binding_id_for_alias)
    )
    second_refresh = harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--json",
    )
    assert second_refresh.returncode == 0, second_refresh.stderr
    second_payload = json.loads(second_refresh.stdout)
    assert second_payload["accepted_generation"] == 2
    assert_canary_free(second_payload)
    second_selection = _select_local(
        harness, home, work_root / "selection-several.json",
        aliases=several, expected_generation=2,
    )
    assert {
        row["binding_id"] for row in second_selection["bindings"]
    } == {binding_id_for_alias(alias) for alias in several}
    second_packet = _pack_local(
        harness, home, work_root / "selection-several.json",
        query="release", intent="messages",
    )
    second_locations = [
        location for item in second_packet["items"] for location in item["locations"]
    ]
    assert second_locations
    assert {
        location["source_binding_id"] for location in second_locations
    } <= {binding_id_for_alias(alias) for alias in several}
    assert all(tuple(location) == CONTEXT_LOCATION_KEYS for location in second_locations)
    assert_canary_free(second_packet)

    empty_home = guard_first_use_root(work_root / "empty-home", work_root)
    write_mixed_v1_sqlite_home(empty_home, working_copy, declared_aliases=())
    with pytest.raises(OpsConfigError) as error:
        load_graph_registry_config_home(empty_home)
    missing_paths = {
        diagnostic.path
        for diagnostic in error.value.diagnostics
        if diagnostic.code == "missing-required-field"
    }
    assert {
        "graphs[0].root_path",
        "graphs[0].repository_name",
        "graphs[0].privacy",
        "graphs[0].extractor_profile",
    } <= missing_paths
