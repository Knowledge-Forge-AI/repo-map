"""Static Nix raw observation extraction without evaluating Nix code."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.nix_common import (
    EXTRACTOR_NAME,
    IDENTIFIER_PATTERN,
    slug,
)
from repomap_kg.extractors.config.nix_inputs import (
    extract_flake_input_observations,
)
from repomap_kg.extractors.config.nix_paths import resolve_repo_path
from repomap_kg.extractors.config.nix_portable_refs import (
    extract_input_reference_observations,
    extract_module_export_observations,
)
from repomap_kg.graph.keys import (
    file_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_package_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

IMPORT_PATTERN = re.compile(
    r"\bimport\s+(?P<path>(?:\./|\../)[0-9A-Za-z_./+-]+\.nix)\b"
)
NIX_PATH_PATTERN = re.compile(
    r"(?<![0-9A-Za-z_$])(?P<path>(?:\./|\../)[0-9A-Za-z_./+-]+)"
)
OUTPUT_ATTR_PATTERN = re.compile(
    r"(?m)^\s*"
    r"(?P<root>apps|packages|devShells|checks)"
    r"\."
    r"(?P<system>[0-9A-Za-z_.+-]+)"
    r"\."
    r"(?P<name>[0-9A-Za-z_.+-]+)"
    r"\s*="
)
PROGRAM_ASSIGNMENT_PATTERN = re.compile(r"\bprogram\s*=\s*(?P<expr>[^;\n]+)")
SELF_PROGRAM_PATTERN = re.compile(r'^"\$\{self\}/(?P<path>[^"]+)"$')
TO_STRING_PROGRAM_PATTERN = re.compile(r"^toString\s+(?P<path>(?:\./|\../)\S+)$")
LITERAL_PROGRAM_PATTERN = re.compile(r"^(?P<path>(?:\./|\../)\S+)$")
OUTPUT_SECTIONS = (
    "homeManagerModules",
    "legacyPackages",
    "darwinModules",
    "nixosModules",
    "devShells",
    "packages",
    "overlays",
    "formatter",
    "templates",
    "checks",
    "apps",
)
OUTPUT_SECTION_NAMES_PATTERN = "|".join(OUTPUT_SECTIONS)
OUTPUT_SECTION_SUFFIX_COMPONENT_PATTERN = (
    rf"(?:{IDENTIFIER_PATTERN}|\"\$\{{[0-9A-Za-z_.+-]+\}}\"|\$\{{[0-9A-Za-z_.+-]+\}})"
)
OUTPUT_SECTION_SUFFIX_PATTERN = rf"(?:\.{OUTPUT_SECTION_SUFFIX_COMPONENT_PATTERN})*"
OUTPUT_SECTION_PATTERN = re.compile(
    rf"^\s*(?P<section>{OUTPUT_SECTION_NAMES_PATTERN})"
    rf"(?P<suffix>{OUTPUT_SECTION_SUFFIX_PATTERN})\s*="
)
OUTPUTS_ATTR_PATTERN = re.compile(r"^\s*outputs\s*=")
OUTPUT_BODY_SECTION_PATTERN = re.compile(
    rf"(?:^|[{{;]|\bin\s*{{)\s*"
    rf"(?P<section>{OUTPUT_SECTION_NAMES_PATTERN})"
    rf"(?P<suffix>{OUTPUT_SECTION_SUFFIX_PATTERN})\s*="
)
INHERIT_OUTPUT_SECTION_PATTERN = re.compile(
    rf"\binherit\s*(?:\([^)]*\)\s*)?"
    rf"(?P<names>[^;]*\b(?:{OUTPUT_SECTION_NAMES_PATTERN})\b[^;]*);"
)
HELPER_FRAMEWORK_TOKENS = (
    "eachDefaultSystem",
    "genAttrs",
    "forAllSystems",
    "flake-utils",
    "flake-parts",
)
IMPORTED_OUTPUTS_PATTERN = re.compile(
    r"^\s*(?P<name>[0-9A-Za-z_.+-]*[Oo]utputs[0-9A-Za-z_.+-]*)"
    r"\s*=\s*import\b"
)


def extract_nix_file_observations(
    relative_path: str,
    content: str,
    *,
    flake_ref: str,
    include_input_references: bool = False,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    consumed_paths: set[tuple[int, str]] = set()

    imports = _extract_import_observations(relative_path, content, consumed_paths)
    observations.extend(imports)
    if include_input_references:
        observations.extend(
            extract_input_reference_observations(
                relative_path, content, extractor_version=__version__
            )
        )

    if PurePosixPath(relative_path).name == "flake.nix":
        observations.extend(extract_flake_input_observations(relative_path, content))
        observations.extend(
            _extract_output_section_observations(relative_path, content)
        )
        if include_input_references:
            observations.extend(
                extract_module_export_observations(
                    relative_path,
                    content,
                    flake_ref=flake_ref,
                    extractor_version=__version__,
                    resolve_repo_path=resolve_repo_path,
                )
            )
        outputs, program_paths = _extract_flake_output_observations(
            relative_path,
            content,
            flake_ref=flake_ref,
        )
        observations.extend(outputs)
        consumed_paths.update(program_paths)

    observations.extend(
        _extract_path_ref_observations(relative_path, content, consumed_paths)
    )
    return tuple(observations)


def _extract_output_section_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    seen_sections: set[str] = set()
    merged_attrset_depth = 0
    brace_depth = 0
    in_outputs_context = False
    outputs_context_root_depth: int | None = None

    for line_number, line in enumerate(content.splitlines(), start=1):
        if OUTPUTS_ATTR_PATTERN.match(line) is not None:
            in_outputs_context = True
            outputs_context_root_depth = brace_depth

        starts_merged_attrset = "//" in line and "{" in line
        if IMPORTED_OUTPUTS_PATTERN.match(line) is not None:
            observations.append(
                _unsupported_flake_shape_observation(
                    relative_path,
                    line_number,
                    pattern="imported_outputs",
                    section="outputs",
                    reason="imported-output-shape-without-static-identity",
                    confidence_reason="imported-output-binding",
                )
            )
        if starts_merged_attrset:
            merged_attrset_depth = max(
                1,
                merged_attrset_depth + line.count("{") - line.count("}"),
            )
            observations.append(
                _unsupported_flake_shape_observation(
                    relative_path,
                    line_number,
                    pattern="merged_attrset",
                    section="outputs",
                    reason="merged-output-attrset-without-static-identity",
                    confidence_reason="merged-output-attrset",
                )
            )
        in_merged_attrset = merged_attrset_depth > 0

        inherit_match = INHERIT_OUTPUT_SECTION_PATTERN.search(line)
        if inherit_match is not None:
            for section in _inherited_output_sections(inherit_match.group("names")):
                if section in seen_sections:
                    continue
                seen_sections.add(section)
                observations.append(
                    _output_section_observation(
                        relative_path,
                        section,
                        line_number,
                        shape="inherit",
                        confidence_reason="inherited-output-section",
                    )
                )
                observations.append(
                    _unsupported_flake_shape_observation(
                        relative_path,
                        line_number,
                        pattern="inherit_outputs",
                        section=section,
                        reason="inherited-output-section-without-static-identity",
                        confidence_reason="inherited-output-section",
                    )
                )

        section_match = OUTPUT_SECTION_PATTERN.match(line)
        if section_match is not None:
            _append_output_section_observations(
                observations,
                seen_sections,
                relative_path,
                line,
                line_number,
                section=section_match.group("section"),
                suffix=section_match.group("suffix"),
                in_merged_attrset=in_merged_attrset,
                confidence_prefix="visible",
            )
        if in_outputs_context:
            for body_match in OUTPUT_BODY_SECTION_PATTERN.finditer(line):
                _append_output_section_observations(
                    observations,
                    seen_sections,
                    relative_path,
                    line,
                    line_number,
                    section=body_match.group("section"),
                    suffix=body_match.group("suffix"),
                    in_merged_attrset=in_merged_attrset,
                    confidence_prefix="output-body",
                )

        if merged_attrset_depth > 0 and not starts_merged_attrset:
            merged_attrset_depth += line.count("{") - line.count("}")
            if merged_attrset_depth <= 0:
                merged_attrset_depth = 0
        brace_depth += line.count("{") - line.count("}")
        if (
            in_outputs_context
            and outputs_context_root_depth is not None
            and brace_depth < outputs_context_root_depth
        ):
            in_outputs_context = False
            outputs_context_root_depth = None

    return tuple(observations)


def _append_output_section_observations(
    observations: list[RawObservation],
    seen_sections: set[str],
    relative_path: str,
    line: str,
    line_number: int,
    *,
    section: str,
    suffix: str,
    in_merged_attrset: bool,
    confidence_prefix: str,
) -> None:
    if section in seen_sections:
        return
    seen_sections.add(section)
    shape = _output_section_shape(
        line,
        suffix=suffix,
        in_merged_attrset=in_merged_attrset,
    )
    observations.append(
        _output_section_observation(
            relative_path,
            section,
            line_number,
            shape=shape,
            confidence_reason=f"{confidence_prefix}-{shape}-output-section",
        )
    )
    dynamic_pattern = _dynamic_output_pattern(line)
    if dynamic_pattern is not None:
        observations.append(
            _dynamic_output_shape_observation(
                relative_path,
                line_number,
                pattern=dynamic_pattern,
                section=section,
                reason="helper-generated-output-section",
                confidence_reason="dynamic-output-helper-pattern",
            )
        )
    unsupported = _unsupported_output_section_shape(section, shape)
    if unsupported is not None:
        pattern, reason = unsupported
        observations.append(
            _unsupported_flake_shape_observation(
                relative_path,
                line_number,
                pattern=pattern,
                section=section,
                reason=reason,
                confidence_reason=f"unsupported-{pattern}",
            )
        )


def _inherited_output_sections(names: str) -> tuple[str, ...]:
    tokens = re.findall(IDENTIFIER_PATTERN, names)
    return tuple(token for token in tokens if token in OUTPUT_SECTIONS)


def _output_section_observation(
    relative_path: str,
    section: str,
    line_number: int,
    *,
    shape: str,
    confidence_reason: str,
) -> RawObservation:
    return RawObservation(
        kind="nix.output_section",
        source_id=f"{relative_path}#nix-output-section:{line_number}:{slug(section)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=section,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "section": section,
            "section_family": _output_section_family(section),
            "scope": "unknown" if shape == "inherit" else "top_level_output",
            "shape": shape,
            "confidence_reason": confidence_reason,
        },
    )


def _output_section_family(section: str) -> str:
    if section in {"apps", "packages", "devShells", "checks"}:
        return "output"
    if section in {"nixosModules", "darwinModules", "homeManagerModules"}:
        return "module"
    if section == "overlays":
        return "overlay"
    if section == "formatter":
        return "formatter"
    if section == "templates":
        return "template"
    return "legacy_package"


def _dynamic_output_pattern(line: str) -> str | None:
    if "eachDefaultSystem" in line:
        return "eachDefaultSystem"
    if "genAttrs" in line:
        return "genAttrs"
    if "forAllSystems" in line:
        return "forAllSystems"
    if "flake-utils" in line:
        return "flake-utils"
    if "flake-parts" in line:
        return "flake-parts"
    if "${" in line:
        return "string_interpolation"
    return None


def _unsupported_output_section_shape(
    section: str,
    shape: str,
) -> tuple[str, str] | None:
    if section == "templates":
        return "template_section", "template-section-is-counted-only"
    if section == "legacyPackages":
        return "legacy_packages_section", "legacy-packages-section-is-counted-only"
    if shape == "nested_attrset":
        return (
            "nested_attrset_without_direct_identity",
            "nested-output-section-without-direct-identity",
        )
    if shape == "merged_attrset":
        return "merged_attrset", "merged-output-section-without-static-identity"
    if shape == "dynamic":
        return "unknown_dynamic", "dynamic-output-section-without-static-identity"
    if shape == "unknown":
        return "unknown_dynamic", "unknown-output-section-without-static-identity"
    return None


def _dynamic_output_shape_observation(
    relative_path: str,
    line_number: int,
    *,
    pattern: str,
    section: str,
    reason: str,
    confidence_reason: str,
) -> RawObservation:
    return _shape_diagnostic_observation(
        relative_path,
        line_number,
        kind="nix.dynamic_output_shape",
        pattern=pattern,
        section=section,
        reason=reason,
        confidence_reason=confidence_reason,
    )


def _unsupported_flake_shape_observation(
    relative_path: str,
    line_number: int,
    *,
    pattern: str,
    section: str,
    reason: str,
    confidence_reason: str,
) -> RawObservation:
    return _shape_diagnostic_observation(
        relative_path,
        line_number,
        kind="nix.unsupported_flake_shape",
        pattern=pattern,
        section=section,
        reason=reason,
        confidence_reason=confidence_reason,
    )


def _shape_diagnostic_observation(
    relative_path: str,
    line_number: int,
    *,
    kind: str,
    pattern: str,
    section: str,
    reason: str,
    confidence_reason: str,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=(
            f"{relative_path}#{kind}:{line_number}:{slug(section)}:{slug(pattern)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pattern,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "pattern": pattern,
            "section": section,
            "reason": reason,
            "counted_only": True,
            "confidence_reason": confidence_reason,
        },
    )


def _output_section_shape(
    line: str,
    *,
    suffix: str,
    in_merged_attrset: bool,
) -> str:
    if in_merged_attrset:
        return "merged_attrset"
    if any(token in line for token in HELPER_FRAMEWORK_TOKENS):
        return "helper_framework"
    if "${" in suffix:
        return "dynamic"
    if suffix:
        return "direct_assignment"
    if re.search(r"=\s*(?:rec\s*)?\{", line):
        return "nested_attrset"
    if "import " in line or "${" in line:
        return "dynamic"
    return "unknown"


def _extract_import_observations(
    relative_path: str,
    content: str,
    consumed_paths: set[tuple[int, str]],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    in_imports_list = False
    for line_number, line in enumerate(content.splitlines(), start=1):
        if "imports" in line and "=" in line and "[" in line:
            in_imports_list = True
        for match in IMPORT_PATTERN.finditer(line):
            import_path = match.group("path")
            consumed_paths.add((line_number, import_path))
            observations.append(
                _nix_import_observation(
                    relative_path,
                    import_path,
                    line_number,
                    syntax="import",
                )
            )
        if in_imports_list:
            for path_match in NIX_PATH_PATTERN.finditer(line):
                import_path = path_match.group("path")
                if not import_path.endswith(".nix"):
                    continue
                if (line_number, import_path) in consumed_paths:
                    continue
                consumed_paths.add((line_number, import_path))
                observations.append(
                    _nix_import_observation(
                        relative_path,
                        import_path,
                        line_number,
                        syntax="imports-list",
                    )
                )
        if in_imports_list and "]" in line:
            in_imports_list = False
    return tuple(observations)


def _nix_import_observation(
    relative_path: str,
    import_path: str,
    line_number: int,
    *,
    syntax: str,
) -> RawObservation:
    target, metadata = _path_target_metadata(
        relative_path,
        import_path,
        literal_field="import_path",
        repo_escaping_reason="repo-escaping-nix-import",
    )
    metadata["syntax"] = syntax
    return RawObservation(
        kind="nix.import",
        source_id=f"{relative_path}#nix-import:{line_number}:{slug(import_path)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        target=target,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _extract_flake_output_observations(
    relative_path: str,
    content: str,
    *,
    flake_ref: str,
) -> tuple[tuple[RawObservation, ...], set[tuple[int, str]]]:
    matches = list(OUTPUT_ATTR_PATTERN.finditer(content))
    observations: list[RawObservation] = []
    program_paths: set[tuple[int, str]] = set()
    for index, match in enumerate(matches):
        block_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(content)
        )
        block = content[match.start() : block_end]
        start_line = content.count("\n", 0, match.start()) + 1
        end_line = start_line + max(0, block.count("\n"))
        root = match.group("root")
        system = match.group("system")
        name = match.group("name")
        observation, consumed_program_path = _flake_output_observation(
            relative_path,
            root,
            system,
            name,
            start_line,
            end_line,
            block,
            flake_ref=flake_ref,
        )
        observations.append(observation)
        if consumed_program_path is not None:
            program_paths.add(consumed_program_path)
    return tuple(observations), program_paths


def _flake_output_observation(
    relative_path: str,
    root: str,
    system: str,
    name: str,
    start_line: int,
    end_line: int,
    block: str,
    *,
    flake_ref: str,
) -> tuple[RawObservation, tuple[int, str] | None]:
    kind, output_kind, source_slug, target = _output_kind_and_target(
        root,
        flake_ref,
        system,
        name,
    )
    attr_path = f"{root}.{system}.{name}"
    metadata: dict[str, Any] = {
        "flake_ref": flake_ref,
        "system": system,
        "name": name,
        "attr_path": attr_path,
        "output_kind": output_kind,
    }
    if kind == "nix.app":
        metadata["app"] = name
        program_metadata, consumed_program_path = _app_program_metadata(
            relative_path,
            block,
            start_line,
        )
        metadata.update(program_metadata)
    else:
        consumed_program_path = None
    return (
        RawObservation(
            kind=kind,
            source_id=f"{relative_path}#nix-{source_slug}:{system}:{name}",
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            name=name,
            target=target,
            confidence="heuristic",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata=metadata,
        ),
        consumed_program_path,
    )


def _output_kind_and_target(
    root: str, flake_ref: str, system: str, name: str
) -> tuple[str, str, str, str]:
    if root == "apps":
        return "nix.app", "app", "app", nix_app_key(flake_ref, system, name)
    if root == "packages":
        return (
            "nix.package",
            "package",
            "package",
            nix_package_key(flake_ref, system, name),
        )
    if root == "devShells":
        return (
            "nix.devShell",
            "devShell",
            "devShell",
            nix_dev_shell_key(flake_ref, system, name),
        )
    return "nix.check", "check", "check", nix_check_key(flake_ref, system, name)


def _app_program_metadata(
    relative_path: str, block: str, start_line: int
) -> tuple[dict[str, Any], tuple[int, str] | None]:
    for offset, line in enumerate(block.splitlines()):
        match = PROGRAM_ASSIGNMENT_PATTERN.search(line)
        if match is None:
            continue
        expression = _clean_expression(match.group("expr"))
        metadata: dict[str, Any] = {"program": expression}
        self_match = SELF_PROGRAM_PATTERN.match(expression)
        if self_match is not None:
            program_path = self_match.group("path")
            if "${" in program_path:
                metadata["program_resolution"] = "dynamic"
                metadata["dynamic_reason"] = "nix-app-program-interpolation"
                return metadata, None
            target_path = resolve_repo_path(relative_path, f"${{self}}/{program_path}")
            if target_path is None:
                metadata["program_resolution"] = "unknown"
                metadata["program_target"] = unknown_key(
                    "file",
                    "repo-escaping-nix-app-program",
                )
                return metadata, None
            metadata["program_path"] = target_path
            metadata["program_resolution"] = "local"
            return metadata, (start_line + offset, f"./{target_path}")
        path_match = TO_STRING_PROGRAM_PATTERN.match(expression)
        if path_match is None:
            path_match = LITERAL_PROGRAM_PATTERN.match(expression)
        if path_match is not None:
            program_literal = _clean_path_literal(path_match.group("path"))
            target, path_metadata = _path_target_metadata(
                relative_path,
                program_literal,
                literal_field="program_literal",
                repo_escaping_reason="repo-escaping-nix-app-program",
            )
            if path_metadata["resolution"] == "local":
                metadata["program_path"] = path_metadata["resolved_path"]
                metadata["program_resolution"] = "local"
                return metadata, (start_line + offset, program_literal)
            metadata["program_resolution"] = path_metadata["resolution"]
            metadata["program_target"] = target
            return metadata, None
        if "${" in expression:
            metadata["program_resolution"] = "dynamic"
            metadata["dynamic_reason"] = "nix-app-program-interpolation"
            return metadata, None
        metadata["program_resolution"] = "external"
        return metadata, None
    return {}, None


def _extract_path_ref_observations(
    relative_path: str,
    content: str,
    consumed_paths: set[tuple[int, str]],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for match in NIX_PATH_PATTERN.finditer(line):
            path_ref = _clean_path_literal(match.group("path"))
            if (line_number, path_ref) in consumed_paths:
                continue
            target, metadata = _path_target_metadata(
                relative_path,
                path_ref,
                literal_field="path_ref",
                repo_escaping_reason="repo-escaping-nix-path-ref",
            )
            observations.append(
                RawObservation(
                    kind="nix.path_ref",
                    source_id=f"{relative_path}#nix-path:{line_number}:{slug(path_ref)}",
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    target=target,
                    confidence="heuristic",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata=metadata,
                )
            )
    return tuple(observations)


def _path_target_metadata(
    relative_path: str,
    literal: str,
    *,
    literal_field: str,
    repo_escaping_reason: str,
) -> tuple[str, dict[str, Any]]:
    metadata = {literal_field: literal}
    resolved_path = resolve_repo_path(relative_path, literal)
    if resolved_path is None:
        metadata["resolution"] = "unknown"
        metadata["dynamic_reason"] = repo_escaping_reason
        return unknown_key("file", repo_escaping_reason), metadata
    metadata["resolved_path"] = resolved_path
    metadata["resolution"] = "local"
    return file_key(resolved_path), metadata


def _clean_expression(expression: str) -> str:
    return expression.strip().rstrip(";").strip()


def _clean_path_literal(path: str) -> str:
    return path.strip().rstrip(";,)]}").strip()
