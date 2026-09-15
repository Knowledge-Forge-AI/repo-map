from __future__ import annotations

import posixpath
from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
    canonical_edge_key,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.dispatch import (
    CanonicalizationState,
    append_unsupported_observation_diagnostic,
    canonicalization_result_from_state,
)
from repomap_kg.canonicalization.diagnostic_helpers import (
    _append_raw_target_diagnostic,
    _graph_key_error_category,
)
from repomap_kg.canonicalization.dispatch_helpers import (
    AWK_MAPPED_KINDS,
    AWK_RAW_ONLY_KINDS,
    BASH_MAPPED_KINDS,
    BASH_RAW_ONLY_KINDS,
    BATS_RAW_ONLY_KINDS,
    DISPATCH_ORDER,
    JS5_FRAMEWORK_RAW_OBSERVATION_KINDS,
    POWERSHELL_FILE_KINDS,
    POWERSHELL_REFERENCE_KINDS,
    POWERSHELL_RAW_ONLY_KINDS,
    TFJSON_PROFILE_RAW_OBSERVATION_KINDS,
    ZSH_MAPPED_KINDS,
    ZSH_RAW_ONLY_KINDS,
    ZUNIT_RAW_ONLY_KINDS,
)
from repomap_kg.canonicalization.evidence_helpers import (
    AWK_EVIDENCE_OMIT_KEYS,
    BASH_EVIDENCE_OMIT_KEYS,
    BATS_EVIDENCE_OMIT_KEYS,
    ZSH_EVIDENCE_OMIT_KEYS,
    ZUNIT_EVIDENCE_OMIT_KEYS,
    _evidence_from_observation,
    _evidence_key,
)
from repomap_kg.canonicalization.file_helpers import (
    FILE_CONFLICT_METADATA_KEYS,
    FILE_METADATA_KEYS,
    _merge_file_node_metadata,
    _upsert_file_node,
)
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_edge,
    _upsert_node,
)
from repomap_kg.canonicalization.value_helpers import (
    CONFIDENCE_RANKS,
    _append_distinct_json_values,
    _metadata_value_list,
    _merge_summary_metadata,
    _stronger_confidence,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    config_document_key,
    config_path_key,
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    document_column_key,
    document_file_key,
    document_latex_command_key,
    document_section_key,
    document_sheet_key,
    document_table_key,
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    dynamic_key,
    email_address_key,
    email_attachment_stub_key,
    email_mailbox_key,
    email_message_key,
    email_part_key,
    email_thread_hint_key,
    env_key,
    external_key,
    external_url_key,
    feed_document_key,
    file_key,
    awk_function_key,
    awk_program_key,
    bats_expectation_key,
    bats_file_key,
    bats_test_case_key,
    bash_function_key,
    bash_script_key,
    host_category_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_package_key,
    parse_key,
    powershell_function_key,
    powershell_manifest_export_key,
    powershell_manifest_key,
    powershell_module_key,
    powershell_script_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
    tool_key,
    unknown_key,
    warc_document_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
    zsh_function_key,
    zsh_script_key,
    zunit_assertion_key,
    zunit_command_under_test_key,
    zunit_expectation_key,
    zunit_file_key,
    zunit_hook_key,
    zunit_mock_key,
    zunit_stub_key,
    zunit_suite_key,
    zunit_test_case_key,
)
from repomap_kg.observations.raw import RawObservation

SECRET_PRONE_ENV_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "KEY",
    "CREDENTIAL",
    "AUTH",
)

HOST_MUTATION_CATEGORIES = frozenset(
    (
        "package-management",
        "service-management",
        "system-activation",
        "filesystem-mutation",
    )
)

