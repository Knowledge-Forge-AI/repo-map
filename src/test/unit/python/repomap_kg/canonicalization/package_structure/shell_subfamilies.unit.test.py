from __future__ import annotations



def test_canon_shell_shared0_edge_helper_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.config_family as config_family
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.feed_family as feed_family
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_awk_family as shell_awk_family
    import repomap_kg.canonicalization.shell_zunit_family as shell_zunit_family
    import repomap_kg.canonicalization.shell_bats_family as shell_bats_family
    import repomap_kg.canonicalization.edge_helpers as edge_helpers
    assert config_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert main._upsert_config_edge is edge_helpers._upsert_config_edge
    assert getattr(canonicalization, "_upsert_config_edge") is getattr(edge_helpers, "_upsert_config_edge")
    assert document_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert feed_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert shell_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert shell_awk_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert shell_zunit_family._upsert_config_edge is edge_helpers._upsert_config_edge
    assert shell_bats_family._upsert_config_edge is edge_helpers._upsert_config_edge


def test_canon_shell_split0_awk_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_awk_family as shell_awk_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert shell_family._is_awk_observation is shell_awk_family._is_awk_observation
    assert (
        shell_family._awk_evidence_from_observation
        is shell_awk_family._awk_evidence_from_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_awk_program_observation")
        is shell_awk_family._canonicalize_awk_program_observation
    )
    assert (
        main._canonicalize_awk_command_intent_observation
        is shell_awk_family._canonicalize_awk_command_intent_observation
    )
    assert (
        shell_family._awk_static_command_summary
        is shell_awk_family._awk_static_command_summary
    )


def test_canon_shell_split1_zunit_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_zunit_family as shell_zunit_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        shell_family._is_zunit_observation
        is shell_zunit_family._is_zunit_observation
    )
    assert (
        shell_family._zunit_evidence_from_observation
        is shell_zunit_family._zunit_evidence_from_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_zunit_file_observation")
        is shell_zunit_family._canonicalize_zunit_file_observation
    )
    assert (
        main._canonicalize_zunit_command_under_test_observation
        is shell_zunit_family._canonicalize_zunit_command_under_test_observation
    )
    assert (
        shell_family._zunit_base_metadata
        is shell_zunit_family._zunit_base_metadata
    )


def test_canon_shell_split2_bats_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_bats_family as shell_bats_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert shell_family._is_bats_observation is shell_bats_family._is_bats_observation
    assert (
        shell_family._bats_evidence_from_observation
        is shell_bats_family._bats_evidence_from_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_bats_file_observation")
        is shell_bats_family._canonicalize_bats_file_observation
    )
    assert (
        main._canonicalize_bats_run_observation
        is shell_bats_family._canonicalize_bats_run_observation
    )
    assert (
        shell_family._bats_base_metadata
        is shell_bats_family._bats_base_metadata
    )


def test_canon_shell_split3_bash_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_bash_family as shell_bash_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert shell_family._is_bash_observation is shell_bash_family._is_bash_observation
    assert (
        shell_family._bash_evidence_from_observation
        is shell_bash_family._bash_evidence_from_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_bash_script_observation")
        is shell_bash_family._canonicalize_bash_script_observation
    )
    assert (
        main._canonicalize_bash_reference_observation
        is shell_bash_family._canonicalize_bash_reference_observation
    )
    assert (
        shell_family._bash_reference_parts
        is shell_bash_family._bash_reference_parts
    )


def test_canon_shell_split4_zsh_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_zsh_family as shell_zsh_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert shell_family._is_zsh_observation is shell_zsh_family._is_zsh_observation
    assert (
        shell_family._zsh_evidence_from_observation
        is shell_zsh_family._zsh_evidence_from_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_zsh_script_observation")
        is shell_zsh_family._canonicalize_zsh_script_observation
    )
    assert (
        main._canonicalize_zsh_command_observation
        is shell_zsh_family._canonicalize_zsh_command_observation
    )
    assert (
        shell_family._zsh_source_target_key
        is shell_zsh_family._zsh_source_target_key
    )


