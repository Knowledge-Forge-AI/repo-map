"""Interpreter-origin and closure witnesses for installed environments (section 6).

``ORIGIN_PROBE`` is fixed source text run twice under the closed child
environment, once normally and once with ``-I``. It witnesses interpreter
resolution, not an instrumented console-wrapper trace. The test
process classifies every reported path; only class names and counts reach the
evidence. Wrappers are inspected by content with the existing console-entrypoint
parser and matched to their own entrypoint, never executed here.
"""

from __future__ import annotations

import json
import os
import sys
import sysconfig
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from installed_experience_pins import ABSENT_FAMILIES
from installed_experience_rules import closure_holds, path_violations
from repomap_test_support.installed_environment import ChildResult, InstalledEnvironment, run_child

ORIGIN_PROBE = """import hashlib, importlib.metadata, importlib.util, json, os, sys
def origin(name):
    spec = importlib.util.find_spec(name)
    return None if spec is None else spec.origin
def triples(items):
    rows = [[i.relative_path, i.changeset_id, i.checksum] for i in items]
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest(), len(rows)
import common_lore_index, repomap_kg, typing_extensions
from common_lore_index.storage import default_rdbms_root, discover_migrations
graph_sha, graph_count = triples(discover_migrations())
control_root = os.path.join(os.path.dirname(str(default_rdbms_root())), 'coordinator-rdbms')
control_sha, control_count = triples(discover_migrations(control_root))
module_path = origin('common_lore_index.coordinator._portable_worker_launch')
parents = os.path.realpath(module_path).split(os.sep)
module_root = os.sep.join(parents[:-6]) if len(parents) > 7 else None
families = __ABSENT_FAMILIES__
driver = {}
if importlib.util.find_spec('psycopg') is not None:
    import psycopg
    driver = {'file': psycopg.__file__, 'version': psycopg.__version__, 'impl': psycopg.pq.__impl__}
print(json.dumps({
    'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'path': list(sys.path),
    'no_user_site': bool(sys.flags.no_user_site), 'isolated': bool(sys.flags.isolated),
    'modules': {'common_lore_index': common_lore_index.__file__, 'repomap_kg': repomap_kg.__file__,
                'typing_extensions': typing_extensions.__file__},
    'resource_root': str(default_rdbms_root()),
    'graph_migrations': graph_count, 'control_migrations': control_count,
    'graph_catalog_sha256': graph_sha, 'control_catalog_sha256': control_sha,
    'absent': {name: importlib.util.find_spec(name) is None for name in families},
    'customize': {name: origin(name) for name in ('sitecustomize', 'usercustomize')},
    'distributions': sorted('%s==%s' % ((d.metadata.get('Name') or 'missing-name').lower().replace('_', '-'), d.version)
                            for d in importlib.metadata.distributions()),
    'probe_checkout_root_present': module_root is not None
        and os.path.isdir(os.path.join(module_root, 'src', 'main', 'python')),
    'python_path_set': 'PYTHONPATH' in os.environ,
    'driver': driver,
}, sort_keys=True))
""".replace('__ABSENT_FAMILIES__', repr(ABSENT_FAMILIES))
BASE_PROBE = "import importlib.util, json; print(json.dumps(importlib.util.find_spec('common_lore_index') is None))"


def _under(path: str, root: Path | str) -> bool:
    candidate, base = os.path.normpath(path), os.path.normpath(str(root))
    return candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep)


def _base_paths() -> dict[str, str]:
    variables = {"base": sys.base_prefix, "platbase": sys.base_exec_prefix,
                 "installed_base": sys.base_prefix, "installed_platbase": sys.base_exec_prefix}
    return sysconfig.get_paths(scheme="posix_prefix", vars=variables)


def classify(path: str | None, env: InstalledEnvironment, checkout: Path) -> str:
    """One closed origin class; empty ``sys.path`` entries are the exact owned cwd."""
    if path is None:
        return "absent"
    if path == "":
        return "owned-cwd"
    for candidate in (path, os.path.realpath(path)):
        if _under(candidate, env.purelib):
            return "env-purelib"
        if _under(candidate, env.resource_root):
            return "env-data"
        if _under(candidate, env.bin) and candidate != str(env.bin):
            return "env-bin"
        if os.path.normpath(candidate) == os.path.normpath(str(env.cwd)):
            return "owned-cwd"
    if _under(path, checkout) or _under(os.path.realpath(path), os.path.realpath(checkout)):
        return "checkout"
    base = _base_paths()
    if os.path.basename(os.path.normpath(path)) == "lib-dynload" and _under(path, sys.base_exec_prefix):
        return "base-dynload"
    if _under(path, base["purelib"]) or _under(path, base["platlib"]) or "dist-packages" in path:
        return "system-site"
    zipped = os.path.join(sys.base_prefix, "lib", f"python{sys.version_info[0]}{sys.version_info[1]}.zip")
    if _under(path, base["stdlib"]) or _under(path, base["platstdlib"]) or path == zipped:
        return "base-stdlib"
    return "other"


