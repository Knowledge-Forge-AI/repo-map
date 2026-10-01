from repomap_kg.runtime.postgres_route import PostgresRoute
from dataclasses import fields, replace
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from repomap_test_support.executable_authority import approved_psql, search_path_for
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_kg.ops.report_records import OpsRefreshError
from repomap_kg.coordinator.limits import HARD_MAX_LIMITS, CoordinatorLimits
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability, RefreshConfigurationError, RefreshSourceError, ResolvedRefreshAuthority,
    _refresh_attempt_supervision_limits, build_refresh_worker_runner, create_refresh_capability,
    execute_refresh, load_refresh_capability, refresh_terminal, run_refresh_worker,
)


_RUNNER_LIMITS = {"process_deadline_seconds": 600, "refresh_attempt_deadline_seconds": 3600}


def _cfg(root: Path) -> Path:
    p = root / "ops.toml"
    p.write_text("version = 1\n", encoding="utf-8")
    p.chmod(0o600)
    return p


def capability(root: Path, config_path: Path) -> RefreshCapability:
    psql_path = approved_psql(root)
    return RefreshCapability(
        schema_version=1, job_id="job-refresh-1", attempt=1, graph_id="synthetic-refresh",
        config_path=config_path, psql_path=psql_path, postgres_user="repomap_refresh_publication",
        postgres_password="test-only", executable_search_path=search_path_for(psql_path),
        source_generation="sg1:source", config_generation="cg1:config",
        extractor_generation="eg1:extractor", canonicalizer_generation="kg1:canonicalizer",
        coordinator_instance_id="instance-refresh-1", singleton_fencing_epoch=7, graph_lease_fencing_epoch=7,
    )


def _authority(
    root: Path, config_path: Path, psql_path: Path | None = None,
    graph_id: str = "synthetic-refresh", source_generation: str = "sg1:source",
) -> ResolvedRefreshAuthority:
    psql = psql_path or approved_psql(root)
    return ResolvedRefreshAuthority(
        graph_id=graph_id, config_path=config_path, psql_path=psql,
        postgres_user="repomap_refresh_publication", postgres_password="test-only",
        executable_search_path=search_path_for(psql), source_generation=source_generation,
        config_generation="cg1:config", extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )


def _claim(
    instance_id: str | None = None, fencing_epoch: int | None = None,
    graph_lease_fencing_epoch: int | None = None,
) -> SimpleNamespace:
    ns = SimpleNamespace(
        job_id="job-refresh-1", attempt=1, graph_id="synthetic-refresh",
        source_generation="sg1:source", config_generation="cg1:config",
        extractor_generation="eg1:extractor", canonicalizer_generation="kg1:canonicalizer",
    )
    if instance_id is not None:
        ns.instance_id = instance_id
    if fencing_epoch is not None:
        ns.fencing_epoch = fencing_epoch
    if graph_lease_fencing_epoch is not None:
        ns.graph_lease_fencing_epoch = graph_lease_fencing_epoch
    return ns


def test_capability_round_trip_is_private_exact_and_parent_owned(tmp_path: Path) -> None:
    config_path = _cfg(tmp_path)
    path = create_refresh_capability(tmp_path, capability(tmp_path, config_path))
    try:
        assert (path.parent, path.stat().st_mode & 0o777) == (tmp_path, 0o600)
        assert load_refresh_capability(path) == capability(tmp_path, config_path)
    finally:
        path.unlink(missing_ok=True)


def test_capability_round_trip_preserves_safe_psql_wrapper(tmp_path: Path) -> None:
    config_path, wrapper, lexical_psql = _cfg(tmp_path), approved_psql(tmp_path, name="pg_wrapper"), tmp_path / "psql"
    lexical_psql.symlink_to(wrapper)
    target = replace(
        capability(tmp_path, config_path), psql_path=lexical_psql,
        executable_search_path=search_path_for(lexical_psql),
    )
    path = create_refresh_capability(tmp_path, target)
    try:
        assert load_refresh_capability(path) == target
    finally:
        path.unlink(missing_ok=True)


def test_capability_accepts_private_config_home_and_rejects_unsafe_home(tmp_path: Path) -> None:
    config_home = tmp_path / "config-home"
    config_home.mkdir(mode=0o700)
    create_refresh_capability(tmp_path, capability(tmp_path, config_home)).unlink()
    config_home.chmod(0o777)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        create_refresh_capability(tmp_path, capability(tmp_path, config_home))


