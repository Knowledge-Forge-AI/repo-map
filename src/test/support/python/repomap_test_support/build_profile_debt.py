"""Visible ownership for real-build tests excluded from ordinary profiles."""

from __future__ import annotations

DEFERRED_BUILD_PROFILE_NODE_IDS = (
    "src/test/int/python/repomap_kg/runtime/scale14_postgres_storage.int.test.py::test_scale14_exact_pgdata_authority_on_disposable_local_runtime",
    "src/test/int/python/repomap_kg/storage/scale14_protected_launch_controls.int.test.py::test_scale15_real_storage_terminal_authority_campaigns",
    "src/test/int/python/repomap_kg/storage/scale18_structural_digest_parity.int.test.py::test_prelaunch_and_streaming_readback_digest_parity_repeats_exactly",
    "src/test/int/python/repomap_kg/storage/scale23_backend_telemetry_lifetime.int.test.py::test_scale23_direct_child_acknowledgement_failure_fails_closed",
    "src/test/int/python/repomap_kg/storage/scale23_backend_telemetry_lifetime.int.test.py::test_scale23_direct_child_backend_telemetry_lifetime_campaign",
    "src/test/int/python/repomap_kg/storage/scale28_backend_observer_lifetime.int.test.py::test_scale28_fix12_fifteen_consecutive_mixed_configured_campaigns",
    "src/test/int/python/repomap_kg/storage/scale28_backend_observer_lifetime.int.test.py::test_scale28_fix12_three_entirely_fresh_public_rehearsals",
    "src/test/int/python/repomap_kg/storage/scale28_backend_observer_lifetime.int.test.py::test_scale28_hybrid_prior_publication_preserves_source_owned_failure",
    "src/test/int/python/repomap_kg/storage/scale28_backend_observer_lifetime.int.test.py::test_scale28_ten_mixed_observer_success_and_failure_campaigns",
    "src/test/int/python/repomap_kg/storage/scale28_backend_observer_lifetime.int.test.py::test_scale28_twenty_long_extraction_observer_campaigns",
    "src/test/int/python/repomap_test_support/test_cov5k_r2_fix1_rehearsal.int.test.py::test_bounded_model_rehearsal_is_complete_and_unqualified",
    "src/test/int/python/repomap_test_support/test_cov5k_r2_fix2_administrative_rehearsal.int.test.py::test_all_group_k_operations_use_actual_disposable_routes[K07]",
)


def enforce_build_profile_authority() -> None:
    """Fail closed until a separately authorized build profile replaces this."""
    raise RuntimeError(
        "real-build test requires an implemented build-profile authority; "
        "TEST-HYGIENE3C remains deferred"
    )


__all__ = [
    "DEFERRED_BUILD_PROFILE_NODE_IDS",
    "enforce_build_profile_authority",
]
