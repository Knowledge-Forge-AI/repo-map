"""Exact offline installed environments, projection and origin closure (rows A01-A07).

A01 checks the shared candidate wheel against the source-derived inventory.
A02-A04 build a pure-Local venv (wheel plus the RECORD-verified SDK
``typing-extensions`` projection, nothing else) and witness its closure. A05-A07
are the declared negatives: a shared-site venv labelled pure, checkout injection
through ``PYTHONPATH`` and three projection refusals over scratch copies.
"""

from __future__ import annotations

import base64
import hashlib
import tomllib
from pathlib import Path
from typing import Any

from common_lore_index.coordinator._control_schema import discover_control_migrations
from common_lore_index.storage import discover_migrations
from installed_experience_pins import TE_DISTRIBUTION, TE_VERSION
from installed_experience_rules import classify_environment, label_refusal
from repomap_test_support.installed_candidate import (
    DIST_INFO, ROOT, candidate_wheel, expected_entry_points, expected_inventory, expected_requires,
    input_names, inventory_sha256, license_bytes_match, license_members, listed_inputs, rows_sha256,
    wheel_inventory,
)
from repomap_test_support.installed_environment import (
    create_environment, include_system_site_packages, install_wheel, pip_check, run_child,
)
from repomap_test_support.installed_experience_driver import Observed, OwnerRun, intent_for, json_object, preparation
from repomap_test_support.installed_origin import (
    base_interpreter_has_product, checkout_refusal, closure, distributions_text, inspect_wrappers,
    observe_origin, wrappers_hold,
)
from repomap_test_support.installed_projection import (
    ProjectionRefused, copy_source_distribution, project_sdk_distribution, requirement_from_wheel,
    target_listing,
)

FS, OUT, EXIT, PIP = "filesystem", "child-stdout", "child-exit", "pip-check"


