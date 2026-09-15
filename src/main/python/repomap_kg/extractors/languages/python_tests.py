"""Python unittest and pytest profile observations."""

from __future__ import annotations

import ast
import re
from pathlib import PurePath
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-python"
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")
PYTHON_TEST_MAX_OBSERVATIONS = 512
PYTHON_TEST_MAX_METADATA_STRING = 160
UNITTEST_ASSERTION_METHODS = frozenset(
    (
        "assertEqual",
        "assertTrue",
        "assertFalse",
        "assertIsNone",
        "assertIsNotNone",
        "assertIn",
        "assertNotIn",
        "assertRaises",
        "assertGreater",
        "assertLess",
        "assertRegex",
    )
)


def python_test_profile_observations(
    relative_path: str,
    module: str,
    tree: ast.Module,
) -> tuple[RawObservation, ...]:
    if not _looks_like_test_path(relative_path):
        return ()
    observations: list[RawObservation] = []
    frameworks: set[str] = set()
    unittest_case_count = 0
    pytest_test_count = 0
    fixture_count = 0
    assertion_total = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            is_unittest = _is_unittest_case(node)
            is_pytest_class = node.name.startswith("Test")
            if is_unittest:
                frameworks.add("unittest")
                test_methods = _test_methods(node)
                unittest_case_count += 1
                observations.append(
                    python_test_profile_observation(
                        "python.unittest_case",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "unittest",
                            "class_name": node.name,
                            "test_method_count": len(test_methods),
                            "setup_teardown_methods": _setup_teardown_methods(node),
                        },
                    )
                )
                for method in test_methods:
                    observations.append(
                        python_test_profile_observation(
                            "python.test_method",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "unittest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "decorator_count": len(method.decorator_list),
                                "skipped": _has_skip_decorator(method),
                            },
                        )
                    )
                    assertion_count = _assertion_count(method)
                    assertion_total += assertion_count
                    if assertion_count:
                        observations.append(
                            python_test_assertion_observation(
                                relative_path,
                                module,
                                method,
                                assertion_count=assertion_count,
                                test_framework="unittest",
                                class_name=node.name,
                            )
                        )
            if is_pytest_class and not is_unittest:
                frameworks.add("pytest")
                for method in _test_methods(node):
                    pytest_test_count += 1
                    observations.append(
                        python_test_profile_observation(
                            "python.test_method",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "pytest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "decorator_count": len(method.decorator_list),
                            },
                        )
                    )
                    observations.append(
                        python_test_profile_observation(
                            "python.pytest_test",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "pytest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "mark_names": _pytest_mark_names(method),
                            },
                        )
                    )
                    assertion_count = _assertion_count(method)
                    assertion_total += assertion_count
                    if assertion_count:
                        observations.append(
                            python_test_assertion_observation(
                                relative_path,
                                module,
                                method,
                                assertion_count=assertion_count,
                                test_framework="pytest",
                                class_name=node.name,
                            )
                        )
                    if _has_pytest_parametrize(method):
                        observations.append(
                            python_test_parametrize_observation(
                                relative_path,
                                module,
                                method,
                                class_name=node.name,
                            )
                        )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_pytest_fixture(node):
                frameworks.add("pytest")
                fixture_count += 1
                for kind in ("python.test_fixture", "python.pytest_fixture"):
                    observations.append(
                        python_test_profile_observation(
                            kind,
                            relative_path,
                            module,
                            node,
                            name=node.name,
                            metadata={
                                "test_framework": "pytest",
                                "fixture_name": node.name,
                                "decorator_count": len(node.decorator_list),
                            },
                        )
                    )
            if node.name.startswith("test_"):
                frameworks.add("pytest")
                pytest_test_count += 1
                observations.append(
                    python_test_profile_observation(
                        "python.test_function",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "pytest",
                            "test_name": node.name,
                            "decorator_count": len(node.decorator_list),
                            "mark_names": _pytest_mark_names(node),
                        },
                    )
                )
                observations.append(
                    python_test_profile_observation(
                        "python.pytest_test",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "pytest",
                            "test_name": node.name,
                            "mark_names": _pytest_mark_names(node),
                        },
                    )
                )
                assertion_count = _assertion_count(node)
                assertion_total += assertion_count
                if assertion_count:
                    observations.append(
                        python_test_assertion_observation(
                            relative_path,
                            module,
                            node,
                            assertion_count=assertion_count,
                            test_framework="pytest",
                        )
                    )
                if _has_pytest_parametrize(node):
                    observations.append(
                        python_test_parametrize_observation(
                            relative_path,
                            module,
                            node,
                            class_name=None,
                        )
                    )
    if observations:
        observations.insert(
            0,
            python_test_file_observation(
                relative_path,
                module,
                tree,
                test_frameworks=frameworks or {"unknown"},
                unittest_case_count=unittest_case_count,
                pytest_test_count=pytest_test_count,
                fixture_count=fixture_count,
                assertion_count=assertion_total,
            ),
        )
    return tuple(observations[:PYTHON_TEST_MAX_OBSERVATIONS])


