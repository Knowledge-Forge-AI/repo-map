"""Separate dossiers preserve old unknowns and verify explicit raw components."""

from pathlib import Path
from typing import Any

from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from repomap_test_support.w5_component_artifacts import make_component_pair
from retrieval_semantic_component_dossier import build_component_dossier
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import digest_bytes
from retrieval_semantic_pair_report import build_pair_report
from retrieval_semantic_pair_v2_report import build_pair_report_v2


def _rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return report["generations"]


def test_complete_raw_components_are_bound_without_acceptance(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    original = sources.paired.read_bytes()
    report = build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
    assert report["schema"] == "cloe-w5-component-dossier-v1"
    for row in _rows(report):
        component = row["component"]
        assert component["recorded"] == "recorded"
        assert component["supplied"] == "supplied"
        assert component["correspondence"] == "verified"
        assert component["artifact_correspondence_verified"] is True
        assert component["verified_counts"] == component["recorded_counts"]
        assert component["verified_counts"]["query_count"] == 0
    acceptance = report["acceptance"]
    assert isinstance(acceptance, dict)
    assert all(value is False for value in acceptance.values())
    assert sources.paired.read_bytes() == original


def test_missing_raw_components_remain_unknown(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    for row in _rows(report):
        component = row["component"]
        assert component["recorded"] == "recorded"
        assert component["supplied"] == "not_supplied"
        assert component["correspondence"] == "unknown"
        assert component["artifact_correspondence_verified"] is None
        assert component["verified_counts"] is None


def test_verification_does_not_retroactively_record_old_counts(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path, recorded=False)
    report = build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
    for row in _rows(report):
        component = row["component"]
        assert component["recorded"] == "not_recorded"
        assert component["recorded_counts"] is None
        assert component["verified_counts"]["query_count"] == 0
        assert component["artifact_correspondence_verified"] is True


def test_original_fixed_v1_and_v2_bytes_rebuild_unchanged(tmp_path: Path) -> None:
    artifacts = {generation:make_pair_artifacts(tmp_path,generation) for generation in (1,2)}
    journals = {generation:value[0] for generation,value in artifacts.items()}
    results = {generation:value[1] for generation,value in artifacts.items()}
    expected = {
        "v1":(146243,"sha256:29b33459b63df5ca7bd2331ab5480036230d5fdc3cd393ead4e73535e56753f7"),
        "v2":(186153,"sha256:7c695f822f873f459e876056746ea7fd7413a8a64ec70f5dc309a263a8bfba2d"),
    }
    for name,builder in (("v1",build_pair_report),("v2",build_pair_report_v2)):
        raw = canonical_json_bytes(builder(journals,results)) + b"\n"
        assert (len(raw),digest_bytes(raw)) == expected[name]
