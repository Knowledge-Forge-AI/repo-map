"""Installed configuration migration apply, rollback and finalize (rows R01-R08).

The homes live under ``owned homes/<name>`` (paths with spaces). Apply and
finalize run through ``common_lore_index.ops.config_migration`` and rollback
through the finite ``repomap_kg.ops.config_migration`` facade, each in an
installed ``python -c`` probe with the home supplied as ``argv[1]``. The
incumbent wheel's own command checks the legacy home where it supports it.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tomllib
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_migration_fs import OPERATION_DIRECTORY
from common_lore_index.server._mcp_dispatch import MCP_PROTOCOL_VERSION
from installed_experience_pins import CODE_KIND, GRAPH_ID, INCUMBENT_DISTRIBUTION, TE_DISTRIBUTION, TE_VERSION
from repomap_test_support.installed_candidate import ROOT, candidate_wheel, expected_requires, incumbent_wheel
from repomap_test_support.installed_environment import run_child
from repomap_test_support.installed_experience_driver import (
    Observed, OwnerRun, intent_for, json_object, preparation, pure_environment,
)
from repomap_test_support.installed_experience_fixture import (
    LEGACY_BASE, expectations, legacy_tiny_home, write_tiny_material,
)
from repomap_test_support.installed_mcp_session import useful_question
from repomap_test_support.installed_experience_witnesses import (
    incumbent_origin_witness, origin_source_values, pure_local_origin_witness,
)

OUT, FS, MCP = "child-stdout", "filesystem", "mcp-reply"
MIGRATION_PROBE = """import json, sys
from common_lore_index.ops import config_migration as current
from repomap_kg.ops import config_migration as legacy
operations = {'apply': current.apply_cloe_config_migration,
              'finalize': current.finalize_cloe_config_migration,
              'rollback': legacy.rollback_cloe_config_migration}
