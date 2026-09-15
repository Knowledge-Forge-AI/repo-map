from pathlib import Path

import pytest

import repomap_kg.coordinator.local_lifecycle as lifecycle
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    maintenance_activity_for_home,
    maintenance_window_for_coordinated_backup,
    maintenance_window_for_database_drop,
    maintenance_window_for_graph_upgrade,
)
from repomap_kg.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    REFRESH_PUBLICATION_ROLE,
)
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError
from repomap_test_support.coordinator_control_fixtures import (
    BareAuthority,
    CaptureConnection,
    OwnedMaintenanceAuthority,
    WindowAuthority,
    WindowEvent,
    statement_text,
)


def _bare_authority(
    connection: CaptureConnection,
    *,
    capability: str = "lifecycle",
) -> BareAuthority:
    return BareAuthority(connection, capability=capability)


def test_control_authority_reads_database_presence_and_rejects_unowned_targets():
    connection = CaptureConnection((True,))
    authority = _bare_authority(connection)
    assert authority.reference_database_exists("repomap_control") is True
    assert statement_text(connection.statements[-1]).startswith("SELECT EXISTS")

    connection.row = (False,)
    assert authority.reference_database_exists("repomap_control_ref_2026") is False
    with pytest.raises(
        CoordinatorControlError,
        match="coordinator_control_database_not_owned",
    ):
        authority.reference_database_exists("foreign_database")


def test_control_authority_connection_uses_capability_specific_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    observed: list[dict[str, object]] = []

    def connect(**kwargs: object) -> object:
        observed.append(kwargs)
        return object()

    monkeypatch.setattr(lifecycle.psycopg, "connect", connect)
    lifecycle_authority = _bare_authority(CaptureConnection())
    assert (
        LocalControlAuthority._connect(
            lifecycle_authority, "repomap_control", autocommit=True
        )
        is not None
    )
    coordinator_authority = _bare_authority(
        CaptureConnection(), capability="coordinator"
    )
    assert (
        LocalControlAuthority._connect(coordinator_authority, "repomap_control")
        is not None
    )
    assert LocalControlAuthority._connect(coordinator_authority, "graph-a") is not None
    with pytest.raises(
        CoordinatorControlError,
        match="coordinator_database_capability_denied",
    ):
        LocalControlAuthority._connect(coordinator_authority, "postgres")
    assert [
        (item["user"], item["dbname"], item["password"], item["autocommit"])
        for item in observed
    ] == [
        ("repomap_owner", "repomap_control", "admin-secret", True),
        (COORDINATOR_CONTROL_ROLE, "repomap_control", "control-secret", False),
        (REFRESH_PUBLICATION_ROLE, "graph-a", "refresh-secret", False),
    ]


def _patch_window_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authority: WindowAuthority,
) -> None:
    monkeypatch.setattr(lifecycle, "resolve_repo_map_home", lambda value: tmp_path)
    monkeypatch.setattr(lifecycle, "LocalControlAuthority", lambda home: authority)


def test_maintenance_wrappers_select_owned_targets_and_release_on_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[WindowEvent] = []
    authority = WindowAuthority(events)
    _patch_window_authority(monkeypatch, tmp_path, authority)

    with maintenance_activity_for_home("/placeholder/home"):
        events.append("activity-owned")
    with maintenance_window_for_graph_upgrade("/placeholder/home", "graph-a"):
        events.append("upgrade-owned")
    with maintenance_window_for_coordinated_backup("/placeholder/home"):
        events.append("backup-owned")
    with maintenance_window_for_database_drop("/placeholder/home", "repomap_control"):
        events.append("drop-control-owned")
    with maintenance_window_for_database_drop("/placeholder/home", "graph-b"):
        events.append("drop-graph-owned")

    assert events == [
        "activity-enter",
        "activity-owned",
        "activity-exit",
        ("window-enter", ("graph-a",)),
        "upgrade-owned",
        ("window-exit", ("graph-a",)),
        ("window-enter", ("graph-a", "graph-b")),
        "backup-owned",
        ("window-exit", ("graph-a", "graph-b")),
        ("window-enter", ("graph-a", "graph-b")),
        "drop-control-owned",
        ("window-exit", ("graph-a", "graph-b")),
        ("window-enter", ("graph-b",)),
        "drop-graph-owned",
        ("window-exit", ("graph-b",)),
    ]


def test_maintenance_wrappers_bound_refusal_and_authority_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = WindowAuthority([], failure=RuntimeError("private"))
    _patch_window_authority(monkeypatch, tmp_path, authority)
    with pytest.raises(MaintenanceUnavailableError):
        with maintenance_window_for_graph_upgrade("/placeholder/home", "foreign"):
            pytest.fail("foreign graph entered maintenance")
    with pytest.raises(MaintenanceUnavailableError):
        with maintenance_window_for_graph_upgrade("/placeholder/home", "graph-a"):
            pytest.fail("failed graph window entered maintenance")
    with pytest.raises(MaintenanceUnavailableError):
        with maintenance_window_for_coordinated_backup("/placeholder/home"):
            pytest.fail("failed backup window entered maintenance")
    with pytest.raises(MaintenanceUnavailableError):
        with maintenance_window_for_database_drop("/placeholder/home", "foreign"):
            pytest.fail("foreign database entered maintenance")


def test_control_authority_maintenance_window_orders_and_validates_graphs():
    events: list[str] = []
    authority = OwnedMaintenanceAuthority(events)
    with authority.maintenance_activity():
        events.append("activity-owned")
    with authority.maintenance_window(
        graph_databases=("graph-b", "graph-a", "graph-a")
    ):
        events.append("window-owned")
    assert events == [
        "activity:control",
        "activity-owned",
        "enter:control",
        "enter:graph-a",
        "enter:graph-b",
        "window-owned",
        "exit:graph-b",
        "exit:graph-a",
        "exit:control",
    ]
    with pytest.raises(MaintenanceUnavailableError, match="not an owned graph"):
        with authority.maintenance_window(graph_databases=("foreign",)):
            pytest.fail("foreign graph entered maintenance")
