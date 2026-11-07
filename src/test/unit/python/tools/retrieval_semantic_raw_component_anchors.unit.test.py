"""Canonical closure and input anchors are independent, strict and original."""

from dataclasses import replace
from pathlib import Path

import pytest

from repomap_test_support.w5_component_artifacts import make_component_pair
from retrieval_semantic_pair_artifacts import PairReportRefusal, load_journal
from retrieval_semantic_raw_component_anchors import canonical_anchors, digest_map, safe_subcode


def test_canonical_source_census_may_be_a_superset(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    anchors = canonical_anchors(journal)
    assert tuple(name for name, _ in anchors.closure) == ("fixture_worker.py",)
    source_files = journal.source_manifest["source_files"]
    assert isinstance(source_files, dict) and len(source_files) == 2


@pytest.mark.parametrize("field", ["source_closure","component_source_closure","controller_admission_sha256"])
def test_missing_original_anchor_refuses(tmp_path: Path, field: str) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    declaration = dict(journal.declaration)
    del declaration[field]
    with pytest.raises(PairReportRefusal):
        canonical_anchors(replace(journal, declaration=declaration))


@pytest.mark.parametrize("field", ["request.json","admission.json"])
def test_canonical_input_digest_disagreement_refuses(tmp_path: Path, field: str) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    manifest = dict(journal.source_manifest)
    inputs = manifest["input_files"]
    assert isinstance(inputs, dict)
    manifest["input_files"] = {**inputs, field:"sha256:"+"f"*64}
    with pytest.raises(PairReportRefusal, match="component_input_anchor"):
        canonical_anchors(replace(journal, source_manifest=manifest))


def test_canonical_source_member_disagreement_refuses(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    manifest = dict(journal.source_manifest)
    manifest["source_files"] = {"tools/fixture_worker.py":"sha256:"+"f"*64}
    with pytest.raises(PairReportRefusal, match="component_source_anchor"):
        canonical_anchors(replace(journal, source_manifest=manifest))


@pytest.mark.parametrize("value", [None, [], {"a":True}, {"a":"sha256:"+"A"*64}, {"a":"/private/fixture"}])
def test_digest_maps_refuse_invalid_types(value: object) -> None:
    with pytest.raises(PairReportRefusal):
        digest_map(value)


def test_unsafe_underlying_message_is_never_a_subcode() -> None:
    class CodedError(ValueError):
        code = "/private/fixture"
    error = CodedError("/private/fixture must stay private")
    assert safe_subcode(error) == "component_validation"
    error.code = "invalid_worker_report"
    assert safe_subcode(error) == "invalid_worker_report"
