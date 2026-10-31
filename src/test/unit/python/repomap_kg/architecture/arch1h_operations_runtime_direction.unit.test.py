from __future__ import annotations



def test_arch1h_config_facade_and_runtime_share_loading_contracts() -> None:
    import common_lore_index.ops.config as config
    import common_lore_index.ops.config_loading as loading
    import common_lore_index.runtime.local as runtime_local
    import common_lore_index.runtime.plan as runtime_plan
    for name in (
        "build_ops_config_from_payload",
        "load_ops_config",
        "load_ops_config_home",
        "resolve_repo_map_home",
    ):
        assert getattr(config, name) is getattr(loading, name)

    assert runtime_local.resolve_repo_map_home is loading.resolve_repo_map_home
    assert runtime_plan.load_ops_config_home is loading.load_ops_config_home
    assert runtime_plan.OpsConfigError is config.OpsConfigError


def test_arch1h_report_records_use_lower_diagnostic_contracts() -> None:
    import common_lore_index.ops.config as config
    import common_lore_index.ops.config_helpers as helpers
    import common_lore_index.ops.report_records as records
    assert config.OpsConfigDiagnostic is helpers.OpsConfigDiagnostic
    assert records.OpsConfigDiagnostic is helpers.OpsConfigDiagnostic
    assert config.redact_text is helpers.redact_text
    assert records.redact_text is helpers.redact_text
