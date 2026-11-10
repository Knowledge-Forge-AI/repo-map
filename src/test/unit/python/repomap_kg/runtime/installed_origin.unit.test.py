"""Section-6 path classification, closure judgment and wrapper inspection without children."""

from __future__ import annotations

import ast
import json
import os
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest

from repomap_test_support.installed_environment import ChildResult, InstalledEnvironment
from repomap_test_support.installed_origin import (
    BASE_PROBE, ORIGIN_PROBE, OriginRecord, checkout_refusal, classify, closure, distributions_text,
    inspect_wrappers, wrappers_hold,
)


def _env(root: Path) -> InstalledEnvironment:
    prefix = root / "venv"
    return InstalledEnvironment(root, "pure-local", prefix, prefix / "bin" / "python", prefix / "bin",
                                prefix / "lib" / "python3.13" / "site-packages", prefix,
                                root / "user home", root / "unrelated cwd")


def _record(counts: dict[str, int], **changes: object) -> OriginRecord:
    values: dict[str, Any] = {
        "result": ChildResult(0, "{}", ""), "payload": {"distributions": ["a==1", "b==2"]},
        "path_counts": counts,
        "module_origins": {"common_lore_index": "env-purelib", "repomap_kg": "env-purelib",
                    "typing_extensions": "env-purelib"},
        "resource_root": "env-data", "customize": {"sitecustomize": "absent", "usercustomize": "absent"},
        "absent_families": True,
    }
    values.update(changes)
    return OriginRecord(**values)


def test_classes_for_every_owned_and_base_location(tmp_path: Path) -> None:
    env, checkout = _env(tmp_path / "owned root"), tmp_path / "checkout"
    base = sysconfig.get_paths(scheme="posix_prefix", vars={"base": sys.base_prefix, "platbase": sys.base_exec_prefix,
                                                             "installed_base": sys.base_prefix,
                                                             "installed_platbase": sys.base_exec_prefix})
    assert classify("", env, checkout) == "owned-cwd"
    assert classify(str(env.cwd), env, checkout) == "owned-cwd"
    assert classify(str(env.purelib / "common_lore_index" / "__init__.py"), env, checkout) == "env-purelib"
    assert classify(str(env.resource_root / "rdbms"), env, checkout) == "env-data"
    assert classify(str(env.bin / "cloe"), env, checkout) == "env-bin"
    assert classify(str(checkout / "src" / "main" / "python"), env, checkout) == "checkout"
    assert classify(base["stdlib"], env, checkout) == "base-stdlib"
    assert classify(os.path.join(base["platstdlib"], "lib-dynload"), env, checkout) == "base-dynload"
    assert classify(base["purelib"], env, checkout) == "system-site"
    assert classify("/opt/unrelated/tmp", env, checkout) == "other"
    assert classify(None, env, checkout) == "absent"


