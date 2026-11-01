"""Real PostgreSQL publication and CLI JSON/table lexical roundtrip proof."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.lexical_output import MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES
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


def _public_home(tmp_path: Path, pg_db: Any) -> tuple[Path, str, str]:
    """Create and publish the maintained all-public two-binding PostgreSQL home."""
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
    publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
    return home, binding_id_for_alias("core"), binding_id_for_alias("companion")


class _CapturedOutput(Protocol):
    @property
    def out(self) -> str: ...

    @property
    def err(self) -> str: ...


def _assert_json_line_budget(capture: _CapturedOutput) -> None:
    """Measure the exact emitted UTF-8 JSON line, including its final newline."""
    assert capture.err == ""
    assert capture.out.endswith("\n")
    assert capture.out.count("\n") == 1
    assert len(capture.out.encode("utf-8")) <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES


def _assert_no_fixture_values(
    capture: _CapturedOutput, home: Path, password: str | None
) -> None:
    """Ensure public output does not disclose fixture paths, credentials, or DSNs."""
    for stream in (capture.out, capture.err):
        assert str(home) not in stream
        assert "postgresql://" not in stream.lower()
        if password:
            assert password not in stream


def _json_payload(
    capture: _CapturedOutput, home: Path, password: str | None
) -> dict[str, Any]:
    _assert_no_fixture_values(capture, home, password)
    _assert_json_line_budget(capture)
    payload = json.loads(capture.out)
    assert isinstance(payload, dict)
    return payload


def _build_json(
    home: Path,
    core_id: str,
    companion_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    rc = cli_main(
        [
            "ops", "lexical-build", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--binding", core_id, "--binding", companion_id, "--json",
        ]
    )
    capture = capsys.readouterr()
    payload = _json_payload(capture, home, password)
    assert rc == 0
    assert payload["status"] == "ready" and payload["result"] == "published"
    assert payload["document_count"] > 0 and payload["chunk_count"] > 0
    assert "TRUNCATABLE_PROSE_PREFIX_MARKER_V1" not in capture.out
    return payload


def _ranked_table(
    home: Path,
    core_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_main(
        [
            "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--query", "RetrievalExecutionPipeline", "--query-style", "ranked_terms",
            "--binding", core_id,
        ]
    )
    capture = capsys.readouterr()
    _assert_no_fixture_values(capture, home, password)
    assert rc == 0
    assert f"lexical-query {MIXED_V1_GRAPH_ID} (ranked_terms): available" in capture.out
    assert "rank | binding_id | path | lines | score | canonical_key" in capture.out
    assert "pkg/pipeline.py" in capture.out


def _literal_fallback_json(
    home: Path,
    core_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_main(
        [
            "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--query", "RetrievalExecutionPipeline", "--query-style", "literal_captured_text",
            "--binding", core_id, "--fallback-from-mode", "graph_investigation",
            "--fallback-reason", "cli_fallback_contract", "--json",
        ]
    )
    payload = _json_payload(capsys.readouterr(), home, password)
    assert rc == 0 and payload["status"] == "available"
    assert payload["envelope"]["effective_mode"] == "literal_captured_text"
    assert payload["envelope"]["fallback"] == {
        "caller_selected": True,
        "from_mode": "graph_investigation",
        "to_mode": "literal_captured_text",
        "reason_code": "cli_fallback_contract",
    }


def _partial_companion_json(
    home: Path,
    companion_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli_main(
        [
            "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--query", "TRUNCATABLE_PROSE_PREFIX_MARKER_V1",
            "--query-style", "literal_captured_text", "--binding", companion_id,
            "--path-prefix", "generated/truncatable_prose.md", "--json",
        ]
    )
    payload = _json_payload(capsys.readouterr(), home, password)
    assert rc == 1
    assert payload["status"] == "partial" and payload["capability_state"] == "partial"
    assert payload["scope_complete"] is False
    assert payload["envelope"]["capability_state"] == "partial"
    assert payload["envelope"]["scope_complete"] is False
    assert any(
        omission["reason_code"] == "oversize_projected_file_truncated"
        for omission in payload["envelope"]["omissions"]
    )


def _revoke_and_check_unavailable(
    home: Path,
    core_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dry_rc = cli_main(
        ["ops", "lexical-revoke", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--dry-run"]
    )
    dry_capture = capsys.readouterr()
    _assert_no_fixture_values(dry_capture, home, password)
    assert dry_rc == 0
    assert dry_capture.out.splitlines()[0] == f"lexical-revoke {MIXED_V1_GRAPH_ID}: dry_run"
    assert "purged_chunks:" in dry_capture.out

    revoke_rc = cli_main(
        [
            "ops", "lexical-revoke", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--yes", "--reason", "cli_roundtrip", "--json",
        ]
    )
    revoke_payload = _json_payload(capsys.readouterr(), home, password)
    assert revoke_rc == 0
    assert revoke_payload["status"] == "revoked" and revoke_payload["result"] == "revoked"
    assert revoke_payload["reason"] == "cli_roundtrip"
    assert revoke_payload["revoked_generation_count"] >= 1
    assert revoke_payload["purged_chunk_count"] > 0

    query_rc = cli_main(
        [
            "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--query", "RetrievalExecutionPipeline", "--binding", core_id, "--json",
        ]
    )
    query_payload = _json_payload(capsys.readouterr(), home, password)
    assert query_rc == 1 and query_payload["status"] == "unavailable"
    assert query_payload["envelope"]["unavailable_reason"] == "projection_absent"
    assert query_payload["envelope"]["provenance"]["revocation_reason"] == "cli_roundtrip"


def _assert_cli_pre_io_errors(
    home: Path,
    core_id: str,
    password: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_rc = cli_main(
        [
            "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--authorize-body", "--query", "pipeline", "--binding", core_id,
            "--fallback-from-mode", "graph_investigation",
        ]
    )
    missing_capture = capsys.readouterr()
    _assert_no_fixture_values(missing_capture, home, password)
    assert missing_rc == 1 and missing_capture.out == ""
    assert missing_capture.err.startswith("ERROR:")
    assert "Traceback" not in missing_capture.err
    assert "--fallback-from-mode and --fallback-reason must be supplied together" in missing_capture.err

    conflict_rc = cli_main(
        [
            "ops", "lexical-revoke", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--dry-run", "--yes",
        ]
    )
    conflict_capture = capsys.readouterr()
    _assert_no_fixture_values(conflict_capture, home, password)
    assert conflict_rc == 1 and conflict_capture.out == ""
    assert conflict_capture.err.startswith("ERROR:")
    assert "Traceback" not in conflict_capture.err
    assert "revoke-conflicting-flags" in conflict_capture.err


def test_real_cli_build_query_fallback_tables_and_revoke_roundtrip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prove real build/query/revoke status mapping and bounded CLI serialization."""
    with temporary_postgres() as pg_db:
        home, core_id, companion_id = _public_home(tmp_path, pg_db)
        _build_json(home, core_id, companion_id, pg_db.password, capsys)
        _ranked_table(home, core_id, pg_db.password, capsys)
        _literal_fallback_json(home, core_id, pg_db.password, capsys)
        _partial_companion_json(home, companion_id, pg_db.password, capsys)
        _revoke_and_check_unavailable(home, core_id, pg_db.password, capsys)
        _assert_cli_pre_io_errors(home, core_id, pg_db.password, capsys)
