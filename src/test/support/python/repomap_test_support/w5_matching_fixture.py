"""Disposable publisher-backed databases for evaluator matching differentials."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

import psycopg

from common_lore_index.ops.config_local import (
    LocalSqliteConfig, load_graph_registry_config_home, sqlite_graph_database_path,
)
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from retrieval_evaluation_current_observations import query_fenced_current_observations
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult


@dataclass(frozen=True)
class MatchingRow:
    relative_path: str
    text: str
    kind: str = "matching.fixture"
    source_id: str = "matching-fixture"
    path: str = "core/matching-fixture"
    invalid_metadata: bool = False


@dataclass
class MatchingDatabases:
    sqlite_home: Path
    postgres_home: Path
    psql_command: str
    sqlite: sqlite3.Connection
    postgres: Any
    sqlite_run: int
    postgres_run: int
    sqlite_rows: list[tuple[int, dict[str, Any]]]
    postgres_rows: list[tuple[int, dict[str, Any]]]

    def set_rows(self, rows: Sequence[MatchingRow]) -> None:
        """Mutate only selected fixture observations; source publications stay fixed.

        This deliberately tests readback against corrupted/public-safe raw rows.
        It does not create new representative corpus, golds or quality evidence.
        Each backend retains its own real binding revision and snapshot IDs.
        """
        assert len(rows) <= min(len(self.sqlite_rows), len(self.postgres_rows))
        for index, row in enumerate(rows):
            for backend, originals, run_id in (
                ("sqlite", self.sqlite_rows, self.sqlite_run),
                ("postgresql", self.postgres_rows, self.postgres_run),
            ):
                ordinal, original = originals[index]
                metadata = {} if row.invalid_metadata else {
                    **original["metadata"], "source_relative_path": row.relative_path,
                }
                payload = json.dumps({"metadata": metadata, "text": row.text}, ensure_ascii=False)
                values = (row.kind, row.source_id, row.path, payload, run_id, ordinal)
                if backend == "sqlite":
                    self.sqlite.execute(
                        "UPDATE raw_observations SET kind=?, source_id=?, path=?, payload_json=? "
                        "WHERE run_id=? AND ordinal=?", values,
                    )
                else:
                    self.postgres.execute(
                        "UPDATE public.raw_observations SET kind=%s, source_id=%s, path=%s, "
                        "payload_json=%s::jsonb WHERE run_id=%s AND ordinal=%s", values,
                    )
        self.sqlite.commit()
        self.postgres.commit()

    def read(self, backend: str, query: str, **kwargs: Any) -> FencedObservationResult:
        return query_fenced_current_observations(
            self.sqlite_home if backend == "sqlite" else self.postgres_home,
            graph_id=MIXED_V1_GRAPH_ID, query=query, psql_command=self.psql_command,
            selected_binding_ids=(binding_id_for_alias("core"),), **kwargs,
        )


def _core_rows(rows: Sequence[Sequence[Any]]) -> list[tuple[int, dict[str, Any]]]:
    answer = []
    for ordinal, raw in rows:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if payload.get("metadata", {}).get("binding_id") == binding_id_for_alias("core"):
            answer.append((int(ordinal), payload))
    assert len(answer) >= 3
    return answer[:3]


@contextmanager
def matching_databases(root: Path) -> Iterator[MatchingDatabases]:
    working = materialize_mixed_v1_working_copy(root / "working")
    sqlite_home = write_mixed_v1_sqlite_home(root / "sqlite-home", working)
    spub = publish_and_load_sqlite_corpus(sqlite_home)
    config = load_graph_registry_config_home(sqlite_home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(g for g in config.graphs if g.id == MIXED_V1_GRAPH_ID)
    with sqlite3.connect(sqlite_graph_database_path(config, graph)) as sqlite:
        srun = int(spub.accepted_reference.run_id)
        srows = _core_rows(sqlite.execute(
            "SELECT ordinal, payload_json FROM raw_observations WHERE run_id=? ORDER BY ordinal",
            (srun,),
        ).fetchall())
        with temporary_postgres() as pg:
            phome = write_mixed_v1_postgres_home(
                root / "postgres-home", working, host=pg.host, port=pg.port,
                database=pg.database, user=pg.user, password=pg.password,
            )
            ppub = publish_and_load_postgres_corpus(phome, psql_command=pg.psql_command)
            prun = int(ppub.accepted_reference.run_id)
            with psycopg.connect(
                host=pg.host, port=pg.port, dbname=pg.database,
                user=pg.user, password=pg.password,
            ) as connection:
                prows = _core_rows(connection.execute(
                    "SELECT ordinal, payload_json FROM public.raw_observations "
                    "WHERE run_id=%s ORDER BY ordinal", (prun,),
                ).fetchall())
                yield MatchingDatabases(
                    sqlite_home, phome, pg.psql_command, sqlite, connection,
                    srun, prun, srows, prows,
                )
