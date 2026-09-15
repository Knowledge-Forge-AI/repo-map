"""Conservative static JavaScript-family extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

import repomap_kg.extractors.languages.javascript_line_references as _line_references
from repomap_kg.graph.keys import (
    dynamic_key,
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_observations import (
    EXTRACTOR,
    FRAMEWORK_SPECIFIER_PREFIXES,
    PARSER,
    _component_observation,
    _definition_observation,
    _diagnostic_observation,
    _framework_observation,
    _framework_specifier_observation,
    _hook_observation,
    _is_framework_specifier,
    _observation,
    _parse_error,
    _reference_observation,
    _source_id_fragment,
)
from repomap_kg.extractors.languages.javascript_detection import (
    JS_EXTENSIONS,
    NEST_DECORATOR_RE,
    _detect_format,
    _detect_module_system,
    _detect_profile,
    _has_express_marker,
    _has_jquery_marker,
    _is_jest_profile,
    _is_node_entrypoint,
)
from repomap_kg.extractors.languages.javascript_jquery import (
    JQUERY_AJAX_CALL_RE,
    JQUERY_AJAX_OBJECT_RE,
    JQUERY_EVENT_RE,
    JQUERY_LOAD_RE,
    JQUERY_PLUGIN_RE,
    JQUERY_SELECTOR_RE,
    MAX_SELECTOR_LENGTH,
    MAX_URL_SUMMARY_LENGTH,
    _jquery_ajax_calls,
    _jquery_observations,
    _object_literal_string_value,
)
from repomap_kg.extractors.languages.javascript_jest import (
    JEST_CASE_RE,
    JEST_HOOK_CALLS,
    JEST_MATCHER_RE,
    JEST_MOCK_RE,
    JEST_SUITE_RE,
    JEST_TEST_CALLS,
    JestScanState,
    _add_jest_observations,
)
from repomap_kg.extractors.languages.javascript_routes import (
    EXPRESS_ROUTE_RE,
    JSX_ROUTE_RE,
    NEST_HTTP_DECORATORS,
    OBJECT_ROUTE_RE,
    ROUTE_METHODS,
    STRING_LITERAL_RE,
    _express_route_metadata,
    _extract_nest_array_names,
    _first_string_literal,
    _looks_like_express_error_handler,
    _nest_class_metadata,
    _nest_route_metadata,
    _next_route_metadata,
    _route_pattern_from_segments,
    _route_patterns,
    _simple_identifier,
    _split_js_args,
    _strip_js_suffix,
    _whole_string_literal,
)
from repomap_kg.extractors.languages.javascript_scanner import (
    CLASS_RE,
    METHOD_RE,
    _brace_delta,
    _is_react_class,
    _looks_like_non_method,
    _strip_line_comment,
    _update_class_stack,
)
from repomap_kg.extractors.languages.javascript_symbols import (
    ARROW_FUNCTION_RE,
    ENUM_RE,
    FUNCTION_EXPR_RE,
    FUNCTION_RE,
    INTERFACE_RE,
    TYPE_RE,
    VARIABLE_RE,
    _function_and_variable_observations,
    _looks_like_component,
    _typescript_observations,
)
from repomap_kg.extractors.languages.javascript_references import (
    LOCAL_RESOLUTION_EXTENSIONS,
    REFERENCE_SCHEMES,
    SECRET_MARKERS,
    _candidate_paths,
    _is_dynamic_literal,
    _is_secret_prone,
    _literal_type,
    _local_path_target,
    _looks_like_secret_literal,
    _package_name,
    _safe_summary,
    _sanitize_url,
    _specifier_target,
)
from repomap_kg.extractors.languages.javascript_reference_observations import (
    ANGULAR_TEMPLATE_RE,
    FETCH_LITERAL_RE,
    IMPORT_SCRIPTS_RE,
    SOURCE_MAP_RE,
    _dynamic_reasons,
    _export_observations,
    _import_observations,
    _literal_reference_observations,
)


MAX_FILE_BYTES = 512 * 1024
REACT_HOOKS = frozenset(
    ("useState", "useEffect", "useMemo", "useCallback", "useReducer")
)
MAX_FRAMEWORK_OBSERVATIONS_PER_KIND = 100

IMPORT_FROM_RE = re.compile(
    r"""^\s*import\s+(?P<body>(?:type\s+)?[\s\S]+?)\s+from\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
