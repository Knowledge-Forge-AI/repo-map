"""Portable attempt path helpers, re-exported unchanged by ``ops.portable_refresh``."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from common_lore_index.ops._portable_retention import PortableRefreshError
from common_lore_index.ops.graph_registry import GraphRegistryConfig


def _publication_root(config):
    control_root = Path(config.config_home or Path(config.config_path).resolve().parent)
    return (control_root / "state" / "portable-publication").resolve()


def portable_attempts_parent(config: GraphRegistryConfig, namespace: str | None = None) -> Path:
    """The directory holding one route's retained attempts; never created here."""
    root = _publication_root(config)
    return root / "attempts" if namespace is None else root / namespace / "attempts"


def _attempt_root(config, graph, operation_id, attempt, namespace=None):
    root = _publication_root(config)
    for binding in graph.effective_source_bindings:
        source = Path(binding.root_path_expanded).resolve()
        if root == source or root.is_relative_to(source):
            raise PortableRefreshError("portable artifact root overlaps source")
    token = hashlib.sha256(f"{operation_id}\0{attempt}".encode()).hexdigest()
    return portable_attempts_parent(config, namespace) / token


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
            raise PortableRefreshError("portable control directory is not private")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


__all__ = ("_attempt_root", "_private_directory", "_publication_root", "portable_attempts_parent")
