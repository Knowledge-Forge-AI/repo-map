from __future__ import annotations



import test_sandbox as sandbox_owner


from pathlib import Path




import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_hosted_test_fixtures import _capacity_boundary as _capacity_boundary, completed, FinishedFollower, finished_follower, report_archive


def test_inner_prerequisites_precede_release_and_logs_are_followed(tmp_path):
    module = sandbox_owner
    calls = []
    follower_calls = []
    outer_id = "d" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="7\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    def follower_factory(command):
        follower_calls.append(command)
        return FinishedFollower()

    assert (
        module.run_in_sandbox(
            ["--suite", "int"],
            repo_root=tmp_path / "repo",
            image_id="sha256:" + "e" * 64,
            runner=fake_runner,
            follower_factory=follower_factory,
            snapshotter=lambda _runner: empty,
            boundary_prover=lambda *_args, **_kwargs: None,
        )
        == 7
    )

    pulls = [
        command
        for command in calls
        if command[:5] == ["docker", "exec", outer_id, "docker", "pull"]
    ]
    assert pulls == [
        ["docker", "exec", outer_id, "docker", "pull", module.TEST_POSTGRES_IMAGE],
        ["docker", "exec", outer_id, "docker", "pull", module.PRODUCTION_POSTGRES_IMAGE],
        ["docker", "exec", outer_id, "docker", "pull", module.ALPINE_PROBE_IMAGE],
        ["docker", "exec", outer_id, "docker", "pull", module.PYTHON_RELEASE_IMAGE],
        ["docker", "exec", outer_id, "docker", "pull", module.GO_RELEASE_IMAGE],
    ]
    release = ["docker", "exec", outer_id, "touch", "/sandbox-scratch/start-tests"]
    assert all(calls.index(command) < calls.index(release) for command in pulls)
    assert not any(command[:2] == ["docker", "pull"] for command in calls)
    assert follower_calls == [["docker", "logs", "--follow", outer_id]]
    assert not any(command[:2] == ["docker", "logs"] for command in calls)



@pytest.mark.parametrize("test_status", [0, 7])
def test_launcher_exports_complete_report_tree_before_exact_outer_removal(
    tmp_path, test_status
):
    module = sandbox_owner
    calls = []
    outer_id = "a" * 64
    host_report = tmp_path / "host-report"
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())
    archive = report_archive(
        {
            "staging/index.html": "report",
            "staging/static/style.css": "style",
        }
    )

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout=f"{test_status}\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    def archive_reader(container_id, required):
        calls.append(["archive", container_id, required])
        assert ["docker", "rm", "-f", "-v", outer_id] not in calls
        return archive

    result = module.run_in_sandbox(
        [
            "--suite",
            "staging",
            "--sandbox",
            "--report",
            "--report-dir",
            str(host_report),
            "--",
            "src/test/int/python/example.int.test.py::test_case[param]",
        ],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "b" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=archive_reader,
    )

    assert result == test_status
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    archive_call = ["archive", outer_id, test_status == 0]
    assert calls.index(archive_call) < calls.index(["docker", "rm", "-f", "-v", outer_id])
    assert (host_report / "staging" / "index.html").read_text(encoding="utf-8") == "report"
    assert (host_report / "staging" / "static" / "style.css").read_text(
        encoding="utf-8"
    ) == "style"
    outer = next(command for command in calls if command[:3] == ["docker", "run", "-d"])
    assert str(host_report) not in outer
    assert str(module.INNER_REPORT_ROOT) in outer
    assert outer[-2:] == [
        "--",
        "src/test/int/python/example.int.test.py::test_case[param]",
    ]



def test_bare_report_injects_fixed_container_report_dir_and_exports(tmp_path):
    module = sandbox_owner
    calls = []
    outer_id = "b" * 64
    repo_root = tmp_path / "repo"
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="0\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    result = module.run_in_sandbox(
        ["--suite", "staging", "--sandbox", "--report"],
        repo_root=repo_root,
        image_id="sha256:" + "c" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=lambda _container_id, _required: report_archive(
            {"staging/index.html": "workspace-report"}
        ),
    )

    assert result == 0
    outer = next(command for command in calls if command[:3] == ["docker", "run", "-d"])
    report_dir_index = outer.index("--report-dir")
    assert outer[report_dir_index + 1] == str(module.INNER_REPORT_ROOT)
    assert "--report" in outer
    assert (repo_root / ".test-reports" / "staging" / "index.html").read_text(
        encoding="utf-8"
    ) == "workspace-report"
