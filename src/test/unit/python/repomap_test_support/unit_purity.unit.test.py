from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

import repomap_test_support.postgres_harness as postgres_harness
from repomap_test_support.postgres_harness import (
    active_or_new_postgres_session,
)
from repomap_test_support.postgres_container import PostgresContainerSession
from repomap_test_support.unit_purity import (
    ENV_UNIT_PURITY_GUARD,
    UnitPurityState,
)


def test_unit_purity_guard_refuses_new_live_postgres(monkeypatch):
    monkeypatch.setattr(postgres_harness, "_ACTIVE_POSTGRES_SESSION", None)
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "1")

    with pytest.raises(RuntimeError, match="canonical unit purity"):
        active_or_new_postgres_session()


def test_unit_purity_guard_preserves_injected_postgres_double(monkeypatch):
    fake_session = Mock()
    monkeypatch.setattr(postgres_harness, "_ACTIVE_POSTGRES_SESSION", fake_session)
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "1")
    session, context = active_or_new_postgres_session()

    assert session is fake_session
    assert context is None


def test_unit_purity_guard_refuses_active_live_postgres(monkeypatch):
    live_session = object.__new__(PostgresContainerSession)
    monkeypatch.setattr(postgres_harness, "_ACTIVE_POSTGRES_SESSION", live_session)
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "1")
    with pytest.raises(RuntimeError, match="active Postgres container"):
        active_or_new_postgres_session()


def test_unit_purity_seams_restore_prior_session_sentinel():
    prior = postgres_harness._ACTIVE_POSTGRES_SESSION
    sentinel = Mock()
    with pytest.MonkeyPatch.context() as outer_mp:
        outer_mp.setattr(postgres_harness, "_ACTIVE_POSTGRES_SESSION", sentinel)
        for test_fn in (
            test_unit_purity_guard_refuses_new_live_postgres,
            test_unit_purity_guard_preserves_injected_postgres_double,
            test_unit_purity_guard_refuses_active_live_postgres,
        ):
            with pytest.MonkeyPatch.context() as inner_mp:
                test_fn(inner_mp)
            assert postgres_harness._ACTIVE_POSTGRES_SESSION is sentinel

    assert postgres_harness._ACTIVE_POSTGRES_SESSION is prior


def test_simulated_combined_unit_int_ordering_preserves_active_session():
    prior = postgres_harness._ACTIVE_POSTGRES_SESSION
    session_owner = Mock(spec=PostgresContainerSession)
    session_owner.database = Mock(return_value="db_handle")

    with pytest.MonkeyPatch.context() as outer_mp:
        outer_mp.setattr(postgres_harness, "_ACTIVE_POSTGRES_SESSION", session_owner)
        outer_mp.setenv(ENV_UNIT_PURITY_GUARD, "1")

        for test_fn in (
            test_unit_purity_guard_refuses_new_live_postgres,
            test_unit_purity_guard_preserves_injected_postgres_double,
            test_unit_purity_guard_refuses_active_live_postgres,
        ):
            with pytest.MonkeyPatch.context() as inner_mp:
                test_fn(inner_mp)
            assert postgres_harness._ACTIVE_POSTGRES_SESSION is session_owner

        assert postgres_harness._ACTIVE_POSTGRES_SESSION is session_owner

        with pytest.MonkeyPatch.context() as int_mp:
            int_mp.delenv(ENV_UNIT_PURITY_GUARD, raising=False)
            session, context = active_or_new_postgres_session()
            assert session is session_owner
            assert context is None

    assert postgres_harness._ACTIVE_POSTGRES_SESSION is prior


def test_unit_purity_state_restores_prior_environment(monkeypatch):
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "prior")
    state = UnitPurityState()

    state.activate(unit_item=True)
    previous = state._previous
    assert previous == "prior"
    state.restore()

    assert state._installed is False
    assert state._previous is None
    assert os.environ["REPOMAP_UNIT_PURITY_GUARD"] == "prior"


def test_unit_purity_state_clears_non_unit_marker(monkeypatch):
    monkeypatch.setenv("REPOMAP_UNIT_PURITY_GUARD", "1")
    state = UnitPurityState()

    state.activate(unit_item=False)
    assert "REPOMAP_UNIT_PURITY_GUARD" not in os.environ
    state.restore()

    assert state._installed is False
    assert os.environ["REPOMAP_UNIT_PURITY_GUARD"] == "1"
