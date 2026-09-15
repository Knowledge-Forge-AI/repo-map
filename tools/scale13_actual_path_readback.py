"""Public-safe semantic readback for SCALE13 disposable actual-path proofs."""

from __future__ import annotations

from typing import Sequence

import psycopg

from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from semantic_digest_readback import read_semantic_digest
from scale15_terminal_contracts import FINAL_FAMILY_CODES


class Scale13ReadbackError(RuntimeError):
    """Raised when SCALE13 readback fails to find expected database state."""

    def __init__(
        self,
        message: str,
        *,
        role: str = "scale13_actual_path_readback",
        phase: str = "readback",
        return_classification: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
    ) -> None:
        super().__init__(message)
        self.role, self.phase = role, phase
        self.return_classification = return_classification
        self.expected, self.observed = expected, observed
        self.add_note(str(self.structural_evidence()))

    def structural_evidence(self) -> dict[str, str | None]:
        return {
            "role": self.role,
            "phase": self.phase,
            "return_classification": self.return_classification,
            "expected": self.expected,
            "observed": self.observed,
        }


def read_actual_path_state(psql_args: Sequence[str]) -> dict[str, object]:
    """Return stable seven-family, receipt, generation, and cleanup evidence."""

    params = _psycopg_connection_params_from_psql_args(psql_args)
    with psycopg.connect(
        host=params.get("host"), port=params.get("port"),
        user=params.get("user"), dbname=params.get("dbname"),
    ) as connection:
        repo_row = connection.execute(
            "SELECT id FROM repositories WHERE name = %s",
            ("public-fixture",),
        ).fetchone()
        if repo_row is None:
            raise Scale13ReadbackError(
                "Repository 'public-fixture' not found",
                role="scale13_actual_path_readback",
                phase="readback_repository",
                expected="repository_row_present",
                observed="repository_row_missing",
            )
        repository_id = int(repo_row[0])
        run = connection.execute(
            "SELECT id, status, source_generation, config_generation, "
            "extractor_generation, canonicalizer_generation "
            "FROM runs WHERE repository_id = %s ORDER BY id DESC LIMIT 1",
            (repository_id,),
        ).fetchone()
        if run is None:
            raise Scale13ReadbackError(
                f"No runs found for repository {repository_id}",
                role="scale13_actual_path_readback",
                phase="readback_run",
                expected="run_row_present",
                observed="run_row_missing",
            )
        run_id = int(run[0])
        counts, digest = read_semantic_digest(connection, repository_id, run_id)
        counts = {family: counts[family] for family in FINAL_FAMILY_CODES}
        stages = connection.execute(
            "SELECT state, merge_status, publication_reconciliation_state, "
            "cleanup_eligibility FROM ingestion_stages "
            "WHERE repository_id = %s ORDER BY created_at, stage_id",
            (repository_id,),
        ).fetchall()
        backend_row = connection.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ).fetchone()
        if backend_row is None:
            raise Scale13ReadbackError(
                "Failed to query pg_stat_activity",
                role="scale13_actual_path_readback",
                phase="readback_backend",
                expected="backend_activity_row",
                observed="backend_activity_missing",
            )
        other_backends = int(backend_row[0])
    return {
        "receipt_complete": run[1] == "complete" and all(run[2:6]),
        "generations": list(run[2:6]),
        "family_counts": counts,
        "structural_digest": digest,
        "cleanup_complete": all(
            stage == ("published", "committed", "reconciled", "eligible")
            for stage in stages
        ),
        "backend_quiescent": other_backends == 0,
    }