options = {'dry': {'dry_run': True}, 'confirmed': {'confirmed': True}, 'none': {}}
home = None if sys.argv[1] == '-' else sys.argv[1]
print(json.dumps(operations[sys.argv[3]](home, **options[sys.argv[2]]), sort_keys=True))
"""


def _config_snapshot(home: Path) -> list[tuple[str, str]]:
    return sorted((child.name, hashlib.sha256(child.read_bytes()).hexdigest()) for child in home.iterdir()
                  if child.name.endswith(".toml") and child.is_file() and not child.is_symlink())


def _tree_snapshot(root: Path) -> list[tuple[Any, ...]]:
    rows = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in [".", *sorted(dirs + files)]:
            path = Path(current) / name
            details = path.lstat()
            content = (os.readlink(path) if stat.S_ISLNK(details.st_mode)
                       else hashlib.sha256(path.read_bytes()).hexdigest()
                       if stat.S_ISREG(details.st_mode) else "")
            rows.append((path.relative_to(root).as_posix(), details.st_mode,
                         details.st_dev, details.st_ino, content))
    return sorted(rows)


def test_installed_config_migration_lifecycle(tmp_path_factory, tmp_path: Path) -> None:
    candidate, incumbent = candidate_wheel(tmp_path_factory), incumbent_wheel(tmp_path_factory)
    owned = tmp_path / "owned root"
    env = pure_environment(owned / "pure env", candidate)
    old = pure_environment(owned / "incumbent env", incumbent, env_class="incumbent-local")
    material = write_tiny_material(owned / "owned material" / "tiny")
    home = legacy_tiny_home(owned / "owned homes" / "legacy home", material)
    expect = expectations()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    scripts = project["scripts"]
    source = {"R00": origin_source_values(ROOT),
              "R02": {"incumbent_stdout": f"repomap-kg {version}\n",
                      "dependency_pin": ",".join(expected_requires())}}
    run = OwnerRun("migration", intent_for("migration", preparation(candidate, incumbent), source))
    run.registry.own(owned)
    run.step("R00", lambda: pure_local_origin_witness(env, ROOT, scripts))
    cloe = str(env.wrapper("cloe"))
    database = home / "state" / "sqlite-local" / "graphs" / f"{GRAPH_ID}.sqlite3"
    state: dict[str, Any] = {}

    def migrate(operation: str, mode: str, target: Path | None = home) -> dict[str, Any]:
        result = run_child(env, (str(env.python), "-c", MIGRATION_PROBE, "-" if target is None else str(target),
                                 mode, operation))
        return (json_object(result.stdout) or {}) if result.returncode == 0 else {}

    def generation(environment: Any, wrapper: str) -> Any:
        result = run_child(environment, (str(environment.wrapper(wrapper)), "ops", "graphs",
                                          "--repo-map-home", str(home), "--check-db", "--json"))
        listing = json_object(result.stdout) if result.returncode == 0 else None
        row: dict[str, Any] = next((item for item in (listing or {}).get("graphs") or []
                    if item.get("graph_id", item.get("id")) == GRAPH_ID), {})
        return (row.get("storage_status") or {}).get("accepted_generation")

    def identity() -> tuple[str, Any]:
        return hashlib.sha256(database.read_bytes()).hexdigest(), generation(env, "cloe")

    def digests() -> Any:
        answer = useful_question(env, (cloe, "mcp", "serve", "--repo-map-home", str(home)), graph_id=GRAPH_ID,
                                 code_query=expect.code_query, code_kind=CODE_KIND,
                                 docs_query=expect.docs_query, protocol=MCP_PROTOCOL_VERSION)
        return answer.digests if answer.complete else None

    def valid(environment: Any, wrapper: str) -> Any:
        result = run_child(environment, (str(environment.wrapper(wrapper)), "ops", "config-check",
                                          "--repo-map-home", str(home), "--json"))
        return (json_object(result.stdout) or {}).get("valid") if result.returncode == 0 else None

    def r01() -> Observed:
        init = run_child(env, (cloe, "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH_ID, "--json"))
        if init.exit != 0:
            return Observed(failure_code="prerequisite-failed")
        refreshed = run_child(env, (cloe, "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH_ID,
                                    "--json"))
        state.update(identity=identity(), config=_config_snapshot(home), mcp=digests())
        return Observed({"accepted_generation": ((json_object(refreshed.stdout) or {}).get("accepted_generation"),
                                                 OUT)}, exit=refreshed.exit)

    def r02() -> Observed:
        result = run_child(old, (str(old.wrapper("repomap-kg")), "--version"))
        if result.returncode != 0:
            return Observed(exit=result.exit, failure_code="child-exit-nonzero")
        expected_distributions = (
            f"{INCUMBENT_DISTRIBUTION}=={version}", f"{TE_DISTRIBUTION}=={TE_VERSION}")
        probe, payload, witness_ok = incumbent_origin_witness(old, ROOT, expected_distributions)
        if probe.returncode != 0 or payload is None:
            return Observed(exit=probe.exit, failure_code="witness-failed")
        valid_observation = valid(old, "repomap-kg") is True
        dependency_rows = [item for item in payload["distributions"]
                           if item.startswith(f"{TE_DISTRIBUTION}==")]
        return Observed({"incumbent_stdout": (result.stdout, OUT), "valid": (valid_observation, OUT),
                         "incumbent_closure_holds": (witness_ok, OUT),
                         "dependency_pin": (",".join(dependency_rows), OUT)}, exit=result.exit)

    def r03() -> Observed:
        before = _config_snapshot(home)
        result = migrate("apply", "dry")
        return Observed({"result": (result.get("result"), OUT), "writes": (result.get("writes_performed"), OUT),
                         "home_unchanged": (_config_snapshot(home) == before and not os.path.lexists(
                             home / OPERATION_DIRECTORY), FS)})

    def r04() -> Observed:
        result = migrate("apply", "confirmed")
        return Observed({"result": (result.get("result"), OUT),
                         "rollback_available": (result.get("rollback_available"), OUT),
                         "valid": (valid(env, "cloe"), OUT),
                         "identity_unchanged": (identity() == state.get("identity"), FS),
                         "mcp_unchanged": (state.get("mcp") is not None and digests() == state.get("mcp"), MCP)})

    def r05() -> Observed:
        result = migrate("rollback", "confirmed")
        return Observed({"result": (result.get("result"), OUT),
                         "names_bytes_restored": (_config_snapshot(home) == state.get("config"), FS),
                         "incumbent_valid": (valid(old, "repomap-kg") is True, OUT),
                         "identity_unchanged": (identity() == state.get("identity"), FS)})

    def r06() -> Observed:
        applied, finalized = migrate("apply", "confirmed"), migrate("finalize", "confirmed")
        retained = os.path.lexists(home / OPERATION_DIRECTORY)
        rolled = migrate("rollback", "confirmed")
        return Observed({"apply": (applied.get("result"), OUT), "finalize": (finalized.get("result"), OUT),
                         "operation_retained": (retained, FS), "rollback": (rolled.get("result"), OUT),
                         "rollback_writes": (rolled.get("writes_performed"), OUT)})

    def r07() -> Observed:
        unsafe = owned / "owned homes" / "symlink home"
        unsafe.mkdir(mode=0o700)
        real = owned / "owned material" / "outside.rp.toml"
        real.write_text((home / sorted(name for name, _ in _config_snapshot(home))[0]).read_text(encoding="utf-8"),
                        encoding="utf-8")
        (unsafe / LEGACY_BASE).symlink_to(real)

        def snapshot() -> tuple[Any, ...]:
            return (_tree_snapshot(home), _tree_snapshot(unsafe),
                    hashlib.sha256(real.read_bytes()).hexdigest())

        before = snapshot()
        results = [migrate("apply", "confirmed", None), migrate("apply", "none"),
                   migrate("apply", "confirmed", unsafe)]
        codes = [((item.get("refusals") or [{}])[0]).get("code") for item in results]
        return Observed({"none_refusal": (codes[0], OUT), "unconfirmed_refusal": (codes[1], OUT),
                         "symlink_refusal": (codes[2], OUT),
                         "home_unchanged": (snapshot() == before and not os.path.lexists(
                             home / OPERATION_DIRECTORY) and not os.path.lexists(unsafe / OPERATION_DIRECTORY), FS),
                         "writes": (sum(int(item.get("writes_performed") or 0) for item in results), OUT)})

    def r08() -> Observed:
        explicit = run_child(env, (cloe, "ops", "graphs", "--repo-map-home", str(home), "--json"))
        selected = run_child(env, (cloe, "ops", "graphs", "--json"), extra={"CLOE_HOME": str(home)})
        same = explicit.exit == 0 and selected.exit == 0 and hashlib.sha256(
            explicit.stdout.encode()).digest() == hashlib.sha256(selected.stdout.encode()).digest()
        return Observed({"selector_equal": (same, OUT)}, exit=selected.exit)

    for scenario, action in (("R01", r01), ("R02", r02), ("R03", r03), ("R04", r04), ("R05", r05),
                             ("R06", r06), ("R07", r07), ("R08", r08)):
        run.step(scenario, action)
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted", (verdict.categories, run.mismatches, [
        (row["scenario"], row["outcome"], row["failure_code"]) for row in verdict.rows])
    assert root.is_dir()
