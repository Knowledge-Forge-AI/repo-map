from __future__ import annotations

from pathlib import Path

import common_lore_index


STANDARD_ROOT_FILES = {"__init__.py", "__main__.py", "entrypoints.py"}


PHASED_ROOT_FILES: dict[str, str] = {"_temporary.py": "ADR0106 shared owned temporary cleanup"}


COMPATIBILITY_HOLDS = {
    "local_runtime.py": "ADR 0036 public runtime import",
    "ops_refresh.py": "ADR 0036 public operations import",
}


def package_root() -> Path:
    assert common_lore_index.__file__ is not None
    return Path(common_lore_index.__file__).resolve().parent


def _module_path(module: object) -> Path:
    file_path = getattr(module, "__file__", None)
    assert file_path is not None
    return Path(file_path)


def test_root_python_files_match_active_rootpkg_inventory() -> None:
    expected = STANDARD_ROOT_FILES | PHASED_ROOT_FILES.keys() | COMPATIBILITY_HOLDS.keys()
    actual = {path.name for path in package_root().glob("*.py")}

    assert actual == expected


def test_rootpkg1_graph_readback_modules_are_package_owned() -> None:
    import common_lore_index.graph.readback.awk as module_0
    import common_lore_index.graph.readback.bash as module_1
    import common_lore_index.graph.readback.bats as module_2
    import common_lore_index.graph.readback.entrypoints as module_3
    import common_lore_index.graph.readback.files as module_4
    import common_lore_index.graph.readback.host_mutators as module_5
    import common_lore_index.graph.readback.powershell as module_6
    import common_lore_index.graph.readback.zsh as module_7
    import common_lore_index.graph.readback.zunit as module_8

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8,):

        assert _module_path(module).resolve().parent.name == "readback"


def test_rootpkg2_api_ingestion_modules_are_package_owned() -> None:
    import common_lore_index.ops.ingestion.api as module_0
    import common_lore_index.ops.ingestion.github_api as module_1
    import common_lore_index.ops.ingestion.github_api_config as module_2
    import common_lore_index.ops.ingestion.github_api_helpers as module_3
    import common_lore_index.ops.ingestion.github_api_records as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg3_bulk_ingestion_modules_are_package_owned() -> None:
    import common_lore_index.ops.ingestion.bulk as module_0
    import common_lore_index.ops.ingestion.bulk_records as module_1

    for module in (module_0, module_1,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg4_source_ingestion_modules_are_package_owned() -> None:
    import common_lore_index.ops.ingestion.source as module_0
    import common_lore_index.ops.ingestion.source_archive as module_1
    import common_lore_index.ops.ingestion.source_common as module_2
    import common_lore_index.ops.ingestion.source_feed as module_3
    import common_lore_index.ops.ingestion.source_warc as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "ingestion"


def test_rootpkg5_canonical_support_modules_are_package_owned() -> None:
    import common_lore_index.canonicalization.core as module_0
    import common_lore_index.canonicalization.diagnostics as module_1
    import common_lore_index.canonicalization.dispatch as module_2
    import common_lore_index.canonicalization.records as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name == "canonicalization"


def test_rootpkg6_server_memory_bridge_is_package_owned() -> None:
    import common_lore_index.server.memory_bridge as module

    assert _module_path(module).resolve().parent.name == "server"


def test_rootpkg7_project_identity_is_package_owned() -> None:
    import common_lore_index.runtime.project_identity as module

    assert _module_path(module).resolve().parent.name == "runtime"


def test_rootpkg8_shell_base_is_package_owned() -> None:
    import common_lore_index.extractors.shell.base as module

    assert _module_path(module).resolve().parent.name == "shell"


def test_rootpkg9_server_implementations_are_package_owned() -> None:
    import common_lore_index.server.http as module_0
    import common_lore_index.server.mcp as module_1
    import common_lore_index.server.mcp_core as module_2
    import common_lore_index.server.mcp_schemas as module_3
    import common_lore_index.server.ops as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "server"


def test_rootpkg10_ops_policy_dogfood_is_package_owned() -> None:
    import common_lore_index.ops.policy_dogfood as module

    assert _module_path(module).resolve().parent.name == "ops"


def test_rootpkg11_cli_implementations_are_package_owned() -> None:
    import common_lore_index.cli.dispatch as module_0
    import common_lore_index.cli.parser as module_1

    for module in (module_0, module_1,):

        assert _module_path(module).resolve().parent.name == "cli"


def test_rootpkg12_graph_observation_implementations_are_package_owned() -> None:
    import common_lore_index.graph.discovery as module_0
    import common_lore_index.graph.keys as module_1
    import common_lore_index.graph.profiles as module_2
    import common_lore_index.observations.normalization as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name in {"graph", "observations"}


def test_rootpkg13_runtime_implementations_are_package_owned() -> None:
    import common_lore_index.runtime.backup as module_0
    import common_lore_index.runtime.commands as module_1
    import common_lore_index.runtime.plan as module_2
    import common_lore_index.runtime.schema_manifest as module_3
    import common_lore_index.runtime.schema_upgrade as module_4

    for module in (module_0, module_1, module_2, module_3, module_4,):

        assert _module_path(module).resolve().parent.name == "runtime"


def test_rootpkg14_ops_implementations_are_package_owned() -> None:
    import common_lore_index.ops.baselines as module_0
    import common_lore_index.ops.config as module_1
    import common_lore_index.ops.preflight as module_2
    import common_lore_index.ops.reports as module_3

    for module in (module_0, module_1, module_2, module_3,):

        assert _module_path(module).resolve().parent.name == "ops"


def test_rootpkg15_shell_shared_extractors_are_package_owned() -> None:
    import common_lore_index.extractors.shared.observations as module_0
    import common_lore_index.extractors.shared.redaction as module_1
    import common_lore_index.extractors.shared.scanner as module_2
    import common_lore_index.extractors.shell.awk as module_3
    import common_lore_index.extractors.shell.bash as module_4
    import common_lore_index.extractors.shell.bats as module_5
    import common_lore_index.extractors.shell.powershell as module_6
    import common_lore_index.extractors.shell.zsh as module_7
    import common_lore_index.extractors.shell.zunit as module_8

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8,):

        assert _module_path(module).resolve().parent.name in {"shell", "shared"}


def test_rootpkg16_config_document_language_extractors_are_package_owned() -> None:
    import common_lore_index.extractors.config.generic as module_0
    import common_lore_index.extractors.config.nix as module_1
    import common_lore_index.extractors.documents.css as module_2
    import common_lore_index.extractors.documents.css_html_matching as module_3
    import common_lore_index.extractors.documents.email as module_4
    import common_lore_index.extractors.documents.feed as module_5
    import common_lore_index.extractors.documents.html as module_6
    import common_lore_index.extractors.documents.markdown as module_7
    import common_lore_index.extractors.documents.office as module_8
    import common_lore_index.extractors.languages.javascript as module_9
    import common_lore_index.extractors.languages.python as module_10
    import common_lore_index.extractors.languages.ruby as module_11

    for module in (module_0, module_1, module_2, module_3, module_4, module_5, module_6, module_7, module_8, module_9, module_10, module_11,):

        assert _module_path(module).resolve().parent.name in {
            "config",
            "documents",
            "languages",
        }
