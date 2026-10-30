"""Documented CLOE configuration migration API at its legacy path (ADR 0114, ADR 0123).

These names are the canonical function objects, not wrappers.
"""

from common_lore_index.ops.config_migration import (
    apply_cloe_config_migration as apply_cloe_config_migration,
    finalize_cloe_config_migration as finalize_cloe_config_migration,
    rollback_cloe_config_migration as rollback_cloe_config_migration,
)
