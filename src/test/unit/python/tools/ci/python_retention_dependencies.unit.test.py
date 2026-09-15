"""Unit tests for Python retention dependency extraction and packaging resolution."""

from __future__ import annotations

from pathlib import Path
import pytest

from ci.python_retention_dependencies import (
    bind_source_identities,
    build_dependency_graph,
    cohort_leaving_dependencies,
    find_cross_cohort_cycles,
    is_external_name,
    map_candidate_modules,
    validate_candidate_path,
    verify_source_identities,
)


def _setup_tree(tmp_path: Path, files: dict[str, str]) -> list[str]:
    candidate_paths: list[str] = []
    for rel_path, content in files.items():
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        candidate_paths.append(rel_path)
    return sorted(candidate_paths)


def test_validate_candidate_path_valid(tmp_path: Path) -> None:
    f = tmp_path / "tools/ci/sample.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# sample\n", encoding="utf-8")
    resolved, rel = validate_candidate_path("tools/ci/sample.py", tmp_path)
    assert rel == "tools/ci/sample.py"
    assert resolved == f.resolve()


def test_validate_candidate_path_traversal_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        validate_candidate_path("../outside.py", tmp_path)


def test_validate_candidate_path_absolute_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        validate_candidate_path("/etc/passwd", tmp_path)


def test_validate_candidate_path_nonexistent_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not an existing file"):
        validate_candidate_path("tools/nonexistent.py", tmp_path)


def test_validate_candidate_path_alias_fails(tmp_path: Path) -> None:
    real = tmp_path / "tools/real.py"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("x = 1\n", encoding="utf-8")
    alias = tmp_path / "tools/symlink.py"
    alias.symlink_to(real)
    with pytest.raises(ValueError, match="alias"):
        validate_candidate_path("tools/symlink.py", tmp_path)


def test_is_external_name() -> None:
    assert is_external_name("__main__") is True
    assert is_external_name("__main__.missing") is False
    assert is_external_name("sys") is True
    assert is_external_name("json.decoder") is True
    assert is_external_name("pytest") is True
    assert is_external_name("typing_extensions") is True
    assert is_external_name("repomap_kg") is False
    assert is_external_name("unknown_nonexistent_mod") is False


