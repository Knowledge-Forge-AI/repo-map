import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from repomap_kg.coordinator._control_schema import discover_control_migrations
from repomap_kg.storage import discover_migrations


REPO_ROOT = Path(__file__).resolve().parents[6]


def test_wheel_contains_complete_graph_and_control_migration_catalogs(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("setuptools build backend is unavailable")
    from runner_coverage_execution import prepare_child_coverage_environment
    from runner_coverage_observer import launch_observed_process

    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()
    pip_env = prepare_child_coverage_environment(os.environ, family="arch7f_pip")
    wheel_build = launch_observed_process(
        (
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_directory),
            str(REPO_ROOT),
        ),
        family="arch7f_pip",
        env=pip_env,
    )
    assert wheel_build.returncode == 0, wheel_build.stderr[-2_000:]
    wheel = next(wheel_directory.glob("repomap_kg-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    graph_resources = tuple(
        path.relative_to(REPO_ROOT / "src/main/resources").as_posix()
        for path in sorted((REPO_ROOT / "src/main/resources/rdbms").rglob("*"))
        if path.is_file()
    )
    control_resources = tuple(
        path.relative_to(REPO_ROOT / "src/main/resources").as_posix()
        for path in sorted(
            (REPO_ROOT / "src/main/resources/coordinator-rdbms").rglob("*")
        )
        if path.is_file()
    )
    installed_data = {
        name.split(".data/data/share/repomap-kg/", 1)[1]
        for name in names
        if ".data/data/share/repomap-kg/" in name
    }

    assert installed_data == {*graph_resources, *control_resources}

    install_root = tmp_path / "installed"
    pip_install_env = prepare_child_coverage_environment(os.environ, family="arch7f_pip")
    pip_install = launch_observed_process(
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_root),
            str(wheel),
        ),
        family="arch7f_pip",
        env=pip_install_env,
    )
    assert pip_install.returncode == 0, pip_install.stderr[-2_000:]
    probe_env = prepare_child_coverage_environment(
        os.environ,
        family="arch7f_probe",
        extra_env={"PYTHONPATH": str(install_root)},
    )
    probe = launch_observed_process(
        (
            sys.executable,
            "-c",
            "import json,sys,sysconfig; "
            "from pathlib import Path; "
            "data_root=Path(sys.argv[1]); "
            "original_get_path=sysconfig.get_path; "
            "sysconfig.get_path=lambda name,*args,**kwargs: "
            "str(data_root) if name == 'data' else "
            "original_get_path(name,*args,**kwargs); "
            "from repomap_kg.storage import discover_migrations; "
            "from repomap_kg.coordinator._control_schema import "
            "discover_control_migrations; "
            "encode=lambda items: [(item.relative_path,item.changeset_id,"
            "item.checksum) for item in items]; "
            "print(json.dumps({'graph':encode(discover_migrations()),"
            "'control':encode(discover_control_migrations())},sort_keys=True))",
            str(install_root),
        ),
        family="arch7f_probe",
        env=probe_env,
    )
    assert probe.returncode == 0, probe.stderr[-2_000:]
    installed = json.loads(probe.stdout)
    source_graph = [
        [item.relative_path, item.changeset_id, item.checksum]
        for item in discover_migrations(REPO_ROOT / "src/main/resources/rdbms")
    ]
    source_control = [
        [item.relative_path, item.changeset_id, item.checksum]
        for item in discover_control_migrations(
            REPO_ROOT / "src/main/resources/coordinator-rdbms"
        )
    ]

    assert installed == {"control": source_control, "graph": source_graph}