SIDE_EFFECT_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
EXPORT_FROM_RE = re.compile(
    r"""^\s*export\s+(?P<body>\*|\{[^}]*\})\s+from\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
EXPORT_DECL_RE = re.compile(
    r"""^\s*export\s+(?:(?P<default>default)\s+)?(?P<kind>function|class|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"""
)
DYNAMIC_IMPORT_LITERAL_RE = re.compile(
    r"""\bimport\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)\s*\)"""
)
REQUIRE_LITERAL_RE = re.compile(
    r"""\brequire\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)\s*\)"""
)
ENV_RE = re.compile(
    r"""\b(?:process\.env|import\.meta\.env)\.([A-Za-z_$][\w$]*)"""
)
MODULE_EXPORTS_RE = re.compile(r"""\bmodule\.exports\s*=""")
NAMED_EXPORTS_RE = re.compile(r"""\bexports\.(?P<name>[A-Za-z_$][\w$]*)\s*=""")
EXPRESS_APP_RE = re.compile(
    r"""\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*express\s*\("""
)
EXPRESS_ROUTER_RE = re.compile(
    r"""\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*express\.Router\s*\("""
)
NEST_DECORATOR_LINE_RE = re.compile(
    r"""^\s*@(?P<name>Module|Controller|Injectable|Get|Post|Put|Patch|Delete|All|Param|Body|Query|UseGuards|UseInterceptors|UsePipes)\s*(?:\((?P<args>.*)\))?"""
)
NEXT_HTTP_EXPORT_RE = re.compile(
    r"""^\s*export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\("""
)


def _reference_patterns() -> _line_references.JavaScriptReferencePatterns:
    return _line_references.JavaScriptReferencePatterns(
        import_from=IMPORT_FROM_RE,
        side_effect_import=SIDE_EFFECT_IMPORT_RE,
        export_from=EXPORT_FROM_RE,
        export_decl=EXPORT_DECL_RE,
        dynamic_import_literal=DYNAMIC_IMPORT_LITERAL_RE,
        require_literal=REQUIRE_LITERAL_RE,
        env=ENV_RE,
        module_exports=MODULE_EXPORTS_RE,
        named_exports=NAMED_EXPORTS_RE,
    )


def extract_javascript_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    """Extract safe, static JavaScript-family facts from local text."""

    file_bytes = len(content.encode("utf-8", errors="replace"))
    js_format = _detect_format(relative_path)
    profile = _detect_profile(relative_path, content, js_format)
    observations: list[RawObservation] = []
    file_canonical_key = js_file_key(relative_path)
    module_canonical_key = js_module_key(relative_path)
    module_system = _detect_module_system(content)
    next_route = _next_route_metadata(relative_path, js_format)
    framework_counts: dict[str, int] = {}
    framework_overflow_kinds: set[str] = set()

    def add_framework_observation(observation: RawObservation) -> None:
        count = framework_counts.get(observation.kind, 0)
        if count >= MAX_FRAMEWORK_OBSERVATIONS_PER_KIND:
            if observation.kind not in framework_overflow_kinds:
                framework_overflow_kinds.add(observation.kind)
                observations.append(
                    _parse_error(
                        relative_path,
                        js_format,
                        profile,
                        "framework-observation-limit",
                        "framework observation kind exceeded static scanner limit",
                        observation.start_line or 1,
                    )
                )
            return
        framework_counts[observation.kind] = count + 1
        observations.append(observation)

    observations.append(
        _observation(
            kind="js.file",
            relative_path=relative_path,
            source_id=f"{relative_path}#js-file",
            name=relative_path,
            target=file_canonical_key,
            metadata={
                "format": js_format,
                "profile": profile,
                "profiles": [profile],
                "parser": PARSER,
                "file_bytes": file_bytes,
            },
        )
    )
    observations.append(
        _definition_observation(
            "js.module",
            relative_path,
            js_format,
            profile,
            1,
            relative_path,
            module_canonical_key,
            source_key=file_canonical_key,
            metadata={"module_system": module_system},
        )
    )

    if file_bytes > MAX_FILE_BYTES:
        observations.append(
            _parse_error(
                relative_path,
                js_format,
                profile,
                "file-size-limit",
                "JavaScript-family file exceeds static scanner limit",
                1,
            )
        )
        return tuple(observations)

    class_stack: list[tuple[str, str, int]] = []
    nest_controller_prefixes: dict[str, str | None] = {}
    pending_nest_decorators: list[dict[str, Any]] = []
    pending_angular_component = False
    jest_state = JestScanState()
    route_count = 0
    reference_patterns = _reference_patterns()

    if _is_node_entrypoint(relative_path, content):
        add_framework_observation(
            _framework_observation(
                "node.entrypoint",
                relative_path,
                js_format,
                profile,
                1,
                PurePosixPath(relative_path).name,
                module_canonical_key,
                metadata={
                    "entrypoint_reason": "entrypoint-path",
                    "module_system": module_system,
                },
            )
        )

    if next_route is not None:
        add_framework_observation(
            _framework_observation(
                next_route["kind"],
                relative_path,
                js_format,
                "next",
                1,
                next_route["route_pattern"],
                module_canonical_key,
                metadata=next_route,
            )
        )

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = _strip_line_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        if "@Component" in stripped:
            pending_angular_component = True

        _line_references.add_line_reference_observations(
            relative_path=relative_path,
            js_format=js_format,
            profile=profile,
            line_number=line_number,
            stripped=stripped,
            module_canonical_key=module_canonical_key,
            repository_paths=repository_paths,
            observations=observations,
            add_framework_observation=add_framework_observation,
            patterns=reference_patterns,
        )

        express_app_match = EXPRESS_APP_RE.search(stripped)
        if express_app_match:
            add_framework_observation(
                _framework_observation(
                    "express.app",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_app_match.group("name"),
                    module_canonical_key,
                    metadata={"app_name": express_app_match.group("name")},
                )
            )
        express_router_match = EXPRESS_ROUTER_RE.search(stripped)
        if express_router_match:
            add_framework_observation(
                _framework_observation(
                    "express.router",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_router_match.group("name"),
                    module_canonical_key,
                    metadata={"router_name": express_router_match.group("name")},
                )
            )

        express_route = _express_route_metadata(stripped)
        if express_route is not None:
            add_framework_observation(
                _framework_observation(
                    "express.route",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_route["route_name"],
                    module_canonical_key,
                    metadata=express_route,
                )
            )
            if express_route["route_method"] == "USE":
                add_framework_observation(
                    _framework_observation(
                        "express.middleware",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        express_route["route_name"],
                        module_canonical_key,
                        metadata=express_route,
                    )
                )
            if express_route.get("error_handler"):
                add_framework_observation(
                    _framework_observation(
                        "express.error_handler",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        express_route["route_name"],
                        module_canonical_key,
                        metadata=express_route,
                    )
                )
            if not express_route["dynamic"] and express_route.get("route_pattern"):
                route_count += 1
                pointer = (
                    f"/routes/{express_route['route_method'].lower()}:"
                    f"{express_route['route_pattern']}"
                )
                observations.append(
                    _definition_observation(
                        "js.route",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        f"{express_route['route_method']} {express_route['route_pattern']}",
                        js_route_key(relative_path, pointer),
                        source_key=module_canonical_key,
                        metadata={
                            "route_method": express_route["route_method"],
                            "route_pattern": express_route["route_pattern"],
                            "route_pointer": pointer,
                            "identity_strength": "structural",
                            "route_ordinal": route_count,
                        },
                    )
                )

        for decorator_match in NEST_DECORATOR_RE.finditer(stripped):
            add_framework_observation(
                _framework_observation(
                    "nest.decorator",
                    relative_path,
                    js_format,
                    "nestjs",
                    line_number,
                    decorator_match.group("name"),
                    module_canonical_key,
                    metadata={
                        "decorator_name": decorator_match.group("name"),
                        "decorator_args_summary": _safe_summary(
                            decorator_match.group("args")
                        ),
                    },
                )
            )
        nest_line_decorator = NEST_DECORATOR_LINE_RE.match(stripped)
        if nest_line_decorator:
            pending_nest_decorators.append(
                {
                    "name": nest_line_decorator.group("name"),
                    "args": nest_line_decorator.group("args") or "",
                    "line_number": line_number,
                }
            )

        if next_route is not None and next_route["route_file_kind"] == "route":
            next_export_match = NEXT_HTTP_EXPORT_RE.match(stripped)
            if next_export_match:
                http_method = next_export_match.group("method")
                add_framework_observation(
                    _framework_observation(
                        "next.route",
                        relative_path,
                        js_format,
                        "next",
                        line_number,
                        f"{http_method} {next_route['route_pattern']}",
                        module_canonical_key,
                        metadata={
                            **next_route,
                            "http_method": http_method,
                            "route_method": http_method,
                        },
                    )
                )
                route_count += 1
                pointer = f"/routes/{http_method.lower()}:{next_route['route_pattern']}"
                observations.append(
                    _definition_observation(
                        "js.route",
                        relative_path,
                        js_format,
                        "next",
                        line_number,
                        f"{http_method} {next_route['route_pattern']}",
                        js_route_key(relative_path, pointer),
                        source_key=module_canonical_key,
                        metadata={
                            "route_method": http_method,
                            "route_pattern": next_route["route_pattern"],
                            "route_pointer": pointer,
                            "identity_strength": "structural",
                            "route_ordinal": route_count,
                        },
                    )
                )

        class_match = CLASS_RE.match(stripped)
        if class_match:
            class_name = class_match.group("name")
            class_key = js_class_key(relative_path, class_name)
            superclass = class_match.group("superclass")
            observations.append(
                _definition_observation(
                    "js.class",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    class_name,
                    class_key,
                    source_key=module_canonical_key,
                    metadata={
                        "class_name": class_name,
                        "qualified_name": class_name,
                        "superclass": superclass,
                    },
                )
            )
            if pending_angular_component or _is_react_class(superclass):
                observations.append(
                    _component_observation(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        class_name,
                        module_canonical_key,
                    )
                )
            nest_metadata = _nest_class_metadata(class_name, pending_nest_decorators)
            if nest_metadata is not None:
                nest_kind = nest_metadata.pop("kind")
                add_framework_observation(
                    _framework_observation(
                        nest_kind,
                        relative_path,
                        js_format,
                        "nestjs",
                        line_number,
                        class_name,
                        module_canonical_key,
                        metadata=nest_metadata,
                    )
                )
                if nest_kind == "nest.controller":
                    nest_controller_prefixes[class_name] = nest_metadata.get(
                        "controller_prefix"
                    )
            pending_nest_decorators.clear()
            class_depth = _brace_delta(stripped)
            if class_depth > 0:
                class_stack.append((class_name, class_key, class_depth))
            pending_angular_component = False
            continue

        current_class = class_stack[-1] if class_stack else None
        if current_class:
            method_match = METHOD_RE.match(stripped)
            if method_match and not _looks_like_non_method(stripped):
                method_name = method_match.group("name")
                method_key = js_method_key(current_class[1], method_name)
                observations.append(
                    _definition_observation(
                        "js.method",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        method_name,
                        method_key,
                        source_key=current_class[1],
                        metadata={
                            "class_name": current_class[0],
                            "method_name": method_name,
                            "qualified_name": f"{current_class[0]}.{method_name}",
                        },
                    )
                )
                nest_route = _nest_route_metadata(
                    current_class[0],
                    method_name,
                    nest_controller_prefixes.get(current_class[0]),
                    pending_nest_decorators,
                )
                if nest_route is not None:
                    add_framework_observation(
                        _framework_observation(
                            "nest.route",
                            relative_path,
                            js_format,
                            "nestjs",
                            line_number,
                            f"{nest_route['route_method']} {nest_route['route_pattern']}",
                            module_canonical_key,
                            metadata=nest_route,
                        )
                    )
                    if not nest_route["dynamic"] and nest_route.get("route_pattern"):
                        route_count += 1
                        pointer = (
                            f"/routes/{nest_route['route_method'].lower()}:"
                            f"{nest_route['controller_prefix']}/"
                            f"{nest_route['route_pattern']}"
                        )
                        observations.append(
                            _definition_observation(
                                "js.route",
                                relative_path,
                                js_format,
                                "nestjs",
                                line_number,
                                f"{nest_route['route_method']} {nest_route['route_pattern']}",
                                js_route_key(relative_path, pointer),
                                source_key=module_canonical_key,
                                metadata={
                                    "route_method": nest_route["route_method"],
                                    "route_pattern": nest_route["route_pattern"],
                                    "route_pointer": pointer,
                                    "identity_strength": "structural",
                                    "route_ordinal": route_count,
                                },
                            )
                        )
                pending_nest_decorators.clear()

        observations.extend(
            _function_and_variable_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                stripped,
                module_canonical_key,
            )
        )
        observations.extend(
            _typescript_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                stripped,
                module_canonical_key,
            )
        )

        _add_jest_observations(
            relative_path,
            js_format,
            profile,
            content,
            line_number,
            stripped,
            file_canonical_key,
            module_canonical_key,
            observations,
            jest_state,
            add_framework_observation,
        )

        for hook in REACT_HOOKS:
            if re.search(rf"\b{hook}\s*\(", stripped):
                observations.append(
                    _hook_observation(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        hook,
                        module_canonical_key,
                    )
                )
        custom_hook = re.search(r"\b(use[A-Z]\w*)\s*\(", stripped)
        if custom_hook and custom_hook.group(1) not in REACT_HOOKS:
            observations.append(
                _hook_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    custom_hook.group(1),
                    module_canonical_key,
                )
            )

        for route_pattern in _route_patterns(stripped, profile):
            route_count += 1
            pointer = f"/routes/path:{route_pattern}"
            route_key = js_route_key(relative_path, pointer)
            observations.append(
                _definition_observation(
                    "js.route",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    f"path {route_pattern}",
                    route_key,
                    source_key=module_canonical_key,
                    metadata={
                        "route_method": "path",
                        "route_pattern": route_pattern,
                        "route_pointer": pointer,
                        "identity_strength": "structural",
                        "route_ordinal": route_count,
                    },
                )
            )

        _update_class_stack(class_stack, stripped)

    return tuple(observations)