def test_map_candidate_modules(tmp_path: Path) -> None:
    files = {
        "src/main/python/repomap_kg/__init__.py": "",
        "src/main/python/repomap_kg/core.py": "x = 1\n",
        "tools/ci/runner.py": "y = 2\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    mod_map, inits = map_candidate_modules(c_paths)
    assert mod_map["repomap_kg"] == "src/main/python/repomap_kg/__init__.py"
    assert mod_map["repomap_kg.core"] == "src/main/python/repomap_kg/core.py"
    assert mod_map["ci.runner"] == "tools/ci/runner.py"
    assert "src/main/python/repomap_kg/__init__.py" in inits["src/main/python/repomap_kg/core.py"]


def test_build_dependency_graph_basic_and_pkg_init(tmp_path: Path) -> None:
    files = {
        "src/main/python/repomap_kg/__init__.py": "# init\n",
        "src/main/python/repomap_kg/a.py": "def f(): return 1\n",
        "src/main/python/repomap_kg/b.py": "from repomap_kg.a import f\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    b_deps = graph["dependencies"]["src/main/python/repomap_kg/b.py"]
    assert "src/main/python/repomap_kg/a.py" in b_deps
    assert "src/main/python/repomap_kg/__init__.py" in b_deps
    assert not graph["unresolved_imports"].get("src/main/python/repomap_kg/b.py")


def test_build_dependency_graph_relative_imports(tmp_path: Path) -> None:
    files = {
        "src/main/python/repomap_kg/__init__.py": "",
        "src/main/python/repomap_kg/sub/__init__.py": "",
        "src/main/python/repomap_kg/sub/helper.py": "VAL = 42\n",
        "src/main/python/repomap_kg/sub/consumer.py": "from .helper import VAL\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    c_deps = graph["dependencies"]["src/main/python/repomap_kg/sub/consumer.py"]
    assert "src/main/python/repomap_kg/sub/helper.py" in c_deps
    assert "src/main/python/repomap_kg/sub/__init__.py" in c_deps
    assert "src/main/python/repomap_kg/__init__.py" in c_deps


def test_build_dependency_graph_escaping_relative_import(tmp_path: Path) -> None:
    files = {
        "tools/mod.py": "from ....outside import something\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    unresolved = graph["unresolved_imports"].get("tools/mod.py", [])
    assert any("escapes package" in u for u in unresolved)


def test_build_dependency_graph_detects_dynamic_calls(tmp_path: Path) -> None:
    files = {
        "tools/dyn1.py": "import importlib\nmod = importlib.import_module('foo')\n",
        "tools/dyn2.py": "x = __import__('bar')\n",
        "tools/dyn3.py": "import sys\nmod = sys.modules['baz']\n",
        "tools/dyn4.py": "eval('1 + 1')\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    for p in c_paths:
        assert p in graph["dynamic_uncertainty"]
        assert len(graph["dynamic_uncertainty"][p]) > 0
        assert p in graph["dynamic_operations"]
        assert len(graph["dynamic_operations"][p]) > 0
        op = graph["dynamic_operations"][p][0]
        assert "kind" in op
        assert "symbol" in op
        assert "fingerprint" in op
        assert "lineno" in op
        assert "expression" in op


def test_build_dependency_graph_docker_reload_negative_and_aliased_dynamic(
    tmp_path: Path,
) -> None:
    files = {
        "tools/docker_clean.py": (
            "class C:\n"
            "    def run(self, container):\n"
            "        container.reload()\n"
        ),
        "tools/aliased_dyn.py": (
            "from importlib import reload as rld\n"
            "import sys\n"
            "def refresh():\n"
            "    rld(sys)\n"
        ),
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    assert "tools/docker_clean.py" not in graph["dynamic_uncertainty"]
    assert "tools/docker_clean.py" not in graph.get("dynamic_operations", {})
    assert "tools/aliased_dyn.py" in graph["dynamic_uncertainty"]
    assert "tools/aliased_dyn.py" in graph["dynamic_operations"]
    ops = graph["dynamic_operations"]["tools/aliased_dyn.py"]
    assert ops[0]["kind"] == "reload"
    assert ops[0]["symbol"] == "refresh"


def test_build_dependency_graph_detects_unresolved_imports(tmp_path: Path) -> None:
    files = {
        "tools/broken.py": "import repomap_kg.nonexistent\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    assert "repomap_kg.nonexistent" in graph["unresolved_imports"].get("tools/broken.py", [])


def test_build_dependency_graph_handles_syntax_error(tmp_path: Path) -> None:
    files = {
        "tools/syntax.py": "def invalid(:\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    graph = build_dependency_graph(tmp_path, c_paths)
    assert "tools/syntax.py" in graph["errors"]
    assert "parse error" in graph["errors"]["tools/syntax.py"]


def test_cohort_leaving_dependencies() -> None:
    members = ["tools/a.py", "tools/b.py"]
    deps = {
        "tools/a.py": ["tools/b.py", "src/main/python/repomap_kg/core.py"],
        "tools/b.py": ["tools/a.py", "tools/util.py"],
    }
    leaving = cohort_leaving_dependencies(members, deps)
    assert leaving == ["src/main/python/repomap_kg/core.py", "tools/util.py"]


def test_find_cross_cohort_cycles_detects_cycle() -> None:
    cohorts = [
        {"id": "cohort_a", "members": ["tools/a.py"]},
        {"id": "cohort_b", "members": ["tools/b.py"]},
    ]
    deps = {
        "tools/a.py": ["tools/b.py"],
        "tools/b.py": ["tools/a.py"],
    }
    cycles = find_cross_cohort_cycles(cohorts, deps)
    assert "cohort_a" in cycles
    assert "cohort_b" in cycles
    assert cycles["cohort_a"] == ["cohort_a", "cohort_b"]


def test_find_cross_cohort_cycles_same_cohort_scc_is_not_cross_cycle() -> None:
    cohorts = [
        {"id": "cohort_ab", "members": ["tools/a.py", "tools/b.py"]},
    ]
    deps = {
        "tools/a.py": ["tools/b.py"],
        "tools/b.py": ["tools/a.py"],
    }
    cycles = find_cross_cohort_cycles(cohorts, deps)
    assert not cycles


def test_find_cross_cohort_cycles_acyclic() -> None:
    cohorts = [
        {"id": "cohort_a", "members": ["tools/a.py"]},
        {"id": "cohort_b", "members": ["tools/b.py"]},
    ]
    deps = {
        "tools/a.py": ["tools/b.py"],
        "tools/b.py": [],
    }
    cycles = find_cross_cohort_cycles(cohorts, deps)
    assert not cycles


def test_source_identity_binding_and_verification(tmp_path: Path) -> None:
    files = {
        "tools/a.py": "x = 1\n",
        "tools/b.py": "y = 2\n",
    }
    c_paths = _setup_tree(tmp_path, files)
    digests = bind_source_identities(tmp_path, c_paths)
    assert len(digests) == 2
    verify_source_identities(tmp_path, digests)

    (tmp_path / "tools/a.py").write_text("x = 999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_source_identities(tmp_path, digests)