def _source_values() -> dict[str, dict[str, Any]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = listed_inputs(ROOT)
    resources = ROOT / "src" / "main" / "resources"
    return {
        "A01": {"inventory_sha256": inventory_sha256(expected_inventory(ROOT, names)),
                "entry_points_sha256": rows_sha256(expected_entry_points(ROOT)),
                "requires_dist": ",".join(expected_requires(ROOT)),
                "license_members": ",".join(license_members(input_names(names)))},
        "A03": {"distributions": ",".join(sorted([f"{project['name']}=={project['version']}",
                                                  f"{TE_DISTRIBUTION}=={TE_VERSION}"])),
                "graph_migrations": len(discover_migrations(resources / "rdbms")),
                "control_migrations": len(discover_control_migrations(resources / "coordinator-rdbms"))},
    }


def _refusal(name: str, version: str, source: Path, target: Path) -> tuple[str, bool]:
    target.mkdir(mode=0o700, parents=True)
    before = target_listing(target)
    try:
        project_sdk_distribution(name, version, target, source_purelib=source)
    except ProjectionRefused as refused:
        return refused.code, target_listing(target) == before
    return "projected", target_listing(target) == before


def test_installed_environment_classes_and_closure(tmp_path_factory, tmp_path: Path) -> None:
    candidate = candidate_wheel(tmp_path_factory)
    owned = tmp_path / "owned root"
    owned.mkdir(mode=0o700)
    run = OwnerRun("environment", intent_for("environment", preparation(candidate), _source_values()))
    run.registry.own(owned)
    state: dict[str, Any] = {}
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]

    def a01() -> Observed:
        inventory = wheel_inventory(candidate.wheel)
        groups_ok = inventory.groups == ("console_scripts",)
        if inventory.forbidden_members:
            return Observed(failure_code="inventory-mismatch")
        return Observed({
            "inventory_sha256": (inventory_sha256(inventory.names), FS),
            "entry_points_sha256": (rows_sha256(inventory.entry_points) if groups_ok else "groups-mismatch", FS),
            "requires_dist": (",".join(inventory.requires), FS),
            "record_hashes_valid": (inventory.record_valid, FS),
            "license_members": (",".join(inventory.licenses) if license_bytes_match(inventory, ROOT)
                                else "license-bytes-mismatch", FS),
            "pth_members": (inventory.pth_members, FS)})

    def a02() -> Observed:
        env = create_environment(owned / "pure env", "pure-local")
        state["env"] = env
        installed = install_wheel(env, candidate.wheel)
        if installed.returncode != 0:
            return Observed(exit=installed.exit, failure_code="child-exit-nonzero")
        name, version = requirement_from_wheel(candidate.wheel, DIST_INFO)
        record = project_sdk_distribution(name, version, env.purelib)
        checked = pip_check(env)
        return Observed({"install_exit": (installed.exit, EXIT),
                         "projection_module_sha256": (hashlib.sha256((env.purelib / "typing_extensions.py")
                                                                     .read_bytes()).hexdigest(), FS),
                         "projection_record_sha256": (hashlib.sha256((env.purelib / f"typing_extensions-{version}"
                                                      ".dist-info" / "RECORD").read_bytes()).hexdigest(), FS),
                         "pip_check_exit": (checked.exit, PIP),
                         "include_system_site_packages": (include_system_site_packages(env), FS)},
                        exit=checked.exit, projection=record.as_payload())

    def a03() -> Observed:
        env = state["env"]
        normal = observe_origin(env, ROOT, isolated=False)
        isolated = observe_origin(env, ROOT, isolated=True)
        if not (normal.ok and isolated.ok):
            return Observed(failure_code="witness-failed")
        payload = isolated.payload or {}
        holds = closure("pure-local", normal, isolated) and wrappers_hold(inspect_wrappers(env, scripts))
        return Observed({
            "closure_holds": (holds, OUT), "product_origin": (isolated.module_origins["common_lore_index"], OUT),
            "facade_origin": (isolated.module_origins["repomap_kg"], OUT),
            "dependency_origin": (isolated.module_origins["typing_extensions"], OUT),
            "resource_root": (isolated.resource_root, OUT), "absent_families": (isolated.absent_families, OUT),
            "distributions": (distributions_text(payload), OUT),
            "graph_migrations": (payload.get("graph_migrations"), OUT),
            "control_migrations": (payload.get("control_migrations"), OUT),
            "base_has_product": (base_interpreter_has_product(env), OUT)}, origin_classes=isolated.path_counts)

    def a04() -> Observed:
        result = run_child(state["env"], (str(state["env"].wrapper("cloe")), "identity", "--installation-check",
                                          "--json"))
        return Observed({"ownership_state": ((json_object(result.stdout) or {}).get("state"), OUT),
                         "exit": (result.exit, EXIT)}, exit=result.exit)

    def a05() -> Observed:
        shared = create_environment(owned / "shared env", "shared-site")
        if install_wheel(shared, candidate.wheel).returncode != 0:
            return Observed(failure_code="prerequisite-failed")
        record = observe_origin(shared, ROOT, isolated=True)
        observed = classify_environment(include_system_site_packages(shared),
                                        record.path_counts.get("system-site", 0) > 0)
        return Observed({"observed_class": (observed, FS),
                         "refusal": (label_refusal("pure-local", observed) or "accepted", FS)})

    def a06() -> Observed:
        record = observe_origin(state["env"], ROOT, isolated=False,
                                extra={"PYTHONPATH": str(ROOT / "src" / "main" / "python")})
        return Observed({"checkout_entries": (record.path_counts.get("checkout", 0) > 0, OUT),
                         "refusal": (checkout_refusal("pure-local", record) or "accepted", OUT)})

    def a07() -> Observed:
        cases: dict[str, tuple[str, bool]] = {}
        for label in ("hash", "symlink", "unknown"):
            scratch = copy_source_distribution(TE_DISTRIBUTION, TE_VERSION, owned / f"scratch {label}")
            module = scratch / "typing_extensions.py"
            if label == "hash":
                body = bytearray(module.read_bytes())
                body[0] = ord("#") if body[0] != ord("#") else ord(" ")
                module.write_bytes(bytes(body))
            elif label == "symlink":
                moved = scratch / "moved_typing_extensions.py"
                module.rename(moved)
                module.symlink_to(moved)
            else:
                record = scratch / f"typing_extensions-{TE_VERSION}.dist-info" / "RECORD"
                digest = base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=").decode()
                record.write_text(record.read_text(encoding="utf-8")
                                  + f"typing_extensions_extra.py,sha256={digest},1\n", encoding="utf-8")
            cases[label] = _refusal(TE_DISTRIBUTION, TE_VERSION, scratch, owned / f"target {label}")
        return Observed({"hash_refusal": (cases["hash"][0], FS), "symlink_refusal": (cases["symlink"][0], FS),
                         "unknown_refusal": (cases["unknown"][0], FS),
                         "target_unchanged": (all(item[1] for item in cases.values()), FS)})

    for scenario, action in (("A01", a01), ("A02", a02), ("A03", a03), ("A04", a04), ("A05", a05),
                             ("A06", a06), ("A07", a07)):
        run.step(scenario, action)
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted", (verdict.categories, run.mismatches, [
        (row["scenario"], row["outcome"], row["failure_code"]) for row in verdict.rows])
    assert root.is_dir()
