"""Offline incumbent/candidate ownership proof in disposable interpreter prefixes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import venv
import zipfile

import pytest

from runner_coverage_bootstrap import resolve_bootstrap_capability
from runner_coverage_execution import prepare_child_coverage_environment
from runner_coverage_observer import launch_observed_process

ROOT = Path(__file__).resolve().parents[6]
INCUMBENT = "6d818ad6d43d38d47c64b8c474c2b64b853f631a"
CATALOGS = ("rdbms", "coordinator-rdbms")


def run(args: tuple[str, ...], cwd: Path, *, pip: bool = False) -> subprocess.CompletedProcess[str]:
    family = "arch7f_pip" if pip else "arch7f_probe"
    cap = resolve_bootstrap_capability(env=os.environ)
    env = prepare_child_coverage_environment(os.environ, family=family, capability=cap,
        extra_env={"PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "PIP_NO_INDEX": "1",
                   "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    return launch_observed_process(args, family=family, capability=cap, env=env, cwd=cwd)


def require(args: tuple[str, ...], cwd: Path, *, pip: bool = False) -> str:
    result = run(args, cwd, pip=pip)
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def catalog_bytes(wheel: Path, prefix: str) -> dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        marker = ".data/data/share/" + prefix + "/"
        return {name.split(marker, 1)[1]: hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist() if marker in name}


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    scratch = tmp_path_factory.mktemp("cloe-offline-wheels")
    # Immutable predecessor objects, not a source working tree or a downloaded wheel.
    archive = scratch / "incumbent.tar"
    require(("git", "archive", "--format=tar", "--output=" + str(archive), INCUMBENT,
             "pyproject.toml", "README.md", "LICENSE", "src/main/python/repomap_kg",
             "src/main/resources"), ROOT)
    incumbent = scratch / "incumbent"
    incumbent.mkdir()
    with tarfile.open(archive) as source_archive:
        source_archive.extractall(incumbent, filter="data")
    built = []
    for label, source in (("old", incumbent), ("new", ROOT)):
        destination = scratch / label
        destination.mkdir()
        require((sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                 "--no-build-isolation", "--wheel-dir", str(destination), str(source)), scratch, pip=True)
        candidates = list(destination.glob("*.whl"))
        assert len(candidates) == 1
        built.append(candidates[0])
    old, new = built
    assert old.name.startswith("repomap_kg-0.0.3-")
    assert new.name.startswith("common_lore_index-0.0.3-")
    old_catalog = catalog_bytes(old, "repomap-kg")
    new_catalog = catalog_bytes(new, "common-lore-index")
    expected = {path.relative_to(ROOT / "src/main/resources").as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest()
                for catalog in CATALOGS for path in (ROOT / "src/main/resources" / catalog).rglob("*")
                if path.is_file()}
    assert old_catalog == new_catalog == expected and expected
    with zipfile.ZipFile(new) as wheel:
        names = wheel.namelist()
        assert not any(".data/data/share/repomap-kg/" in name for name in names)
        legacy = {name for name in names if name.startswith("repomap_kg/")}
        assert legacy == {"repomap_kg/" + suffix for suffix in (
            "__init__.py", "__main__.py", "ops/__init__.py", "ops/config_migration.py",
            "server/__init__.py", "server/mcp.py")}
    source_files = require(("git", "ls-files", "--cached", "--others", "--exclude-standard"), ROOT).splitlines()
    inputs = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(set(source_files))
              if (ROOT / name).is_file() and (name in {"README.md", "LICENSE", "pyproject.toml"}
                  or name.startswith(("src/main/python/", "src/main/resources/")))}
    print(json.dumps({"schema": "cloe-offline-wheel-proof-v1", "incumbent_commit": INCUMBENT,
        "old_wheel_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
        "new_wheel_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
        "candidate_input_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_input_count": len(inputs), "catalog_files": len(expected),
        "catalog_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}, sort_keys=True))
    return old, new


def interpreter(tmp_path: Path) -> Path:
    # Reuse the pinned SDK dependencies; do not seed or download another installer.
    environment = tmp_path / "environment"
    venv.EnvBuilder(with_pip=False, system_site_packages=True).create(environment)
    return environment / "bin/python"


def install(python: Path, wheel: Path, cwd: Path) -> None:
    require((sys.executable, "-m", "pip", "--python", str(python), "install", "--no-index",
             "--no-deps", str(wheel)), cwd, pip=True)


def probe(python: Path, code: str, cwd: Path) -> dict:
    return json.loads(require((str(python), "-I", "-c", code), cwd))


OWNERSHIP = """import json
from common_lore_index.runtime.installation_ownership import inspect_installation_ownership
print(json.dumps(inspect_installation_ownership().as_dict()))
"""
CATALOG_PROBE = """import json
from common_lore_index.storage import discover_migrations
from common_lore_index.coordinator._control_schema import discover_control_migrations
encode=lambda items:[(i.relative_path,i.changeset_id,i.checksum) for i in items]
print(json.dumps({'graph':encode(discover_migrations()),'control':encode(discover_control_migrations())}))
"""


def test_fresh_candidate_commands_resources_and_finite_object_identity(wheels, tmp_path: Path) -> None:
    _old, new = wheels
    python = interpreter(tmp_path)
    install(python, new, tmp_path)
    assert probe(python, OWNERSHIP, tmp_path)["state"] == "single-owner"
    from smoke.host_mcp_native_launch import console_entrypoint
    console = console_entrypoint(python.parent / "cloe")
    assert console.form == "absolute-shebang" and console.targets_cli_main
    for name in ("cloe", "common-lore-index", "repomap-kg"):
        wrapper = python.parent / name
        result = run((str(wrapper), "--version"), tmp_path)
        assert result.returncode == 0 and result.stdout == name + " 0.0.3\n"
        assert bool(result.stderr) == (name == "repomap-kg")
        identity = run((str(wrapper), "identity", "--json"), tmp_path)
        payload = json.loads(identity.stdout)
        assert identity.returncode == 0 and len(payload) == 6
        assert payload["distribution"] == "common-lore-index" and payload["package"] == "common_lore_index"
        assert payload["cli"] == "cloe"
    objects = probe(python, """import json
