"""Zsh file identity, startup, and completion observations."""

from __future__ import annotations

import re
from pathlib import Path

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    ZSH_STARTUP_FILENAMES,
    configuration_metadata,
    is_dynamic_value,
    redaction_for_value,
    split_words,
    zsh_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug

ZSH_SHEBANG_RE = re.compile(r"^#!.*(?:^|/|\s)zsh(?:\s|$)")
ZSH_STARTUP_ORDER = {
    ".zshenv": "early",
    ".zprofile": "login-before-zshrc",
    ".zshrc": "interactive",
    ".zlogin": "login-after-zshrc",
    ".zlogout": "logout",
}
ZSH_COMPLETION_PATH_PARTS = frozenset(
    {"functions", "completions", "completion", "site-functions"}
)


def is_zsh_shebang(line: str) -> bool:
    return bool(ZSH_SHEBANG_RE.match(line.strip()))


def is_zsh_file_path(path: Path) -> bool:
    return path.suffix == ".zsh" or path.name in ZSH_STARTUP_FILENAMES


def is_zsh_startup_file_path(path: Path) -> bool:
    return path.name in ZSH_STARTUP_FILENAMES


def is_zsh_completion_candidate(path: Path, content: str | None = None) -> bool:
    if path.name.startswith("_") and any(
        part in ZSH_COMPLETION_PATH_PARTS for part in path.parts[:-1]
    ):
        return True
    if content is None:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
    return has_completion_content_evidence(content)


def has_completion_content_evidence(content: str) -> bool:
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#compdef"):
            return True
        if stripped.startswith("_arguments"):
            return True
    return False


def zsh_script_observation(relative_path: str, content: str) -> RawObservation:
    first = content.splitlines()[0].strip() if content.splitlines() else ""
    metadata = zsh_metadata(
        {
            "file_type": file_type(relative_path, content),
            "shebang": first if first.startswith("#!") else None,
            "classification_evidence": classification_evidence(relative_path, content),
            "parser": "stdlib-static-scanner",
        }
    )
    return RawObservation(
        kind="zsh.script",
        source_id=f"{relative_path}#zsh-script",
        path=relative_path,
        name=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def classification_evidence(relative_path: str, content: str) -> list[str]:
    path = Path(relative_path)
    first = content.splitlines()[0].strip() if content.splitlines() else ""
    evidence: list[str] = []
    if path.suffix == ".zsh":
        evidence.append("extension")
    if is_zsh_shebang(first):
        evidence.append("shebang")
    if path.name in ZSH_STARTUP_FILENAMES:
        evidence.append("startup_filename")
    if path.name.startswith("_") and any(
        part in ZSH_COMPLETION_PATH_PARTS for part in path.parts[:-1]
    ):
        evidence.append("completion_path")
    if re.search(r"^\s*#compdef\b", content, flags=re.MULTILINE):
        evidence.append("compdef")
    if re.search(r"^\s*_arguments(?:\s|$)", content, flags=re.MULTILINE):
        evidence.append("arguments_function")
    return evidence


def file_type(relative_path: str, content: str) -> str:
    path = Path(relative_path)
    if path.name in ZSH_STARTUP_FILENAMES:
        return "startup"
    if (
        "completion_path" in classification_evidence(relative_path, content)
        or has_completion_content_evidence(content)
    ):
        return "completion"
    if path.suffix == ".zsh" or is_zsh_shebang(
        content.splitlines()[0].strip() if content.splitlines() else ""
    ):
        return "script"
    return "unknown"


def startup_file_observation(relative_path: str) -> RawObservation | None:
    filename = Path(relative_path).name
    if filename not in ZSH_STARTUP_FILENAMES:
        return None
    startup_kind = filename.removeprefix(".")
    return RawObservation(
        kind="zsh.startup_file",
        source_id=f"{relative_path}#zsh-startup:{startup_kind}",
        path=relative_path,
        name=startup_kind,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "startup_file_kind": startup_kind,
                "startup_order": ZSH_STARTUP_ORDER.get(filename, "unknown"),
                "startup_executed": False,
                "profile_loaded": False,
            }
        ),
    )


def completion_function_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    path = Path(relative_path)
    if not is_zsh_completion_candidate(path, content):
        return ()
    completion_name = path.name[1:] if path.name.startswith("_") else path.stem
    compdef_target = None
    compdef_line = None
    uses_arguments = False
    arguments_line = None
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("#compdef"):
            words = split_words(stripped)
            if len(words) > 1 and not is_dynamic_value(words[1]):
                redacted, _reason = redaction_for_value(words[1])
                compdef_target = "[redacted]" if redacted else words[1]
            compdef_line = line_number
        elif stripped.startswith("_arguments"):
            uses_arguments = True
            arguments_line = line_number
    if compdef_line is None and arguments_line is None:
        return ()
    line_number = compdef_line or arguments_line or 1
    metadata = configuration_metadata(
        {
            "completion_name": completion_name,
            "compdef_target": compdef_target,
            "uses_arguments": uses_arguments,
            "completion_loaded": False,
            "compinit_executed": False,
        }
    )
    return (
        RawObservation(
            kind="zsh.completion_function",
            source_id=f"{relative_path}#zsh-completion-function:{line_number}:{slug(completion_name)}",
            path=relative_path,
            start_line=line_number,
            end_line=arguments_line or compdef_line or line_number,
            name=completion_name,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(metadata),
        ),
    )
