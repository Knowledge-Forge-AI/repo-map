"""Opt-in separation of report destinations from sources and managed state.

Only when an operator selects ``--resource-report`` does admission perform
metadata-only ``resolve(strict=False)`` checks on configured roots and the
destination ancestry. It never enumerates a directory, reads a source body,
issues SQL or adds a discovery exclusion. Default commands remain source-blind.
The claim is scoped to admission under stable configured roots; a hostile
same-UID rename or mount after admission is a documented limit.
"""

from __future__ import annotations

from collections.abc import Iterable
import errno
import os
from pathlib import Path

from ._delivery import AdmittedDestination, DeliveryError, admit_destination

ADMISSION_CATEGORIES = frozenset({"protected_root_overlap", "protected_root_unresolvable"})


class ResourceReportRefusal(ValueError):
    """Path-free refusal raised before the subject starts."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(f"resource-report-refused: {category}")


def configured_roots(config: object, *, overrides: Iterable[object] = ()) -> tuple[str, ...]:
    """Collect every configured source root and managed home/store directory.

    All graphs and all effective bindings count, not only the selected graph.
    ``overrides`` carries explicit portable-store or source-root options.
    """
    roots: list[str] = []
    home = getattr(config, "config_home", None)
    config_path = getattr(config, "config_path", None)
    if home:
        roots.append(str(home))
    elif config_path:
        # The deprecated single-file shim keeps managed state beside its file;
        # a home-loaded config may record the home directory itself here.
        path, canonical = _forms(str(config_path))
        roots.append(str(path if path.is_dir() else path.parent))
        roots.append(str(canonical if canonical.is_dir() else canonical.parent))
    memory = getattr(config, "server_memory", None)
    memory_path = getattr(memory, "path_expanded", None)
    if memory_path:
        roots.append(str(memory_path))
    for graph in getattr(config, "graphs", ()) or ():
        expanded = getattr(graph, "root_path_expanded", None)
        if expanded:
            roots.append(str(expanded))
        for binding in getattr(graph, "effective_source_bindings", ()) or ():
            binding_root = getattr(binding, "root_path_expanded", None)
            if binding_root:
                roots.append(str(binding_root))
    roots.extend(str(item) for item in overrides if item is not None and str(item))
    return tuple(dict.fromkeys(roots))


_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        details = os.stat(path)
    except OSError as error:
        if error.errno in _MISSING_ERRNOS:
            return None
        raise ResourceReportRefusal("protected_root_unresolvable") from None
    except (RuntimeError, ValueError):
        raise ResourceReportRefusal("protected_root_unresolvable") from None
    return details.st_dev, details.st_ino


def _forms(path: str | Path) -> tuple[Path, Path]:
    normalized = Path(os.path.abspath(os.path.expanduser(str(path))))
    try:
        canonical = normalized.resolve(strict=False)
        # Non-strict resolution tolerates loops on newer interpreters; one
        # metadata-only stat distinguishes a missing root from a looped or
        # permission-denied one. No directory is listed and no body is read.
        os.stat(canonical)
    except FileNotFoundError:
        return normalized, canonical
    except OSError as error:
        if error.errno in _MISSING_ERRNOS:
            return normalized, canonical
        raise ResourceReportRefusal("protected_root_unresolvable") from None
    except (RuntimeError, ValueError):
        raise ResourceReportRefusal("protected_root_unresolvable") from None
    return normalized, canonical


def _within(candidate: Path, root: Path) -> bool:
    return candidate == root or candidate.is_relative_to(root)


def check_separation(destination: AdmittedDestination, roots: Iterable[str | Path]) -> None:
    """Refuse a destination inside any protected root, including alias overlap."""
    try:
        target_forms = (
            destination.normalized_target,
            destination.normalized_target.parent.resolve(strict=False) / destination.name,
            destination.canonical_target,
        )
        if destination.descriptor is None:
            raise ResourceReportRefusal("protected_root_unresolvable")
        held = os.fstat(destination.descriptor)
        ancestor_ids = {(held.st_dev, held.st_ino)}
        for ancestor in destination.canonical_target.parent.parents:
            identity = _identity(ancestor)
            if identity is None:
                raise ResourceReportRefusal("protected_root_unresolvable")
            ancestor_ids.add(identity)
    except (OSError, RuntimeError):
        raise ResourceReportRefusal("protected_root_unresolvable") from None
    for root in roots:
        for form in _forms(root):
            if any(_within(target, form) for target in target_forms):
                raise ResourceReportRefusal("protected_root_overlap")
            identity = _identity(form)
            if identity is not None and identity in ancestor_ids:
                raise ResourceReportRefusal("protected_root_overlap")


def admit_report_destination(text: object, roots: Iterable[str | Path]) -> AdmittedDestination:
    """Admit a destination once, after config resolution and before DB/source work."""
    try:
        destination = admit_destination(text)
    except DeliveryError as error:
        raise ResourceReportRefusal(error.category) from None
    try:
        check_separation(destination, roots)
    except BaseException:
        destination.close()
        raise
    return destination


__all__ = (
    "ADMISSION_CATEGORIES", "ResourceReportRefusal", "admit_report_destination",
    "check_separation", "configured_roots",
)
