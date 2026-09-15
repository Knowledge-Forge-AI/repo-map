"""Source-reference observation helpers for JavaScript extraction."""

from __future__ import annotations

import re

from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_observations import (
    PARSER,
    _observation,
    _reference_observation,
)
from repomap_kg.extractors.languages.javascript_references import (
    _safe_summary,
    _sanitize_url,
    _specifier_target,
)


FETCH_LITERAL_RE = re.compile(
    r"""\b(?P<call>fetch|axios\.get)\s*\(\s*(?P<quote>["'])(?P<url>.+?)(?P=quote)"""
)
IMPORT_SCRIPTS_RE = re.compile(
    r"""\bimportScripts\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
SOURCE_MAP_RE = re.compile(r"""sourceMappingURL=(?P<specifier>\S+)""")
ANGULAR_TEMPLATE_RE = re.compile(
    r"""\b(?P<kind>templateUrl|styleUrls?)\s*:\s*(?:\[\s*)?(?P<quote>["'])(?P<path>.+?)(?P=quote)"""
)


def _import_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    import_kind: str,
    specifier: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
    *,
    dynamic: bool = False,
) -> tuple[RawObservation, ...]:
    target, reason = _specifier_target(relative_path, specifier, repository_paths)
    import_observation = _observation(
        kind="js.import",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-import:{line_number}:{len(specifier)}",
        start_line=line_number,
        name=_safe_summary(specifier),
        target=target,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "import_kind": import_kind,
            "import_specifier": _safe_summary(_sanitize_url(specifier)),
            "source_key": source_key,
            "target_key": target,
            "not_loaded": True,
            "dynamic": dynamic,
            "dynamic_reason": "dynamic-import" if dynamic else None,
        },
    )
    reference = _reference_observation(
        relative_path,
        js_format,
        profile,
        line_number,
        import_kind,
        specifier,
        target,
        source_key,
        resolution_reason=reason,
        dynamic=dynamic,
        extra_metadata={"import_kind": import_kind},
    )
    return (import_observation, reference)


def _export_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    export_kind: str,
    specifier: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    target, reason = _specifier_target(relative_path, specifier, repository_paths)
    export_observation = _observation(
        kind="js.export",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-export:{line_number}:{len(specifier)}",
        start_line=line_number,
        name=_safe_summary(specifier),
        target=target,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "export_kind": export_kind,
            "import_specifier": _safe_summary(_sanitize_url(specifier)),
            "source_key": source_key,
            "target_key": target,
            "not_loaded": True,
        },
    )
    reference = _reference_observation(
        relative_path,
        js_format,
        profile,
        line_number,
        export_kind,
        specifier,
        target,
        source_key,
        resolution_reason=reason,
        extra_metadata={"export_kind": export_kind},
    )
    return (export_observation, reference)


def _literal_reference_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for match in FETCH_LITERAL_RE.finditer(line):
        raw_url = match.group("url")
        target, reason = _specifier_target(relative_path, raw_url, repository_paths)
        if target.startswith("external.url:"):
            observations.append(
                _reference_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    match.group("call"),
                    raw_url,
                    target,
                    source_key,
                    resolution_reason=reason,
                )
            )
    for match in IMPORT_SCRIPTS_RE.finditer(line):
        specifier = match.group("specifier")
        target, reason = _specifier_target(relative_path, specifier, repository_paths)
        observations.append(
            _reference_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                "importScripts",
                specifier,
                target,
                source_key,
                resolution_reason=reason,
            )
        )
    source_map_match = SOURCE_MAP_RE.search(line)
    if source_map_match:
        specifier = source_map_match.group("specifier")
        target, reason = _specifier_target(relative_path, specifier, repository_paths)
        observations.append(
            _reference_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                "source_map",
                specifier,
                target,
                source_key,
                resolution_reason=reason,
                extra_metadata={"not_fetched": True},
            )
        )
    if profile == "angular":
        for match in ANGULAR_TEMPLATE_RE.finditer(line):
            raw_path = match.group("path")
            target, reason = _specifier_target(relative_path, raw_path, repository_paths)
            observations.append(
                _reference_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    match.group("kind"),
                    raw_path,
                    target,
                    source_key,
                    resolution_reason=reason,
                )
            )
    return tuple(observations)


def _dynamic_reasons(line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "${" in line or "`" in line and ("import(" in line or "require(" in line):
        reasons.append("interpolation")
    if re.search(r"\bimport\s*\(\s*[^\"'`]", line) or re.search(
        r"\bimport\s*\(\s*`", line
    ):
        reasons.append("dynamic-import")
    if re.search(r"\brequire\s*\(\s*[^\"']", line):
        reasons.append("dynamic-require")
    for token in ("eval", "Function"):
        if re.search(rf"\b{re.escape(token)}\b", line):
            reasons.append(token)
    return tuple(dict.fromkeys(reasons))
