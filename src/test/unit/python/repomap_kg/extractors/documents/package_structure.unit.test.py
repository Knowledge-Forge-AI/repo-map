from __future__ import annotations


def test_pkg5_configdoc_discovery_routes_to_package_symbols() -> None:
    import repomap_kg.graph.discovery as discovery

    import repomap_kg.extractors.config.generic as owner_0
    import repomap_kg.extractors.config.nix as owner_1
    import repomap_kg.extractors.documents.css as owner_2
    import repomap_kg.extractors.documents.css_html_matching as owner_3
    import repomap_kg.extractors.documents.email as owner_4
    import repomap_kg.extractors.documents.feed as owner_5
    import repomap_kg.extractors.documents.html as owner_6
    import repomap_kg.extractors.documents.markdown as owner_7
    import repomap_kg.extractors.documents.office as owner_8

    for package_module, symbol_name in (
        (owner_0, 'extract_config_file_observations'),
        (owner_1, 'extract_nix_file_observations'),
        (owner_2, 'extract_css_file_observations'),
        (owner_3, 'extract_css_selector_match_observations'),
        (owner_4, 'extract_eml_file_observations'),
        (owner_4, 'extract_mbox_file_observations'),
        (owner_5, 'extract_feed_file_observations'),
        (owner_6, 'extract_html_file_observations'),
        (owner_7, 'extract_markdown_file_observations'),
        (owner_7, 'markdown_anchors_for_content'),
        (owner_8, 'extract_document_file_observations'),
        (owner_8, 'extract_odf_file_observations'),
    ):

        assert getattr(discovery, symbol_name) is getattr(package_module, symbol_name)


def test_pkg5_configdoc_ingestion_consumers_use_package_symbols() -> None:
    import repomap_kg.extractors.documents.css_html_matching as css_html_matching
    import repomap_kg.extractors.documents.feed as feed
    import repomap_kg.ops.ingestion.bulk as bulk_ingestion
    import repomap_kg.ops.ingestion.source_archive as source_archive
    import repomap_kg.ops.ingestion.source as source_ingestion

    assert (
        bulk_ingestion.extract_css_selector_match_observations
        is css_html_matching.extract_css_selector_match_observations
    )
    assert (
        source_archive.extract_css_selector_match_observations
        is css_html_matching.extract_css_selector_match_observations
    )
    assert (
        source_ingestion.extract_feed_file_observations
        is feed.extract_feed_file_observations
    )


def test_pkg5_configdoc_packages_preserve_private_helper_attributes() -> None:
    import repomap_kg.extractors.config.generic as config_package
    import repomap_kg.extractors.config.paths as config_paths
    import repomap_kg.extractors.documents.css as css_package
    import repomap_kg.extractors.documents.html as html_package

    assert config_package.json_pointer is config_paths.json_pointer
    assert config_package._pointer_segments is config_paths._pointer_segments
    assert (
        config_package._escape_pointer_segment
        is config_paths._escape_pointer_segment
    )
    assert callable(config_package._resolve_repo_path)
    assert callable(css_package._resolve_repo_path)
    assert callable(html_package._resolve_repo_path)


def test_config_ref2_python_ecosystem_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.python as python_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "PYTHON_REQUIREMENTS_FORMAT", "PYTHON_REQUIREMENTS_PROFILE",
        "PYTHON_REQUIREMENTS_NAME_PATTERN", "PYTHON_REQUIREMENT_NAME_PATTERN",
        "PYTHON_MAX_REQUIREMENTS", "PYTHON_MAX_REQUIREMENT_REFERENCES",
        "PYTHON_MAX_REQUIREMENT_DIAGNOSTICS", "PYTHON_MAX_METADATA_STRING",
        "_PythonRequirement", "_extract_python_requirements_observations",
        "_python_package_file_observation", "_python_requirement_line_without_comment",
        "_parse_python_requirement_line", "_python_requirement_extras",
        "_python_requirement_package_from_source", "_python_requirement_observation",
        "_python_requirement_source_observations", "_python_requirement_file_reference_observations",
        "_python_requirement_url_reference_observations", "_python_reference_observation",
        "_python_pyproject_metadata_overrides", "_python_pyproject_observations",
        "_python_requirement_observations_from_values", "_python_entry_point_observations",
        "_python_parse_error_observation", "_python_redaction_observation",
        "_python_dependency_source_metadata", "_python_requirement_file_family",
        "_python_requirement_is_direct_source", "_python_requirement_is_vcs_source",
        "_python_requirement_is_local_path", "_python_requirement_local_path_value",
        "_python_requirement_local_path_target", "_python_pyproject_walk",
        "_python_pyproject_value_requires_redaction", "_python_value_has_credentialed_url_fragment",
        "_python_sequence_count", "_python_bounded_string", "_python_slug",
        "_is_python_requirements_file_name", "_is_pyproject_file_name",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(python_config, name)


