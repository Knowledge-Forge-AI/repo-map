from __future__ import annotations



TERRAFORM_HCL_OBSERVATION_EXPORTS = (
    "_terraform_hcl_attribute_redactions",
    "_terraform_hcl_block_observation",
    "_terraform_hcl_observation",
    "_terraform_hcl_parse_error_observation",
    "_terraform_hcl_redaction_observation",
    "_terraform_hcl_reference_observation",
    "_terraform_hcl_reference_observations_from_attribute",
)

TERRAFORM_HCL_PROFILE_EXPORTS = (
    "_terraform_hcl_block_profile_observations",
    "_terraform_hcl_data_observations",
    "_terraform_hcl_import_observations",
    "_terraform_hcl_local_observations",
    "_terraform_hcl_module_observations",
    "_terraform_hcl_move_like_observations",
    "_terraform_hcl_output_observations",
    "_terraform_hcl_provider_observations",
    "_terraform_hcl_resource_observations",
    "_terraform_hcl_scan_blocks",
    "_terraform_hcl_terraform_block_observations",
    "_terraform_hcl_top_level_attributes",
    "_terraform_hcl_variable_observations",
)


def test_rootpkg20_terraform_reexports_split_hcl_helpers() -> None:
    import repomap_kg.extractors.config.terraform as terraform
    import repomap_kg.extractors.config.terraform_hcl_observations as observations
    import repomap_kg.extractors.config.terraform_hcl_profiles as profiles
    for name in TERRAFORM_HCL_OBSERVATION_EXPORTS:
        assert getattr(terraform, name) is getattr(observations, name)
    for name in TERRAFORM_HCL_PROFILE_EXPORTS:
        assert getattr(terraform, name) is getattr(profiles, name)
