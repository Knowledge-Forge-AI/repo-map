"""Symbol definition helpers for JavaScript extraction."""

from __future__ import annotations

import re

from repomap_kg.graph.keys import js_function_key, js_variable_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_observations import (
    PARSER,
    _component_observation,
    _definition_observation,
    _observation,
)
from repomap_kg.extractors.languages.javascript_references import (
    _is_secret_prone,
    _literal_type,
    _looks_like_secret_literal,
)


FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\b"""
)
FUNCTION_EXPR_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b"""
)
ARROW_FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"""
)
VARIABLE_RE = re.compile(
    r"""^\s*(?:export\s+)?(?P<kind>const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:=\s*(?P<value>.+?))?;?\s*$"""
)
INTERFACE_RE = re.compile(
    r"""^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)\b"""
)
TYPE_RE = re.compile(r"""^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\b""")
ENUM_RE = re.compile(r"""^\s*(?:export\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)\b""")


def _function_and_variable_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    function_name = None
    for regex in (FUNCTION_RE, FUNCTION_EXPR_RE, ARROW_FUNCTION_RE):
        match = regex.match(line)
        if match:
            function_name = match.group("name")
            break
    if function_name:
        function_key = js_function_key(relative_path, function_name)
        observations.append(
            _definition_observation(
                "js.function",
                relative_path,
                js_format,
                profile,
                line_number,
                function_name,
                function_key,
                source_key=source_key,
                metadata={
                    "function_name": function_name,
                    "qualified_name": function_name,
                },
            )
        )
        if _looks_like_component(function_name, profile, js_format, line):
            observations.append(
                _component_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    function_name,
                    source_key,
                )
            )

    variable_match = VARIABLE_RE.match(line)
    if variable_match:
        variable_name = variable_match.group("name")
        value = variable_match.group("value") or ""
        redacted = _is_secret_prone(variable_name) or _looks_like_secret_literal(value)
        metadata = {
            "variable_kind": variable_match.group("kind"),
            "local_name": variable_name,
            "literal_type": _literal_type(value),
            "redacted": redacted,
            "redaction_reason": "secret-prone-variable" if redacted else None,
        }
        observations.append(
            _definition_observation(
                "js.variable",
                relative_path,
                js_format,
                profile,
                line_number,
                variable_name,
                js_variable_key(relative_path, variable_name),
                source_key=source_key,
                metadata=metadata,
            )
        )
        if (
            function_name is None
            and (
                "defineComponent" in value
                or _looks_like_component(variable_name, profile, js_format, line)
            )
        ):
            observations.append(
                _component_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    variable_name,
                    source_key,
                )
            )
    return tuple(observations)


def _typescript_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for kind, regex in (
        ("js.interface", INTERFACE_RE),
        ("js.type_alias", TYPE_RE),
        ("js.enum", ENUM_RE),
    ):
        match = regex.match(line)
        if not match:
            continue
        name = match.group("name")
        observations.append(
            _observation(
                kind=kind,
                relative_path=relative_path,
                source_id=f"{relative_path}#{kind}:{name}:{line_number}",
                start_line=line_number,
                name=name,
                metadata={
                    "format": js_format,
                    "profile": profile,
                    "parser": PARSER,
                    "local_name": name,
                    "source_key": source_key,
                    "identity_strength": "symbolic",
                },
            )
        )
    return tuple(observations)


def _looks_like_component(name: str, profile: str, js_format: str, line: str) -> bool:
    if not name[:1].isupper():
        return False
    if name.isupper():
        return False
    return (
        profile in ("react", "vue", "angular")
        or js_format in ("jsx", "tsx")
        or "<" in line
    )