@dataclass(frozen=True)
class OriginRecord:
    result: ChildResult
    payload: dict[str, Any] | None
    path_counts: dict[str, int]
    module_origins: dict[str, str]
    resource_root: str
    customize: dict[str, str]
    absent_families: bool

    @property
    def ok(self) -> bool:
        return self.payload is not None


def observe_origin(
    env: InstalledEnvironment, checkout: Path, *, isolated: bool,
    extra: Mapping[str, str] | None = None,
) -> OriginRecord:
    """Run ``ORIGIN_PROBE`` with the environment's own interpreter and classify its paths."""
    argv = [str(env.python), *(("-I",) if isolated else ()), "-c", ORIGIN_PROBE]
    result = run_child(env, argv, extra=extra)
    payload: dict[str, Any] | None = None
    if result.returncode == 0:
        try:
            decoded = json.loads(result.stdout)
        except json.JSONDecodeError:
            decoded = None
        payload = decoded if isinstance(decoded, dict) else None
    if payload is None:
        return OriginRecord(result, None, {}, {}, "other", {}, False)
    counts = Counter(classify(entry, env, checkout) for entry in payload["path"])
    module_origins = {name: classify(value, env, checkout) for name, value in payload["modules"].items()}
    customize = {name: classify(value, env, checkout) for name, value in payload["customize"].items()}
    return OriginRecord(result, payload, dict(sorted(counts.items())), module_origins,
                        classify(payload["resource_root"], env, checkout), customize,
                        all(payload["absent"].values()))


def closure(env_class: str, normal: OriginRecord, isolated: OriginRecord) -> bool:
    """Section 6 for both probe runs, judged by the shared tool rules."""
    if not (normal.ok and isolated.ok):
        return False
    if (normal.module_origins != isolated.module_origins
            or normal.resource_root != isolated.resource_root
            or normal.customize != isolated.customize
            or normal.absent_families != isolated.absent_families):
        return False
    return closure_holds(env_class, normal.path_counts, isolated.path_counts, isolated.module_origins,
                         isolated.resource_root, isolated.customize, isolated.absent_families)


def checkout_refusal(env_class: str, record: OriginRecord) -> str | None:
    """A pure label over a checkout-injected interpreter refuses ``origin-checkout``."""
    if "origin-checkout" in path_violations(env_class, record.path_counts, isolated=False):
        return "origin-checkout"
    if any(value == "checkout" for value in record.module_origins.values()):
        return "origin-checkout"
    return None


def base_interpreter_has_product(env: InstalledEnvironment) -> bool | None:
    """``sys.executable -I`` under the same environment must not find the product."""
    result = run_child(env, (sys.executable, "-I", "-c", BASE_PROBE))
    if result.returncode != 0:
        return None
    return result.stdout.strip() != "true"


def distributions_text(payload: Mapping[str, Any]) -> str:
    return ",".join(payload["distributions"])


@dataclass(frozen=True)
class WrapperWitness:
    name: str
    form: str
    interpreter_matches: bool
    targets_entrypoint: bool


def inspect_wrappers(env: InstalledEnvironment, scripts: Mapping[str, str]) -> list[WrapperWitness]:
    """Each wrapper's direct shebang or quoted sh-exec trampoline must select ``env.python``."""
    from smoke.host_mcp_native_launch import console_entrypoint

    witnesses: list[WrapperWitness] = []
    for name, target in sorted(scripts.items()):
        module, _sep, function = target.partition(":")
        entry = console_entrypoint(env.wrapper(name))
        text = env.wrapper(name).read_bytes()[:8192].decode("utf-8", errors="replace")
        targets = f"from {module} import {function}" in text and f"sys.exit({function}())" in text
        matches = entry.interpreter is not None and os.path.normpath(entry.interpreter) == os.path.normpath(
            str(env.python))
        witnesses.append(WrapperWitness(name, entry.form, matches, targets))
    return witnesses


def wrappers_hold(witnesses: Sequence[WrapperWitness]) -> bool:
    return bool(witnesses) and all(
        item.form in ("absolute-shebang", "sh-exec-trampoline") and item.interpreter_matches
        and item.targets_entrypoint for item in witnesses)


__all__ = [
    "BASE_PROBE", "ORIGIN_PROBE", "OriginRecord", "WrapperWitness", "base_interpreter_has_product",
    "checkout_refusal", "classify", "closure", "distributions_text", "inspect_wrappers",
    "observe_origin", "wrappers_hold",
]
