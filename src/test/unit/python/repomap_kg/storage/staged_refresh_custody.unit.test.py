"""Unit proof for staged-refresh teardown exception custody."""

from __future__ import annotations

import pytest

import common_lore_index.storage.staged_ingestion as staged_ingestion
from common_lore_index.storage._staged_refresh_custody import settle_owned_cleanup
from common_lore_index.storage.publication_phase_witness import (
    PublicationPhase, PublicationPhaseWitness,
)
from src.test.unit.python.repomap_kg.storage.scale8_staged_helpers_fixtures import _authority


class _Prepared:
    files = 0
    row_counts: dict[str, int] = {}

    def __init__(self, close_error: BaseException | None = None) -> None:
        self.closed = 0
        self.close_error = close_error

    def close(self) -> None:
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


class _Connection:
    def __init__(
        self,
        rollback_error: BaseException | None,
        commit_error: BaseException | None = None,
    ) -> None:
        self.rollback_error = rollback_error
        self.commit_error = commit_error
        self.final_transaction_started = False
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append(
            "post-final-commit" if self.final_transaction_started else "commit"
        )
        if self.final_transaction_started and self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.events.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.events.append("close")


def _configure_staged_entry(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
    prepared: _Prepared,
    primary: BaseException | None,
    *,
    mark_error: BaseException | None = None,
) -> tuple[list[bool], list[bool]]:
    restored: list[bool] = []
    failed_marks: list[bool] = []

    def fail_final(_connection: object, _handoff: object, **_kwargs: object) -> None:
        connection.final_transaction_started = True
        if primary is not None:
            raise primary

    def mark_failed(*_args: object, **_kwargs: object) -> None:
        failed_marks.append(True)
        if mark_error is not None:
            raise mark_error

    monkeypatch.setattr(
        staged_ingestion,
        "_resolve_prepared_rows",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        staged_ingestion,
        "_psycopg_connection_params_from_psql_args",
        lambda _args: {},
    )
    monkeypatch.setattr(
        staged_ingestion,
        "open_owned_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        staged_ingestion,
        "close_owned_connection",
        lambda value: value.close(),
    )
    monkeypatch.setattr(
        staged_ingestion,
        "_install_connection_signal_handlers",
        lambda _connection: {},
    )
    monkeypatch.setattr(
        staged_ingestion,
        "_restore_connection_signal_handlers",
        lambda _handlers: restored.append(True),
    )
    monkeypatch.setattr(staged_ingestion, "_ensure_repository", lambda *_args, **_kwargs: 7)
    monkeypatch.setattr(staged_ingestion, "existing_stage_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "_create_run", lambda *_args, **_kwargs: 11)
    monkeypatch.setattr(staged_ingestion, "_create_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "_execute", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "_copy_families", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        staged_ingestion,
        "_refresh_canonical_node_evidence_statistics",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        staged_ingestion,
        "_refresh_canonical_edge_evidence_statistics",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(staged_ingestion, "_mark_prepared", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "mark_validating", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "validate_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(staged_ingestion, "mark_validated", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        staged_ingestion,
        "_run_system_test_publication_pause",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        staged_ingestion,
        "_run_system_test_post_publication_pause",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(staged_ingestion, "execute_final_transaction", fail_final)
    monkeypatch.setattr(staged_ingestion, "mark_failed_before_publication", mark_failed)
    return restored, failed_marks


def _run_staged_failure(
    connection: _Connection,
    witness: PublicationPhaseWitness,
) -> None:
    staged_ingestion._run_staged_full_refresh_admitted(
        ("psql",),
        (),
        repository_name="fixture",
        root_path="fixture-root",
        authority=_authority(),
        stage_id="stage-custody-final-transaction",
        connect=lambda **_kwargs: connection,
        publication_witness=witness,
    )


def test_active_primary_survives_multiple_baseexception_cleanup_faults() -> None:
    primary = KeyboardInterrupt("publication interrupted")
    first_cleanup = SystemExit("prepared close failed")
    second_cleanup = RuntimeError("connection close failed")
    calls: list[str] = []

    def fail_prepared() -> None:
        calls.append("prepared")
        raise first_cleanup

    def fail_connection() -> None:
        calls.append("connection")
        raise second_cleanup

    def finish_remaining_cleanup() -> None:
        calls.append("remaining")

    with pytest.raises(KeyboardInterrupt) as caught:
        try:
            raise primary
        except BaseException as active:
            settle_owned_cleanup(
                active,
                (
                    ("prepared rows close", fail_prepared),
                    ("connection close", fail_connection),
                    ("remaining cleanup", finish_remaining_cleanup),
                ),
            )
            raise

    assert caught.value is primary
    assert calls == ["prepared", "connection", "remaining"]
    assert any("prepared rows close" in note for note in primary.__notes__)
    assert any("connection close" in note for note in primary.__notes__)


def test_cleanup_only_fault_is_observable_after_all_callbacks_run() -> None:
    first_cleanup = RuntimeError("prepared close failed")
    second_cleanup = SystemExit("connection close failed")
    calls: list[str] = []

    def fail_prepared() -> None:
        calls.append("prepared")
        raise first_cleanup

    def fail_connection() -> None:
        calls.append("connection")
        raise second_cleanup

    with pytest.raises(RuntimeError) as caught:
        settle_owned_cleanup(
            None,
            (
                ("prepared rows close", fail_prepared),
                ("connection close", fail_connection),
            ),
        )

    assert caught.value is first_cleanup
    assert calls == ["prepared", "connection"]
    assert any("connection close" in note for note in first_cleanup.__notes__)


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_failed_rollback_preserves_primary_and_skips_failed_mark_and_commit(
    monkeypatch: pytest.MonkeyPatch,
    primary_type: type[BaseException],
) -> None:
    primary = primary_type("final transaction failed")
    connection = _Connection(RuntimeError("rollback failed"))
    prepared = _Prepared()
    witness = PublicationPhaseWitness()
    restored, failed_marks = _configure_staged_entry(
        monkeypatch, connection, prepared, primary
    )

    with pytest.raises(primary_type) as caught:
        _run_staged_failure(connection, witness)

    assert caught.value is primary
    assert failed_marks == []
    assert "post-final-commit" not in connection.events
    rollback_index = connection.events.index("rollback")
    assert connection.events[rollback_index:] == ["rollback", "close"]
    assert prepared.closed == 1
    assert restored == [True]
    assert witness.phase is PublicationPhase.FINAL_TRANSACTION


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_failed_stage_mark_preserves_primary_and_skips_followup_commit(
    monkeypatch: pytest.MonkeyPatch,
    primary_type: type[BaseException],
) -> None:
    primary = primary_type("final transaction failed")
    connection = _Connection(None)
    prepared = _Prepared()
    witness = PublicationPhaseWitness()
    restored, failed_marks = _configure_staged_entry(
        monkeypatch,
        connection,
        prepared,
        primary,
        mark_error=RuntimeError("failed-stage mark failed"),
    )

    with pytest.raises(primary_type) as caught:
        _run_staged_failure(connection, witness)

    assert caught.value is primary
    assert failed_marks == [True]
    assert "post-final-commit" not in connection.events
    rollback_index = connection.events.index("rollback")
    assert connection.events[rollback_index:] == ["rollback", "close"]
    assert prepared.closed == 1
    assert restored == [True]
    assert witness.phase is PublicationPhase.ROLLED_BACK


def test_cleanup_only_fault_is_observable_after_reconciled_commit_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_fault = RuntimeError("prepared close failed after reconciliation")
    connection = _Connection(None, commit_error=RuntimeError("commit uncertain"))
    prepared = _Prepared(close_error=cleanup_fault)
    witness = PublicationPhaseWitness()
    restored, failed_marks = _configure_staged_entry(
        monkeypatch, connection, prepared, None
    )

    def complete_final_transaction(
        _connection: object, _handoff: object, **_kwargs: object
    ) -> None:
        connection.final_transaction_started = True

    monkeypatch.setattr(
        staged_ingestion, "execute_final_transaction", complete_final_transaction
    )
    monkeypatch.setattr(
        staged_ingestion, "reconcile_commit_unknown", lambda *_args, **_kwargs: True
    )

    with pytest.raises(RuntimeError) as caught:
        _run_staged_failure(connection, witness)

    assert caught.value is cleanup_fault
    assert failed_marks == []
    assert restored  # The final empty-handler restore is an intentional no-op.
    assert prepared.closed == 1
    assert witness.phase is PublicationPhase.RECONCILING
