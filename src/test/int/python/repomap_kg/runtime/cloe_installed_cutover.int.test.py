"""Offline incumbent/candidate ownership proof in disposable interpreter prefixes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile

import pytest

from runner_coverage_bootstrap import resolve_bootstrap_capability
from runner_coverage_execution import prepare_child_coverage_environment
from runner_coverage_observer import launch_observed_process

ROOT = Path(__file__).resolve().parents[6]
INCUMBENT = "6d818ad6d43d38d47c64b8c474c2b64b853f631a"
CATALOGS = ("rdbms", "coordinator-rdbms")
W3_APPEND_ONLY = {"rdbms/2026/10/31-001-cloe-lexical-create-derived-schema.sql"}


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
    # Immutable predecessor objects and the exact candidate, shared per pytest process.
    from repomap_test_support.installed_candidate import candidate_wheel, incumbent_wheel

    old_build, new_build = incumbent_wheel(tmp_path_factory, ROOT), candidate_wheel(tmp_path_factory, ROOT)
    incumbent = old_build.source
    built = [old_build.wheel, new_build.wheel]
    old, new = built
    assert old.name.startswith("repomap_kg-0.0.3-")
    assert new.name.startswith("common_lore_index-0.0.3-")
    old_catalog = catalog_bytes(old, "repomap-kg")
    new_catalog = catalog_bytes(new, "common-lore-index")
    old_expected = {path.relative_to(incumbent / "src/main/resources").as_posix():
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for catalog in CATALOGS for path in (incumbent / "src/main/resources" / catalog).rglob("*")
                    if path.is_file()}
    new_expected = {path.relative_to(ROOT / "src/main/resources").as_posix():
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for catalog in CATALOGS for path in (ROOT / "src/main/resources" / catalog).rglob("*")
                    if path.is_file()}
    incumbent_tree_files = {
        line.removeprefix("src/main/resources/")
        for line in require(("git", "ls-tree", "-r", "--name-only", INCUMBENT, "--",
                             "src/main/resources/rdbms", "src/main/resources/coordinator-rdbms"), ROOT).splitlines()
        if line
    }
    assert set(old_expected) == incumbent_tree_files
    assert old_catalog == old_expected and old_expected
    assert new_catalog == new_expected and new_expected
    assert old_expected.items() <= new_expected.items()
    assert set(new_expected) - set(old_expected) == W3_APPEND_ONLY
    dated_rdbms = [k for k in sorted(new_expected) if k.startswith("rdbms/202")]
    assert dated_rdbms and dated_rdbms[-1] == "rdbms/2026/10/31-001-cloe-lexical-create-derived-schema.sql"
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
    old_cat_sha = hashlib.sha256(json.dumps(old_expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    new_cat_sha = hashlib.sha256(json.dumps(new_expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    print(json.dumps({"schema": "cloe-offline-wheel-proof-v1", "incumbent_commit": INCUMBENT,
        "old_wheel_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
        "new_wheel_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
        "candidate_input_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_input_count": len(inputs), "old_catalog_files": len(old_expected),
        "old_catalog_sha256": old_cat_sha, "new_catalog_files": len(new_expected),
        "new_catalog_sha256": new_cat_sha, "w3_additions": sorted(W3_APPEND_ONLY),
        "catalog_files": len(new_expected), "catalog_sha256": new_cat_sha}, sort_keys=True))
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
