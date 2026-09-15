from __future__ import annotations

from pathlib import Path


def test_canon_clean0_selected_families_drop_main_scaffold() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.feed_family as feed_family
    import repomap_kg.canonicalization.nix_family as nix_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_feed_definition_observation")
        is feed_family._canonicalize_feed_definition_observation
    )
    assert (
        main._canonicalize_feed_reference_observation
        is feed_family._canonicalize_feed_reference_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_nix_import_observation")
        is nix_family._canonicalize_nix_import_observation
    )
    assert (
        main._canonicalize_nix_output_observation
        is nix_family._canonicalize_nix_output_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_nix_output_section_observation")
        is nix_family._canonicalize_nix_output_section_observation
    )

    root = Path("src/main/python/repomap_kg/canonicalization")
    for family_path in (root / "feed_family.py", root / "nix_family.py"):
        source = family_path.read_text()
        assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
        assert "globals().update" not in source


def test_canon_clean1_selected_families_drop_main_scaffold() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.file_family as file_family
    import repomap_kg.canonicalization.config_family as config_family
    import repomap_kg.canonicalization.file_helpers as file_helpers
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_file_observation")
        is file_family._canonicalize_file_observation
    )
    assert main._file_node_metadata is file_family._file_node_metadata
    assert (
        getattr(canonicalization, "_canonicalize_config_definition_observation")
        is config_family._canonicalize_config_definition_observation
    )
    assert (
        main._canonicalize_config_reference_observation
        is config_family._canonicalize_config_reference_observation
    )
    assert file_family.FILE_METADATA_KEYS is file_helpers.FILE_METADATA_KEYS
    assert main.FILE_METADATA_KEYS is file_helpers.FILE_METADATA_KEYS
    assert getattr(canonicalization, "FILE_METADATA_KEYS") is getattr(file_helpers, "FILE_METADATA_KEYS")

    root = Path("src/main/python/repomap_kg/canonicalization")
    for family_path in (root / "file_family.py", root / "config_family.py"):
        source = family_path.read_text()
        assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
        assert "globals().update" not in source


def test_canon_clean2_selected_families_drop_main_scaffold() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.email_family as email_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_document_definition_observation")
        is document_family._canonicalize_document_definition_observation
    )
    assert (
        main._canonicalize_document_reference_observation
        is document_family._canonicalize_document_reference_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_email_definition_observation")
        is email_family._canonicalize_email_definition_observation
    )
    assert (
        main._canonicalize_email_reference_observation
        is email_family._canonicalize_email_reference_observation
    )

    root = Path("src/main/python/repomap_kg/canonicalization")
    for family_path in (root / "document_family.py", root / "email_family.py"):
        source = family_path.read_text()
        assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
        assert "globals().update" not in source


def test_canon_clean3_selected_family_drops_main_scaffold() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.language_family as language_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_python_definition_observation")
        is language_family._canonicalize_python_definition_observation
    )
    assert (
        main._canonicalize_ruby_reference_observation
        is language_family._canonicalize_ruby_reference_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_js_definition_observation")
        is language_family._canonicalize_js_definition_observation
    )

    source = Path(
        "src/main/python/repomap_kg/canonicalization/language_family.py"
    ).read_text()
    assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
    assert "globals().update" not in source


def test_canon_clean4_shell_facade_drops_final_main_scaffold() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert getattr(canonicalization, "_is_zsh_observation") is getattr(shell_family, "_is_zsh_observation")
    assert (
        main._canonicalize_bash_command_observation
        is shell_family._canonicalize_bash_command_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_shell_command_observation")
        is shell_family._canonicalize_shell_command_observation
    )
    assert (
        main._canonicalize_powershell_command_observation
        is shell_family._canonicalize_powershell_command_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_awk_program_observation")
        is shell_family._canonicalize_awk_program_observation
    )
    assert (
        main._canonicalize_zunit_test_case_observation
        is shell_family._canonicalize_zunit_test_case_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_bats_test_case_observation")
        is shell_family._canonicalize_bats_test_case_observation
    )

    source = Path(
        "src/main/python/repomap_kg/canonicalization/shell_family.py"
    ).read_text()
    assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
    assert "globals().update" not in source


