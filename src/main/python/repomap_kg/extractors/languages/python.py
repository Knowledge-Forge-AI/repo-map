"""Stdlib AST-backed Python raw observation extraction."""

from __future__ import annotations

import ast
import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterable, Mapping

from repomap_kg import __version__
from repomap_kg.extractors.languages.python_common import (
    EXTRACTOR_NAME,
    SLUG_PATTERN,
    end_line,
    slug,
)
from repomap_kg.extractors.languages.python_imports import (
    import_target_for_absolute,
    import_target_for_from,
    module_candidates,
    python_import_observation,
    python_import_observations,
    relative_module_candidates,
    resolve_relative_base,
)
from repomap_kg.extractors.languages.python_modules import (
    PythonModuleIndex,
    importable_module_name,
    module_name_from_suffix,
    normalize_root,
    package_roots,
    pyproject_package_roots,
    test_python_roots,
)
from repomap_kg.extractors.languages.python_symbols import (
    _ast_name,
    python_class_observation,
    python_function_observation,
    python_method_observations,
    safe_decorator_summary,
    safe_unparse,
)
from repomap_kg.extractors.languages.python_tests import (
    PYTHON_TEST_MAX_METADATA_STRING,
    PYTHON_TEST_MAX_OBSERVATIONS,
    UNITTEST_ASSERTION_METHODS,
    _assertion_count,
    _has_pytest_parametrize,
    _has_skip_decorator,
    _is_pytest_fixture,
    _is_unittest_case,
    _looks_like_test_path,
    _pytest_mark_names,
    _setup_teardown_methods,
    _test_methods,
    python_test_assertion_observation,
    python_test_file_observation,
    python_test_parametrize_observation,
    python_test_profile_observation,
    python_test_profile_observations,
)
from repomap_kg.graph.keys import (
    external_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


from repomap_kg.extractors.languages.python_web import (
    FASTAPI_METHOD_DECORATORS,
    FLASK_METHOD_DECORATORS,
    PYTHON_WEB_MAX_METADATA_STRING,
    PYTHON_WEB_MAX_OBSERVATIONS,
    PYTHON_WEB_MAX_ROUTES_PER_FILE,
    PYTHON_WEB_SECRET_MARKERS,
    WEB_HTTP_METHODS,
    _assignment_names,
    _assignment_target_nodes,
    _assignment_value,
    _assigns_name,
    _bounded_metadata_string,
    _call_arg,
    _call_receiver_attr,
    _django_app_observation,
    _django_model_observation,
    _django_setting_observations,
    _django_urlpattern_observations,
    _expression_kind,
    _fastapi_dependencies,
    _fastapi_include_router_reference,
    _fastapi_route_from_decorator,
    _flask_add_url_rule_observation,
    _flask_route_from_decorator,
    _function_default_redactions,
    _is_secret_like_name,
    _keyword,
    _line_slug,
    _literal_string,
    _literal_string_list,
    _looks_credentialed_url,
    _looks_like_django_settings_path,
    _methods_from_keyword,
    _python_web_import_aliases,
    _qualified_ast_name,
    _route_path_metadata,
    _safe_reference_name,
    _sha256_text,
    _value_looks_credentialed,
    add_config_redaction_if_needed,
    python_web_framework_observations,
    python_web_parse_error_observation,
    python_web_profile_observation,
    python_web_redaction_observation,
    python_web_reference_observation,
)


def extract_python_file_observations(
    relative_path: str,
    content: str,
    *,
    module_index: PythonModuleIndex,
    repository_root: Path | str | None = None,
) -> tuple[RawObservation, ...]:
    module = importable_module_name(relative_path, repository_root=repository_root)
    if module is None:
        return ()
    try:
        tree = ast.parse(content, filename=relative_path)
    except SyntaxError as error:
        return (python_parse_error_observation(relative_path, module, error),)

    observations: list[RawObservation] = [
        python_module_observation(relative_path, module, tree, content)
    ]
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            observations.extend(
                python_import_observations(
                    relative_path,
                    module,
                    node,
                    module_index=module_index,
                )
            )
        elif isinstance(node, ast.ClassDef):
            observations.append(python_class_observation(relative_path, module, node))
            observations.extend(
                python_method_observations(relative_path, module, node)
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            observations.append(
                python_function_observation(relative_path, module, node)
            )
    observations.extend(
        python_test_profile_observations(relative_path, module, tree)
    )
    observations.extend(
        python_web_framework_observations(relative_path, module, tree)
    )
    return tuple(observations)


def python_module_observation(
    relative_path: str, module: str, tree: ast.Module, content: str
) -> RawObservation:
    line_count = max(1, len(content.splitlines()))
    return RawObservation(
        kind="python.module",
        source_id=f"{relative_path}#module:{module}",
        path=relative_path,
        start_line=1,
        end_line=line_count,
        name=module,
        target=python_module_key(module),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "package_root": package_root_for_path(relative_path),
            "parser": "ast",
        },
    )


def python_parse_error_observation(
    relative_path: str,
    module: str,
    error: SyntaxError,
) -> RawObservation:
    line_number = error.lineno if isinstance(error.lineno, int) else None
    return RawObservation(
        kind="python.parse_error",
        source_id=f"{relative_path}#python-parse-error:{line_number or 'module'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=module,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "parser": "stdlib-ast",
            "error_kind": "malformed-python",
            "message_summary": (error.msg or "syntax error")[:120],
            "recovered": False,
            "raw_profile_only": True,
        },
    )


def package_root_for_path(relative_path: str) -> str:
    normalized_path = relative_path.replace("\\", "/")
    for root in ("src/main/python", *test_python_roots):
        if normalized_path.startswith(f"{root}/"):
            return root
    return "."