from common_lore_index.ops import config_migration as current
from repomap_kg.ops import config_migration as legacy
names=('apply_cloe_config_migration','rollback_cloe_config_migration','finalize_cloe_config_migration')
print(json.dumps({'same':all(getattr(current,n) is getattr(legacy,n) for n in names)}))
""", tmp_path)
    assert objects == {"same": True}
    unsupported = probe(python, """import importlib,json
names=('repomap_kg.cli','repomap_kg.storage','repomap_kg.server.http','repomap_kg.ops.config')
refused=[]
for name in names:
    try: importlib.import_module(name)
    except ModuleNotFoundError: refused.append(name)
print(json.dumps({'refused':refused}))
""", tmp_path)
    assert unsupported == {"refused": ["repomap_kg.cli", "repomap_kg.storage", "repomap_kg.server.http", "repomap_kg.ops.config"]}
    installed = probe(python, CATALOG_PROBE, tmp_path)
    from common_lore_index.storage import discover_migrations
    from common_lore_index.coordinator._control_schema import discover_control_migrations
    encode = lambda items: [[i.relative_path, i.changeset_id, i.checksum] for i in items]
    assert installed == {"graph": encode(discover_migrations(ROOT / "src/main/resources/rdbms")),
                         "control": encode(discover_control_migrations(ROOT / "src/main/resources/coordinator-rdbms"))}


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
@pytest.mark.parametrize("remove", [0, 1])
def test_overlap_is_diagnosed_and_shared_wrapper_uninstall_is_observed(wheels, tmp_path: Path, order, remove):
    python = interpreter(tmp_path)
    for index in order:
        install(python, wheels[index], tmp_path)
    assert probe(python, OWNERSHIP, tmp_path)["state"] == "conflicting"
    shared = python.parent / "repomap-kg"
    assert shared.is_file()
    legacy_files = probe(python, """import json,sysconfig
from pathlib import Path
root=Path(sysconfig.get_path('purelib'))/'repomap_kg'
names=('__init__.py','__main__.py','ops/__init__.py','ops/config_migration.py','server/__init__.py','server/mcp.py')
print(json.dumps({name:str(root/name) for name in names}))
""", tmp_path)
    assert len(legacy_files) == 6 and all(Path(path).is_file() for path in legacy_files.values())
    owner = ("repomap-kg", "common-lore-index")[remove]
    require((sys.executable, "-m", "pip", "--python", str(python), "uninstall", "-y", owner), tmp_path, pip=True)
    # RECORD ownership is per distribution; neither installer order makes overlap safe.
    assert not shared.exists()
    assert not any(Path(path).exists() for path in legacy_files.values())
    canonical = python.parent / "cloe"
    assert canonical.exists() is (remove == 0)
    if remove == 0:
        result = run((str(canonical), "identity", "--json"), tmp_path)
        assert result.returncode == 0 and json.loads(result.stdout)["distribution"] == "common-lore-index"
        assert probe(python, OWNERSHIP, tmp_path)["state"] == "single-owner"
    print(json.dumps({"schema": "cloe-installer-overlap-proof-v1", "order": order,
                      "removed": owner, "shared_wrapper_removed": True,
                      "shared_legacy_files_removed": sorted(legacy_files),
                      "canonical_wrapper_present": canonical.exists()}, sort_keys=True))
