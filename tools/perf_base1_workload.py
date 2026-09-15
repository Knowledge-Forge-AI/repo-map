"""Deterministic public-safe source workload for PERF-BASE1."""

from __future__ import annotations

import hashlib
from pathlib import Path


PYTHON_FILES = 2_048
ANCILLARY_FILES_PER_FAMILY = 8


def create_representative_source(root: Path) -> dict[str, object]:
    """Create one bounded multi-language source tree and return safe counts."""

    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    digest = hashlib.sha256()
    file_count = 0
    for index in range(PYTHON_FILES):
        relative = Path("python") / f"module_{index:05d}.py"
        imported = [
            (index + offset) % PYTHON_FILES for offset in range(1, 5)
        ]
        content = "".join(
            f"from python.module_{target:05d} import function_{target:05d}\n"
            for target in imported
        )
        content += (
            f"\nclass Type_{index:05d}:\n"
            f"    value = {index}\n\n"
            f"def function_{index:05d}():\n"
            f"    return function_{imported[0]:05d} if False else {index}\n"
        )
        _write(root, relative, content, digest)
        file_count += 1

    families = {
        "javascript": ("js", _javascript),
        "go": ("go", _go),
        "bash": ("sh", _bash),
        "markdown": ("md", _markdown),
        "yaml": ("yaml", _yaml),
    }
    for family, (suffix, render) in families.items():
        for index in range(ANCILLARY_FILES_PER_FAMILY):
            _write(
                root,
                Path(family) / f"fixture_{index:02d}.{suffix}",
                render(index),
                digest,
            )
            file_count += 1
    return {
        "schema_version": 1,
        "file_count": file_count,
        "extractor_family_count": 6,
        "source_input_digest": digest.hexdigest(),
    }


def _write(root: Path, relative: Path, content: str, digest) -> None:
    target = root / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    target.chmod(0o600)
    digest.update(relative.as_posix().encode("utf-8"))
    digest.update(b"\0")
    digest.update(data)
    digest.update(b"\0")


def _javascript(index: int) -> str:
    return f"export function value{index}() {{ return {index}; }}\n"


def _go(index: int) -> str:
    return f"package fixture\n\nfunc Value{index}() int {{ return {index} }}\n"


def _bash(index: int) -> str:
    return f"#!/usr/bin/env bash\nvalue_{index}() {{ printf '%s\\n' {index}; }}\n"


def _markdown(index: int) -> str:
    return f"# Fixture {index}\n\n[related](../python/module_{index:05d}.py)\n"


def _yaml(index: int) -> str:
    return f"fixture:\n  id: {index}\n  enabled: true\n"


__all__ = [
    "ANCILLARY_FILES_PER_FAMILY",
    "PYTHON_FILES",
    "create_representative_source",
]
