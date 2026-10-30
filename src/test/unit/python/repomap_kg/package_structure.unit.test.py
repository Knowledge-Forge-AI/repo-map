from __future__ import annotations

from pathlib import Path

import common_lore_index


SAFE_PACKAGE_NAMES = [
    "common_lore_index.cli",
    "common_lore_index.extractors",
    "common_lore_index.extractors.shell",
    "common_lore_index.extractors.languages",
    "common_lore_index.extractors.documents",
    "common_lore_index.extractors.config",
    "common_lore_index.extractors.shared",
    "common_lore_index.canonicalization",
    "common_lore_index.ops",
    "common_lore_index.runtime",
    "common_lore_index.server",
    "common_lore_index.graph",
    "common_lore_index.observations",
    "common_lore_index.storage",
]


def _package_root() -> Path:
    return Path(common_lore_index.__file__).resolve().parent


def test_pkg1_non_conflicting_package_skeleton_imports() -> None:
    import common_lore_index.cli as pkg_cli
    import common_lore_index.extractors as pkg_extractors
    import common_lore_index.extractors.shell as pkg_extractors_shell
    import common_lore_index.extractors.languages as pkg_extractors_languages
    import common_lore_index.extractors.documents as pkg_extractors_documents
    import common_lore_index.extractors.config as pkg_extractors_config
    import common_lore_index.extractors.shared as pkg_extractors_shared
    import common_lore_index.canonicalization as pkg_canonicalization
    import common_lore_index.ops as pkg_ops
    import common_lore_index.runtime as pkg_runtime
    import common_lore_index.server as pkg_server
    import common_lore_index.graph as pkg_graph
    import common_lore_index.observations as pkg_observations
    import common_lore_index.storage as pkg_storage

    packages = {
        "common_lore_index.cli": pkg_cli,
        "common_lore_index.extractors": pkg_extractors,
        "common_lore_index.extractors.shell": pkg_extractors_shell,
        "common_lore_index.extractors.languages": pkg_extractors_languages,
        "common_lore_index.extractors.documents": pkg_extractors_documents,
        "common_lore_index.extractors.config": pkg_extractors_config,
        "common_lore_index.extractors.shared": pkg_extractors_shared,
        "common_lore_index.canonicalization": pkg_canonicalization,
        "common_lore_index.ops": pkg_ops,
        "common_lore_index.runtime": pkg_runtime,
        "common_lore_index.server": pkg_server,
        "common_lore_index.graph": pkg_graph,
        "common_lore_index.observations": pkg_observations,
        "common_lore_index.storage": pkg_storage,
    }

    for package_name in SAFE_PACKAGE_NAMES:
        module = packages[package_name]

        assert hasattr(module, "__path__"), package_name
        assert module.__file__ is not None
        assert Path(module.__file__).name == "__init__.py"


def test_pkg1_current_public_root_modules_still_import() -> None:
    import common_lore_index.cli as cli
    import common_lore_index.storage as storage
    import common_lore_index.canonicalization as canonicalization
    import common_lore_index.observations as observations
    import common_lore_index.ops_refresh as ops_refresh
    import common_lore_index.local_runtime as local_runtime

    assert callable(cli.main)
    assert not hasattr(storage, "load_file_observations")
    assert callable(canonicalization.canonicalize_observations)
    assert hasattr(observations, "RawObservation")
    assert callable(getattr(ops_refresh, "refresh_graph"))
    assert callable(getattr(local_runtime, "setup_local_runtime"))


def test_pkg1_cli_package_has_no_conflicting_root_module() -> None:
    assert (_package_root() / "cli" / "__init__.py").is_file()
    assert not (_package_root() / "cli.py").exists()
