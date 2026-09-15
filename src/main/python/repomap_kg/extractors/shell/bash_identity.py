"""Bash file identity and script observations."""

from __future__ import annotations

import re
from pathlib import Path

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash_common import EXTRACTOR, bash_metadata
from repomap_kg.observations.raw import RawObservation

BASH_PROFILE_FILENAMES = frozenset({".bashrc", ".bash_profile", ".bash_login"})
BASH_SHEBANG_RE = re.compile(r"^#!.*(?:^|/|\s)bash(?:\s|$)")


def is_bash_file_path(path: Path) -> bool:
    return path.suffix == ".bash" or path.name in BASH_PROFILE_FILENAMES


def is_bash_shebang(line: str) -> bool:
    return bool(BASH_SHEBANG_RE.match(line.strip()))


def shell_script_observation(relative_path: str, content: str) -> RawObservation:
    first = content.splitlines()[0].strip() if content.splitlines() else ""
    evidence = classification_evidence(relative_path, first)
    metadata = bash_metadata(
        {
            "file_type": "script",
            "shebang": first if first.startswith("#!") else None,
            "classification_evidence": evidence,
        }
    )
    return RawObservation(
        kind="shell.script",
        source_id=f"{relative_path}#bash-script",
        path=relative_path,
        name=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def classification_evidence(relative_path: str, shebang: str) -> list[str]:
    path = Path(relative_path)
    evidence = []
    if path.suffix == ".bash":
        evidence.append("extension")
    if path.name in BASH_PROFILE_FILENAMES:
        evidence.append("filename")
    if is_bash_shebang(shebang):
        evidence.append("shebang")
    return evidence
