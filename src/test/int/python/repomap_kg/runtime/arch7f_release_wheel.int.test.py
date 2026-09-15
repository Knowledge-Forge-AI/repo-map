import importlib.util
import json
import os
import subprocess
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
    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()
    wheel_build = subprocess.run(
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
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
    subprocess.run(
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
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    probe = subprocess.run(
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
        check=False,
        env={**os.environ, "PYTHONPATH": str(install_root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
