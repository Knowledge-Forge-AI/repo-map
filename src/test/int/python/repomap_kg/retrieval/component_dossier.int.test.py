"""Real temporary-file joins across canonical, raw-worker and paired artifacts."""

from pathlib import Path
from typing import Any

import pytest

import retrieval_semantic_component_dossier as dossier_module
from repomap_test_support.w5_component_artifacts import make_component_pair
from retrieval_semantic_component_dossier import build_component_dossier
from retrieval_semantic_component_dossier_io import read_component_dossier, write_component_dossier
from retrieval_semantic_pair_artifacts import PairReportRefusal


def test_two_generation_raw_artifacts_round_trip_with_original_bytes(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    original = {path:path.read_bytes() for path in [sources.paired,*sources.results.values(),
        *(member for root in sources.journals.values() for member in root.iterdir()),
        *(member for root in sources.models.values() for member in root.iterdir())]}
    report = build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
    output = tmp_path / "dossier.json"
    write_component_dossier(output, report)
    parsed: Any = read_component_dossier(output)
    assert [row["component"]["correspondence"] for row in parsed["generations"]] == ["verified","verified"]
    assert all(path.read_bytes() == raw for path,raw in original.items())
    assert output.stat().st_size < 64 * 1024


@pytest.mark.parametrize("member", ["declaration.json","report.json","source-manifest.json","sources.zip","terminal.json"])
def test_tampered_complete_raw_bundle_refuses(tmp_path: Path, member: str) -> None:
    sources = make_component_pair(tmp_path)
    path = sources.models[2] / member
    path.write_bytes(path.read_bytes()+b"tampered")
    with pytest.raises(PairReportRefusal):
        build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)


def test_partial_supplied_bundle_is_not_downgraded_to_unknown(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    (sources.models[1] / "terminal.json").unlink()
    with pytest.raises(PairReportRefusal):
        build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
    report: Any = build_component_dossier(sources.journals, sources.results, sources.paired)
    assert all(row["component"]["artifact_correspondence_verified"] is None for row in report["generations"])


def test_result_identity_mismatch_refuses_real_source_join(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    with pytest.raises(PairReportRefusal):
        build_component_dossier(sources.journals, {1:sources.results[2],2:sources.results[1]}, sources.paired)


def test_same_name_raw_model_content_drift_refuses_composed_join(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    original = dossier_module.build_pair_report_v2
    def change_after_rebuild(*args, **kwargs):
        report = original(*args, **kwargs)
        path = sources.models[1] / "report.json"
        path.write_bytes(path.read_bytes() + b" ")
        return report
    monkeypatch.setattr(dossier_module, "build_pair_report_v2", change_after_rebuild)
    with pytest.raises(PairReportRefusal, match="source_changed"):
        build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
