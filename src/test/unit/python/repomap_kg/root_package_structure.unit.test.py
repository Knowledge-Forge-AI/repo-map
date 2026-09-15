from __future__ import annotations

from pathlib import Path

import repomap_kg


STANDARD_ROOT_FILES = {"__init__.py", "__main__.py"}


PHASED_ROOT_FILES: dict[str, str] = {}


COMPATIBILITY_HOLDS = {
    "local_runtime.py": "ADR 0036 public runtime import",
    "ops_refresh.py": "ADR 0036 public operations import",
}


def package_root() -> Path:
    assert repomap_kg.__file__ is not None
    return Path(repomap_kg.__file__).resolve().parent


def _module_path(module: object) -> Path:
    file_path = getattr(module, "__file__", None)
    assert file_path is not None
    return Path(file_path)


def test_root_python_files_match_active_rootpkg_inventory() -> None:
    expected = STANDARD_ROOT_FILES | PHASED_ROOT_FILES.keys() | COMPATIBILITY_HOLDS.keys()
    actual = {path.name for path in package_root().glob("*.py")}

    assert actual == expected


def test_rootpkg1_graph_readback_modules_are_package_owned() -> None:
    import repomap_kg.graph.readback.awk as module_0
    import repomap_kg.graph.readback.bash as module_1
    import repomap_kg.graph.readback.bats as module_2
    import repomap_kg.graph.readback.entrypoints as module_3
    import repomap_kg.graph.readback.files as module_4
    import repomap_kg.graph.readback.host_mutators as module_5
    import repomap_kg.graph.readback.powershell as module_6
    import repomap_kg.graph.readback.zsh as module_7
    import repomap_kg.graph.readback.zunit as module_8

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8,):

        assert _module_path(module).resolve().parent.name == "readback"


def test_rootpkg2_api_ingestion_modules_are_package_owned() -> None:
    import repomap_kg.ops.ingestion.api as module_0
    import repomap_kg.ops.ingestion.github_api as module_1
    import repomap_kg.ops.ingestion.github_api_config as module_2
    import repomap_kg.ops.ingestion.github_api_helpers as module_3
    import repomap_kg.ops.ingestion.github_api_records as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg3_bulk_ingestion_modules_are_package_owned() -> None:
    import repomap_kg.ops.ingestion.bulk as module_0
    import repomap_kg.ops.ingestion.bulk_records as module_1

    for module in (module_0, module_1,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg4_source_ingestion_modules_are_package_owned() -> None:
    import repomap_kg.ops.ingestion.source as module_0
    import repomap_kg.ops.ingestion.source_archive as module_1
    import repomap_kg.ops.ingestion.source_common as module_2
    import repomap_kg.ops.ingestion.source_feed as module_3
    import repomap_kg.ops.ingestion.source_warc as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg5_canonical_support_modules_are_package_owned() -> None:
    import repomap_kg.canonicalization.core as module_0
    import repomap_kg.canonicalization.diagnostics as module_1
    import repomap_kg.canonicalization.dispatch as module_2
    import repomap_kg.canonicalization.records as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name == "canonicalization"


def test_rootpkg6_server_memory_bridge_is_package_owned() -> None:
    import repomap_kg.server.memory_bridge as module

    assert _module_path(module).resolve().parent.name == "server"


def test_rootpkg7_project_identity_is_package_owned() -> None:
    import repomap_kg.runtime.project_identity as module

    assert _module_path(module).resolve().parent.name == "runtime"


def test_rootpkg8_shell_base_is_package_owned() -> None:
    import repomap_kg.extractors.shell.base as module

    assert _module_path(module).resolve().parent.name == "shell"


def test_rootpkg9_server_implementations_are_package_owned() -> None:
    import repomap_kg.server.http as module_0
    import repomap_kg.server.mcp as module_1
    import repomap_kg.server.mcp_core as module_2
    import repomap_kg.server.mcp_schemas as module_3
    import repomap_kg.server.ops as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "server"


def test_rootpkg10_ops_policy_dogfood_is_package_owned() -> None:
    import repomap_kg.ops.policy_dogfood as module

    assert _module_path(module).resolve().parent.name == "ops"


def test_rootpkg11_cli_implementations_are_package_owned() -> None:
    import repomap_kg.cli.dispatch as module_0
    import repomap_kg.cli.parser as module_1

    for module in (module_0, module_1,):

        assert _module_path(module).resolve().parent.name == "cli"


def test_rootpkg12_graph_observation_implementations_are_package_owned() -> None:
    import repomap_kg.graph.discovery as module_0
    import repomap_kg.graph.keys as module_1
    import repomap_kg.graph.profiles as module_2
    import repomap_kg.observations.normalization as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name in {"graph", "observations"}


def test_rootpkg13_runtime_implementations_are_package_owned() -> None:
    import repomap_kg.runtime.backup as module_0
    import repomap_kg.runtime.commands as module_1
    import repomap_kg.runtime.plan as module_2
    import repomap_kg.runtime.schema_manifest as module_3
    import repomap_kg.runtime.schema_upgrade as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "runtime"


def test_rootpkg14_ops_implementations_are_package_owned() -> None:
    import repomap_kg.ops.baselines as module_0
    import repomap_kg.ops.config as module_1
    import repomap_kg.ops.preflight as module_2
    import repomap_kg.ops.reports as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name == "ops"


def test_rootpkg15_shell_shared_extractors_are_package_owned() -> None:
    import repomap_kg.extractors.shared.observations as module_0
    import repomap_kg.extractors.shared.redaction as module_1
    import repomap_kg.extractors.shared.scanner as module_2
    import repomap_kg.extractors.shell.awk as module_3
    import repomap_kg.extractors.shell.bash as module_4
    import repomap_kg.extractors.shell.bats as module_5
    import repomap_kg.extractors.shell.powershell as module_6
    import repomap_kg.extractors.shell.zsh as module_7
    import repomap_kg.extractors.shell.zunit as module_8

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8,):

        assert _module_path(module).resolve().parent.name in {"shell", "shared"}


def test_rootpkg16_config_document_language_extractors_are_package_owned() -> None:
    import repomap_kg.extractors.config.generic as module_0
    import repomap_kg.extractors.config.nix as module_1
    import repomap_kg.extractors.documents.css as module_2
    import repomap_kg.extractors.documents.css_html_matching as module_3
    import repomap_kg.extractors.documents.email as module_4
    import repomap_kg.extractors.documents.feed as module_5
    import repomap_kg.extractors.documents.html as module_6
    import repomap_kg.extractors.documents.markdown as module_7
    import repomap_kg.extractors.documents.office as module_8
    import repomap_kg.extractors.languages.javascript as module_9
    import repomap_kg.extractors.languages.python as module_10
    import repomap_kg.extractors.languages.ruby as module_11

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8, module_9, module_10, module_11,):

        assert _module_path(module).resolve().parent.name in {
            "config",
            "documents",
            "languages",
        }
