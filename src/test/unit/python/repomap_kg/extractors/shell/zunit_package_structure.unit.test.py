from __future__ import annotations

import ast
from pathlib import Path


ZUNIT_OBSERVATION_EXPORTS = (
    "assertion_observations",
    "assignment_observations",
    "command_under_test_observations",
    "dynamic_assertion_observations",
    "helper_observations",
    "load_fixture_observations",
    "mock_or_stub_observations",
    "skip_or_todo_observation",
    "strip_inline_comment",
)


def test_rootpkg24_zunit_reexports_observation_builders() -> None:
    import repomap_kg.extractors.shell.zunit as zunit
    import repomap_kg.extractors.shell.zunit_observations as observations
    for name in ZUNIT_OBSERVATION_EXPORTS:
        assert getattr(zunit, name) is getattr(observations, name)


def test_rootpkg24_zunit_observation_builders_keep_focused_dependencies() -> None:
    import repomap_kg.extractors.shell.zunit_observations as observations
    assert observations.__file__ is not None
    source_path = Path(observations.__file__)
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in module_ast.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imported_modules == {
        "__future__",
        "repomap_kg.extractors.shell.zunit_helpers",
        "repomap_kg.observations.raw",
        "typing",
    }
