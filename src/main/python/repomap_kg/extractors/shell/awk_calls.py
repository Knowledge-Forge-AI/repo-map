"""Static AWK call and gawk extension observation builders."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.awk_runtime import (
    EXTRACTOR,
    argument_count_for_call,
    argument_count_for_statement,
    io_pipe_system_observations,
    resolved_include_path,
    target_info,
)
from repomap_kg.extractors.shell.base import slug
from repomap_kg.observations.raw import RawObservation


FUNCTION_RE = re.compile(
    r"^\s*function\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)"
)
BUILTIN_FAMILIES = {
    "print": "output",
    "printf": "output",
    "getline": "input",
    "system": "system",
    "close": "lifecycle",
    "length": "string",
    "substr": "string",
    "split": "string",
    "tolower": "string",
    "toupper": "string",
    "sprintf": "string",
    "index": "string",
    "sub": "regex",
    "gsub": "regex",
    "match": "regex",
    "gensub": "regex",
    "int": "numeric",
    "rand": "numeric",
    "srand": "numeric",
}
STATEMENT_BUILTINS = frozenset({"print", "printf", "getline"})


def awk2_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
    call_context: str,
    function_definitions: dict[str, str],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(include_extension_observations(relative_path, line_number, line, masked, dialect))
    observations.extend(
        builtin_call_observations(relative_path, line_number, line, masked, dialect, call_context)
    )
    observations.extend(
        user_function_call_observations(
            relative_path,
            line_number,
            line,
            masked,
            dialect,
            call_context,
            function_definitions,
        )
    )
    observations.extend(io_pipe_system_observations(relative_path, line_number, line, masked, dialect))
    return tuple(observations)



def builtin_call_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
    call_context: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    stripped = masked.strip()
    seen: set[str] = set()
    for builtin in sorted(BUILTIN_FAMILIES):
        if builtin in STATEMENT_BUILTINS and re.match(rf"^{builtin}\b", stripped):
            observations.append(
                builtin_call_observation(
                    relative_path,
                    line_number,
                    builtin,
                    call_context,
                    argument_count_for_statement(line, builtin),
                    dialect,
                )
            )
            seen.add(builtin)
        if re.search(rf"\b{re.escape(builtin)}\s*\(", masked):
            if builtin in seen:
                continue
            observations.append(
                builtin_call_observation(
                    relative_path,
                    line_number,
                    builtin,
                    call_context,
                    argument_count_for_call(masked, builtin),
                    dialect,
                )
            )
            seen.add(builtin)
    if "getline" not in seen and re.search(r"\bgetline\b", masked):
        observations.append(
            builtin_call_observation(
                relative_path,
                line_number,
                "getline",
                call_context,
                argument_count_for_statement(line, "getline"),
                dialect,
            )
        )
    return tuple(observations)


def builtin_call_observation(
    relative_path: str,
    line_number: int,
    builtin: str,
    call_context: str,
    argument_count: int | None,
    dialect: str,
) -> RawObservation:
    return RawObservation(
        kind="awk.builtin_call",
        source_id=f"{relative_path}#awk-builtin:{line_number}:{slug(builtin)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=builtin,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=awk_metadata(
            dialect,
            {
                "builtin_name": builtin,
                "builtin_family": BUILTIN_FAMILIES.get(builtin, "unknown"),
                "argument_count": argument_count,
                "call_context": call_context,
            },
        ),
    )


def user_function_call_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
    call_context: str,
    function_definitions: dict[str, str],
) -> tuple[RawObservation, ...]:
    if FUNCTION_RE.match(line.strip()):
        return ()
    observations: list[RawObservation] = []
    for function_name, source_id in sorted(function_definitions.items()):
        if re.search(rf"\b{re.escape(function_name)}\s*\(", masked) is None:
            continue
        observations.append(
            RawObservation(
                kind="awk.user_function_call",
                source_id=f"{relative_path}#awk-user-call:{line_number}:{slug(function_name)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=function_name,
                target=source_id,
                confidence="heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=awk_metadata(
                    dialect,
                    {
                        "function_name": function_name,
                        "definition_source_id": source_id,
                        "argument_count": argument_count_for_call(masked, function_name),
                        "call_context": call_context,
                        "function_executed": False,
                        "return_value_inferred": False,
                    },
                ),
            )
        )
    return tuple(observations)


def include_extension_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
) -> tuple[RawObservation, ...]:
    stripped = masked.strip()
    include_match = re.match(r"^@include\b", stripped)
    load_match = re.match(r"^@load\b", stripped)
    if include_match is None and load_match is None:
        return ()
    expression = line.split(maxsplit=1)[1] if len(line.split(maxsplit=1)) > 1 else ""
    target = target_info(expression, secret_source="include_target")
    gawk_dialect = "gawk" if dialect != "gawk" else dialect
    if include_match is not None:
        metadata = awk_metadata(
            gawk_dialect,
            {
                "include_target": target["display"],
                "target_kind": target["kind"],
                "resolution": target["resolution"],
                "resolved_path": resolved_include_path(relative_path, target),
                "file_read": False,
                "include_loaded": False,
                "raw_value_stored": target["raw_value_stored"],
                **target.get("extra", {}),
            },
        )
        return (
            RawObservation(
                kind="awk.include",
                source_id=f"{relative_path}#awk-include:{line_number}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=target["display"],
                target=target["display"] if target["kind"] == "static" else None,
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=metadata,
            ),
        )
    metadata = awk_metadata(
        gawk_dialect,
        {
            "extension_name": target["display"],
            "target_kind": target["kind"],
            "resolution": target["resolution"],
            "extension_loaded": False,
            "raw_value_stored": target["raw_value_stored"],
            **target.get("extra", {}),
        },
    )
    return (
        RawObservation(
            kind="awk.extension",
            source_id=f"{relative_path}#awk-extension:{line_number}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=target["display"],
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=metadata,
        ),
    )


def awk_metadata(dialect: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "language": "awk",
        "dialect": dialect,
        "static_only": True,
        "awk_executed": False,
        "shell_executed": False,
        **metadata,
    }
