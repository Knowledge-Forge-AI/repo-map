import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.server.mcp import repomap_canonical_nodes
from repomap_kg.storage import CanonicalNodeRecord


def _node(key: str) -> CanonicalNodeRecord:
    return CanonicalNodeRecord(
        canonical_key=key,
        graph_key_version=1,
        kind="tool",
        display_name=key.removeprefix("tool:"),
        confidence="extracted",
        conflict=False,
        metadata={},
        first_seen_run_id=1,
        last_seen_run_id=1,
    )


def test_arch7a1_cli_json_uses_versioned_bounded_page_envelope() -> None:
    records = (_node("tool:a"), _node("tool:b"), _node("tool:c"))
    stdout = io.StringIO()

    with patch(
        "repomap_kg.cli.query_canonical_node_records",
        return_value=records,
    ) as query:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "storage",
                    "nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--limit",
                    "2",
                    "--offset",
                    "4",
                    "--json",
                ]
            )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload == {
        "diagnostics": [
            {
                "code": "result_truncated",
                "message": "additional results are available",
            }
        ],
        "items": [
            {
                "canonical_key": "tool:a",
                "confidence": "extracted",
                "conflict": False,
                "display_name": "a",
                "first_seen_run_id": 1,
                "graph_key_version": 1,
                "kind": "tool",
                "last_seen_run_id": 1,
                "metadata": {},
            },
            {
                "canonical_key": "tool:b",
                "confidence": "extracted",
                "conflict": False,
                "display_name": "b",
                "first_seen_run_id": 1,
                "graph_key_version": 1,
                "kind": "tool",
                "last_seen_run_id": 1,
                "metadata": {},
            },
        ],
        "page": {
            "limit": 2,
            "next_offset": 6,
            "offset": 4,
            "returned": 2,
            "truncated": True,
        },
        "result_kind": "canonical_nodes",
        "schema_version": 1,
    }
    assert query.call_args.kwargs["limit"] == 3
    assert query.call_args.kwargs["offset"] == 4


def test_arch7a1_cli_table_and_json_share_page_membership() -> None:
    records = (_node("tool:a"), _node("tool:b"), _node("tool:c"))
    stdout = io.StringIO()

    with patch(
        "repomap_kg.cli.query_canonical_node_records",
        return_value=records,
    ):
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "storage",
                    "nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--limit",
                    "2",
                ]
            )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "tool:a" in output
    assert "tool:b" in output
    assert "tool:c" not in output
    assert "page: offset=0 returned=2 limit=2 next_offset=2 truncated=true" in output


def test_arch7a1_cli_rejects_limit_above_public_maximum() -> None:
    stderr = io.StringIO()

    with patch("repomap_kg.cli.query_canonical_node_records") as query:
        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "storage",
                    "nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--limit",
                    "201",
                ]
            )

    assert exit_code == 1
    assert "limit must be between 1 and 200" in stderr.getvalue()
    query.assert_not_called()


def test_arch7a1_cli_retains_bounded_legacy_json_array_alias() -> None:
    records = (_node("tool:a"), _node("tool:b"))
    stdout = io.StringIO()

    with patch(
        "repomap_kg.cli.query_canonical_node_records",
        return_value=records,
    ):
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "storage",
                    "nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--limit",
                    "1",
                    "--legacy-json-array",
                    "--json",
                ]
            )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == [
        {
            "canonical_key": "tool:a",
            "confidence": "extracted",
            "conflict": False,
            "display_name": "a",
            "first_seen_run_id": 1,
            "graph_key_version": 1,
            "kind": "tool",
            "last_seen_run_id": 1,
            "metadata": {},
        }
    ]


def test_arch7a1_mcp_uses_same_page_envelope_and_lookahead() -> None:
    records = (_node("tool:a"), _node("tool:b"), _node("tool:c"))

    with patch(
        "repomap_kg.server.mcp.query_canonical_node_records",
        return_value=records,
    ) as query:
        payload = repomap_canonical_nodes(
            root_path="/tmp/fixture",
            pg_database="postgres",
            limit=2,
            offset=4,
        )

    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    assert payload["result_kind"] == "canonical_nodes"
    assert [item["canonical_key"] for item in payload["items"]] == [
        "tool:a",
        "tool:b",
    ]
    assert payload["page"] == {
        "limit": 2,
        "next_offset": 6,
        "offset": 4,
        "returned": 2,
        "truncated": True,
    }
    assert query.call_args.kwargs["limit"] == 3
    assert query.call_args.kwargs["offset"] == 4
