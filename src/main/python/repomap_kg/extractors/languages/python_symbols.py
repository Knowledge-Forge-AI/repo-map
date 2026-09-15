"""Python class, function, and method observation helpers."""

from __future__ import annotations

import ast

from repomap_kg import __version__
from repomap_kg.extractors.languages.python_common import (
    EXTRACTOR_NAME,
    end_line,
    slug,
)
from repomap_kg.graph.keys import (
    python_class_key,
    python_function_key,
    python_method_key,
)
from repomap_kg.observations.raw import RawObservation


def python_class_observation(
    relative_path: str, module: str, node: ast.ClassDef
) -> RawObservation:
    return RawObservation(
        kind="python.class",
        source_id=f"{relative_path}#class:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        target=python_class_key(module, node.name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "bases": [safe_unparse(base) for base in node.bases],
            "decorators": [
                safe_decorator_summary(item) for item in node.decorator_list
            ],
        },
    )


def python_function_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> RawObservation:
    return RawObservation(
        kind="python.function",
        source_id=f"{relative_path}#function:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        target=python_function_key(module, node.name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "async": isinstance(node, ast.AsyncFunctionDef),
            "decorators": [
                safe_decorator_summary(item) for item in node.decorator_list
            ],
        },
    )


def python_method_observations(
    relative_path: str, module: str, class_node: ast.ClassDef
) -> tuple[RawObservation, ...]:
    observations = []
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            observations.append(
                RawObservation(
                    kind="python.method",
                    source_id=(
                        f"{relative_path}#method:{node.lineno}:"
                        f"{slug(class_node.name + '.' + node.name)}"
                    ),
                    path=relative_path,
                    start_line=node.lineno,
                    end_line=end_line(node),
                    name=node.name,
                    target=python_method_key(module, class_node.name, node.name),
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "module": module,
                        "class": class_node.name,
                        "async": isinstance(node, ast.AsyncFunctionDef),
                        "decorators": [
                            safe_decorator_summary(item)
                            for item in node.decorator_list
                        ],
                    },
                )
            )
    return tuple(observations)


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _ast_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _ast_name(node.value)
    return ""


def safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except ValueError:
        return node.__class__.__name__


def safe_decorator_summary(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        call_name = _ast_name(node.func)
        return f"{call_name}(...)" if call_name else "call(...)"
    return safe_unparse(node)