def test_config_ref3_javascript_ecosystem_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.javascript as javascript_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "TFJSON_PACKAGE_DEPENDENCY_GROUPS", "TFJSON_FRAMEWORK_DEPENDENCY_HINTS",
        "_package_json_observations", "_package_dependency_observations",
        "_package_framework_hints", "_package_reference_observations",
        "_package_lock_observations", "_typescript_config_observations",
        "_typescript_reference_observation", "_angular_observations",
        "_playwright_observation", "_script_is_secret_prone", "_script_command_summary",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(javascript_config, name)


def test_config_ref4_terraform_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.terraform as terraform_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "TERRAFORM_HCL_FORMAT",
        "TERRAFORM_HCL_PROFILE",
        "TERRAFORM_HCL_TFVARS_PROFILE",
        "TERRAFORM_HCL_PARSER",
        "TERRAFORM_HCL_BLOCK_TYPES",
        "TERRAFORM_HCL_MAX_FILE_BYTES",
        "TERRAFORM_HCL_MAX_BLOCKS",
        "TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK",
        "TERRAFORM_HCL_MAX_REFERENCES",
        "TERRAFORM_HCL_MAX_METADATA_STRING",
        "TERRAFORM_HCL_MAX_DIAGNOSTICS",
        "TERRAFORM_HCL_BLOCK_HEADER_PATTERN",
        "TERRAFORM_HCL_ATTRIBUTE_PATTERN",
        "TERRAFORM_HCL_TRAVERSAL_PATTERN",
        "_TerraformHclBlock",
        "_TerraformHclAttribute",
        "_terraform_json_observations",
        "_terraform_named_block_observations",
        "_terraform_block_names",
        "_terraform_reference_observation",
        "_terraform_tfvars_observations",
        "_extract_terraform_hcl_observations",
        "_extract_terraform_hcl_tfvars_observations",
        "_terraform_hcl_scan_blocks",
        "_terraform_hcl_block_profile_observations",
        "_terraform_hcl_terraform_block_observations",
        "_terraform_hcl_provider_observations",
        "_terraform_hcl_resource_observations",
        "_terraform_hcl_data_observations",
        "_terraform_hcl_module_observations",
        "_terraform_hcl_variable_observations",
        "_terraform_hcl_output_observations",
        "_terraform_hcl_local_observations",
        "_terraform_hcl_move_like_observations",
        "_terraform_hcl_import_observations",
        "_terraform_hcl_block_observation",
        "_terraform_hcl_observation",
        "_terraform_hcl_reference_observations_from_attribute",
        "_terraform_hcl_reference_observation",
        "_terraform_hcl_redaction_observation",
        "_terraform_hcl_parse_error_observation",
        "_terraform_hcl_attribute_redactions",
        "_terraform_hcl_top_level_attributes",
        "_terraform_hcl_labels",
        "_terraform_hcl_brace_delta",
        "_terraform_hcl_collection_delta",
        "_terraform_hcl_delimiter_delta",
        "_terraform_hcl_strip_comment",
        "_terraform_hcl_nested_block_body",
        "_terraform_hcl_nested_block_labels",
        "_terraform_hcl_nested_block_count",
        "_terraform_hcl_collection_body",
        "_terraform_hcl_module_source",
        "_terraform_hcl_local_path_target",
        "_terraform_hcl_reference_names",
        "_terraform_hcl_literal_string",
        "_terraform_hcl_bool_literal",
        "_terraform_hcl_value_type",
        "_terraform_hcl_expression_kind",
        "_terraform_hcl_expression_summary",
        "_terraform_hcl_text_presence_metadata",
        "_terraform_hcl_credentialed_url",
        "_terraform_hcl_bounded_string",
        "_is_terraform_hcl_file_name",
        "_is_terraform_tfvars_hcl_file_name",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(terraform_config, name)


def test_config_ref5_openapi_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.openapi as openapi_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "OPENAPI_HTTP_METHODS",
        "OPENAPI_MAX_PATHS",
        "OPENAPI_MAX_OPERATIONS",
        "OPENAPI_MAX_PARAMETERS_PER_OPERATION",
        "OPENAPI_MAX_RESPONSES_PER_OPERATION",
        "OPENAPI_MAX_SCHEMAS",
        "OPENAPI_MAX_REFERENCES",
        "OPENAPI_MAX_EXAMPLES",
        "OPENAPI_MAX_METADATA_STRING",
        "OPENAPI_TEXT_KEYS",
        "OPENAPI_EXAMPLE_KEYS",
        "_openapi_profile_observations",
        "_openapi_spec_metadata",
        "_openapi_info_observations",
        "_openapi_server_observations",
        "_openapi_path_operation_observations",
        "_openapi_parameter_observation",
        "_openapi_request_body_observations",
        "_openapi_response_observations",
        "_openapi_tag_observations",
        "_openapi_component_observations",
        "_openapi_reference_observations",
        "_openapi_example_and_redaction_observations",
        "_openapi_components",
        "_openapi_parameters",
        "_openapi_media_types",
        "_openapi_operation_count",
        "_openapi_server_count",
        "_openapi_ref_values",
        "_openapi_walk",
        "_openapi_reference_metadata",
        "_openapi_reference_scope",
        "_openapi_oauth_flow_names",
        "_openapi_scope_names",
        "_openapi_text_metadata",
        "_openapi_url_metadata",
        "_openapi_safe_string",
        "_openapi_string_list",
        "_openapi_bounded_string",
        "_openapi_pointer_is_redacted",
        "_openapi_redaction_reason",
        "_openapi_sensitive_key",
        "_openapi_source_suffix",
        "_openapi_parse_error_observation",
        "_is_openapi_document",
        "_is_openapi_file_name",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(openapi_config, name)