def canonicalize_observations(
    observations: Sequence[RawObservation],
    *,
    repository_scope: str | None = None,
) -> CanonicalizationResult:
    from repomap_kg.canonicalization._document_dispatch import (
        _try_canonicalize_document_observation,
    )
    from repomap_kg.canonicalization._go_context import build_go_canonical_context
    from repomap_kg.canonicalization._go_family import (
        canonicalize_go_observation,
        finalize_go_canonicalization,
    )

    state = CanonicalizationState()
    go_context = build_go_canonical_context(
        observations,
        repository_scope=repository_scope,
    )
    state.diagnostics.extend(go_context.diagnostics)
    nodes = state.nodes
    edges = state.edges
    evidence = state.evidence
    node_evidence_links = state.node_evidence_links
    edge_evidence_links = state.edge_evidence_links
    diagnostics = state.diagnostics

    for ordinal, observation in enumerate(observations):
        if observation.kind == "file":
            _canonicalize_file_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if canonicalize_go_observation(
            observation=observation,
            ordinal=ordinal,
            context=go_context,
            state=state,
        ):
            continue
        if _try_canonicalize_awk_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if _try_canonicalize_zunit_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if _try_canonicalize_zsh_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if _try_canonicalize_bats_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if _try_canonicalize_bash_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if observation.kind == "shell.command":
            _canonicalize_shell_command_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.source":
            _canonicalize_shell_source_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.env":
            _canonicalize_shell_env_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.host_mutation":
            _canonicalize_shell_host_mutation_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if _try_canonicalize_powershell_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        ):
            continue
        if observation.kind in (
            "python.module",
            "python.class",
            "python.function",
            "python.method",
        ):
            _canonicalize_python_definition_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "python.import":
            _canonicalize_python_import_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in (
            "ruby.file",
            "ruby.module",
            "ruby.class",
            "ruby.method",
            "ruby.singleton_method",
            "ruby.constant",
            "ruby.test_case",
            "ruby.test_method",
            "ruby.route",
        ):
            _canonicalize_ruby_definition_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "ruby.reference":
            _canonicalize_ruby_reference_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in (
            "ruby.require",
            "ruby.include",
            "ruby.extend",
            "ruby.dsl",
            "ruby.gem_dependency",
            "ruby.vagrant_config",
            "ruby.parse_error",
        ):
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind in (
            "js.file",
            "js.module",
            "js.function",
            "js.class",
            "js.method",
            "js.variable",
            "js.component",
            "js.test_suite",
            "js.test_case",
            "js.route",
        ):
            _canonicalize_js_definition_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "js.reference":
            _canonicalize_js_reference_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in (
            "js.import",
            "js.export",
            "js.hook",
            "js.test_expectation",
            "js.interface",
            "js.type_alias",
            "js.enum",
            "js.parse_error",
        ):
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind in (
            "email.mailbox",
            "email.message",
            "email.part",
            "email.attachment_stub",
            "email.thread_hint",
        ):
            _canonicalize_email_definition_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "email.address":
            _canonicalize_email_address_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "email.reference":
            _canonicalize_email_reference_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in ("email.header", "email.parse_error"):
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind == "nix.import":
            _canonicalize_nix_import_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "nix.output_section":
            _canonicalize_nix_output_section_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in (
            "nix.app",
            "nix.package",
            "nix.devShell",
            "nix.check",
        ):
            _canonicalize_nix_output_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if _try_canonicalize_document_observation(
            observation=observation,
            ordinal=ordinal,
            state=state,
        ):
            continue
        append_unsupported_observation_diagnostic(diagnostics, observation, ordinal)

    finalize_go_canonicalization(context=go_context, state=state)
    return canonicalization_result_from_state(
        state,
        raw_observation_count=len(observations),
    )

from repomap_kg.canonicalization.file_family import (
    _canonicalize_file_observation,
    _file_node_metadata,
)
from repomap_kg.canonicalization.config_family import (
    _canonicalize_config_definition_observation,
    _canonicalize_config_reference_observation,
    _upsert_config_edge,
)
from repomap_kg.canonicalization.document_family import (
    _canonicalize_css_definition_observation,
    _canonicalize_css_reference_observation,
    _canonicalize_css_selector_match_observation,
    _canonicalize_document_definition_observation,
    _canonicalize_document_reference_observation,
    _canonicalize_html_definition_observation,
    _canonicalize_html_reference_observation,
    _canonicalize_markdown_definition_observation,
    _canonicalize_markdown_link_observation,
    _canonicalize_markdown_page_evidence_observation,
    _canonicalize_warc_definition_observation,
    _canonicalize_warc_reference_observation,
    _canonicalize_xml_definition_observation,
    _canonicalize_xml_reference_observation,
    _upsert_css_edge,
)
from repomap_kg.canonicalization.feed_family import (
    _canonicalize_feed_definition_observation,
    _canonicalize_feed_reference_observation,
)

from repomap_kg.canonicalization.nix_family import (
    _canonicalize_nix_import_observation,
    _canonicalize_nix_output_observation,
    _canonicalize_nix_output_section_observation,
    _nix_app_exposes_edge_metadata,
    _nix_define_edge_metadata,
    _nix_import_edge_metadata,
    _nix_import_target_key,
    _nix_output_target,
    _upsert_nix_edge,
)
from repomap_kg.canonicalization.email_family import (
    _canonicalize_email_address_observation,
    _canonicalize_email_definition_observation,
    _canonicalize_email_reference_observation,
    _email_address_target_key,
    _email_define_edge_metadata,
    _email_definition_source_key,
    _email_definition_target_key,
    _email_display_name,
    _email_node_metadata,
    _email_reference_edge_metadata,
    _email_reference_source_key,
    _email_reference_target_key,
)

