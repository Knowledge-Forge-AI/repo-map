"""Small DB-API fakes for coordinator control-store unit tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Any


class ScriptedCursor(AbstractContextManager["ScriptedCursor"]):
    """Record SQL while returning a caller-supplied fetch/rowcount script."""

    def __init__(
        self,
        *,
        rows: Iterable[Any] = (),
        rowcounts: Iterable[int] = (),
        execute_error: Exception | None = None,
        execute_errors: Iterable[Exception | None] = (),
    ) -> None:
        self.rows = deque(rows)
        self.rowcounts = deque(rowcounts)
        self.execute_error = execute_error
        self.execute_errors = deque(execute_errors)
        self.rowcount = 1
        self.executions: list[tuple[str, object | None]] = []
        self.closed = False
        self.exits: list[tuple[object, ...]] = []
        self.connection: FakeConnection | None = None

    def __enter__(self) -> ScriptedCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True
        self.exits.append(exc_info)
        return None

    def execute(self, statement: str, parameters: object | None = None) -> None:
        self.executions.append((statement, parameters))
        if self.execute_errors:
            err = self.execute_errors.popleft()
            if err is not None:
                raise err
        elif self.execute_error is not None:
            raise self.execute_error
        self.rowcount = self.rowcounts.popleft() if self.rowcounts else 1

    def fetchone(self) -> Any:
        return self.rows.popleft() if self.rows else None

    def fetchall(self) -> list[Any]:
        result = list(self.rows)
        self.rows.clear()
        return result


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, cursor: ScriptedCursor) -> None:
        self.scripted_cursor = cursor
        self.closed = False
        self.exits: list[tuple[object, ...]] = []
        cursor.connection = self

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True
        self.exits.append(exc_info)
        return None

    def cursor(self, **_kwargs: object) -> ScriptedCursor:
        return self.scripted_cursor


def connect_with(cursor: ScriptedCursor):
    """Return a connection factory backed by ``cursor``."""
    return lambda: FakeConnection(cursor)
