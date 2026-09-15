from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from unittest.mock import patch


DISCOVERY_EXTRACTOR_EXPORTS = (
    "extract_awk_file_observations_from_file",
    "extract_bash_file_observations_from_file",
    "extract_bats_file_observations_from_file",
    "extract_config_file_observations_from_file",
    "extract_css_file_observations_from_file",
    "extract_document_file_observations_from_file",
    "extract_eml_file_observations_from_file",
    "extract_feed_file_observations_from_file",
    "extract_html_file_observations_from_file",
    "extract_javascript_file_observations_from_file",
    "extract_markdown_file_observations_from_file",
    "extract_mbox_file_observations_from_file",
    "extract_nix_file_observations_from_file",
    "extract_powershell_file_observations_from_file",
    "extract_python_file_observations_from_file",
    "extract_ruby_file_observations_from_file",
    "extract_shell_file_observations",
    "extract_zsh_file_observations_from_file",
    "extract_zunit_file_observations_from_file",
    "markdown_anchor_index",
)


def test_rootpkg19_discovery_reexports_extractor_adapters() -> None:
    import repomap_kg.graph.discovery as discovery
    import repomap_kg.graph.discovery_extractors as adapters
    for name in DISCOVERY_EXTRACTOR_EXPORTS:
        assert getattr(discovery, name) is getattr(adapters, name)


def test_arch1e_discovery_reexports_neutral_file_info() -> None:
    import repomap_kg.graph.discovery as discovery
    import repomap_kg.graph.discovery_records as records
    assert discovery.FileInfo is records.FileInfo

def test_arch1e_extractor_routing_depends_on_neutral_records() -> None:
    import repomap_kg.graph.discovery_extractors as adapters
    assert adapters.__file__ is not None
    source = Path(adapters.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "repomap_kg.graph.discovery_records" in imported_modules
    assert "repomap_kg.graph.discovery" not in imported_modules


def test_pkg6_discovery_package_patch_target() -> None:
    import repomap_kg.graph.discovery as package_discovery
    with patch("repomap_kg.graph.discovery.classify_path") as patched_classify_path:
        assert package_discovery.classify_path is patched_classify_path


def test_pkg6_discovery_classifies_representative_paths_from_package() -> None:
    import repomap_kg.graph.discovery as discovery
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        script = root / "bin" / "repomap-kg"
        script.parent.mkdir()
        script.write_text("#!/usr/bin/env python3\nprint('ok')\n")
        script.chmod(script.stat().st_mode | 0o111)
        generated = root / "generated" / "schema.json"
        generated.parent.mkdir()
        generated.write_text("{}\n")

        script_info = discovery.classify_path(root, script)
        generated_info = discovery.classify_path(root, generated)

    assert script_info.path == "bin/repomap-kg"
    assert script_info.language == "python"
    assert script_info.role == "entrypoint"
    assert script_info.executable is True
    assert script_info.generated is False
    assert generated_info.path == "generated/schema.json"
    assert generated_info.language == "json"
    assert generated_info.role == "generated"
    assert generated_info.generated is True
