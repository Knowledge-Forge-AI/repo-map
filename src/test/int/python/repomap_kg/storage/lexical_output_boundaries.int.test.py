"""Integration proof for real lexical publication plus bounded output transport."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_output import (
    MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES,
    lexical_build_to_jsonable,
    lexical_query_to_jsonable,
)
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.storage.lexical_driver import LexicalStorageError
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def _assert_json_line_budget(payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    assert len(encoded) <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES


def test_real_public_lexical_output_budget_and_cli_transport_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Publish/query a real corpus, then stress only the output transport seam."""
    with temporary_postgres() as pg_db:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "home",
            working_copy,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        core_id = binding_id_for_alias("core")

        genuine_build = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id,),
            authorize_body=True,
        )
        assert genuine_build.result == "published"
        assert genuine_build.published is not None
        genuine_query = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
                limit=10,
            ),
            authorize_body=True,
        )
        assert genuine_query.hits

        genuine_build_json = lexical_build_to_jsonable(genuine_build)
        _assert_json_line_budget(genuine_build_json)
        genuine_query_json = lexical_query_to_jsonable(
            MIXED_V1_GRAPH_ID, "ranked_terms", genuine_query
        )
        _assert_json_line_budget(genuine_query_json)

        # Complete CLI ready output uses a genuine typed result after real publication/build.
        import common_lore_index.ops.lexical_service as lexical_service

        monkeypatch.setattr(
            lexical_service,
            "build_graph_lexical_generation",
            lambda *_args, **_kwargs: genuine_build,
        )
        cli_build_rc = cli_main(
            [
                "ops",
                "lexical-build",
                "--repo-map-home",
                str(home),
                "--graph",
                MIXED_V1_GRAPH_ID,
                "--authorize-body",
                "--binding",
                core_id,
                "--json",
            ]
        )
        cli_build_capture = capsys.readouterr()
        assert cli_build_rc == 0
        cli_build_payload = json.loads(cli_build_capture.out)
        assert cli_build_payload["status"] == "ready"
        _assert_json_line_budget(cli_build_payload)
        assert cli_build_capture.err == ""

        # Injected transport stress only: the QueryEnvelope was produced by the real query above.
        sentinel = "INTEGRATION_TRANSPORT_STRESS_SENTINEL"
        oversized_query = replace(
            genuine_query,
            provenance={
                **genuine_query.provenance,
                "transport_stress": sentinel * 4000,
            },
        )
        with pytest.raises(LexicalStorageError) as direct_error:
            lexical_query_to_jsonable(
                MIXED_V1_GRAPH_ID, "ranked_terms", oversized_query
            )
        assert direct_error.value.code == "output_budget_exceeded"
        assert sentinel not in str(direct_error.value)

        # The following monkeypatch returns only the injected envelope; no backend qualification follows.
        monkeypatch.setattr(
            lexical_service,
            "query_graph_lexical_generation",
            lambda *_args, **_kwargs: oversized_query,
        )
        cli_query_rc = cli_main(
            [
                "ops",
                "lexical-query",
                "--repo-map-home",
                str(home),
                "--graph",
                MIXED_V1_GRAPH_ID,
                "--query",
                "RetrievalExecutionPipeline",
                "--authorize-body",
                "--binding",
                core_id,
                "--json",
            ]
        )
        cli_query_capture = capsys.readouterr()
        assert cli_query_rc == 1
        assert cli_query_capture.out == ""
        assert "output_budget_exceeded" in cli_query_capture.err
        assert sentinel not in cli_query_capture.err
        assert "Traceback" not in cli_query_capture.err
        assert len(cli_query_capture.err.encode("utf-8")) <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES
