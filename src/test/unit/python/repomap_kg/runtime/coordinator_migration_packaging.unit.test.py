"""Package-manifest and release-input contracts for coordinator migrations."""

from pathlib import Path
import shutil
import tomllib

from repomap_kg.coordinator._control_schema import discover_control_migrations
from repomap_kg.runtime.commands import render_server_dockerfile


ROOT = Path(__file__).resolve().parents[6]
CONTROL_ROOT = ROOT / "src/main/resources/coordinator-rdbms"


def _manifest(
    metadata: dict | None = None,
    root: Path = ROOT,
) -> dict[str, Path]:
    if metadata is None:
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    result = {}
    for destination, patterns in metadata["tool"]["setuptools"]["data-files"].items():
        for pattern in patterns:
            for source in root.glob(pattern):
                installed = (Path(destination) / source.name).as_posix()
                assert installed not in result, "ambiguous installed resource"
                result[installed] = source
    return result


def transform_pyproject_for_public(text: str) -> str:
    assert 'version = "0.1.0"' in text, "pyproject.toml must declare private version 0.1.0"
    return text.replace('version = "0.1.0"', 'version = "0.0.2"', 1)


def test_october_has_exact_explicit_destination_and_maintained_glob():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["tool"]["setuptools"]["data-files"][
        "share/repomap-kg/coordinator-rdbms/2026/10"
    ] == ["src/main/resources/coordinator-rdbms/2026/10/*.sql"]
    october = set(CONTROL_ROOT.glob("2026/10/*.sql"))
    assert october
    manifest = _manifest()
    assert october <= set(manifest.values())


def test_changelog_catalog_resolves_only_packaged_migrations(tmp_path):
    manifest = _manifest()
    for destination, source in manifest.items():
        target = tmp_path / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    installed_root = tmp_path / "share/repomap-kg/coordinator-rdbms"
    assert (installed_root / "changelog.yaml").read_bytes() == (
        CONTROL_ROOT / "changelog.yaml"
    ).read_bytes()
    source_catalog = discover_control_migrations(CONTROL_ROOT)
    installed_catalog = discover_control_migrations(installed_root)
    encode = lambda catalog: [(m.relative_path, m.changeset_id, m.checksum) for m in catalog]
    assert source_catalog and encode(installed_catalog) == encode(source_catalog)
    for migration in source_catalog:
        assert f"share/repomap-kg/coordinator-rdbms/{migration.relative_path}" in manifest


def test_release_install_consumes_manifest_and_verifies_installed_control_catalog():
    dockerfile = render_server_dockerfile()
    assert "COPY pyproject.toml README.md ./" in dockerfile
    assert "COPY src/main/resources ./src/main/resources" in dockerfile
    assert 'pip install --no-cache-dir --no-build-isolation ".[postgres]"' in dockerfile
    assert "installed_control == source_control" in dockerfile
    dockerignore = (ROOT / ".dockerignore").read_text()
    assert "!pyproject.toml\n" in dockerignore
    assert "!src/main/resources/**\n" in dockerignore


def test_public_transformation_preserves_october_manifest_and_metadata():
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = tomllib.loads(raw)["project"]["version"]
    assert version in {"0.1.0", "0.0.2"}
    private_input = raw.replace('version = "0.0.2"', 'version = "0.1.0"', 1)
    transformed = transform_pyproject_for_public(private_input)
    data = tomllib.loads(transformed)
    assert data["project"]["version"] == "0.0.2"
    assert data["project"]["dependencies"] == ["typing-extensions==4.16.0"]
    assert not any(
        driver in req.lower()
        for req in data["project"]["dependencies"]
        for driver in ("psycopg", "libpq", "pg8000", "asyncpg")
    )
    assert data["project"]["optional-dependencies"]["postgres"] == [
        "psycopg[binary]==3.2.12"
    ]
    assert (
        data["tool"]["setuptools"]["data-files"][
            "share/repomap-kg/coordinator-rdbms/2026/10"
        ]
        == ["src/main/resources/coordinator-rdbms/2026/10/*.sql"]
    )
    private_manifest = _manifest()
    public_manifest = _manifest(data)
    assert public_manifest == private_manifest
    october_resources = set(CONTROL_ROOT.glob("2026/10/*.sql"))
    assert october_resources
    assert october_resources <= set(public_manifest.values())


def test_dynamic_exact_catalog_accommodates_added_october_schema(tmp_path: Path):
    simulated_root = tmp_path / "simulated_repo"
    simulated_root.mkdir()
    shutil.copyfile(ROOT / "pyproject.toml", simulated_root / "pyproject.toml")
    simulated_resources = (
        simulated_root / "src/main/resources/coordinator-rdbms/2026/10"
    )
    simulated_resources.mkdir(parents=True)
    for sql_file in CONTROL_ROOT.glob("2026/10/*.sql"):
        shutil.copyfile(sql_file, simulated_resources / sql_file.name)
    added_sql = simulated_resources / "02-999-dynamic-schema-by-q2.sql"
    added_sql.write_text("-- synthetic catalog expansion\n", encoding="utf-8")

    manifest = _manifest(root=simulated_root)
    added_installed_key = (
        "share/repomap-kg/coordinator-rdbms/2026/10/02-999-dynamic-schema-by-q2.sql"
    )
    assert added_installed_key in manifest
    assert manifest[added_installed_key] == added_sql
