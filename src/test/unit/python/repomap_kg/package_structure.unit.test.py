from __future__ import annotations

from pathlib import Path

import repomap_kg


SAFE_PACKAGE_NAMES = [
    "repomap_kg.cli",
    "repomap_kg.extractors",
    "repomap_kg.extractors.shell",
    "repomap_kg.extractors.languages",
    "repomap_kg.extractors.documents",
    "repomap_kg.extractors.config",
    "repomap_kg.extractors.shared",
    "repomap_kg.canonicalization",
    "repomap_kg.ops",
    "repomap_kg.runtime",
    "repomap_kg.server",
    "repomap_kg.graph",
    "repomap_kg.observations",
    "repomap_kg.storage",
]


def _package_root() -> Path:
    return Path(repomap_kg.__file__).resolve().parent


def test_pkg1_non_conflicting_package_skeleton_imports() -> None:
    import repomap_kg.cli as pkg_cli
    import repomap_kg.extractors as pkg_extractors
    import repomap_kg.extractors.shell as pkg_extractors_shell
    import repomap_kg.extractors.languages as pkg_extractors_languages
    import repomap_kg.extractors.documents as pkg_extractors_documents
    import repomap_kg.extractors.config as pkg_extractors_config
    import repomap_kg.extractors.shared as pkg_extractors_shared
    import repomap_kg.canonicalization as pkg_canonicalization
    import repomap_kg.ops as pkg_ops
    import repomap_kg.runtime as pkg_runtime
    import repomap_kg.server as pkg_server
    import repomap_kg.graph as pkg_graph
    import repomap_kg.observations as pkg_observations
    import repomap_kg.storage as pkg_storage

    packages = {
        "repomap_kg.cli": pkg_cli,
        "repomap_kg.extractors": pkg_extractors,
        "repomap_kg.extractors.shell": pkg_extractors_shell,
        "repomap_kg.extractors.languages": pkg_extractors_languages,
        "repomap_kg.extractors.documents": pkg_extractors_documents,
        "repomap_kg.extractors.config": pkg_extractors_config,
        "repomap_kg.extractors.shared": pkg_extractors_shared,
        "repomap_kg.canonicalization": pkg_canonicalization,
        "repomap_kg.ops": pkg_ops,
        "repomap_kg.runtime": pkg_runtime,
        "repomap_kg.server": pkg_server,
        "repomap_kg.graph": pkg_graph,
        "repomap_kg.observations": pkg_observations,
        "repomap_kg.storage": pkg_storage,
    }

    for package_name in SAFE_PACKAGE_NAMES:
        module = packages[package_name]

        assert hasattr(module, "__path__"), package_name
        assert module.__file__ is not None
        assert Path(module.__file__).name == "__init__.py"


def test_pkg1_current_public_root_modules_still_import() -> None:
    import repomap_kg.cli as cli
    import repomap_kg.storage as storage
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.observations as observations
    import repomap_kg.ops_refresh as ops_refresh
    import repomap_kg.local_runtime as local_runtime

    assert callable(cli.main)
    assert not hasattr(storage, "load_file_observations")
    assert callable(canonicalization.canonicalize_observations)
    assert hasattr(observations, "RawObservation")
    assert callable(getattr(ops_refresh, "refresh_graph"))
    assert callable(getattr(local_runtime, "setup_local_runtime"))


def test_pkg1_cli_package_has_no_conflicting_root_module() -> None:
    assert (_package_root() / "cli" / "__init__.py").is_file()
    assert not (_package_root() / "cli.py").exists()
