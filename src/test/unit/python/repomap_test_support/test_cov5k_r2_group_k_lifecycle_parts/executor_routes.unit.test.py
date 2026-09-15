from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import subprocess
import pytest
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.test_cov5k_r2_group_k_container import execute_group_k_docker
from contextlib import contextmanager
from repomap_test_support.test_cov5k_r2_fix1_catalog import _group_k
from repomap_test_support.test_cov5k_r2_fix1_executors import _execution_receipt_digest, execute_group_k

from src.test.unit.python.repomap_test_support.test_cov5k_r2_group_k_lifecycle_parts.fixtures import FakeContainer, FakeDockerClient, _make_resource_run, _make_entry

def test_group_k_setup_timeout_cleans_up_owned_container_and_preserves_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    cid = "timeout-container-id-77778888"
    name = "repomap-fix1-k09-timeout"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    timeout_container = FakeContainer(cid, expected_labels)

    def timeout_setup(*a: Any, **kw: Any) -> Any:
        fake_client.containers.register(name, timeout_container)
        raise subprocess.TimeoutExpired(["docker", "create"], 10)

    monkeypatch.setattr("docker.from_env", lambda: fake_client)
    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup",
        timeout_setup,
    )

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(subprocess.TimeoutExpired):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert timeout_container.removed is True
    assert fake_client.closed is True


def test_group_k_cleanup_error_surfaces_secondary_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    cid = "cleanup-fail-id-88889999"
    name = "repomap-fix1-k09-cleanfail"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    failing_container = FakeContainer(
        cid,
        expected_labels,
        remove_error=RuntimeError("engine communication error during remove"),
    )

    def failing_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, failing_container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr("docker.from_env", lambda: fake_client)
    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup",
        failing_setup,
    )

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(Exception, match="exact Docker cleanup failed"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
            runner=lambda cmd, cwd, env: subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr=""),
        )

    assert fake_client.closed is True


def test_group_k_client_closed_on_every_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def fatal_setup(*a: Any, **kw: Any) -> Any:
        raise KeyboardInterrupt("simulated operator interrupt")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", fatal_setup)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(KeyboardInterrupt):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name="repomap-fix1-k09-interrupt",
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert fake_client.closed is True


@pytest.mark.parametrize(
    "condition_id",
    [f"K{i:02d}" for i in range(1, 13)],
)
def test_group_k_outer_executor_all_routes_parameterized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    condition_id: str,
) -> None:
    entry = next(item for item in _group_k() if item.condition_id == condition_id)
    raw_shape = dict(entry.parameter_values)["rehearsal_argv_shape"]
    assert isinstance(raw_shape, tuple)
    shape: tuple[str, ...] = tuple(str(x) for x in raw_shape)

    run_k_calls: list[dict[str, Any]] = []

    def fake_run_k(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        run_k_calls.append({"cmd": list(cmd), "cwd": cwd, "env": dict(env)})
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_fix1_executors._run_k", fake_run_k)

    @contextmanager
    def fake_database():
        yield None, SimpleNamespace(
            host="127.0.0.1", port=5432, user="test_user", database="test_db", password="test_pw"
        )

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_fix1_executors._database", fake_database)

    ephemeral_called = False

    def fake_ephemeral(repo_root: Path):
        nonlocal ephemeral_called
        ephemeral_called = True
        return shape, subprocess.CompletedProcess(list(shape), 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_fix1_executors.execute_group_k_ephemeral", fake_ephemeral)

    docker_called = False

    def fake_docker(**kw: Any):
        nonlocal docker_called
        docker_called = True
        s = kw["shape"]
        return s, subprocess.CompletedProcess(list(s), 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_fix1_executors.execute_group_k_docker", fake_docker)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_fix1_executors._free_loopback_port", lambda: 54321)
    monkeypatch.setattr("shutil.which", lambda name: f"/mock/bin/{name}")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    temp_root = tmp_path / "scratch"
    temp_root.mkdir()

    result = execute_group_k(repo_root, temp_root, entry)
    obs = dict(result)

    assert obs["execution_disposition"] == "bounded_operation_completed"
    assert obs["returncode"] == 0
    assert obs["cleanup_disposition"] == "disposable_resource_settled"
    assert obs["disposable_resource_owned"] is True
    assert obs["argv"] == obs["effective_argv"]

    argv = obs["argv"]
    assert isinstance(argv, tuple)

    expected_digest = _execution_receipt_digest(
        effective_argv=argv,
        returncode=0,
        execution_disposition="bounded_operation_completed",
        shell=False,
        timeout_seconds=10,
    )
    assert obs["argv_execution_digest"] == expected_digest

    case_root = temp_root / condition_id
    assert not case_root.exists(), "case_root must be cleaned up"

    if condition_id in {"K01", "K02", "K03", "K04", "K05"}:
        assert argv == shape
        assert len(run_k_calls) == 1
        call_env = run_k_calls[0]["env"]
        assert isinstance(call_env, dict)
        assert run_k_calls[0]["cwd"] == case_root
        assert "REPOMAP_HOME" in call_env
        assert str(case_root) in call_env["REPOMAP_HOME"]
        assert "PGPASSWORD" not in call_env
    elif condition_id == "K06":
        assert argv[0] == "psql"
        assert argv[4] == "{port}"
        assert argv[-1] == "rows.sql"
        assert len(run_k_calls) == 1
        call_env = run_k_calls[0]["env"]
        assert isinstance(call_env, dict)
        assert run_k_calls[0]["cwd"] == case_root
        assert "PGPASSWORD" in call_env
        assert call_env["PGPASSWORD"] == "test_pw"
    elif condition_id == "K07":
        assert argv == shape
        assert ephemeral_called is True
        assert len(run_k_calls) == 0
    elif condition_id in {"K08", "K09", "K10", "K12"}:
        assert argv == shape
        assert docker_called is True
        assert len(run_k_calls) == 0
    elif condition_id == "K11":
        assert argv[0] == "{python}"
        assert "{port}" in argv
        assert len(run_k_calls) == 1
        call_cmd = run_k_calls[0]["cmd"]
        assert isinstance(call_cmd, list)
        assert run_k_calls[0]["cwd"] == repo_root
        assert "54321" in call_cmd


def test_group_k_combined_operation_failure_plus_cleanup_failure_preserves_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    cid = "comb-fail-id-11112222"
    name = "repomap-fix1-k09-combfail"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    failing_container = FakeContainer(
        cid,
        expected_labels,
        remove_error=RuntimeError("simulated cleanup removal failure"),
    )

    def ok_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, failing_container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr("docker.from_env", lambda: fake_client)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", ok_setup)

    def failing_runner(cmd: list[str], cwd: Path, env: dict[str, str]) -> Any:
        raise RuntimeError("primary operation crashed")

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="primary operation crashed") as excinfo:
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
            runner=failing_runner,
        )

    assert excinfo.value.__context__ is not None
    context_chain = []
    seen: set[int] = set()
    curr: BaseException | None = excinfo.value.__context__
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        context_chain.append(str(curr))
        curr = curr.__cause__ or curr.__context__
    assert any("simulated cleanup removal failure" in msg for msg in context_chain)
    assert fake_client.closed is True
