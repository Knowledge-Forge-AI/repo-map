"""Repository path classification, re-exported unchanged by ``graph.discovery``.

``classify_path`` and ``detect_language`` accept optional reader hooks so a
governed or observe-only sealing call can meter its classification reads. When
no hook is supplied, the module-global reader names are resolved at call time,
so the incumbent behavior and patch seams are preserved.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Protocol

from common_lore_index.extractors.languages.go_metadata import detect_go_generated_marker
from common_lore_index.extractors.shell.awk import is_awk_shebang
from common_lore_index.extractors.shell.bash import (
    BASH_PROFILE_FILENAMES,
    is_bash_file_path,
    is_bash_shebang,
)
from common_lore_index.extractors.shell.zsh import (
    is_zsh_completion_candidate,
    is_zsh_file_path,
    is_zsh_shebang,
    is_zsh_startup_file_path,
)
from common_lore_index.extractors.shell.zunit import is_zunit_file_path
from common_lore_index.graph.discovery_file_metadata import content_hash, first_line
from common_lore_index.graph.discovery_records import FileInfo
from common_lore_index.graph.profiles import ProjectProfile


class ClassificationReaderHooks(Protocol):
    def content_hash(self, path: Path) -> str: ...

    def first_line(self, path: Path) -> str: ...

    def is_go_generated_file(self, path: Path) -> bool: ...

    def completion(self, path: Path) -> bool: ...


GENERATED_DIR_NAMES = frozenset({"coverage", "generated", "reports"})
LANGUAGE_BY_EXTENSION = {
    ".applescript": "applescript",
    ".awk": "awk",
    ".bash": "bash",
    ".bats": "bats",
    ".css": "css",
    ".csv": "csv",
    ".eml": "eml",
    ".mbox": "mbox",
    ".htm": "html",
    ".html": "html",
    ".cjs": "javascript",
    ".json": "json",
    ".jsonc": "jsonc",
    ".jsonl": "jsonl",
    ".js": "javascript",
    ".jsx": "javascript",
    ".markdown": "markdown",
    ".md": "markdown",
    ".mjs": "javascript",
    ".mts": "javascript",
    ".nix": "nix",
    ".ods": "odf",
    ".odt": "odf",
    ".ots": "odf",
    ".ott": "odf",
    ".plist": "plist",
    ".ps1": "powershell",
    ".psd1": "powershell",
    ".psm1": "powershell",
    ".py": "python",
    ".rake": "ruby",
    ".rb": "ruby",
    ".gemspec": "ruby",
    ".go": "go",
    ".sh": "shell",
    ".sql": "sql",
    ".latex": "latex",
    ".tex": "latex",
    ".tsv": "tsv",
    ".txt": "text",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".toml": "toml",
    ".cts": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zunit": "zunit",
    ".zsh": "zsh",
}
GO_METADATA_LANGUAGE_BY_NAME = {
    "go.mod": "go-module",
    "go.sum": "go-checksum",
    "go.work": "go-workspace",
}
RUBY_FILENAMES = frozenset({"Gemfile", "Rakefile", "Vagrantfile"})
CONFIG_FILENAMES = (
    frozenset(
        {
            ".gitignore",
            "flake.lock",
            "flake.nix",
            "pyproject.toml",
        }
    )
    | BASH_PROFILE_FILENAMES
)
PYTHON_REQUIREMENTS_NAME_PATTERN = re.compile(
    r"^(?:requirements(?:-[0-9A-Za-z_.-]+)?|dev-requirements|test-requirements)\.txt$"
)


def classify_path(
    root: Path | str,
    path: Path | str,
    *,
    profile: ProjectProfile | None = None,
    readers: ClassificationReaderHooks | None = None,
) -> FileInfo:
    repository_root = Path(root).resolve()
    file_path = Path(path).resolve()
    relative_path = file_path.relative_to(repository_root).as_posix()
    executable = os.access(file_path, os.X_OK)
    generated = is_generated(relative_path)
    if file_path.suffix == ".go":
        generated = generated or (
            is_go_generated_file(file_path)
            if readers is None
            else readers.is_go_generated_file(file_path)
        )
    language = (
        detect_language(file_path)
        if readers is None
        else detect_language(
            file_path, first_line_fn=readers.first_line, completion_fn=readers.completion
        )
    )
    role = detect_role(relative_path, executable=executable, generated=generated)
    confidence = "extracted"
    if profile is not None:
        generated = profile.generated_for_path(relative_path, generated)
        role = profile.role_for_path(relative_path, role)
        confidence = profile.confidence_for_path(relative_path, confidence)

    return FileInfo(
        path=relative_path,
        language=language,
        role=role,
        content_hash=(
            content_hash(file_path) if readers is None else readers.content_hash(file_path)
        ),
        executable=executable,
        generated=generated,
        confidence=confidence,
    )


def detect_language(
    path: Path,
    *,
    first_line_fn: Callable[[Path], str] | None = None,
    completion_fn: Callable[[Path], bool] | None = None,
) -> str:
    read_first_line = first_line if first_line_fn is None else first_line_fn
    go_metadata_language = GO_METADATA_LANGUAGE_BY_NAME.get(path.name)
    if go_metadata_language is not None:
        return go_metadata_language
    if path.name == "modules.txt" and path.parent.name == "vendor":
        return "go-vendor-manifest"
    if is_python_requirements_file_name(path.name):
        return "python"
    if path.name in RUBY_FILENAMES:
        return "ruby"
    if is_bash_file_path(path):
        return "bash"
    if is_zunit_file_path(path):
        return "zunit"
    if is_zsh_file_path(path):
        return "zsh"
    if path.suffix == ".sh" or path.name == ".profile":
        shebang = read_first_line(path)
        if is_zsh_shebang(shebang):
            return "zsh"
        if is_bash_shebang(shebang):
            return "bash"
    language = LANGUAGE_BY_EXTENSION.get(path.suffix)
    if language is not None:
        return language
    shebang = read_first_line(path)
    if shebang.startswith("#!"):
        if is_zsh_shebang(shebang):
            return "zsh"
        if is_awk_shebang(shebang):
            return "awk"
        if "python" in shebang:
            return "python"
        if "bash" in shebang or "sh" in shebang or "zsh" in shebang:
            return "shell"
        if "ruby" in shebang:
            return "ruby"
    if (
        is_zsh_completion_candidate(path)
        if completion_fn is None
        else completion_fn(path)
    ):
        return "zsh"
    return "unknown"


def detect_role(relative_path: str, *, executable: bool, generated: bool) -> str:
    parts = relative_path.split("/")
    filename = parts[-1]
    if generated:
        return "generated"
    if filename.endswith(("_test.go", ".bats", ".zunit")):
        return "test"
    if "test" in parts or "tests" in parts or ".test." in filename:
        return "test"
    if relative_path.startswith("docs/") or filename.endswith(".md"):
        return "documentation"
    if (
        filename in CONFIG_FILENAMES
        or filename in ("go.mod", "go.sum", "go.work")
        or (filename == "modules.txt" and "vendor" in parts)
        or is_zsh_startup_file_path(Path(filename))
        or is_python_requirements_file_name(filename)
        or filename.endswith(".psd1")
        or filename.endswith(".plist")
        or filename.endswith(".tf")
        or filename.endswith(".tfvars")
        or relative_path.startswith(".github/")
    ):
        return "config"
    if filename.endswith((".awk", ".go")):
        return "source"
    if filename.endswith(".zsh") or is_zsh_completion_candidate(
        Path(relative_path), ""
    ):
        return "source"
    if executable or relative_path.startswith("bin/"):
        return "entrypoint"
    if relative_path.startswith("src/"):
        return "source"
    return "unknown"


def is_python_requirements_file_name(relative_path: str) -> bool:
    return bool(PYTHON_REQUIREMENTS_NAME_PATTERN.match(Path(relative_path).name))


def is_generated(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return any(part in GENERATED_DIR_NAMES for part in parts)


def is_go_generated_file(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as handle:
            content = "".join(handle.readline() for _ in range(40))
    except UnicodeDecodeError:
        return False
    return detect_go_generated_marker(content) is not None


__all__ = (
    "CONFIG_FILENAMES",
    "ClassificationReaderHooks",
    "GENERATED_DIR_NAMES",
    "GO_METADATA_LANGUAGE_BY_NAME",
    "LANGUAGE_BY_EXTENSION",
    "PYTHON_REQUIREMENTS_NAME_PATTERN",
    "RUBY_FILENAMES",
    "classify_path",
    "detect_language",
    "detect_role",
    "is_generated",
    "is_go_generated_file",
    "is_python_requirements_file_name",
)
