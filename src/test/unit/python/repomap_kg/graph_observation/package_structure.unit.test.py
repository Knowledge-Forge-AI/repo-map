from __future__ import annotations



RAW_OBSERVATION_EXPORTS = [
    "RawObservation",
    "ObservationValidationError",
    "read_observations_jsonl",
    "write_observations_jsonl",
    "VALID_CONFIDENCES",
    "_read_observations_lines",
]


def test_pkg6_observations_package_exports_raw_symbols() -> None:
    import repomap_kg.observations as observations
    import repomap_kg.observations.raw as raw
    for symbol_name in RAW_OBSERVATION_EXPORTS:
        assert getattr(observations, symbol_name) is getattr(raw, symbol_name)


def test_pkg6_graph_keys_round_trip_through_package_path() -> None:
    import repomap_kg.graph.keys as graph_keys
    key = graph_keys.file_key("src/main/python/repomap_kg/cli.py")

    assert graph_keys.parse_key(key).path == "src/main/python/repomap_kg/cli.py"


def test_pkg6_observation_and_normalization_work_through_package_paths() -> None:
    import repomap_kg.observations as observations
    import repomap_kg.observations.raw as raw
    import repomap_kg.observations.normalization as normalization
    observation = raw.RawObservation(
        kind="file",
        source_id="pkg6",
        path="README.md",
        confidence="extracted",
        extractor="pkg6-test",
        extractor_version="0",
        name="README.md",
    )

    normalized = normalization.normalize_observations([observation])

    assert observations.RawObservation is raw.RawObservation
    assert normalized.raw_observations == 1
    assert len(normalized.nodes) == 1
