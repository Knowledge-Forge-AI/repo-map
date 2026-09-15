from __future__ import annotations

import json

import scale7_measure_ingestion as scale7_measure_ingestion


def _tool():
    return scale7_measure_ingestion


def test_scale7_probe_is_public_safe_and_staged_only() -> None:
    tool = _tool()
    result = tool.measure_size(2)

    staged = result["staged"]
    assert "current" not in result
    assert staged["mode"] == "copy_set_based_merge"
    assert all(staged["family_rows"][family] > 0 for family in tool.FAMILIES)
    assert staged["statement_count"] > 0
    assert staged["server_statement_count"] >= staged["statement_count"]
    assert staged["normalized_bytes"] > 0
    assert staged["postgres_stats"]["wal_bytes"] > 0

    serialized = json.dumps(result, sort_keys=True)
    for forbidden in ("synthetic-root", "scale7-fixture", "raw_sql", "psql_args"):
        assert forbidden not in serialized
