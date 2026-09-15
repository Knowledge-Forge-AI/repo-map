"""PowerShell alias-definition helpers."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    _is_dynamic_token,
    _strip_quotes,
    slug,
)
from repomap_kg.extractors.shell.powershell_tokens import _command_tokens
from repomap_kg.extractors.shell.powershell_vocabulary import (
    CANONICAL_CMDLETS,
    EXTERNAL_COMMANDS,
)
from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class AliasDefinition:
    alias_name: str
    target_name: str
    target_family: str
    source_id: str


def _alias_definition_observation(
    relative_path: str,
    line_number: int,
    stripped: str,
) -> RawObservation | None:
    tokens = _command_tokens(stripped)
    if not tokens or tokens[0].lower() not in {"set-alias", "new-alias"}:
        return None
    alias_name, target_name = _alias_definition_parts(tokens[1:])
    if alias_name is None or target_name is None:
        return None
    alias_name = _strip_quotes(alias_name)
    target_name = _strip_quotes(target_name)
    if _is_dynamic_token(alias_name) or _is_dynamic_token(target_name):
        return RawObservation(
            kind="powershell.alias_definition",
            source_id=f"{relative_path}#alias-definition:{line_number}:dynamic",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name="[dynamic]",
            confidence="unknown",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata={
                "resolution": "unknown",
                "unknown_reason": "dynamic-alias-definition",
                "static_only": True,
                "powershell_executed": False,
            },
        )
    target_family = _alias_target_family(target_name)
    return RawObservation(
        kind="powershell.alias_definition",
        source_id=f"{relative_path}#alias-definition:{line_number}:{slug(alias_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=alias_name,
        target=(
            f"tool:{target_name.lower()}"
            if target_family == "external"
            else f"powershell.command:{target_name}"
        ),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "alias_name": alias_name,
            "target_name": target_name,
            "target_family": target_family,
            "definition_scope": "file",
            "static_only": True,
            "powershell_executed": False,
        },
    )


def _alias_definition_parts(tokens: list[str]) -> tuple[str | None, str | None]:
    alias_name: str | None = None
    target_name: str | None = None
    positional: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if lowered in {"-name", "-value"} and index + 1 < len(tokens):
            if lowered == "-name":
                alias_name = tokens[index + 1]
            else:
                target_name = tokens[index + 1]
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        positional.append(token)
        index += 1
    if alias_name is None and positional:
        alias_name = positional[0]
    if target_name is None and len(positional) > 1:
        target_name = positional[1]
    return alias_name, target_name


def _alias_target_family(target_name: str) -> str:
    if CANONICAL_CMDLETS.get(target_name.lower()) is not None:
        return "cmdlet"
    if target_name.lower() in EXTERNAL_COMMANDS:
        return "external"
    return "unknown"
