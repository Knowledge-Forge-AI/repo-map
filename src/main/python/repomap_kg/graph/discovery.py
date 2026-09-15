"""Repository file discovery and classification."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePosixPath
from typing import Sequence

from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.languages.go_metadata import detect_go_generated_marker
from repomap_kg.extractors.languages.golang import (
    extract_go_repository_observations,
)
from repomap_kg.extractors.languages.python import PythonModuleIndex
from repomap_kg.extractors.shell.awk import is_awk_shebang
from repomap_kg.extractors.shell.bash import (
    BASH_PROFILE_FILENAMES,
    is_bash_file_path,
    is_bash_shebang,
)
from repomap_kg.extractors.shell.zsh import (
    is_zsh_completion_candidate,
    is_zsh_file_path,
    is_zsh_shebang,
    is_zsh_startup_file_path,
)
from repomap_kg.extractors.shell.zunit import is_zunit_file_path

# Same-name aliases are facade compatibility re-exports pinned by the PKG5 tests.
from repomap_kg.graph.discovery_extractors import (
    extract_awk_file_observations as extract_awk_file_observations,
    extract_awk_file_observations_from_file,
    extract_bash_file_observations as extract_bash_file_observations,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations as extract_bats_file_observations,
    extract_bats_file_observations_from_file,
    extract_config_file_observations as extract_config_file_observations,
    extract_config_file_observations_from_file,
    extract_css_file_observations as extract_css_file_observations,
    extract_css_file_observations_from_file,
    extract_document_file_observations as extract_document_file_observations,
    extract_document_file_observations_from_file,
    extract_eml_file_observations as extract_eml_file_observations,
    extract_eml_file_observations_from_file,
    extract_feed_file_observations as extract_feed_file_observations,
    extract_feed_file_observations_from_file,
    extract_html_file_observations as extract_html_file_observations,
    extract_html_file_observations_from_file,
    extract_go_metadata_observations_from_file,
    extract_javascript_file_observations as extract_javascript_file_observations,
    extract_javascript_file_observations_from_file,
    extract_markdown_file_observations as extract_markdown_file_observations,
    extract_markdown_file_observations_from_file,
    extract_mbox_file_observations as extract_mbox_file_observations,
    extract_mbox_file_observations_from_file,
    extract_nix_file_observations as extract_nix_file_observations,
    extract_nix_file_observations_from_file,
    extract_odf_file_observations as extract_odf_file_observations,
    extract_powershell_file_observations as extract_powershell_file_observations,
    extract_powershell_file_observations_from_file,
    extract_python_file_observations as extract_python_file_observations,
    extract_python_file_observations_from_file,
    extract_ruby_file_observations as extract_ruby_file_observations,
    extract_ruby_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations as extract_zsh_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations as extract_zunit_file_observations,
    extract_zunit_file_observations_from_file,
    markdown_anchor_index,
    markdown_anchors_for_content as markdown_anchors_for_content,
)
from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.graph.discovery_file_metadata import content_hash, first_line
from repomap_kg.graph.profiles import ProjectProfile
from repomap_kg.observations.raw import RawObservation


IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".direnv",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".serena",
        ".terraform",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
    }
)
DEFAULT_DISCOVERY_EXCLUDE_PATHS = tuple(sorted(IGNORED_DIR_NAMES))
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


def normalize_discovery_exclude_paths(
    exclude_paths: Sequence[str] = (),
) -> tuple[str, ...]:
    normalized: list[str] = []
    for exclude_path in exclude_paths:
        if not isinstance(exclude_path, str):
            raise ValueError("exclude path must be a string")
        candidate = exclude_path.strip().replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        candidate = candidate.rstrip("/")
        parsed = PurePosixPath(candidate)
        if not candidate or parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("exclude path must stay relative to the repository root")
        normalized.append(candidate)
    return tuple(normalized)


def _matches_glob(relative_path: str, pattern: str) -> bool:
    candidate = relative_path
    while candidate:
        if fnmatch.fnmatchcase(candidate, pattern):
            return True
        if "/" not in candidate:
            break
        candidate = candidate.rsplit("/", 1)[0]
    return False


def _is_excluded_relative_path(
    relative_path: str,
    exclude_paths: Sequence[str],
) -> bool:
    relative_path = relative_path.strip("/")
    if not relative_path:
        return False
    parts = relative_path.split("/")
    for exclude_path in exclude_paths:
        if any(marker in exclude_path for marker in "*?["):
            if _matches_glob(relative_path, exclude_path):
                return True
            continue
        if "/" not in exclude_path and exclude_path in parts:
            return True
        if relative_path == exclude_path or relative_path.startswith(
            f"{exclude_path}/"
        ):
            return True
    return False


def _relative_posix_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolved_path_stays_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def discover_repository(
    root: Path | str,
    *,
    profile: ProjectProfile | None = None,
    exclude_paths: Sequence[str] = (),
) -> list[FileInfo]:
    repository_root = Path(root).resolve()
    configured_excludes = normalize_discovery_exclude_paths(exclude_paths)
    files = []
    for directory, dirnames, filenames in os.walk(repository_root):
        directory_path = Path(directory)
        kept_dirnames = []
        for dirname in sorted(dirnames):
            dir_path = directory_path / dirname
            relative_dir = _relative_posix_path(repository_root, dir_path)
            if dir_path.is_symlink() and not _resolved_path_stays_under(
                repository_root, dir_path
            ):
                continue
            if dirname in IGNORED_DIR_NAMES or _is_excluded_relative_path(
                relative_dir, configured_excludes
            ):
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames
        for filename in sorted(filenames):
            file_path = directory_path / filename
            relative_file = _relative_posix_path(repository_root, file_path)
            if file_path.is_symlink() and not _resolved_path_stays_under(
                repository_root, file_path
            ):
                continue
            if not file_path.is_file():
                continue
            if _is_excluded_relative_path(relative_file, configured_excludes):
                continue
            files.append(classify_path(repository_root, file_path, profile=profile))
    files_by_path = {file_info.path: file_info for file_info in files}
    return sorted(files_by_path.values(), key=lambda file_info: file_info.path)


def discover_observations(
    root: Path | str,
    *,
    profile: ProjectProfile | None = None,
    exclude_paths: Sequence[str] = (),
) -> list[RawObservation]:
    repository_root = Path(root).resolve()
    file_infos = discover_repository(
        repository_root,
        profile=profile,
        exclude_paths=exclude_paths,
    )
    return extract_observations_from_repository_files(repository_root, file_infos)


def extract_observations_from_repository_files(
    repository_root: Path,
    file_infos: Sequence[FileInfo],
    *,
    nix_flake_ref: str | None = None,
    include_nix_input_references: bool = False,
) -> list[RawObservation]:
    """Extract observations from one already discovered static file inventory."""

    module_index = PythonModuleIndex.from_python_paths(
        (file_info.path for file_info in file_infos if file_info.language == "python"),
        repository_root=repository_root,
    )
    repository_paths = frozenset(file_info.path for file_info in file_infos)
    markdown_anchors = markdown_anchor_index(repository_root, file_infos)
    observations = []
    for file_info in file_infos:
        observations.append(file_info.to_observation())
        if file_info.language in ("go", "go-module", "go-workspace"):
            observations.extend(
                extract_go_metadata_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "markdown":
            observations.extend(
                extract_markdown_file_observations_from_file(
                    repository_root,
                    file_info,
                    repository_paths=repository_paths,
                    markdown_anchors=markdown_anchors,
                )
            )
        if file_info.language == "shell":
            observations.extend(
                extract_shell_file_observations(repository_root, file_info.path)
            )
        if file_info.language == "bash":
            observations.extend(
                extract_bash_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "bats":
            observations.extend(
                extract_bats_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "awk":
            observations.extend(
                extract_awk_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "zsh":
            observations.extend(
                extract_zsh_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "zunit":
            observations.extend(
                extract_zunit_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if is_python_requirements_file_name(file_info.path):
            observations.extend(
                extract_config_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        elif file_info.language == "python":
            observations.extend(
                extract_python_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    module_index=module_index,
                )
            )
        if file_info.language == "ruby":
            observations.extend(
                extract_ruby_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
        if file_info.language == "javascript":
            observations.extend(
                extract_javascript_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
        if file_info.language == "eml":
            observations.extend(
                extract_eml_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "mbox":
            observations.extend(
                extract_mbox_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "nix":
            observations.extend(
                extract_nix_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    flake_ref=nix_flake_ref,
                    include_input_references=include_nix_input_references,
                )
            )
        if file_info.language == "powershell":
            observations.extend(
                extract_powershell_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language in ("json", "xml"):
            feed_observations = extract_feed_file_observations_from_file(
                repository_root,
                file_info.path,
            )
            if feed_observations:
                observations.extend(feed_observations)
                continue
        if file_info.language in (
            "json",
            "jsonc",
            "jsonl",
            "toml",
            "terraform",
            "plist",
            "xml",
            "yaml",
        ):
            observations.extend(
                extract_config_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "html":
            observations.extend(
                extract_html_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "css":
            observations.extend(
                extract_css_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language in ("text", "csv", "tsv", "latex", "odf"):
            observations.extend(
                extract_document_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
    observations.extend(extract_go_repository_observations(repository_root, file_infos))
    observations.extend(extract_css_selector_match_observations(observations))
    return observations


def classify_path(
    root: Path | str, path: Path | str, *, profile: ProjectProfile | None = None
) -> FileInfo:
    repository_root = Path(root).resolve()
    file_path = Path(path).resolve()
    relative_path = file_path.relative_to(repository_root).as_posix()
    executable = os.access(file_path, os.X_OK)
    generated = is_generated(relative_path)
    if file_path.suffix == ".go":
        generated = generated or is_go_generated_file(file_path)
    language = detect_language(file_path)
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
        content_hash=content_hash(file_path),
        executable=executable,
        generated=generated,
        confidence=confidence,
    )


def detect_language(path: Path) -> str:
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
        shebang = first_line(path)
        if is_zsh_shebang(shebang):
            return "zsh"
        if is_bash_shebang(shebang):
            return "bash"
    language = LANGUAGE_BY_EXTENSION.get(path.suffix)
    if language is not None:
        return language
    shebang = first_line(path)
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
    if is_zsh_completion_candidate(path):
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
