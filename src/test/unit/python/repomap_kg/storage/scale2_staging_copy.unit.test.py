from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest

from repomap_kg.storage.staging_copy import (
    STAGING_COPY_TABLES,
    CopyContractError,
    CopyTransferResult,
    StagingCopyTable,
    copy_stage_rows,
)


def stage_file_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "stage_id": "stage-001",
        "family_ordinal": 0,
        "path": "fixture/readme.md",
        "language": "markdown",
        "role": "documentation",
        "confidence": "extracted",
        "content_hash": None,
        "executable": False,
        "generated": False,
        "metadata_json": {"title": "fixture"},
    }
    row.update(overrides)
    return row


class FakeCopy:
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []
        self.exit_exception: BaseException | None = None

    def __enter__(self) -> "FakeCopy":
        return self

    def __exit__(self, _type: object, value: BaseException | None, _traceback: object) -> None:
        self.exit_exception = value

    def write_row(self, row: tuple[object, ...]) -> None:
        self.rows.append(row)


class FakeCursor:
    def __init__(self) -> None:
        self.copy_operation = FakeCopy()
        self.statement: object | None = None
        self.exit_exception: BaseException | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, _type: object, value: BaseException | None, _traceback: object) -> None:
        self.exit_exception = value

    def copy(self, statement: object) -> FakeCopy:
        self.statement = statement
        return self.copy_operation


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commit_calls = 0
        self.rollback_calls = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_catalog_covers_only_the_seven_active_stage_families() -> None:
    assert set(STAGING_COPY_TABLES) == {
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    }
    assert all(table.table_name.startswith("stage_") for table in STAGING_COPY_TABLES.values())
    assert all("stage_id" in table.columns for table in STAGING_COPY_TABLES.values())
    assert all("files" != table.table_name for table in STAGING_COPY_TABLES.values())


def test_catalog_rejects_unlisted_staging_targets() -> None:
    with pytest.raises(CopyContractError):
        StagingCopyTable(
            family="files",
            table_name="stage_custom",
            ordinal_column="family_ordinal",
            column_types={"stage_id": "text", "family_ordinal": "integer"},
        )


def test_row_adaptation_has_closed_column_order_and_jsonb_wrapping() -> None:
    table = STAGING_COPY_TABLES["files"]
    adapted = table.adapt_row(stage_file_row(), expected_stage_id="stage-001")

    assert len(adapted) == len(table.columns)
    assert adapted[:6] == (
        "stage-001",
        0,
        "fixture/readme.md",
        "markdown",
        "documentation",
        "extracted",
    )
    assert adapted[6] is None
    assert adapted[7:9] == (False, False)
    assert getattr(adapted[9], "obj", None) == {"title": "fixture"}


@pytest.mark.parametrize(
    "row",
    [
        stage_file_row(stage_id="stage-002"),
        stage_file_row(family_ordinal=True),
        stage_file_row(family_ordinal=-1),
        stage_file_row(path=42),
        {"stage_id": "stage-001"},
        {**stage_file_row(), "unexpected": "value"},
    ],
)
def test_row_adaptation_rejects_ownership_and_type_errors(
    row: Mapping[str, object],
) -> None:
    with pytest.raises(CopyContractError):
        STAGING_COPY_TABLES["files"].adapt_row(row, expected_stage_id="stage-001")


def test_copy_transport_streams_rows_without_owning_transaction() -> None:
    connection = FakeConnection()
    result = copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["files"],
        (stage_file_row(), stage_file_row(family_ordinal=1)),
        expected_stage_id="stage-001",
    )

    assert result == CopyTransferResult(family="files", row_count=2)
    assert len(connection.cursor_instance.copy_operation.rows) == 2
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    assert connection.cursor_instance.copy_operation.exit_exception is None


def test_copy_transport_propagates_source_failure_and_does_not_rollback() -> None:
    connection = FakeConnection()

    def rows() -> Iterable[Mapping[str, object]]:
        yield stage_file_row()
        raise RuntimeError("synthetic cancellation")

    with pytest.raises(RuntimeError, match="synthetic cancellation"):
        copy_stage_rows(
            connection,
            STAGING_COPY_TABLES["files"],
            rows(),
            expected_stage_id="stage-001",
        )

    assert len(connection.cursor_instance.copy_operation.rows) == 1
    assert connection.cursor_instance.copy_operation.exit_exception is not None
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0


@pytest.mark.parametrize("invalid_json", [
    {"nested": [float("nan")]},
    {"nested": [float("inf")]},
    {"nested": [{1: "non-string key"}]},
    {"nested": [object()]},
])
def test_copy_rejects_nested_json_after_partial_transfer_without_transaction_ownership(
    invalid_json: object,
) -> None:
    connection = FakeConnection()
    cursor = connection.cursor_instance
    table = STAGING_COPY_TABLES["files"]
    with pytest.raises(CopyContractError, match="staging COPY JSON value is invalid") as caught:
        copy_stage_rows(
            connection, table,
            (stage_file_row(), stage_file_row(family_ordinal=1, metadata_json=invalid_json)),
            expected_stage_id="stage-001",
        )
    assert len(cursor.copy_operation.rows) == 1
    assert cursor.copy_operation.rows[0][table.columns.index("path")] == "fixture/readme.md"
    assert cursor.copy_operation.exit_exception is caught.value
    assert cursor.exit_exception is caught.value
    assert connection.commit_calls == connection.rollback_calls == 0


def test_copy_adapts_nested_json_without_changing_caller_rows() -> None:
    metadata = {"nested": [None, True, 1, 1.25, ("value", {"key": "text"})]}
    row = stage_file_row(metadata_json=metadata)
    connection = FakeConnection()
    result = copy_stage_rows(
        connection, STAGING_COPY_TABLES["files"], (row,), expected_stage_id="stage-001",
    )
    adapted = connection.cursor_instance.copy_operation.rows[0]
    assert getattr(adapted[-1], "obj") == metadata
    assert row["metadata_json"] is metadata
    assert metadata == {"nested": [None, True, 1, 1.25, ("value", {"key": "text"})]}
    assert result.row_count == 1
    assert connection.commit_calls == connection.rollback_calls == 0


def test_copy_rejects_uncatalogued_table_before_acquiring_cursor() -> None:
    from dataclasses import replace

    connection = FakeConnection()
    uncatalogued = replace(STAGING_COPY_TABLES["files"])
    with pytest.raises(CopyContractError, match="staging COPY table is invalid"):
        copy_stage_rows(connection, uncatalogued, (), expected_stage_id="stage-001")
    assert connection.cursor_instance.statement is None
    assert connection.cursor_instance.copy_operation.rows == []
    assert connection.commit_calls == connection.rollback_calls == 0