def test_capability_write_failure_removes_partial_private_file(tmp_path: Path) -> None:
    config_path = _cfg(tmp_path)
    with patch("repomap_kg.coordinator.refresh_adapter.os.write", return_value=0):
        with pytest.raises(ValueError, match="invalid refresh capability"):
            create_refresh_capability(tmp_path, capability(tmp_path, config_path))
    assert not tuple(tmp_path.glob("refresh-*.json"))


@pytest.mark.parametrize("updates", [
    {"attempt": 0}, {"graph_id": "../outside"}, {"source_generation": "wrong"},
    {"config_generation": "wrong"}, {"extractor_generation": "wrong"},
    {"canonicalizer_generation": "wrong"}, {"job_id": "command--unsafe"},
    {"singleton_fencing_epoch": 0}, {"graph_lease_fencing_epoch": 0}, {"coordinator_instance_id": None},
])
def test_capability_rejects_invalid_identity_without_echoing_values(tmp_path: Path, updates: dict[str, object]) -> None:
    values = capability(tmp_path, tmp_path / "ops.toml").__dict__ | updates
    with pytest.raises(ValueError, match="invalid refresh capability") as error:
        RefreshCapability(**values).validate()
    assert str(next(iter(updates.values()))) not in str(error.value)


def test_capability_loader_rejects_unsafe_permissions_and_unknown_fields(tmp_path: Path) -> None:
    config_path = _cfg(tmp_path)
    path = create_refresh_capability(tmp_path, capability(tmp_path, config_path))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        load_refresh_capability(path)


def test_capability_rejects_non_psql_executable_and_world_writable_search_path(tmp_path: Path) -> None:
    config_path = _cfg(tmp_path)
    unsafe_directory = tmp_path / "unsafe-bin"
    unsafe_directory.mkdir(mode=0o777)
    unsafe_directory.chmod(0o777)
    wrong_executable = replace(capability(tmp_path, config_path), psql_path=approved_psql(tmp_path, name="pg-console"))
    with pytest.raises(ValueError, match="invalid refresh capability"):
        wrong_executable.validate()
    unsafe_search = replace(capability(tmp_path, config_path), executable_search_path=(unsafe_directory,))
    with pytest.raises(ValueError, match="invalid refresh capability"):
        create_refresh_capability(tmp_path, unsafe_search)


@pytest.mark.parametrize(("target_mode", "broken"), [(0o644, False), (0o775, False), (0o755, True)])
def test_capability_rejects_unsafe_psql_wrapper_targets(tmp_path: Path, target_mode: int, broken: bool) -> None:
    config_path = _cfg(tmp_path)
    wrapper = tmp_path / "pg_wrapper"
    if not broken:
        wrapper.write_text("synthetic executable", encoding="utf-8")
        wrapper.chmod(target_mode)
    lexical_psql = tmp_path / "psql"
    lexical_psql.symlink_to(wrapper)
    values = capability(tmp_path, config_path).__dict__ | {
        "psql_path": lexical_psql, "executable_search_path": search_path_for(lexical_psql),
    }
    with pytest.raises(ValueError, match="invalid refresh capability"):
        create_refresh_capability(tmp_path, RefreshCapability(**values))


def test_capability_rejects_wrong_lexical_name_and_dot_segments(tmp_path: Path) -> None:
    config_path, wrapper = _cfg(tmp_path), approved_psql(tmp_path, name="pg_wrapper")
    wrong_name = tmp_path / "pg-console"
    wrong_name.symlink_to(wrapper)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        create_refresh_capability(tmp_path, RefreshCapability(**(capability(tmp_path, config_path).__dict__ | {"psql_path": wrong_name, "executable_search_path": search_path_for(wrong_name)})))
    lexical_psql = tmp_path / "psql"
    lexical_psql.symlink_to(wrapper)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        create_refresh_capability(tmp_path, RefreshCapability(**(capability(tmp_path, config_path).__dict__ | {"psql_path": tmp_path / "bin" / ".." / "psql", "executable_search_path": (tmp_path,)})))


def test_successful_refresh_maps_to_committed_protocol_result(tmp_path: Path) -> None:
    target = capability(tmp_path, tmp_path / "ops.toml")
    result = SimpleNamespace(
        result="success", started_at="2026-07-13T12:00:00Z", finished_at="2026-07-13T12:00:01Z",
        files=3, observations=5, run_id=7,
    )
    terminal = refresh_terminal(target, result)
    assert (terminal["message_type"], terminal["status"], terminal["publication_state"],
            terminal["latest_run_identity"], terminal["files"], terminal["observations"]) == ("result", "succeeded", "committed", "run-7", 3, 5)


