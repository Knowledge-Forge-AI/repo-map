"""Closed TEST-COV5K-R2-FIX1 qualification case catalog facade."""

from __future__ import annotations

from repomap_test_support.test_cov5k_r2_fix1_catalog_administrative import (
    K_FIXED_ARGV_SHAPES as K_FIXED_ARGV_SHAPES,
    K_REHEARSAL_ARGV_SHAPES as K_REHEARSAL_ARGV_SHAPES,
    _gates_and_selections as _gates_and_selections,
    _group_k as _group_k,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog_runtime import (
    _group_a as _group_a,
    _group_b as _group_b,
    _group_c as _group_c,
    _group_f as _group_f,
    _group_g as _group_g,
    _group_h as _group_h,
    _groups_b_c_e_f as _groups_b_c_e_f,
    _groups_i_j as _groups_i_j,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog_storage import (
    _group_d as _group_d,
    _group_e as _group_e,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog_values import (
    CatalogEntry as CatalogEntry,
    ParameterTuple as ParameterTuple,
    REQUIRED_MANIFEST_GROUPS as REQUIRED_MANIFEST_GROUPS,
    Scalar as Scalar,
    _BASE_OBSERVATION as _BASE_OBSERVATION,
    _GROUP_G_OBSERVATION as _GROUP_G_OBSERVATION,
    _OWNER_ROOT as _OWNER_ROOT,
    _TOOL_ROOT as _TOOL_ROOT,
    _entry as _entry,
    _numbered_group as _numbered_group,
)


def build_closed_catalog() -> tuple[CatalogEntry, ...]:
    """Return the complete immutable A-K, gate, and selection catalog."""
    entries = (
        *_group_a(),
        *_groups_b_c_e_f(),
        *_group_d(),
        *_group_g(),
        *_group_h(),
        *_groups_i_j(),
        *_group_k(),
        *_gates_and_selections(),
    )
    legacy_case_id = {
        "A04": "two_source_failures",
        "A05": "source_failure_then_timeout",
        "A06": "timeout_then_source_failure",
        "A09": "cleanup_limitation",
    }.get
    return tuple(sorted(entries, key=lambda item: legacy_case_id(item.condition_id, item.case_id)))
