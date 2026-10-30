from __future__ import annotations


def test_pkg5_lang_discovery_routes_to_language_package_symbols() -> None:
    import common_lore_index.graph.discovery as discovery

    import common_lore_index.extractors.languages.python as owner_0
    import common_lore_index.extractors.languages.javascript as owner_1
    import common_lore_index.extractors.languages.ruby as owner_2

    for package_module, symbol_name in (
        (owner_0, 'extract_python_file_observations'),
        (owner_0, 'PythonModuleIndex'),
        (owner_1, 'extract_javascript_file_observations'),
        (owner_2, 'extract_ruby_file_observations'),
    ):

        assert getattr(discovery, symbol_name) is getattr(package_module, symbol_name)


def test_pkg5_lang_python_index_consumers_use_package_class() -> None:
    import common_lore_index.extractors.languages.python as package_module
    import common_lore_index.ops.ingestion.bulk as bulk_ingestion
    import common_lore_index.ops.ingestion.source_archive as source_archive

    assert bulk_ingestion.PythonModuleIndex is package_module.PythonModuleIndex
    assert source_archive.PythonModuleIndex is package_module.PythonModuleIndex