def test_rootpkg32_zsh_intent_handlers_are_reexported() -> None:
    import repomap_kg.canonicalization.shell_zsh_family as shell_zsh_family
    import repomap_kg.canonicalization._shell_zsh_intents as zsh_intents
    handler_names = (
        "_canonicalize_zsh_env_observation",
        "_canonicalize_zsh_file_intent_observation",
        "_canonicalize_zsh_host_mutation_intent_observation",
        "_canonicalize_zsh_network_intent_observation",
        "_canonicalize_zsh_package_intent_observation",
    )
    for name in handler_names:
        assert getattr(shell_zsh_family, name) is getattr(zsh_intents, name)


def test_canon_shell_shared1_shell_helper_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_awk_family as shell_awk_family
    import repomap_kg.canonicalization.shell_bash_family as shell_bash_family
    import repomap_kg.canonicalization.shell_zsh_family as shell_zsh_family
    import repomap_kg.canonicalization.shell_shared_helpers as shell_shared_helpers
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "lib/common.sh",
        )
        == "scripts/lib/common.sh"
    )
    assert (
        shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "../escape.sh",
        )
        == "escape.sh"
    )
    assert (
        shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "../../escape.sh",
        )
        is None
    )
    assert (
        shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "/etc/passwd",
        )
        is None
    )
    assert (
        shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "$HOME/.profile",
        )
        is None
    )
    assert (
        shell_family._bash_safe_relative_target
        is shell_bash_family._bash_safe_relative_target
    )
    assert (
        shell_family._zsh_safe_relative_target
        is shell_zsh_family._zsh_safe_relative_target
    )
    assert (
        shell_family._awk_safe_relative_target
        is shell_awk_family._awk_safe_relative_target
    )
    assert (
        shell_bash_family._safe_relative_shell_target
        is shell_shared_helpers._safe_relative_shell_target
    )
    assert (
        shell_zsh_family._safe_relative_shell_target
        is shell_shared_helpers._safe_relative_shell_target
    )
    assert (
        shell_awk_family._safe_relative_shell_target
        is shell_shared_helpers._safe_relative_shell_target
    )
    assert (
        shell_bash_family._bash_safe_relative_target(
            "scripts/setup.sh",
            "lib/common.sh",
        )
        == shell_shared_helpers._safe_relative_shell_target(
            "scripts/setup.sh",
            "lib/common.sh",
        )
    )
    assert (
        shell_zsh_family._zsh_safe_relative_target(
            "scripts/setup.sh",
            "../../escape.sh",
        )
        is None
    )
    assert (
        shell_awk_family._awk_safe_relative_target(
            "scripts/setup.awk",
            "`cmd`",
        )
        is None
    )


def test_canon_shell_split5_powershell_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_powershell_family as shell_powershell_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        shell_family._canonicalize_powershell_file_observation
        is shell_powershell_family._canonicalize_powershell_file_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_powershell_function_observation")
        is shell_powershell_family._canonicalize_powershell_function_observation
    )
    assert (
        main._canonicalize_powershell_reference_observation
        is shell_powershell_family._canonicalize_powershell_reference_observation
    )
    assert (
        shell_family._powershell_reference_parts
        is shell_powershell_family._powershell_reference_parts
    )
    assert (
        shell_family._powershell_file_node_metadata
        is shell_powershell_family._powershell_file_node_metadata
    )
    assert (
        shell_family._powershell_command_name
        is shell_powershell_family._powershell_command_name
    )


def test_canon_shell_split6_legacy_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.shell_family as shell_family
    import repomap_kg.canonicalization.shell_legacy_family as shell_legacy_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        shell_family._canonicalize_shell_command_observation
        is shell_legacy_family._canonicalize_shell_command_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_shell_source_observation")
        is shell_legacy_family._canonicalize_shell_source_observation
    )
    assert (
        main._canonicalize_shell_host_mutation_observation
        is shell_legacy_family._canonicalize_shell_host_mutation_observation
    )
    assert (
        shell_family._shell_command_target
        is shell_legacy_family._shell_command_target
    )
    assert (
        shell_family._shell_env_evidence_metadata
        is shell_legacy_family._shell_env_evidence_metadata
    )
    assert (
        shell_family._shell_host_mutation_edge_metadata
        is shell_legacy_family._shell_host_mutation_edge_metadata
    )
