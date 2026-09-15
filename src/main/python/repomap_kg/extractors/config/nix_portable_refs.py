"""Non-evaluating Nix input-reference and module-export extraction."""

from __future__ import annotations

from collections.abc import Callable
import re

from repomap_kg.extractors.config.nix_common import EXTRACTOR_NAME, slug
from repomap_kg.observations.raw import RawObservation


_INPUT_REFERENCE_PATTERN = re.compile(
    r"\binputs\.(?P<input>[A-Za-z0-9_-]+)"
    r"(?:\.nixosModules\.(?P<module>[A-Za-z0-9_-]+))?\b"
)
_MODULE_EXPORT_DIRECT_PATTERN = re.compile(
    r"(?:^|[;{])\s*nixosModules\.(?P<name>[A-Za-z0-9_-]+)\s*=\s*"
    r"(?:(?P<syntax>import)\s+)?"
    r"(?P<path>(?:\./|\.\./)[0-9A-Za-z_./+-]+)\s*(?:;|$)"
)
_MODULE_EXPORT_ATTRSET_PATTERN = re.compile(
    r"(?<![0-9A-Za-z_.-])(?P<name>[A-Za-z0-9_-]+)\s*=\s*"
    r"(?:(?P<syntax>import)\s+)?"
    r"(?P<path>(?:\./|\.\./)[0-9A-Za-z_./+-]+)\s*;?"
)
_MODULE_EXPORT_ATTRSET_START_PATTERN = re.compile(r"^\s*nixosModules\s*=\s*\{")
_HELPER_FRAMEWORK_TOKENS = (
    "eachDefaultSystem",
    "genAttrs",
    "forAllSystems",
    "flake-utils",
    "flake-parts",
)


def extract_input_reference_observations(
    relative_path: str, content: str, *, extractor_version: str
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for ordinal, match in enumerate(
            _INPUT_REFERENCE_PATTERN.finditer(line), start=1
        ):
            expression = match.group(0)
            evaluation_dependency = None
            if "${" in line:
                evaluation_dependency = "interpolation"
            elif re.search(r"\b(if|then|else)\b", line):
                evaluation_dependency = "conditional"
            observations.append(
                RawObservation(
                    kind="nix.input_ref",
                    source_id=(
                        f"{relative_path}#nix-input-ref:{line_number}:{ordinal}:"
                        f"{slug(match.group('input'))}"
                    ),
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    name=match.group("input"),
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=extractor_version,
                    metadata={
                        "expression": expression,
                        "input_name": match.group("input"),
                        "module_name": match.group("module"),
                        "evaluation_dependency": evaluation_dependency,
                        "syntax": "flake-input-reference",
                    },
                )
            )
    return tuple(observations)


def extract_module_export_observations(
    relative_path: str,
    content: str,
    *,
    flake_ref: str,
    extractor_version: str,
    resolve_repo_path: Callable[[str, str], str | None],
) -> tuple[RawObservation, ...]:
    """Extract only directly visible literal ``nixosModules`` exports."""

    observations: list[RawObservation] = []
    attrset_depth = 0
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = _strip_nix_line_comment(raw_line)
        if not line.strip():
            continue
        unsupported_line = (
            "${" in line
            or "//" in line
            or any(token in line for token in _HELPER_FRAMEWORK_TOKENS)
            or re.search(r"\b(if|then|else|inherit)\b", line) is not None
        )
        direct_match = (
            None if unsupported_line else _MODULE_EXPORT_DIRECT_PATTERN.search(line)
        )
        if direct_match is not None:
            _append_module_export(
                observations,
                relative_path,
                line_number,
                flake_ref,
                extractor_version,
                direct_match,
                resolve_repo_path,
            )

        start_match = _MODULE_EXPORT_ATTRSET_START_PATTERN.match(line)
        if attrset_depth > 0:
            member_matches = (
                ()
                if unsupported_line or attrset_depth != 1
                else _MODULE_EXPORT_ATTRSET_PATTERN.finditer(line)
            )
            for member_match in member_matches:
                _append_module_export(
                    observations,
                    relative_path,
                    line_number,
                    flake_ref,
                    extractor_version,
                    member_match,
                    resolve_repo_path,
                )
            attrset_depth = max(0, attrset_depth + line.count("{") - line.count("}"))
            continue

        if start_match is not None and not unsupported_line:
            for member_match in _MODULE_EXPORT_ATTRSET_PATTERN.finditer(
                line[start_match.end() :]
            ):
                _append_module_export(
                    observations,
                    relative_path,
                    line_number,
                    flake_ref,
                    extractor_version,
                    member_match,
                    resolve_repo_path,
                )
            attrset_depth = max(0, line.count("{") - line.count("}"))
    return tuple(observations)


def _append_module_export(
    observations: list[RawObservation],
    relative_path: str,
    line_number: int,
    flake_ref: str,
    extractor_version: str,
    match: re.Match[str],
    resolve_repo_path: Callable[[str, str], str | None],
) -> None:
    resolved_path = resolve_repo_path(relative_path, match.group("path"))
    if resolved_path is None:
        return
    module_name = match.group("name")
    export_path = f"nixosModules.{module_name}"
    observations.append(
        RawObservation(
            kind="nix.module_export",
            source_id=(
                f"{relative_path}#nix-module-export:{line_number}:"
                f"{slug(export_path)}:{slug(resolved_path)}"
            ),
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=module_name,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=extractor_version,
            metadata={
                "flake_ref": flake_ref,
                "module_name": module_name,
                "export_path": export_path,
                "resolved_path": resolved_path,
                "literal_syntax": match.group("syntax") or "path",
                "resolution": "local",
            },
        )
    )


def _strip_nix_line_comment(line: str) -> str:
    return re.sub(r"/\*.*?\*/", "", line).split("#", 1)[0]


__all__ = ["extract_input_reference_observations", "extract_module_export_observations"]