def python_test_file_observation(
    relative_path: str,
    module: str,
    tree: ast.Module,
    *,
    test_frameworks: set[str],
    unittest_case_count: int,
    pytest_test_count: int,
    fixture_count: int,
    assertion_count: int,
) -> RawObservation:
    end = max(1, getattr(tree, "end_lineno", 1) or 1)
    return RawObservation(
        kind="python.test_file",
        source_id=f"{relative_path}#python-test-file",
        path=relative_path,
        start_line=1,
        end_line=end,
        name=module,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "module": module,
            "test_frameworks": sorted(test_frameworks),
            "unittest_case_count": unittest_case_count,
            "pytest_test_count": pytest_test_count,
            "fixture_count": fixture_count,
            "assertion_count": assertion_count,
            "raw_profile_only": True,
        },
    )


def python_test_profile_observation(
    kind: str,
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    metadata: dict[str, Any],
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.replace('.', '-')}:"
        f"{getattr(node, 'lineno', 'module')}:{_slug(name)}",
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=_end_line(node),
        name=name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "module": module,
            "raw_profile_only": True,
            **metadata,
        },
    )


def python_test_assertion_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    assertion_count: int,
    test_framework: str,
    class_name: str | None = None,
) -> RawObservation:
    metadata = {
        "profile": "python",
        "source_format": "python",
        "module": module,
        "test_framework": test_framework,
        "test_name": node.name,
        "assertion_count": assertion_count,
        "raw_profile_only": True,
    }
    if class_name is not None:
        metadata["class_name"] = class_name
    return RawObservation(
        kind="python.test_assertion",
        source_id=f"{relative_path}#python-test-assertion:{node.lineno}:{_slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=_end_line(node),
        name=node.name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def python_test_parametrize_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    class_name: str | None,
) -> RawObservation:
    metadata = {
        "profile": "python",
        "source_format": "python",
        "module": module,
        "test_framework": "pytest",
        "test_name": node.name,
        "parametrize": True,
        "raw_profile_only": True,
    }
    if class_name is not None:
        metadata["class_name"] = class_name
    return RawObservation(
        kind="python.test_parametrize",
        source_id=f"{relative_path}#python-test-parametrize:{node.lineno}:{_slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=_end_line(node),
        name=node.name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _looks_like_test_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    filename = PurePath(normalized).name
    parts = set(normalized.split("/"))
    return (
        "tests" in parts
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or "/test_" in normalized
    )


def _test_methods(
    class_node: ast.ClassDef,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _is_unittest_case(class_node: ast.ClassDef) -> bool:
    return any(
        _test_ast_name(base) in ("unittest.TestCase", "TestCase")
        for base in class_node.bases
    )


def _setup_teardown_methods(class_node: ast.ClassDef) -> list[str]:
    names = []
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "setUp",
            "tearDown",
            "setUpClass",
            "tearDownClass",
        ):
            names.append(node.name)
    return sorted(names)


def _has_skip_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("skip" in _test_ast_name(item).lower() for item in node.decorator_list)


def _is_pytest_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _test_ast_name(decorator) in ("pytest.fixture", "fixture")
        for decorator in node.decorator_list
    )


def _has_pytest_parametrize(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _test_ast_name(decorator) in ("pytest.mark.parametrize", "mark.parametrize")
        for decorator in node.decorator_list
    )


def _pytest_mark_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = []
    for decorator in node.decorator_list:
        decorator_name = _test_ast_name(decorator)
        if decorator_name.startswith("pytest.mark."):
            names.append(decorator_name.removeprefix("pytest.mark."))
        elif decorator_name.startswith("mark."):
            names.append(decorator_name.removeprefix("mark."))
    return sorted(names)


def _assertion_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.Call):
            call_name = _test_ast_name(child.func)
            if call_name.split(".")[-1] in UNITTEST_ASSERTION_METHODS:
                count += 1
    return count


def _test_ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _test_ast_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _test_ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _test_ast_name(node.value)
    return ""


def _end_line(node: ast.AST) -> int:
    lineno = getattr(node, "end_lineno", None)
    if isinstance(lineno, int):
        return lineno
    return getattr(node, "lineno", 1)


def _slug(value: str) -> str:
    stripped = value.strip() or "unknown"
    return SLUG_PATTERN.sub("-", stripped).strip("-")[:80] or "unknown"
