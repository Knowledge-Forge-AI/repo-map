"""Versioned repository-scoped graph keys for observed Go source."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

from repomap_kg.graph.keys import (
    MAX_GO_NAME_IDENTITY_BYTES,
    MAX_GO_PATH_IDENTITY_BYTES,
    GraphKeyError,
    _bounded_go_identity,
    _bounded_go_path_identity,
    _key,
    parse_key,
)


MAX_GO_REPOSITORY_SCOPE_BYTES = 512
GO_REPOSITORY_SCOPE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
GO_SOURCE_PACKAGE_NAMESPACES = frozenset(
    {"go.source-package.v2", "go.source-package-fallback.v2"}
)


def validate_go_repository_scope(scope: str) -> str:
    """Return one bounded public-safe repository scope or raise."""
    scope = _bounded_go_identity(scope, MAX_GO_REPOSITORY_SCOPE_BYTES)
    if not GO_REPOSITORY_SCOPE_PATTERN.fullmatch(scope):
        raise GraphKeyError("Go repository scope must be a public-safe identifier")
    return scope


def go_source_module_key(
    scope: str,
    module_root: str,
    module_path: str,
) -> str:
    """Build a v2 key for one observed module occurrence."""
    return _key(
        "go.source-module.v2",
        validate_go_repository_scope(scope),
        _bounded_relative_directory(module_root),
        _bounded_go_path_identity(module_path),
    )


def go_source_package_key(
    source_module_key: str,
    relative_directory: str,
    package_name: str,
) -> str:
    """Build a v2 package key beneath one source-module instance."""
    return _key(
        "go.source-package.v2",
        _coerce_source_module_key(source_module_key),
        _bounded_relative_directory(relative_directory),
        _bounded_go_identity(package_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_source_package_fallback_key(
    scope: str,
    repository_directory: str,
    package_name: str,
) -> str:
    """Build a v2 repository-scoped package key without module ownership."""
    return _key(
        "go.source-package-fallback.v2",
        validate_go_repository_scope(scope),
        _bounded_relative_directory(repository_directory),
        _bounded_go_identity(package_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_source_type_key(source_package_key: str, declaration_name: str) -> str:
    return _source_declaration_key(
        "go.source-type.v2",
        source_package_key,
        declaration_name,
    )


def go_source_function_key(source_package_key: str, declaration_name: str) -> str:
    return _source_declaration_key(
        "go.source-function.v2",
        source_package_key,
        declaration_name,
    )


def go_source_method_key(
    source_package_key: str,
    receiver_base: str,
    declaration_name: str,
) -> str:
    return _key(
        "go.source-method.v2",
        _coerce_source_package_key(source_package_key),
        _bounded_go_identity(receiver_base, MAX_GO_NAME_IDENTITY_BYTES),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_source_const_key(source_package_key: str, declaration_name: str) -> str:
    return _source_declaration_key(
        "go.source-const.v2",
        source_package_key,
        declaration_name,
    )


def go_source_var_key(source_package_key: str, declaration_name: str) -> str:
    return _source_declaration_key(
        "go.source-var.v2",
        source_package_key,
        declaration_name,
    )


def _source_declaration_key(
    namespace: str,
    source_package_key: str,
    declaration_name: str,
) -> str:
    return _key(
        namespace,
        _coerce_source_package_key(source_package_key),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def _bounded_relative_directory(value: str) -> str:
    value = _bounded_go_identity(value, MAX_GO_PATH_IDENTITY_BYTES)
    if value == ".":
        return value
    parsed = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value
        or parsed.is_absolute()
        or windows.drive
        or str(parsed) != value
        or any(component in {"", ".", ".."} for component in parsed.parts)
    ):
        raise GraphKeyError("Go source directory must be normalized and repository-relative")
    return value


def _coerce_source_module_key(key: str) -> str:
    parsed = parse_key(key)
    if parsed.namespace != "go.source-module.v2":
        raise GraphKeyError(
            "go.source-package.v2 keys require a go.source-module.v2 parent key"
        )
    validate_go_repository_scope(parsed.segments[0])
    _bounded_relative_directory(parsed.segments[1])
    _bounded_go_path_identity(parsed.segments[2])
    return key


def _coerce_source_package_key(key: str) -> str:
    parsed = parse_key(key)
    if parsed.namespace not in GO_SOURCE_PACKAGE_NAMESPACES:
        raise GraphKeyError("Go source declarations require a source-package parent key")
    if parsed.namespace == "go.source-package.v2":
        _coerce_source_module_key(parsed.segments[0])
    else:
        validate_go_repository_scope(parsed.segments[0])
    _bounded_relative_directory(parsed.segments[1])
    _bounded_go_identity(parsed.segments[2], MAX_GO_NAME_IDENTITY_BYTES)
    return key
