import ast
import sys
import tomllib
from pathlib import Path

from repomap_kg.runtime.commands import (
    render_compose_yaml,
    render_server_dockerfile,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import build_local_runtime_plan


REPO_ROOT = Path(__file__).resolve().parents[6]


def test_release_metadata_pins_psycopg_and_preserves_migration_paths() -> None:
    metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(metadata)["project"]

    assert 'requires = ["setuptools==83.0.0"]' in metadata
    assert project["dependencies"] == ["typing-extensions==4.16.0"]
    assert project["optional-dependencies"]["postgres"] == ["psycopg[binary]==3.2.12"]
    assert set(project["optional-dependencies"]) == {
        "test",
        "scale-tools",
        "static-analysis",
        "postgres",
    }
    assert not any(
        driver in requirement.lower()
        for requirement in project["dependencies"]
        for driver in ("psycopg", "libpq", "pg8000", "asyncpg")
    )
    for destination in (
        '"share/repomap-kg/rdbms"',
        '"share/repomap-kg/rdbms/2026/06"',
        '"share/repomap-kg/rdbms/2026/07"',
        '"share/repomap-kg/coordinator-rdbms"',
        '"share/repomap-kg/coordinator-rdbms/2026/07"',
    ):
        assert destination in metadata


def test_release_dockerfile_uses_only_pinned_build_and_runtime_resources() -> None:
    dockerfile = render_server_dockerfile()

    assert (
        "postgres:16-bookworm@sha256:"
        "92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55"
        in dockerfile
    )
    assert (
        "python:3.12-slim-bookworm@sha256:"
        "d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
        in dockerfile
    )
    assert (
        "golang:1.25-bookworm@sha256:"
        "ea341baa9bd5ba6784f6d7161ace70544349a6242d54d34a0fbfd2c4d51c9d58"
        in dockerfile
    )
    assert "ARG POSTGRES_IMAGE" not in dockerfile
    assert "ARG PYTHON_IMAGE" not in dockerfile
    assert "ARG GO_IMAGE" not in dockerfile
    assert "FROM ${" not in dockerfile
    assert dockerfile.count("go build") == 1
    assert "setuptools==83.0.0" in dockerfile
    assert (
        'python -m pip install --no-cache-dir --no-build-isolation ".[postgres]"'
        in dockerfile
    )
    assert "--no-build-isolation .\n" not in dockerfile
    assert "installed_graph == source_graph" in dockerfile
    assert "installed_control == source_control" in dockerfile
    assert "python -m pip uninstall -y pip setuptools" in dockerfile
    assert "/usr/local/lib/python3.12/ensurepip" in dockerfile
    assert "find_spec('pip') is None" in dockerfile
    assert "find_spec('setuptools') is None" in dockerfile
    assert "/usr/share/doc/repomap-kg/go/LICENSE" in dockerfile
    assert "/usr/local/lib/python3.12/LICENSE.txt" in dockerfile
    assert "apt-get" not in dockerfile
    assert "postgresql-client" not in dockerfile
    assert "REPOMAP_PACKAGED_PSQL=/usr/lib/postgresql/16/bin/psql" in dockerfile
    assert "REPOMAP_PACKAGED_PG_DUMP=/usr/bin/pg_dump" in dockerfile
    assert "REPOMAP_PACKAGED_PG_RESTORE=/usr/bin/pg_restore" in dockerfile
    assert "command -v go" in dockerfile
    assert "! command -v go" in dockerfile
    assert "PYTHONPATH" not in dockerfile
    assert "assert pq.version() == 170006" in dockerfile


def test_packaged_modules_import_only_the_postgres_extra_driver() -> None:
    package_root = REPO_ROOT / "src/main/python/repomap_kg"
    third_party: set[str] = set()
    for path in package_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, (ast.Attribute, ast.Name))
                and getattr(node.func, "attr", getattr(node.func, "id", None))
                in {"import_module", "__import__"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names = [node.args[0].value]
            else:
                continue
            third_party.update(
                top
                for top in (name.split(".")[0] for name in names)
                if top and top not in sys.stdlib_module_names and top != "repomap_kg"
            )

    assert third_party == {"psycopg"}


def test_release_notices_cover_binary_runtime_redistribution() -> None:
    notices = (REPO_ROOT / "docs/legal/third-party-notices.md").read_text(
        encoding="utf-8"
    )

    assert "## Go runtime and standard library" in notices
    assert "BSD-3-Clause" in notices
    assert "/usr/share/doc/repomap-kg/go/LICENSE" in notices
    assert "## Python runtime and standard library" in notices
    assert "PSF-2.0" in notices
    assert "/usr/local/lib/python3.12/LICENSE.txt" in notices


def test_docker_context_is_an_explicit_release_input_allowlist() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert dockerignore.startswith("**\n")
    assert "!pyproject.toml\n" in dockerignore
    assert "!README.md\n" in dockerignore
    assert "!src/main/python/**\n" in dockerignore
    assert "!src/main/resources/**\n" in dockerignore
    assert "!src/main/go/**\n" in dockerignore


def test_compose_uses_the_same_pinned_postgres_release_image(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    compose = render_compose_yaml(plan)

    assert (
        "image: postgres:16-bookworm@sha256:"
        "92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55"
        in compose
    )
    assert "postgres:16-alpine" not in compose
    assert f"image: repomap-runtime:{plan.identity.home_hash}" in compose
    assert f"repomap-runtime-{plan.identity.home_hash}" not in compose
