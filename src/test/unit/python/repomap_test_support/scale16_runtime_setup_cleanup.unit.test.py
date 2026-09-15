"""Setup failure preserves startup cleanup and exact child settlement."""
from pathlib import Path
from types import SimpleNamespace
import pytest
import repomap_test_support.scale15_runtime_campaign as runtime_campaign
from actual_refresh_startup import ActualRefreshStartup, StartupState
from repomap_kg.runtime.plan import default_local_runtime_plan
from repomap_kg.storage.authority import PublicationGenerations
from repomap_test_support.scale15_runtime_environment import Scale15RuntimeFixture
from scale14_supervisor_contracts import ProtectedLaunchLimits
from scale15_terminal_contracts import ExpectedRefreshAuthority


class _Fixture(Scale15RuntimeFixture):
    def psql_args(self, graph_id: str) -> tuple[str, ...]:
        return ("public-safe",)


def test_supervised_refresh_setup_failure_closes_gate_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    startup = ActualRefreshStartup.create()

    class _Process:
        pid = 1

        def __init__(self):
            self.killed = False
            self.waited = False

        def poll(self):
            return -9 if self.killed else None

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            del timeout
            self.waited = True
            return -9

    process = _Process()
    fixture = _Fixture(
        home=tmp_path, repository=tmp_path, config_path=tmp_path / "config.toml",
        plan=default_local_runtime_plan(tmp_path), password="public-safe",
        graph_ids=("public-graph",), proxy_container="public-proxy",
    )
    expected = ExpectedRefreshAuthority(
        repository_identity="repo1:public-fixture", repository_name="public-fixture",
        generations=PublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer",
        ),
        execution_mode="direct", zero_state_first_publication=True,
        expected_family_counts={},
    )
    storage = SimpleNamespace(capture_baseline=lambda: object())
    monkeypatch.setattr(runtime_campaign, "_wait_fresh_backend", lambda _args: None)
    monkeypatch.setattr(
        runtime_campaign,
        "PostgresStorageAuthority",
        lambda _plan: object(),
    )
    monkeypatch.setattr(
        runtime_campaign,
        "AsyncPostgresStorageAuthority",
        lambda _storage, **_kwargs: storage,
    )
    monkeypatch.setattr(
        runtime_campaign.ActualRefreshStartup,
        "create",
        lambda: startup,
    )
    monkeypatch.setattr(
        runtime_campaign,
        "_refresh_argv",
        lambda *_args: ("public",),
    )

    def start_child(*_args, startup, **_kwargs):
        startup.child_started()
        return process

    monkeypatch.setattr(runtime_campaign, "start_actual_refresh_child", start_child)
    monkeypatch.setattr(
        runtime_campaign,
        "_psycopg_connection_params_from_psql_args",
        lambda _args: {},
    )
    monkeypatch.setattr(
        runtime_campaign,
        "BackendOwnershipMonitor",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("setup failed")),
    )

    try:
        with pytest.raises(RuntimeError, match="setup failed"):
            runtime_campaign.run_supervised_refresh(
                fixture,
                "public-graph",
                expected,
                cancel_code=None,
                limits=ProtectedLaunchLimits(),
            )

        assert startup.state is StartupState.CLOSED
        assert process.killed is True
        assert process.waited is True
    finally:
        startup.close()

