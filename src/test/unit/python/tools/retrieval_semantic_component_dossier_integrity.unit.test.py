"""Dossier source joins and closed structural states refuse contradictory credit."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import retrieval_semantic_component_dossier as dossier_module
from repomap_test_support.w5_component_artifacts import make_component_pair
from retrieval_semantic_component_dossier import build_component_dossier
from retrieval_semantic_component_dossier_contract import validate_component_dossier
from retrieval_semantic_pair_artifacts import PairReportRefusal


@pytest.mark.parametrize("slots", [{True:"bad",2:"bad"}, {1:"bad"}, [(1,"bad"),(1,"bad"),(2,"bad")], {0:"bad",2:"bad"}, "bad", ["bad"], [(1,"bad",3),(2,"bad")]])
def test_invalid_generation_slots_refuse_before_io(slots: object) -> None:
    with pytest.raises(PairReportRefusal, match="source_slots"):
        build_component_dossier(slots, {}, "not-a-path")


@pytest.mark.parametrize("slots", [{True:"bad"}, [(1,"a"),(1,"b")], {3:"bad"}])
def test_invalid_optional_model_slots_refuse_before_io(slots: object) -> None:
    with pytest.raises(PairReportRefusal, match="source_slots"):
        build_component_dossier({1:"unused",2:"unused"}, {1:"unused",2:"unused"}, "unused", slots)


def test_swapped_journal_generations_refuse(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    with pytest.raises(PairReportRefusal, match="journal_generation"):
        build_component_dossier({1:sources.journals[2],2:sources.journals[1]}, sources.results, sources.paired)


def test_same_json_with_different_paired_bytes_refuses(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    sources.paired.write_bytes(sources.paired.read_bytes() + b" ")
    with pytest.raises(PairReportRefusal, match="paired_source_mismatch"):
        build_component_dossier(sources.journals, sources.results, sources.paired)


def test_result_replacement_during_build_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    original = dossier_module.build_pair_report_v2
    def replace_result(*args, **kwargs):
        report = original(*args, **kwargs)
        replacement = tmp_path / "replacement"
        replacement.write_bytes(sources.results[1].read_bytes())
        replacement.replace(sources.results[1])
        return report
    monkeypatch.setattr(dossier_module, "build_pair_report_v2", replace_result)
    with pytest.raises(PairReportRefusal, match="source_changed"):
        build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)


def test_late_extra_model_member_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    original = dossier_module.build_pair_report_v2
    def add_extra(*args, **kwargs):
        report = original(*args, **kwargs)
        (sources.models[1] / "extra").write_bytes(b"public")
        return report
    monkeypatch.setattr(dossier_module, "build_pair_report_v2", add_extra)
    with pytest.raises(PairReportRefusal, match="component_members"):
        build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)


def test_one_explicit_raw_bundle_does_not_verify_the_other(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired, {1:sources.models[1]})
    rows: Any = report["generations"]
    assert rows[0]["component"]["artifact_correspondence_verified"] is True
    assert rows[1]["component"]["artifact_correspondence_verified"] is None


@pytest.mark.parametrize("path,value", [
    (("acceptance","production_admitted"), True),
    (("private_path",), "/private/fixture"),
    (("generations",0,"component","vector"), [1.0]),
    (("generations",0,"generation"), True),
    (("generations",0,"component","recorded_counts","query_count"), False),
    (("generations",0,"component","recorded_counts","query_count"), -1),
    (("generations",0,"component","recorded_counts","record_count"), 999999),
    (("generations",0,"attempt_id"), "other"),
    (("generations",0,"component","verified_counts"), {"query_count":0}),
    (("generations",0,"component","artifact_correspondence_verified"), False),
    (("generations",0,"component","correspondence"), "verified"),
    (("generations",0,"component","recorded_component_digests","unknown"), "sha256:"+"a"*64),
    (("disclosures","reader"), "/private/fixture"),
    (("generations",0,"result_v2","sha256"), "sha256:"+"A"*64),
    (("generations",0,"result_v2","length"), True),
])
def test_structural_reader_refuses_forged_closed_states(tmp_path: Path, path: tuple[object, ...], value: object) -> None:
    sources = make_component_pair(tmp_path)
    report: Any = deepcopy(build_component_dossier(sources.journals, sources.results, sources.paired))
    cursor = report
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    with pytest.raises(PairReportRefusal):
        validate_component_dossier(report)
