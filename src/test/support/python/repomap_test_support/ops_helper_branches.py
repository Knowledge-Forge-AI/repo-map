from repomap_test_support.ops_helper_branches_baselines import (
    OpsBaselineHelperBranchContract,
)
from repomap_test_support.ops_helper_branches_preflight_config_mcp import (
    OpsPreflightConfigMcpHelperBranchContract,
)
from repomap_test_support.ops_helper_branches_runtime_backup_mcp import (
    OpsRuntimeBackupMcpHelperBranchContract,
)


class OpsHelperBranchContractTests(
    OpsBaselineHelperBranchContract,
    OpsPreflightConfigMcpHelperBranchContract,
    OpsRuntimeBackupMcpHelperBranchContract,
):
    __test__ = False

    pass