from repomap_kg.canonicalization.language_family import (
    _canonicalize_js_definition_observation,
    _canonicalize_js_reference_observation,
    _canonicalize_python_definition_observation,
    _canonicalize_python_import_observation,
    _canonicalize_ruby_definition_observation,
    _canonicalize_ruby_reference_observation,
    _js_define_edge_metadata,
    _js_definition_source_key,
    _js_definition_target_key,
    _js_display_name,
    _js_node_metadata,
    _js_reference_edge_metadata,
    _js_reference_source_key,
    _js_reference_target_key,
    _python_definition_target,
    _python_import_edge_metadata,
    _python_import_target_key,
    _ruby_define_edge_metadata,
    _ruby_definition_source_key,
    _ruby_definition_target_key,
    _ruby_display_name,
    _ruby_node_metadata,
    _ruby_reference_edge_metadata,
    _ruby_reference_source_key,
    _ruby_reference_target_key,
)

from repomap_kg.canonicalization.shell_family import (
    _awk_evidence_from_observation,
    _bash_evidence_from_observation,
    _bats_evidence_from_observation,
    _canonicalize_awk_builtin_call_observation,
    _canonicalize_awk_command_intent_observation,
    _canonicalize_awk_extension_observation,
    _canonicalize_awk_file_reference_observation,
    _canonicalize_awk_function_observation,
    _canonicalize_awk_include_observation,
    _canonicalize_awk_program_observation,
    _canonicalize_awk_user_function_call_observation,
    _canonicalize_bash_command_observation,
    _canonicalize_bash_env_observation,
    _canonicalize_bash_function_observation,
    _canonicalize_bash_host_mutation_observation,
    _canonicalize_bash_reference_observation,
    _canonicalize_bash_script_observation,
    _canonicalize_bash_source_observation,
    _canonicalize_bats_assertion_observation,
    _canonicalize_bats_file_observation,
    _canonicalize_bats_fixture_reference_observation,
    _canonicalize_bats_helper_reference_observation,
    _canonicalize_bats_library_load_observation,
    _canonicalize_bats_load_observation,
    _canonicalize_bats_run_observation,
    _canonicalize_bats_test_case_observation,
    _canonicalize_powershell_command_observation,
    _canonicalize_powershell_env_observation,
    _canonicalize_powershell_file_observation,
    _canonicalize_powershell_function_observation,
    _canonicalize_powershell_host_mutation_observation,
    _canonicalize_powershell_reference_observation,
    _canonicalize_shell_command_observation,
    _canonicalize_shell_env_observation,
    _canonicalize_shell_host_mutation_observation,
    _canonicalize_shell_source_observation,
    _canonicalize_zsh_autoload_observation,
    _canonicalize_zsh_command_observation,
    _canonicalize_zsh_completion_function_observation,
    _canonicalize_zsh_env_observation,
    _canonicalize_zsh_file_intent_observation,
    _canonicalize_zsh_function_observation,
    _canonicalize_zsh_host_mutation_intent_observation,
    _canonicalize_zsh_network_intent_observation,
    _canonicalize_zsh_package_intent_observation,
    _canonicalize_zsh_plugin_manager_observation,
    _canonicalize_zsh_plugin_observation,
    _canonicalize_zsh_script_observation,
    _canonicalize_zsh_source_observation,
    _canonicalize_zsh_startup_file_observation,
    _canonicalize_zsh_zmodload_observation,
    _canonicalize_zunit_assertion_observation,
    _canonicalize_zunit_command_under_test_observation,
    _canonicalize_zunit_expectation_observation,
    _canonicalize_zunit_file_observation,
    _canonicalize_zunit_fixture_reference_observation,
    _canonicalize_zunit_helper_observation,
    _canonicalize_zunit_hook_observation,
    _canonicalize_zunit_mock_or_stub_observation,
    _canonicalize_zunit_suite_observation,
    _canonicalize_zunit_test_case_observation,
    _is_awk_observation,
    _is_bash_observation,
    _is_bats_observation,
    _is_zsh_observation,
    _is_zunit_observation,
    _try_canonicalize_awk_observation,
    _try_canonicalize_bats_observation,
    _try_canonicalize_bash_observation,
    _try_canonicalize_powershell_observation,
    _try_canonicalize_zsh_observation,
    _try_canonicalize_zunit_observation,
    _zsh_evidence_from_observation,
    _zunit_evidence_from_observation,
)
