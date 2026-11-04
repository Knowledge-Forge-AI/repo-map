"""Original journal anchors, rather than current source, bind raw components."""

from dataclasses import FrozenInstanceError, replace
import json
import io
from pathlib import Path
import stat
import zipfile

import pytest

from repomap_test_support.w5_component_artifacts import encoded, make_component_pair
from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from retrieval_semantic_pair_artifacts import PairReportRefusal, digest_bytes, load_journal
from retrieval_semantic_raw_component import read_raw_component, verify_raw_component
from retrieval_semantic_raw_component_anchors import COMPONENT_ROLES, MEMBER_ROLES
from retrieval_semantic_raw_component_io import read_model_members
from retrieval_semantic_generator_output_receipt import read_worker_archive_inputs
from retrieval_semantic_provenance import RepresentationValidationError


def test_reader_projects_only_frozen_counts_and_digests(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    summary = read_raw_component(sources.journals[1], sources.models[1])
    assert summary.generation == 1 and summary.attempt_id == "w5-semantic-g1"
    assert set(dict(summary.component_digests)) == set(COMPONENT_ROLES)
    assert dict(summary.counts)["query_count"] == 0
    assert set(summary.__dataclass_fields__) == {"generation","attempt_id","counts","component_digests"}
    with pytest.raises(FrozenInstanceError):
        setattr(summary, "generation", 2)


@pytest.mark.parametrize("name", MEMBER_ROLES)
def test_every_supplied_member_digest_is_bound(tmp_path: Path, name: str) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    members = dict(read_model_members(sources.models[1]))
    members[name] += b"tampered"
    with pytest.raises(PairReportRefusal):
        verify_raw_component(journal, members)


@pytest.mark.parametrize("role", COMPONENT_ROLES)
def test_every_independent_recorded_digest_is_mandatory(tmp_path: Path, role: str) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    report = dict(journal.report)
    component = report["component"]
    assert isinstance(component, dict)
    report["component"] = {**component, role:"sha256:"+"f"*64}
    with pytest.raises(PairReportRefusal):
        verify_raw_component(replace(journal, report=report), read_model_members(sources.models[1]))


def test_other_generation_raw_bundle_refuses(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    with pytest.raises(PairReportRefusal):
        read_raw_component(sources.journals[1], sources.models[2])


def test_boolean_recorded_count_refuses_even_when_equal_to_one(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    report = dict(journal.report)
    counts = report["component_counts"]
    assert isinstance(counts, dict)
    report["component_counts"] = {**counts, "query_count":False}
    with pytest.raises(PairReportRefusal, match="pair_v2_component_counts"):
        verify_raw_component(replace(journal, report=report), read_model_members(sources.models[1]))


def test_extra_member_refuses_at_public_bytes_seam(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    members = {**read_model_members(sources.models[1]), "unexpected.json":b"{}\n"}
    with pytest.raises(PairReportRefusal, match="component_members"):
        verify_raw_component(load_journal(sources.journals[1]), members)


@pytest.mark.parametrize("field,value,code", [
    ("record_count",True,"invalid_worker_counts"),
    ("claim","/private/fixture","invalid_worker_report"),
    ("elapsed_seconds",-1,"invalid_worker_elapsed"),
    ("partial",True,"invalid_worker_partial_state"),
    ("query_count",1,"worker_count_mismatch"),
    ("input_identity","sha256:"+"f"*64,"worker_request_identity_mismatch"),
])
def test_coherent_outer_digests_do_not_bypass_real_response_parser(
    tmp_path: Path, field: str, value: object, code: str,
) -> None:
    sources = make_component_pair(tmp_path)
    journal = load_journal(sources.journals[1])
    members = dict(read_model_members(sources.models[1]))
    response = json.loads(members["report.json"])
    response[field] = value
    members["report.json"] = encoded(response)
    terminal = json.loads(members["terminal.json"])
    terminal["report_sha256"] = digest_bytes(members["report.json"])
    members["terminal.json"] = encoded(terminal)
    report = dict(journal.report)
    component = report["component"]
    assert isinstance(component, dict)
    report["component"] = {**component,"report":digest_bytes(members["report.json"]),
                           "terminal":digest_bytes(members["terminal.json"])}
    with pytest.raises(PairReportRefusal) as caught:
        verify_raw_component(replace(journal, report=report), members)
    assert caught.value.code == "component_response." + code
    assert "/private/fixture" not in str(caught.value)


def test_real_admission_parser_subcode_is_preserved(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path, admission_admitted=False)
    with pytest.raises(PairReportRefusal) as caught:
        read_raw_component(sources.journals[1], sources.models[1])
    assert caught.value.code == "component_response.component_execution_not_admitted"


@pytest.mark.parametrize("violation", ["compressed","comment","traversal","symlink"])
def test_public_archive_seam_preserves_existing_refusal_rules(violation: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as archive:
        name = "sources/../fixture.py" if violation == "traversal" else "sources/fixture.py"
        member = zipfile.ZipInfo(name)
        member.compress_type = zipfile.ZIP_DEFLATED if violation == "compressed" else zipfile.ZIP_STORED
        member.external_attr = ((stat.S_IFLNK | 0o777) if violation == "symlink" else (stat.S_IFREG | 0o644)) << 16
        archive.writestr(member,b"public fixture")
        if violation == "comment": archive.comment = b"comment"
    with pytest.raises(RepresentationValidationError) as caught:
        read_worker_archive_inputs(buffer.getvalue())
    assert caught.value.code == "invalid_worker_archive"


def test_supplied_bundle_cannot_replace_absent_canonical_component_identity(tmp_path: Path) -> None:
    old_journal, _result = make_pair_artifacts(tmp_path / "old", 1)
    supplied = make_component_pair(tmp_path / "new")
    with pytest.raises(PairReportRefusal, match="component_digest_map"):
        read_raw_component(old_journal, supplied.models[1])
