import importlib.util
import json
import os
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.coordinator._control_schema import discover_control_migrations
from repomap_kg.storage import discover_migrations


REPO_ROOT = Path(__file__).resolve().parents[6]


def _verify_wheel_contents(
    wheel: Path,
    expected_version: str,
    tmp_path: Path,
    cap: Any,
    family_suffix: str,
) -> None:
    from runner_coverage_execution import prepare_child_coverage_environment
    from runner_coverage_observer import launch_observed_process

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata = archive.read(f"repomap_kg-{expected_version}.dist-info/METADATA").decode("utf-8")
    header = metadata.split("\n\n", 1)[0].splitlines()

    requirements = [line for line in header if line.startswith("Requires-Dist: ")]
    unconditional = [line for line in requirements if "; extra ==" not in line]

    assert unconditional == ["Requires-Dist: typing-extensions==4.16.0"]
    assert [line for line in requirements if "psycopg" in line] == [
        'Requires-Dist: psycopg[binary]==3.2.12; extra == "postgres"'
    ]
    assert "Provides-Extra: postgres" in header

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
    october = {path for path in control_resources if path.startswith("coordinator-rdbms/2026/10/")}
    assert october, "October coordinator migration catalog must be nonempty"
    assert october <= installed_data

    install_root = tmp_path / f"installed_{family_suffix}"
    pip_install_env = prepare_child_coverage_environment(
        os.environ, family="arch7f_pip", capability=cap
    )
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
        capability=cap,
    )
    assert pip_install.returncode == 0, pip_install.stderr[-2_000:]
    probe_env = prepare_child_coverage_environment(
        os.environ,
        family="arch7f_probe",
        extra_env={"PYTHONPATH": str(install_root)},
        capability=cap,
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
        capability=cap,
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


def test_wheel_contains_complete_graph_and_control_migration_catalogs(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("setuptools build backend is unavailable")
    from runner_coverage_bootstrap import resolve_bootstrap_capability
    from runner_coverage_execution import prepare_child_coverage_environment
    from runner_coverage_observer import launch_observed_process

    cap = resolve_bootstrap_capability(env=os.environ)
    wheel_directory = tmp_path / "wheel_private"
    wheel_directory.mkdir()
    pip_env = prepare_child_coverage_environment(os.environ, family="arch7f_pip", capability=cap)
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
        capability=cap,
    )
    assert wheel_build.returncode == 0, wheel_build.stderr[-2_000:]
    wheel = next(wheel_directory.glob("repomap_kg-*.whl"))
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]
    _verify_wheel_contents(wheel, version, tmp_path, cap, "private")


def test_projected_public_wheel_contains_complete_graph_and_control_migration_catalogs(
    tmp_path: Path,
) -> None:
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("setuptools build backend is unavailable")
    from runner_coverage_bootstrap import resolve_bootstrap_capability
    from runner_coverage_execution import prepare_child_coverage_environment
    from runner_coverage_observer import launch_observed_process

    cap = resolve_bootstrap_capability(env=os.environ)
    current_version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]
    if current_version == "0.0.2":
        test_wheel_contains_complete_graph_and_control_migration_catalogs(tmp_path)
        return

    projected_src = tmp_path / "projected_source"
    projected_src.mkdir()
    raw_pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.0"' in raw_pyproject
    (projected_src / "pyproject.toml").write_text(
        raw_pyproject.replace('version = "0.1.0"', 'version = "0.0.2"', 1),
        encoding="utf-8",
    )
    shutil.copyfile(REPO_ROOT / "README.md", projected_src / "README.md")
    shutil.copytree(REPO_ROOT / "src", projected_src / "src")

    wheel_directory = tmp_path / "wheel_public"
    wheel_directory.mkdir()
    pip_env = prepare_child_coverage_environment(os.environ, family="arch7f_pip", capability=cap)
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
            str(projected_src),
        ),
        family="arch7f_pip",
        env=pip_env,
        capability=cap,
    )
    assert wheel_build.returncode == 0, wheel_build.stderr[-2_000:]
    wheel = next(wheel_directory.glob("repomap_kg-0.0.2-*.whl"))
    _verify_wheel_contents(wheel, "0.0.2", tmp_path, cap, "public")
