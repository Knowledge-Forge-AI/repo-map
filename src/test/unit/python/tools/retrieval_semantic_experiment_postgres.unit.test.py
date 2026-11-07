"""Pure readback contracts for the disposable PostgreSQL experiment adapter."""

from types import SimpleNamespace
from typing import cast

import pytest

from common_lore_index.storage.errors import StorageSchemaError
import repomap_test_support.w5_experiment_postgres as postgres_support


MULTILINE_EXPLAIN = """[
  {
    "Plan": {
      "Node Type": "Result",
      "Plans": []
    },
    "Planning Time": 0.021,
    "Execution Time": 0.004
  }
]
"""


def test_json_array_accepts_multiline_explain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(command, *, input_text):
        calls.append((command, input_text))
        return SimpleNamespace(stdout=MULTILINE_EXPLAIN)

    monkeypatch.setattr(postgres_support, "run_psql", fake_run)
    postgres = cast(
        postgres_support.PostgresHandle,
        SimpleNamespace(psql_command="psql", psql_args=["-d", "fixture"]),
    )

    payload = postgres_support._json_array(
        postgres,
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT 1 AS probe;",
        role="w5_experiment_reader",
        label="hnsw explain",
    )

    assert len(calls) == 1
    assert 'SET ROLE "w5_experiment_reader";' in calls[0][1]
    row = payload[0]
    assert isinstance(row, dict)
    plan = row.get("Plan")
    assert isinstance(plan, dict)
    assert plan.get("Node Type") == "Result"


def test_json_array_preserves_strict_shape_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_support,
        "run_psql",
        lambda _command, *, input_text: SimpleNamespace(stdout="{}\n"),
    )
    postgres = cast(
        postgres_support.PostgresHandle,
        SimpleNamespace(psql_command="psql", psql_args=[]),
    )

    with pytest.raises(StorageSchemaError, match="explain refusal did not return an array"):
        postgres_support._json_array(
            postgres,
            "SELECT '{}'::json;",
            role="w5_experiment_reader",
            label="explain refusal",
        )