def test_canon_facade0_package_root_all_preserves_current_surface() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_file_observation")
        is main._canonicalize_file_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_config_definition_observation")
        is main._canonicalize_config_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_markdown_definition_observation")
        is main._canonicalize_markdown_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_shell_command_observation")
        is main._canonicalize_shell_command_observation
    )
    assert getattr(canonicalization, "_is_zsh_observation") is getattr(main, "_is_zsh_observation")
    assert getattr(canonicalization, "FILE_METADATA_KEYS") is getattr(main, "FILE_METADATA_KEYS")

    public_names = {
        name for name in dir(canonicalization) if not name.startswith("_")
    }
    assert set(canonicalization.__all__) == public_names
    assert all(not name.startswith("_") for name in canonicalization.__all__)
    assert "nix_multi_source" not in canonicalization.__all__
    assert "nix_multi_source" not in public_names
    assert "_nix_multi_source" not in canonicalization.__all__
    assert "_nix_multi_source" not in public_names
    assert not hasattr(canonicalization, "nix_multi_source")

    import repomap_kg.canonicalization.nix_family as nix_family
    import repomap_kg.canonicalization._nix_multi_source as private_helper
    assert (
        nix_family.multi_source_opaque_target_key
        is private_helper.multi_source_opaque_target_key
    )

    root = Path("src/main/python/repomap_kg/canonicalization")
    for family_path in root.glob("*_family.py"):
        source = family_path.read_text()
        assert 'sys.modules["repomap_kg.canonicalization.main"]' not in source
        assert "globals().update" not in source


def test_canon_facade1_package_root_static_surface_preserves_main_exports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    compat_names = canonicalization._COMPATIBILITY_EXPORT_NAMES
    generated_main_surface = tuple(
        name
        for name in dir(main)
        if name not in canonicalization._MODULE_DUNDER_NAMES
    )

    assert isinstance(compat_names, tuple)
    assert compat_names == generated_main_surface
    assert len(compat_names) == 291
    assert len(compat_names) == len(set(compat_names))
    assert all(hasattr(main, name) for name in compat_names)
    assert all(hasattr(canonicalization, name) for name in compat_names)
    assert "__spec__" not in compat_names
    assert "_canonicalize_file_observation" in compat_names
    assert "_canonicalize_shell_command_observation" in compat_names
    assert "_canonicalize_markdown_definition_observation" in compat_names
    assert "_is_zsh_observation" in compat_names
    assert "FILE_METADATA_KEYS" in compat_names

    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "_canonicalize_file_observation")
        is main._canonicalize_file_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_config_definition_observation")
        is main._canonicalize_config_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_markdown_definition_observation")
        is main._canonicalize_markdown_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_shell_command_observation")
        is main._canonicalize_shell_command_observation
    )
    assert getattr(canonicalization, "_is_zsh_observation") is getattr(main, "_is_zsh_observation")
    assert getattr(canonicalization, "FILE_METADATA_KEYS") is getattr(main, "FILE_METADATA_KEYS")

    public_names = {
        name for name in dir(canonicalization) if not name.startswith("_")
    }
    assert set(canonicalization.__all__) == public_names

    source = Path("src/main/python/repomap_kg/canonicalization/__init__.py").read_text()
    assert "_COMPATIBILITY_EXPORT_NAMES = (" in source
    assert "dir(_impl)" not in source


def test_canon1_family_handlers_remain_on_compatibility_surface() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.file_family as file_family
    import repomap_kg.canonicalization.config_family as config_family
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.feed_family as feed_family
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.language_family as language_family
    import repomap_kg.canonicalization.nix_family as nix_family
    import repomap_kg.canonicalization.email_family as email_family
    assert (
        getattr(canonicalization, "_canonicalize_file_observation")
        is file_family._canonicalize_file_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_config_definition_observation")
        is config_family._canonicalize_config_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_markdown_definition_observation")
        is document_family._canonicalize_markdown_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_feed_definition_observation")
        is feed_family._canonicalize_feed_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_shell_command_observation")
        is shell_family._canonicalize_shell_command_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_powershell_command_observation")
        is shell_family._canonicalize_powershell_command_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_python_definition_observation")
        is language_family._canonicalize_python_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_ruby_definition_observation")
        is language_family._canonicalize_ruby_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_js_definition_observation")
        is language_family._canonicalize_js_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_nix_import_observation")
        is nix_family._canonicalize_nix_import_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_email_definition_observation")
        is email_family._canonicalize_email_definition_observation
    )
