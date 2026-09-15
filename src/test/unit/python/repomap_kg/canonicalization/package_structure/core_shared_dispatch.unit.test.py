from __future__ import annotations

from pathlib import Path


def test_canon1_canonicalization_package_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main

    assert hasattr(canonicalization, "__path__")
    assert canonicalization.__file__ is not None
    assert Path(canonicalization.__file__).name == "__init__.py"
    assert canonicalization.canonicalize_observations is main.canonicalize_observations
    assert canonicalization._upsert_node is main._upsert_node


def test_canon1_family_modules_import() -> None:
    import repomap_kg.canonicalization.file_family as owner_0
    import repomap_kg.canonicalization.config_family as owner_1
    import repomap_kg.canonicalization.document_family as owner_2
    import repomap_kg.canonicalization.feed_family as owner_3
    import repomap_kg.canonicalization.shell_family as owner_4
    import repomap_kg.canonicalization.language_family as owner_5
    import repomap_kg.canonicalization.nix_family as owner_6
    import repomap_kg.canonicalization.email_family as owner_7

    for module_name, module in (
        ('repomap_kg.canonicalization.file_family', owner_0),
        ('repomap_kg.canonicalization.config_family', owner_1),
        ('repomap_kg.canonicalization.document_family', owner_2),
        ('repomap_kg.canonicalization.feed_family', owner_3),
        ('repomap_kg.canonicalization.shell_family', owner_4),
        ('repomap_kg.canonicalization.language_family', owner_5),
        ('repomap_kg.canonicalization.nix_family', owner_6),
        ('repomap_kg.canonicalization.email_family', owner_7),
    ):
        assert module.__name__ == module_name


def test_canon_shared0_shared_helper_modules_import() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.metadata_helpers as metadata_helpers
    import repomap_kg.canonicalization.diagnostic_helpers as diagnostic_helpers
    import repomap_kg.canonicalization.file_helpers as file_helpers

    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert metadata_helpers._metadata_text({"x": " y "}, "x") == " y "
    assert metadata_helpers._metadata_text({"x": "  "}, "x") is None
    assert getattr(canonicalization, "_metadata_text") is getattr(metadata_helpers, "_metadata_text")
    assert (
        getattr(canonicalization, "_append_metadata_text")
        is metadata_helpers._append_metadata_text
    )
    assert main._metadata_text is metadata_helpers._metadata_text
    assert main._append_metadata_text is metadata_helpers._append_metadata_text
    assert (
        getattr(canonicalization, "_append_raw_target_diagnostic")
        is diagnostic_helpers._append_raw_target_diagnostic
    )
    assert (
        getattr(canonicalization, "_graph_key_error_category")
        is diagnostic_helpers._graph_key_error_category
    )
    assert (
        main._append_raw_target_diagnostic
        is diagnostic_helpers._append_raw_target_diagnostic
    )
    assert main._graph_key_error_category is diagnostic_helpers._graph_key_error_category
    assert getattr(canonicalization, "_upsert_file_node") is getattr(file_helpers, "_upsert_file_node")
    assert (
        getattr(canonicalization, "_merge_file_node_metadata")
        is file_helpers._merge_file_node_metadata
    )
    assert main._upsert_file_node is file_helpers._upsert_file_node
    assert main._merge_file_node_metadata is file_helpers._merge_file_node_metadata


def test_canon_shared1_evidence_helper_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.evidence_helpers as evidence_helpers
    import repomap_kg.canonicalization.shell_family as shell_family

    assert (
        getattr(canonicalization, "_evidence_from_observation")
        is evidence_helpers._evidence_from_observation
    )
    assert main._evidence_from_observation is evidence_helpers._evidence_from_observation
    assert canonicalization._evidence_key is evidence_helpers._evidence_key
    assert main._evidence_key is evidence_helpers._evidence_key
    assert (
        getattr(canonicalization, "BASH_EVIDENCE_OMIT_KEYS")
        is evidence_helpers.BASH_EVIDENCE_OMIT_KEYS
    )
    assert (
        getattr(canonicalization, "ZUNIT_EVIDENCE_OMIT_KEYS")
        is evidence_helpers.ZUNIT_EVIDENCE_OMIT_KEYS
    )
    assert "raw" in evidence_helpers.BASH_EVIDENCE_OMIT_KEYS
    assert shell_family.BASH_EVIDENCE_OMIT_KEYS is evidence_helpers.BASH_EVIDENCE_OMIT_KEYS
    assert shell_family._bash_evidence_metadata({"raw": "x", "kept": "y"}) == {
        "kept": "y"
    }


