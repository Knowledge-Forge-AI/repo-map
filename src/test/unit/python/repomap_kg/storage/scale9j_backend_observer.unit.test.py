from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repomap_kg.storage.backend_observer import (
    MAX_OBSERVER_CONNECTIONS,
    BackendObservationError,
    BackendOwnershipObserver,
)
from repomap_kg.storage.backend_ownership import BackendIdentity


def _identity(pid: int, second: int) -> BackendIdentity:
    return BackendIdentity(
        pid,
        datetime(2026, 7, 15, 0, 1, second, tzinfo=timezone.utc),
    )


def test_observer_registration_is_exact_and_hard_bounded() -> None:
    observer = BackendOwnershipObserver()
    first = _identity(901, 1)
    second = _identity(902, 2)

    observer.register_observer(first)

    assert observer.observer_identities == (first,)
    assert MAX_OBSERVER_CONNECTIONS == 1
    with pytest.raises(BackendObservationError, match="observer limit"):
        observer.register_observer(second)


def test_observer_connection_requires_caller_owned_autocommit() -> None:
    observer = BackendOwnershipObserver()

    with pytest.raises(BackendObservationError, match="observer connection"):
        observer.register_connection(type("Connection", (), {"autocommit": False})())
