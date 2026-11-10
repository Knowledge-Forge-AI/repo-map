"""Pure origin-closure and environment-class rules (contract sections 2 and 6).

The test process classifies every probe path; these rules only judge the
resulting class names and counts, so the same predicate is applied by the
in-sandbox owner and by the checkout-only reconciler. No path reaches here.
"""

from __future__ import annotations

from collections.abc import Mapping

from installed_experience_domains import ORIGIN_CLASSES

PURE_PATH_CLASSES = frozenset({"base-stdlib", "base-dynload", "env-purelib"})
PURE_MODULE_CLASS = "env-purelib"
PURE_RESOURCE_CLASS = "env-data"
CUSTOMIZE_CLASSES = frozenset({"absent", "base-stdlib"})
PROVISIONED_PATH_CLASSES = PURE_PATH_CLASSES | {"system-site"}


def path_violations(
    env_class: str, counts: Mapping[str, int], *, isolated: bool,
) -> list[str]:
    """Return closed reasons why a ``sys.path`` class census breaks section 6."""
    reasons: list[str] = []
    unknown = set(counts) - set(ORIGIN_CLASSES)
    if unknown:
        reasons.append("unknown-class")
    if counts.get("checkout", 0):
        reasons.append("origin-checkout")
    if env_class in ("pure-local", "incumbent-local"):
        allowed = set(PURE_PATH_CLASSES)
        owned_cwd = counts.get("owned-cwd", 0)
        if isolated and owned_cwd:
            reasons.append("isolated-cwd-entry")
        elif not isolated and owned_cwd > 1:
            reasons.append("multiple-cwd-entries")
        extra = {name for name, count in counts.items()
                 if count and name not in allowed and name != "owned-cwd"}
        if extra - {"checkout"}:
            reasons.append("foreign-path-class")
        if not counts.get("env-purelib", 0):
            reasons.append("env-purelib-missing")
    elif env_class == "provisioned-server":
        extra = {name for name, count in counts.items()
                 if count and name not in PROVISIONED_PATH_CLASSES and name != "owned-cwd"}
        if extra - {"checkout"}:
            reasons.append("foreign-path-class")
    return sorted(set(reasons))


def module_violations(env_class: str, modules: Mapping[str, str], resource_root: str) -> list[str]:
    """Product, facade and dependency modules and the resource root of an installed env."""
    reasons: list[str] = []
    for name in ("common_lore_index", "repomap_kg", "typing_extensions"):
        observed = modules.get(name)
        if env_class == "provisioned-server" and name == "typing_extensions":
            if observed not in ("env-purelib", "system-site"):
                reasons.append("dependency-origin")
        elif observed != PURE_MODULE_CLASS:
            reasons.append("module-origin")
    if resource_root != PURE_RESOURCE_CLASS:
        reasons.append("resource-origin")
    return sorted(set(reasons))


def classify_environment(include_system_site: bool, has_system_site_entries: bool) -> str:
    """The only labels a venv may carry, decided from its config and observed path."""
    if include_system_site or has_system_site_entries:
        return "provisioned"
    return "pure"


def label_refusal(label: str, observed: str) -> str | None:
    """A ``pure-local`` label over a shared-site venv is a class mismatch."""
    if label == "pure-local" and observed != "pure":
        return "environment-class-mismatch"
    if label == "provisioned-server" and observed != "provisioned":
        return "environment-class-mismatch"
    return None


def closure_holds(
    env_class: str,
    normal: Mapping[str, int],
    isolated: Mapping[str, int],
    modules: Mapping[str, str],
    resource_root: str,
    customize: Mapping[str, str],
    absent_families: bool,
) -> bool:
    """All section-6 conditions for one environment's two probe runs."""
    if path_violations(env_class, normal, isolated=False):
        return False
    if path_violations(env_class, isolated, isolated=True):
        return False
    expected = dict(normal)
    expected.pop("owned-cwd", None)
    if {key: value for key, value in expected.items() if value} != {
            key: value for key, value in isolated.items() if value}:
        return False
    if module_violations(env_class, modules, resource_root):
        return False
    if any(value not in CUSTOMIZE_CLASSES for value in customize.values()):
        return False
    return absent_families or env_class == "provisioned-server"


__all__ = [
    "CUSTOMIZE_CLASSES", "PROVISIONED_PATH_CLASSES", "PURE_MODULE_CLASS", "PURE_PATH_CLASSES",
    "PURE_RESOURCE_CLASS", "classify_environment", "closure_holds", "label_refusal",
    "module_violations", "path_violations",
]
