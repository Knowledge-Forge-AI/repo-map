"""Line-level references for conservative JavaScript extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from repomap_kg.extractors.languages.javascript_jquery import _jquery_observations
from repomap_kg.extractors.languages.javascript_observations import (
    PARSER,
    _diagnostic_observation,
    _framework_observation,
    _framework_specifier_observation,
    _observation,
    _parse_error,
)
from repomap_kg.extractors.languages.javascript_reference_observations import (
    _dynamic_reasons,
    _export_observations,
    _import_observations,
    _literal_reference_observations,
)
from repomap_kg.extractors.languages.javascript_references import (
    _is_secret_prone,
    _safe_summary,
    _sanitize_url,
    _specifier_target,
)
from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class JavaScriptReferencePatterns:
    """Patchable regular expressions supplied by the extractor facade."""

    import_from: re.Pattern[str]
    side_effect_import: re.Pattern[str]
    export_from: re.Pattern[str]
    export_decl: re.Pattern[str]
    dynamic_import_literal: re.Pattern[str]
    require_literal: re.Pattern[str]
    env: re.Pattern[str]
    module_exports: re.Pattern[str]
    named_exports: re.Pattern[str]


def add_line_reference_observations(
    *,
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    stripped: str,
    module_canonical_key: str,
    repository_paths: frozenset[str] | None,
    observations: list[RawObservation],
    add_framework_observation: Callable[[RawObservation], None],
    patterns: JavaScriptReferencePatterns,
) -> None:
    for dynamic_reason in _dynamic_reasons(stripped):
        observations.append(
            _parse_error(
                relative_path,
                js_format,
                profile,
                f"dynamic-{dynamic_reason}",
                "dynamic JavaScript construct kept as diagnostic",
                line_number,
                dynamic_reason=dynamic_reason,
            )
        )

    for env_name in patterns.env.findall(stripped):
        redacted = _is_secret_prone(env_name)
        observations.append(
            _diagnostic_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                "env-reference",
                env_name,
                redacted=redacted,
            )
        )
        add_framework_observation(
            _framework_observation(
                "js.framework_reference",
                relative_path,
                js_format,
                profile,
                line_number,
                "environment",
                module_canonical_key,
                metadata={
                    "reference_kind": "environment",
                    "env_name": None if redacted else env_name,
                    "redacted": redacted,
                    "redaction_reason": (
                        "secret-prone-env-name" if redacted else None
                    ),
                },
            )
        )

    import_match = patterns.import_from.match(stripped)
    if import_match:
        specifier = import_match.group("specifier")
        import_kind = (
            "type_import"
            if import_match.group("body").strip().startswith("type ")
            else "import"
        )
        observations.extend(
            _import_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                import_kind,
                specifier,
                module_canonical_key,
                repository_paths,
            )
        )
        framework_reference = _framework_specifier_observation(
            relative_path,
            js_format,
            profile,
            line_number,
            specifier,
            module_canonical_key,
        )
        if framework_reference is not None:
            add_framework_observation(framework_reference)
    else:
        side_effect_match = patterns.side_effect_import.match(stripped)
        if side_effect_match and not stripped.startswith("import("):
            specifier = side_effect_match.group("specifier")
            observations.extend(
                _import_observations(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "side_effect_import",
                    specifier,
                    module_canonical_key,
                    repository_paths,
                )
            )
            framework_reference = _framework_specifier_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                specifier,
                module_canonical_key,
            )
            if framework_reference is not None:
                add_framework_observation(framework_reference)

    export_from_match = patterns.export_from.match(stripped)
    if export_from_match:
        specifier = export_from_match.group("specifier")
        observations.extend(
            _export_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                "re_export",
                specifier,
                module_canonical_key,
                repository_paths,
            )
        )
        framework_reference = _framework_specifier_observation(
            relative_path,
            js_format,
            profile,
            line_number,
            specifier,
            module_canonical_key,
        )
        if framework_reference is not None:
            add_framework_observation(framework_reference)
    else:
        export_decl_match = patterns.export_decl.match(stripped)
        if export_decl_match:
            observations.append(
                _observation(
                    kind="js.export",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#js-export:{line_number}",
                    start_line=line_number,
                    name=export_decl_match.group("name"),
                    metadata={
                        "format": js_format,
                        "profile": profile,
                        "parser": PARSER,
                        "export_kind": export_decl_match.group("kind"),
                        "exported_name": export_decl_match.group("name"),
                        "source_key": module_canonical_key,
                    },
                )
            )

    for match in patterns.require_literal.finditer(stripped):
        specifier = match.group("specifier")
        observations.extend(
            _import_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                "require",
                specifier,
                module_canonical_key,
                repository_paths,
            )
        )
        target, reason = _specifier_target(relative_path, specifier, repository_paths)
        add_framework_observation(
            _framework_observation(
                "node.require",
                relative_path,
                js_format,
                profile,
                line_number,
                specifier,
                module_canonical_key,
                target=target,
                metadata={
                    "specifier": _safe_summary(_sanitize_url(specifier)),
                    "target_key": target,
                    "resolution_reason": reason,
                    "module_system": "commonjs",
                    "not_loaded": True,
                },
            )
        )
        framework_reference = _framework_specifier_observation(
            relative_path,
            js_format,
            profile,
            line_number,
            specifier,
            module_canonical_key,
        )
        if framework_reference is not None:
            add_framework_observation(framework_reference)

    if patterns.module_exports.search(stripped):
        add_framework_observation(
            _framework_observation(
                "node.export",
                relative_path,
                js_format,
                profile,
                line_number,
                "module.exports",
                module_canonical_key,
                metadata={
                    "export_kind": "module.exports",
                    "module_system": "commonjs",
                },
            )
        )
    for match in patterns.named_exports.finditer(stripped):
        add_framework_observation(
            _framework_observation(
                "node.export",
                relative_path,
                js_format,
                profile,
                line_number,
                match.group("name"),
                module_canonical_key,
                metadata={
                    "export_kind": "exports.name",
                    "exported_name": match.group("name"),
                    "module_system": "commonjs",
                },
            )
        )

    for match in patterns.dynamic_import_literal.finditer(stripped):
        specifier = match.group("specifier")
        observations.extend(
            _import_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                "dynamic_import",
                specifier,
                module_canonical_key,
                repository_paths,
                dynamic=True,
            )
        )

    observations.extend(
        _literal_reference_observations(
            relative_path,
            js_format,
            profile,
            line_number,
            stripped,
            module_canonical_key,
            repository_paths,
        )
    )

    for framework_observation in _jquery_observations(
        relative_path,
        js_format,
        profile,
        line_number,
        stripped,
        module_canonical_key,
        repository_paths,
    ):
        if framework_observation.kind == "js.parse_error":
            observations.append(framework_observation)
        else:
            add_framework_observation(framework_observation)