def test_config_ref6_yaml_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.yaml as yaml_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "YAML_FORMAT",
        "YAML_PARSER",
        "YAML_MAX_FILE_BYTES",
        "YAML_MAX_DOCUMENTS",
        "YAML_MAX_NODES",
        "YAML_MAX_DEPTH",
        "YAML_MAX_SCALAR_LENGTH",
        "YAML_MAX_ALIASES",
        "YAML_TAG_PATTERN",
        "YAML_ANCHOR_PATTERN",
        "YAML_ALIAS_PATTERN",
        "YAML_SIMPLE_IMAGE_PATTERN",
        "YamlParseError",
        "_YamlLine",
        "_YamlValue",
        "_YamlParseState",
        "_extract_yaml_observations",
        "_parse_yaml_documents",
        "_split_yaml_documents",
        "_yaml_logical_lines",
        "_parse_yaml_block",
        "_parse_yaml_mapping",
        "_parse_yaml_sequence",
        "_yaml_value_or_nested_block",
        "_parse_yaml_scalar",
        "_record_yaml_value_metadata",
        "_strip_yaml_comment",
        "_yaml_first_token",
        "_split_yaml_mapping_pair",
        "_looks_like_yaml_mapping_pair",
        "_yaml_mapping_colon_index",
        "_parse_yaml_inline_sequence",
        "_parse_yaml_inline_mapping",
        "_split_yaml_inline_items",
        "_parse_yaml_plain_scalar",
        "_unquote_yaml_scalar",
        "_yaml_profile",
        "_yaml_documents",
        "_apply_yaml_profile_metadata",
        "_apply_yaml_stable_array_metadata",
        "_yaml_pointer_values",
        "_yaml_document_index_from_pointer",
        "_yaml_pointer_is_redacted",
        "_yaml_pointer_is_kubernetes_secret_data",
        "_yaml_redaction_reason",
        "_yaml_string_references",
        "_yaml_openapi_ref",
        "_yaml_uses_reference",
        "_yaml_spring_file_reference_value",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(yaml_config, name)


def test_config_ref7_xml_plist_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.xml as xml_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "PLIST_XML_FORMAT",
        "PLIST_XML_SAFETY_MODE",
        "GENERIC_XML_FORMAT",
        "GENERIC_XML_SAFETY_MODE",
        "UNSAFE_XML_DECLARATION_PATTERN",
        "UNSAFE_PROCESSING_INSTRUCTION_PATTERN",
        "PLIST_ROOT_PATTERN",
        "PlistXmlSafetyError",
        "PlistXmlParseError",
        "GenericXmlSafetyError",
        "_extract_plist_xml_observations",
        "_extract_generic_xml_observations",
        "_looks_like_plist_xml",
        "_check_safe_plist_xml",
        "_check_safe_generic_xml",
        "_xml_parse_error_line",
        "_plist_root_value",
        "_plist_value",
        "_plist_dict",
        "_xml_local_name",
        "_xml_name_parts",
        "_xml_attribute_parts",
        "_xml_namespace_summary",
        "_generic_xml_document_role",
        "_walk_xml_element",
        "_xml_child_pointers",
        "_xml_element_metadata",
        "_xml_attribute_metadata",
        "_xml_role_hint",
        "_xml_domain_metadata",
        "_xml_direct_child_texts",
        "_xml_parentish_property_name",
        "_xml_attribute_semantic_key",
        "_is_secret_xml_element",
        "_is_placeholder_heavy",
        "_xml_reference_observations",
        "_detect_xml_references",
        "_looks_like_xml_file_key",
        "_xml_file_reference",
        "_xml_parse_error_observation",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(xml_config, name)


def test_config_ref8_infrastructure_imports_are_preserved() -> None:
    import repomap_kg.extractors.config.infrastructure as infrastructure_config
    import repomap_kg.extractors.config.generic as config_package

    moved_names = (
        "_json_pointer_is_kubernetes_secret_data",
        "_kubernetes_json_observations",
        "_argocd_observations",
        "_liquibase_observations",
        "_liquibase_changeset_count",
        "_docker_json_observations",
        "_docker_image_observations",
        "_json_image_values",
        "_is_argocd_json_document",
        "_is_liquibase_json_document",
        "_is_kubernetes_document",
        "_is_docker_compose_document",
        "_is_grafana_document",
        "_looks_like_container_image",
    )

    for name in moved_names:
        assert getattr(config_package, name) is getattr(infrastructure_config, name)