def test_empty_path_entry_is_never_a_wildcard_temporary(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    assert classify(str(tmp_path / "another cwd"), env, tmp_path / "checkout") == "other"


def test_closure_over_both_probe_runs() -> None:
    normal = _record({"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1, "owned-cwd": 1})
    isolated = _record({"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1})
    assert closure("pure-local", normal, isolated)
    assert not closure("pure-local", normal, _record({"base-stdlib": 2, "env-purelib": 1, "system-site": 1}))
    assert not closure("pure-local", normal, _record(isolated.path_counts, payload=None))
    assert not closure("pure-local", normal, _record(isolated.path_counts, resource_root="checkout"))
    assert not closure("pure-local", normal, _record(isolated.path_counts, absent_families=False))


def test_checkout_injection_refuses_a_pure_label() -> None:
    injected = _record({"checkout": 1, "base-stdlib": 2, "env-purelib": 1, "owned-cwd": 1})
    assert checkout_refusal("pure-local", injected) == "origin-checkout"
    module_only = _record({"base-stdlib": 2, "env-purelib": 1},
                          module_origins={"common_lore_index": "checkout", "repomap_kg": "env-purelib",
                                   "typing_extensions": "env-purelib"})
    assert checkout_refusal("pure-local", module_only) == "origin-checkout"
    assert checkout_refusal("pure-local", _record({"base-stdlib": 2, "env-purelib": 1})) is None
    assert distributions_text({"distributions": ["a==1", "b==2"]}) == "a==1,b==2"


@pytest.mark.parametrize("field,changed", [
    ("module_origins", {"common_lore_index": "checkout", "repomap_kg": "env-purelib",
                        "typing_extensions": "env-purelib"}),
    ("resource_root", "checkout"),
    ("customize", {"sitecustomize": "owned-cwd", "usercustomize": "absent"}),
    ("absent_families", False),
])
def test_normal_probe_cannot_hide_foreign_origins(field: str, changed: Any) -> None:
    counts = {"base-stdlib": 2, "env-purelib": 1}
    normal = _record({**counts, "owned-cwd": 1}, **{field: changed})
    assert not closure("pure-local", normal, _record(counts))


def test_provisioned_probe_pair_keeps_facade_dependency_and_customize_guards() -> None:
    counts = {"base-stdlib": 2, "env-purelib": 1, "system-site": 1}
    origins = {"common_lore_index": "env-purelib", "repomap_kg": "env-purelib",
               "typing_extensions": "system-site"}
    normal = _record({**counts, "owned-cwd": 1}, module_origins=origins, absent_families=False)
    isolated = _record(counts, module_origins=origins, absent_families=False)
    assert closure("provisioned-server", normal, isolated)
    bad = {**origins, "repomap_kg": "system-site"}
    assert not closure("provisioned-server", normal, _record(counts, module_origins=bad, absent_families=False))
    custom = {"sitecustomize": "system-site", "usercustomize": "absent"}
    assert not closure("provisioned-server", _record(counts, module_origins=origins, customize=custom),
                       _record(counts, module_origins=origins, customize=custom))


def test_probe_sources_are_fixed_text_that_compiles() -> None:
    ast.parse(ORIGIN_PROBE, filename="<origin-probe>")
    ast.parse(BASE_PROBE, filename="<base-probe>")
    assert "'psycopg_c'" in ORIGIN_PROBE and "probe_checkout_root_present" in ORIGIN_PROBE


def test_wrappers_direct_and_quoted_trampoline(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    env.bin.mkdir(parents=True)
    body = ("import re\nimport sys\nfrom common_lore_index.entrypoints import {function}\n"
            "if __name__ == '__main__':\n    sys.exit({function}())\n")
    (env.wrapper("cloe")).write_text(f"#!/bin/sh\n'''exec' \"{env.python}\" \"$0\" \"$@\"\n' '''\n"
                                     + body.format(function="cloe_main"), encoding="utf-8")
    (env.wrapper("repomap-kg")).write_text(f"#!{tmp_path}/plain/python\n" + body.format(function="cloe_main"),
                                           encoding="utf-8")
    witnesses = inspect_wrappers(env, {"cloe": "common_lore_index.entrypoints:cloe_main",
                                       "repomap-kg": "common_lore_index.entrypoints:legacy_main"})
    by_name = {item.name: item for item in witnesses}
    assert by_name["cloe"].form == "sh-exec-trampoline" and by_name["cloe"].interpreter_matches
    assert by_name["cloe"].targets_entrypoint
    assert by_name["repomap-kg"].form == "absolute-shebang"
    assert not by_name["repomap-kg"].interpreter_matches and not by_name["repomap-kg"].targets_entrypoint
    assert not wrappers_hold(witnesses) and wrappers_hold([by_name["cloe"]])


@pytest.mark.parametrize("change", ["none", "extra-distribution", "driver", "system-site", "current-product"])
def test_incumbent_witness_requires_its_exact_pure_closure(tmp_path: Path, monkeypatch, change: str) -> None:
    import repomap_test_support.installed_experience_witnesses as witness

    env = _env(tmp_path / "incumbent root")
    expected = ("repomap-kg==0.0.3", "typing-extensions==4.16.0")
    payload: dict[str, Any] = {"path": [str(env.purelib)],
               "modules": {"repomap_kg": str(env.purelib / "repomap_kg/__init__.py"),
                           "typing_extensions": str(env.purelib / "typing_extensions.py")},
               "distributions": list(expected), "current_product_absent": True,
               "driver_absent": True, "pyvenv_system_site": False, "python_path_set": False}
    if change == "extra-distribution":
        payload["distributions"] = [*expected, "unexpected-runtime==1"]
    elif change == "driver":
        payload["driver_absent"] = False
    elif change == "system-site":
        payload["pyvenv_system_site"] = True
    elif change == "current-product":
        payload["current_product_absent"] = False
    monkeypatch.setattr(witness, "run_child", lambda *_a, **_k: ChildResult(0, json.dumps(payload), ""))
    _result, _observed, accepted = witness.incumbent_origin_witness(env, tmp_path / "checkout", expected)
    assert accepted is (change == "none")
    ast.parse(witness.INCUMBENT_PROBE, filename="<incumbent-probe>")