def test_failed_refresh_never_infers_rollback_or_success(tmp_path: Path) -> None:
    target = capability(tmp_path, tmp_path / "ops.toml")
    result = SimpleNamespace(
        result="failure", started_at="2026-07-13T12:00:00Z", finished_at="2026-07-13T12:00:01Z",
        files=None, observations=None, run_id=None,
    )
    terminal = refresh_terminal(target, result)
    assert (terminal["message_type"], terminal["status"], terminal["publication_state"], terminal["latest_run_identity"]) == (
        "error", "failed", "commit_unknown", None,
    )
    unstarted = SimpleNamespace(result="failure", started_at="2026-07-13T12:00:00Z",
                                finished_at="2026-07-13T12:00:01Z", publication_state="not_started", error_category="worker_crash")
    term = refresh_terminal(target, unstarted)
    assert (term["publication_state"], term["error_category"]) == ("not_started", "worker_crash")


def test_execute_refresh_emits_bounded_system_interruption_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, pause_path = capability(tmp_path, _cfg(tmp_path)), tmp_path / "pause"
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(pause_path))
    with (
        patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_PAUSE_PATH", pause_path),
        patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_READY_PATH", pause_path.with_name("pause.ready")),
        patch("repomap_kg.ops.config.load_ops_config", return_value="loaded-config"),
        patch("repomap_kg.ops.refresh.refresh_graph", return_value="complete"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value="execution-config"),
    ):
        assert execute_refresh(target) == "complete"
    assert pause_path.with_name("pause.ready").read_text(encoding="utf-8") == "job_id=job-refresh-1\nattempt=1\n"


def test_execute_refresh_ignores_unapproved_system_interruption_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, unapproved_path = capability(tmp_path, _cfg(tmp_path)), tmp_path / "unapproved-pause"
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(unapproved_path))
    with (
        patch("repomap_kg.ops.config.load_ops_config", return_value="loaded-config"),
        patch("repomap_kg.ops.refresh.refresh_graph", return_value="complete"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value="execution-config"),
        patch("repomap_kg.coordinator._refresh_execution.time.sleep") as sleep,
    ):
        assert execute_refresh(target) == "complete"
    assert not unapproved_path.with_name("unapproved-pause.ready").exists()
    sleep.assert_not_called()


def test_execute_refresh_does_not_follow_system_marker_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, pause_path, ready_path, victim_path = capability(tmp_path, _cfg(tmp_path)), tmp_path / "pause", tmp_path / "pause.ready", tmp_path / "victim"
    victim_path.write_text("preserved\n", encoding="utf-8")
    ready_path.symlink_to(victim_path)
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(pause_path))
    with (
        patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_PAUSE_PATH", pause_path),
        patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_READY_PATH", ready_path),
        patch("repomap_kg.ops.config.load_ops_config", return_value="loaded-config"),
        patch("repomap_kg.ops.refresh.refresh_graph", return_value="complete"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value="execution-config"),
    ):
        assert execute_refresh(target) == "complete"
    assert victim_path.read_text(encoding="utf-8") == "preserved\n"


