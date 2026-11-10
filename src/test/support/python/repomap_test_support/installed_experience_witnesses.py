"""Reusable first-row witnesses for each pure-local installed owner."""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from common_lore_index.coordinator._control_schema import discover_control_migrations
from common_lore_index.storage import discover_migrations
from installed_experience_pins import TE_DISTRIBUTION, TE_VERSION
from repomap_test_support.installed_environment import ChildResult, include_system_site_packages, run_child
from repomap_test_support.installed_experience_driver import Observed
from repomap_test_support.installed_origin import (
    base_interpreter_has_product,
    closure,
    distributions_text,
    inspect_wrappers,
    observe_origin,
    classify,
    wrappers_hold,
)
from installed_experience_rules import path_violations


OUT = "child-stdout"
FS = "filesystem"


INCUMBENT_PROBE = """import importlib.metadata, importlib.util, json, os, sys
import repomap_kg, typing_extensions

def pyvenv_system_site():
    try:
        with open(os.path.join(sys.prefix, 'pyvenv.cfg'), encoding='utf-8') as stream:
            for line in stream:
                key, _, value = line.partition('=')
                if key.strip() == 'include-system-site-packages':
                    return value.strip().lower() == 'true'
    except OSError:
        return None
    return None

rows = []
for distribution in importlib.metadata.distributions():
    name = (distribution.metadata.get('Name') or 'missing-name').lower().replace('_', '-')
    rows.append('%s==%s' % (name, distribution.version))
print(json.dumps({
    'modules': {'repomap_kg': repomap_kg.__file__, 'typing_extensions': typing_extensions.__file__},
    'path': list(sys.path),
    'distributions': sorted(rows),
    'current_product_absent': importlib.util.find_spec('common_lore_index') is None,
    'driver_absent': all(importlib.util.find_spec(name) is None
                         for name in ('psycopg', 'psycopg_c', 'psycopg_binary', 'psycopg2', 'psycopg_pool')),
    'pyvenv_system_site': pyvenv_system_site(),
    'python_path_set': 'PYTHONPATH' in os.environ,
    'repomap_kg_version': importlib.metadata.version('repomap-kg'),
}, sort_keys=True))
"""


def origin_source_values(checkout: Path) -> dict[str, Any]:
    """Compute the immutable origin facts used to build an owner intent."""
    project = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    resources = checkout / "src" / "main" / "resources"
    product = project["name"].lower().replace("_", "-")
    distributions = sorted((f"{product}=={project['version']}", f"{TE_DISTRIBUTION}=={TE_VERSION}"))
    return {
        "distributions": ",".join(distributions),
        "graph_migrations": len(discover_migrations(resources / "rdbms")),
        "control_migrations": len(discover_control_migrations(resources / "coordinator-rdbms")),
    }


def pure_local_origin_witness(
    env: Any,
    checkout: Path,
    scripts: Mapping[str, str],
) -> Observed:
    """Witness one owner's actual fresh pure-local environment before workflows."""
    normal = observe_origin(env, checkout, isolated=False)
    isolated = observe_origin(env, checkout, isolated=True)
    if not (normal.ok and isolated.ok):
        return Observed(failure_code="witness-failed")
    payload = isolated.payload or {}
    origins = isolated.module_origins
    if not all(name in origins for name in ("common_lore_index", "repomap_kg", "typing_extensions")):
        return Observed(failure_code="witness-failed")
    driver = payload.get("driver")
    if not isinstance(driver, dict):
        return Observed(failure_code="witness-failed")
    facts: dict[str, tuple[Any, str]] = {
        "closure_holds": (closure(env.env_class, normal, isolated) and not driver, OUT),
        "product_origin": (origins["common_lore_index"], OUT),
        "facade_origin": (origins["repomap_kg"], OUT),
        "dependency_origin": (origins["typing_extensions"], OUT),
        "resource_root": (isolated.resource_root, OUT),
        "absent_families": (isolated.absent_families, OUT),
        "distributions": (distributions_text(payload), OUT),
        "graph_migrations": (payload.get("graph_migrations"), OUT),
        "control_migrations": (payload.get("control_migrations"), OUT),
        "base_has_product": (base_interpreter_has_product(env), OUT),
        "pyvenv_system_site": (include_system_site_packages(env), FS),
        "wrappers_hold": (wrappers_hold(inspect_wrappers(env, scripts)), FS),
    }
    return Observed(facts, origin_classes=isolated.path_counts)


def incumbent_origin_witness(
    env: Any, checkout: Path, expected_distributions: tuple[str, ...],
) -> tuple[ChildResult, dict[str, Any] | None, bool]:
    """Run the fixed old-wheel probe and reduce its origin facts to one closed bool."""
    result = run_child(env, (str(env.python), "-I", "-c", INCUMBENT_PROBE))
    if result.returncode != 0:
        return result, None, False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result, None, False
    if not isinstance(payload, dict):
        return result, None, False
    counts = Counter(classify(path, env, checkout) for path in payload.get("path", []))
    modules = payload.get("modules") or {}
    module_ok = all(
        classify(modules.get(name), env, checkout) == "env-purelib"
        for name in ("repomap_kg", "typing_extensions")
    )
    valid = (
        not path_violations("incumbent-local", counts, isolated=True)
        and module_ok
        and payload.get("distributions") == list(expected_distributions)
        and payload.get("current_product_absent") is True
        and payload.get("driver_absent") is True
        and payload.get("pyvenv_system_site") is False
        and payload.get("python_path_set") is False
    )
    return result, payload, valid


__all__ = ["INCUMBENT_PROBE", "incumbent_origin_witness", "origin_source_values", "pure_local_origin_witness"]
