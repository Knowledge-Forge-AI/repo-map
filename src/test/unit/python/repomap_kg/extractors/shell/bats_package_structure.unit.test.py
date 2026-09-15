from __future__ import annotations



BATS_OBSERVATION_EXPORTS = (
    "assertion_observations",
    "fixture_reference_metadata",
    "fixture_reference_observations",
    "helper_reference_from_load",
    "helper_reference_observation",
    "library_load_observation",
    "library_load_observations",
    "load_observations",
    "load_target",
    "output_expectation_observation",
    "run_observations",
    "skip_observations",
    "status_expectation_observation",
)


def test_rootpkg22_bats_reexports_observation_builders() -> None:
    import repomap_kg.extractors.shell.bats as bats
    import repomap_kg.extractors.shell.bats_observations as observations
    for name in BATS_OBSERVATION_EXPORTS:
        assert getattr(bats, name) is getattr(observations, name)