def test_execute_refresh_distinguishes_preflight_from_operation_failure(tmp_path: Path) -> None:
    target = capability(tmp_path, _cfg(tmp_path))
    with patch("repomap_kg.ops.config.load_ops_config", side_effect=ValueError("invalid")), pytest.raises(RefreshConfigurationError):
        execute_refresh(target)
    with (patch("repomap_kg.ops.config.load_ops_config", return_value="loaded"), patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")), patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value="projected"), patch("repomap_kg.ops.refresh.refresh_graph", side_effect=OSError("publication state unknown")), pytest.raises(OSError, match="publication state unknown")):
        execute_refresh(target)


@pytest.mark.parametrize("err", [RefreshConfigurationError("multi-source-refresh-unsupported"), OpsRefreshError("multi-source-refresh-unsupported")])
def test_execute_refresh_unsupported_configuration_errors(tmp_path: Path, err: Exception) -> None:
    with (
        patch("repomap_kg.ops.config.load_ops_config", return_value="loaded"),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value="projected"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations", side_effect=err if isinstance(err, RefreshConfigurationError) else None),
        patch("repomap_kg.ops.refresh.refresh_graph", side_effect=err if isinstance(err, OpsRefreshError) else None),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        pytest.raises(RefreshConfigurationError, match="^multi-source-refresh-unsupported$"),
    ):
        execute_refresh(capability(tmp_path, _cfg(tmp_path)))


def test_run_refresh_worker_timeout_trigger_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, safe_dir = capability(tmp_path, _cfg(tmp_path)), tmp_path / "safe"
    safe_dir.mkdir(mode=0o700)
    trigger = safe_dir / "trigger"
    ident, ctx = {"job_id": target.job_id, "attempt": target.attempt}, {"graph_id": target.graph_id, "source_generation": target.source_generation, "config_generation": target.config_generation}
    fake_res = SimpleNamespace(waited=True, process_group_cleaned=True, synthesized_terminal=False, process_timed_out=False,
                               heartbeat_timed_out=False, protocol_error=None, terminal={"status": "succeeded", "publication_state": "committed"})

    def _invoke() -> MagicMock:
        d = tmp_path / f"r{len(tuple(tmp_path.iterdir()))}"
        d.mkdir(mode=0o700)
        cap_file = create_refresh_capability(d, target)
        with patch("repomap_kg.coordinator.refresh_adapter._run_protocol_worker", return_value=fake_res) as m:
            run_refresh_worker(cap_file, ident, _RUNNER_LIMITS, job_context=ctx)
        return m

    monkeypatch.delenv("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER", raising=False)
    m = _invoke()
    assert m.call_args.kwargs["_timeout_probe"] is None and "_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER" not in m.call_args.args[1]
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER", "/tmp/unsafe/trigger")
    assert _invoke().call_args.kwargs["_timeout_probe"] is None
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER", str(trigger))
    probe = _invoke().call_args.kwargs["_timeout_probe"]
    assert callable(probe) and not probe()
    trigger.touch()
    assert probe()


def test_runner_rejects_resolver_graph_identity_mismatch(tmp_path: Path) -> None:
    authority = _authority(tmp_path, tmp_path / "ops.toml", graph_id="synthetic-other")
    runner = build_refresh_worker_runner(lambda _graph_id: authority, tmp_path, _RUNNER_LIMITS)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        runner(_claim(), threading.Event())


def test_runner_rejects_stale_resolved_generation_before_capability_creation(tmp_path: Path) -> None:
    runner = build_refresh_worker_runner(lambda _graph_id: _authority(tmp_path, _cfg(tmp_path), source_generation="sg1:newer"), tmp_path, _RUNNER_LIMITS)
    terminal = runner(_claim(), threading.Event())
    assert (terminal["status"], terminal["publication_state"], terminal["error_category"], terminal["_termination_proved"]) == ("failed", "not_started", "generation_changed", True)
    assert not tuple(tmp_path.glob("refresh-*.json"))


@pytest.mark.parametrize("category", ("source_unavailable", "source_capture"))
def test_runner_preserves_typed_source_failure_before_worker_launch(tmp_path: Path, category: str) -> None:
    runner = build_refresh_worker_runner(lambda _graph_id: (_ for _ in ()).throw(RefreshSourceError(category)), tmp_path, _RUNNER_LIMITS)
    terminal = runner(_claim(), threading.Event())
    assert (terminal["status"], terminal["publication_state"], terminal["error_category"], terminal["_termination_proved"]) == ("failed", "not_started", category, True)
    assert not tuple(tmp_path.glob("refresh-*.json"))


def test_runner_reports_psql_authority_failure_before_worker_launch(tmp_path: Path) -> None:
    psql = tmp_path / "psql"
    psql.write_text("not executable", encoding="utf-8")
    psql.chmod(0o644)
    runner = build_refresh_worker_runner(lambda _graph_id: _authority(tmp_path, _cfg(tmp_path), psql_path=psql), tmp_path, _RUNNER_LIMITS)
    with patch("repomap_kg.coordinator.refresh_adapter.run_refresh_worker") as launch:
        terminal = runner(_claim(instance_id="instance-refresh-1", fencing_epoch=7, graph_lease_fencing_epoch=7), threading.Event())
    assert not launch.called and (terminal["publication_state"], terminal["error_category"], terminal["diagnostics"], terminal["_termination_proved"]) == ("not_started", "configuration", ["psql_authority_invalid"], True)
    assert not tuple(tmp_path.glob("refresh-*.json"))


def test_runner_preserves_distinct_graph_claim_epoch(tmp_path: Path) -> None:
    worker_res = SimpleNamespace(terminal={"status": "succeeded"}, protocol_error=None, process_timed_out=False, heartbeat_timed_out=False, synthesized_terminal=False, waited=True, process_group_cleaned=True)
    runner = build_refresh_worker_runner(lambda _graph_id: _authority(tmp_path, _cfg(tmp_path)), tmp_path, _RUNNER_LIMITS)
    with patch("repomap_kg.coordinator.refresh_adapter.create_refresh_capability", return_value=tmp_path / "capability.json") as create, patch("repomap_kg.coordinator.refresh_adapter.run_refresh_worker", return_value=worker_res):
        runner(_claim(instance_id="instance-refresh-1", fencing_epoch=7, graph_lease_fencing_epoch=101), threading.Event())
    assert (create.call_args.args[1].singleton_fencing_epoch, create.call_args.args[1].graph_lease_fencing_epoch) == (7, 101)


def test_refresh_attempt_supervision_limits_anti_aliasing() -> None:
    res_limits = _refresh_attempt_supervision_limits(CoordinatorLimits(process_deadline_seconds=600, refresh_attempt_deadline_seconds=3600))
    res_dict = _refresh_attempt_supervision_limits({"process_deadline_seconds": 600, "refresh_attempt_deadline_seconds": 2400})
    res_custom = _refresh_attempt_supervision_limits(SimpleNamespace(process_deadline_seconds=500, refresh_attempt_deadline_seconds=1800))
    assert isinstance(res_limits, CoordinatorLimits) and res_limits.process_deadline_seconds == 3600 and isinstance(res_dict, dict) and res_dict["process_deadline_seconds"] == 2400 and getattr(res_custom, "process_deadline_seconds") == 1800
    for bad in ({"process_deadline_seconds": 600}, {"process_deadline_seconds": 600, "refresh_attempt_deadline_seconds": 600},
                SimpleNamespace(process_deadline_seconds=500), SimpleNamespace(process_deadline_seconds=500, refresh_attempt_deadline_seconds=500)):
        with pytest.raises(ValueError):
            _refresh_attempt_supervision_limits(bad)


def test_runner_delivers_leaf_deadline_to_refresh_capability(tmp_path: Path) -> None:
    authority = _authority(tmp_path, _cfg(tmp_path))
    worker_res = SimpleNamespace(terminal={"status": "succeeded"}, protocol_error=None, process_timed_out=False, heartbeat_timed_out=False, synthesized_terminal=False, waited=True, process_group_cleaned=True)
    runner = build_refresh_worker_runner(lambda _graph_id: authority, tmp_path, {"process_deadline_seconds": 450, "refresh_attempt_deadline_seconds": 1800})
    with patch("repomap_kg.coordinator.refresh_adapter.create_refresh_capability", return_value=tmp_path / "capability.json") as create, patch("repomap_kg.coordinator.refresh_adapter.run_refresh_worker", return_value=worker_res):
        runner(_claim(instance_id="instance-refresh-1", fencing_epoch=7, graph_lease_fencing_epoch=101), threading.Event())
    assert create.call_args.args[1].process_deadline_seconds == 450


def test_runner_validates_limits_at_construction(tmp_path: Path) -> None:
    authority = _authority(tmp_path, _cfg(tmp_path))
    for bad, match in ((({"process_deadline_seconds": 500, "refresh_attempt_deadline_seconds": 500}), "refresh_attempt_deadline_seconds must be greater"),
                       ({"process_deadline_seconds": 4000, "refresh_attempt_deadline_seconds": 5000}, "process_deadline_seconds must be a positive integer <= 3600"),
                       ({"refresh_attempt_deadline_seconds": 5000}, "process_deadline_seconds must be a positive integer <= 3600")):
        with pytest.raises(ValueError, match=match):
            build_refresh_worker_runner(lambda _graph_id: authority, tmp_path, bad)


def test_coordinator_test_limits_satisfy_refresh_attempt_supervision(tmp_path: Path) -> None:
    helper = coordinator_test_limits()
    assert getattr(_refresh_attempt_supervision_limits(helper), "process_deadline_seconds") == helper.refresh_attempt_deadline_seconds > helper.process_deadline_seconds == 10
    CoordinatorLimits(**{f.name: getattr(helper, f.name) for f in fields(CoordinatorLimits)}).validate(hard_maxima=HARD_MAX_LIMITS)
    assert (helper.hello_deadline_seconds, helper.cancellation_after_seconds, helper.process_termination_grace_seconds) == (2.0, 1.0, 1.0)
    build_refresh_worker_runner(lambda _graph_id: _authority(tmp_path, _cfg(tmp_path)), tmp_path, helper)