def test_canon_shared2_core_route_helper_modules_import() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.node_edge_helpers as node_edge_helpers
    import repomap_kg.canonicalization.value_helpers as value_helpers
    import repomap_kg.canonicalization.document_family as document_family

    assert canonicalization._upsert_node is node_edge_helpers._upsert_node
    assert getattr(canonicalization, "_upsert_edge") is getattr(node_edge_helpers, "_upsert_edge")
    assert canonicalization._node_kind_from_key is node_edge_helpers._node_kind_from_key
    assert (
        canonicalization._display_name_from_key
        is node_edge_helpers._display_name_from_key
    )
    assert main._upsert_node is node_edge_helpers._upsert_node
    assert main._display_name_from_key is node_edge_helpers._display_name_from_key
    assert document_family._upsert_node is node_edge_helpers._upsert_node
    assert (
        document_family._display_name_from_key
        is node_edge_helpers._display_name_from_key
    )
    assert node_edge_helpers._node_kind_from_key("file:README.md") == "file"
    assert node_edge_helpers._display_name_from_key("file:README.md") == "README.md"

    assert canonicalization._stronger_confidence is value_helpers._stronger_confidence
    assert getattr(canonicalization, "_metadata_value_list") is getattr(value_helpers, "_metadata_value_list")
    assert (
        getattr(canonicalization, "_append_distinct_json_values")
        is value_helpers._append_distinct_json_values
    )
    assert getattr(canonicalization, "_merge_summary_metadata") is getattr(value_helpers, "_merge_summary_metadata")
    assert main._stronger_confidence is value_helpers._stronger_confidence
    assert main.CONFIDENCE_RANKS is value_helpers.CONFIDENCE_RANKS
    assert value_helpers._stronger_confidence("heuristic", "extracted") == "extracted"
    assert value_helpers._metadata_value_list(["one"]) == ["one"]
    assert value_helpers._metadata_value_list("one") == ["one"]


def test_canon_dispatch0_dispatch_helper_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.dispatch_helpers as dispatch_helpers
    import repomap_kg.canonicalization.shell_family as shell_family

    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        getattr(canonicalization, "TFJSON_PROFILE_RAW_OBSERVATION_KINDS")
        is dispatch_helpers.TFJSON_PROFILE_RAW_OBSERVATION_KINDS
    )
    assert (
        main.JS5_FRAMEWORK_RAW_OBSERVATION_KINDS
        is dispatch_helpers.JS5_FRAMEWORK_RAW_OBSERVATION_KINDS
    )
    assert (
        getattr(canonicalization, "POWERSHELL_RAW_ONLY_KINDS")
        is dispatch_helpers.POWERSHELL_RAW_ONLY_KINDS
    )
    assert main.BASH_RAW_ONLY_KINDS is dispatch_helpers.BASH_RAW_ONLY_KINDS
    assert shell_family.BASH_RAW_ONLY_KINDS is dispatch_helpers.BASH_RAW_ONLY_KINDS
    assert shell_family.ZSH_MAPPED_KINDS is dispatch_helpers.ZSH_MAPPED_KINDS
    assert dispatch_helpers.DISPATCH_ORDER[:6] == (
        "file",
        "awk",
        "zunit",
        "zsh",
        "bats",
        "bash",
    )
    assert dispatch_helpers.DISPATCH_ORDER[-1] == "unsupported"


def test_rootpkg33_document_dispatch_remains_private_to_main() -> None:
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization._document_dispatch as document_dispatch

    assert callable(document_dispatch._try_canonicalize_document_observation)
    assert not hasattr(main, "_try_canonicalize_document_observation")
