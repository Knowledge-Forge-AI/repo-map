"""The maintained worker journal is the only accepted generation receipt."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest

import retrieval_semantic_generator_worker as worker
from repomap_test_support.w5_semantic_support import (
    make_w5_sample_nodes_and_evidence,
    make_w5_verified_pin,
)
from retrieval_semantic_generator_inputs import (
    build_worker_request,
    prepare_public_generation_input,
)
from retrieval_semantic_generator_kernel import (
    QUERY_PREFIX,
    SemanticCost,
    SemanticEmbedding,
    SemanticGeneration,
    SemanticMode,
)
from retrieval_semantic_generator_output import (
    parse_verified_worker_response,
    seal_generation_result,
)
from retrieval_semantic_generator_output_receipt import _digest
from retrieval_semantic_generator_runtime import RuntimeFactory
from retrieval_semantic_provenance import RepresentationValidationError
from retrieval_semantic_representation import validate_canonical_node_representations

PROFILE = "sha256:" + "4" * 64
OPERATOR = "sha256:" + "a" * 64
GATE = "sha256:" + "b" * 64


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        + b"\n"
    )


def _inputs():
    pin = make_w5_verified_pin()
    nodes, evidence = make_w5_sample_nodes_and_evidence()
    report = validate_canonical_node_representations(
        pin, accepted_nodes=nodes, accepted_evidence=evidence
    )
    return prepare_public_generation_input(
        report,
        (),
        read_current=lambda: pin,
        read_representations=lambda: report,
    )


def _generation(records):
    records = tuple(records)
    embeddings = tuple(
        SemanticEmbedding(
            record.record_id,
            record.mode,
            (1.0,) + (0.0,) * 383,
            20,
            20,
            0,
            False,
        )
        for record in records
    )
    input_bytes = sum(
        len(record.record_id.encode()) + len(record.text.encode()) for record in records
    )
    model_bytes = sum(
        len(((QUERY_PREFIX if record.mode is SemanticMode.QUERY else "") + record.text).encode())
        for record in records
    )
    cost = SemanticCost(
        len(records),
        input_bytes,
        model_bytes,
        20 * len(records),
        20 * len(records),
        0,
        0,
        0.1,
        0.2,
        0.3,
    )
    return SemanticGeneration(embeddings, cost, "complete", False)


def _run_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime_factory: RuntimeFactory | None = None,
    forwarded: dict[str, object] | None = None,
):
    inputs = _inputs()
    request = build_worker_request(
        inputs,
        attempt_id="protocol-positive-1",
        artifact_profile_identity=PROFILE,
    )
    request_raw = _canonical(request)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(request_raw)
    source_files = worker._source_files()
    closure = worker._source_digests(source_files)
    admission = {
        "schema": worker.CONTROLLER_ADMISSION_SCHEMA,
        "phase": "unit-protocol",
        "operator_authority_sha256": OPERATOR,
        "gate_references": {"protocol": GATE},
        "bounded_component_execution_admitted": True,
        "request_sha256": _digest(request_raw),
        "input_identity": request["input_identity"],
        "representation_report_identity": request["representation_report_identity"],
        "publication_identity": request["publication_identity"],
        "artifact_profile_identity": PROFILE,
        "candidate_closure_digests": closure,
        "scope": "maintained journal protocol unit proof",
    }
    admission_raw = _canonical(admission)
    admission_path = tmp_path / "admission.json"
    admission_path.write_bytes(admission_raw)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    class FakeKernel:
        def __init__(self, _profile, *, runtime_factory: RuntimeFactory | None = None):
            if forwarded is not None:
                forwarded["runtime_factory"] = runtime_factory

        def generate(self, records):
            return _generation(records)

    monkeypatch.setattr(
        worker,
        "verify_artifact_directory",
        lambda _root: SimpleNamespace(source_identity_sha256=PROFILE),
    )
    monkeypatch.setattr(worker, "SemanticGeneratorKernel", FakeKernel)
    output_root = tmp_path / "output"
    worker.run_worker(
        request_path,
        artifact_root,
        output_root,
        admission_path=admission_path,
        expected_admission_sha256=_digest(admission_raw),
        runtime_factory=runtime_factory,
    )
    directory = output_root / "protocol-positive-1"
    files = {
        name: (directory / name).read_bytes()
        for name in (
            "declaration.json",
            "source-manifest.json",
            "sources.zip",
            "report.json",
            "terminal.json",
        )
    }
    return inputs, request_raw, admission_raw, closure, files


def _parse(files, request_raw, admission_raw, closure):
    return parse_verified_worker_response(
        request_raw=request_raw,
        report_raw=files["report.json"],
        terminal_raw=files["terminal.json"],
        declaration_raw=files["declaration.json"],
        source_manifest_raw=files["source-manifest.json"],
        sources_archive_raw=files["sources.zip"],
        expected_controller_admission_sha256=_digest(admission_raw),
        expected_source_closure=closure,
    )


def _relink(files, *, report=None, archive=None):
    updated = dict(files)
    report_raw = updated["report.json"] if report is None else report
    archive_raw = updated["sources.zip"] if archive is None else archive
    manifest = json.loads(updated["source-manifest.json"])
    manifest["archive_sha256"] = _digest(archive_raw)
    manifest_raw = _canonical(manifest)
    terminal = json.loads(updated["terminal.json"])
    terminal["report_sha256"] = _digest(report_raw)
    terminal["source_manifest_sha256"] = _digest(manifest_raw)
    terminal["sources_archive_sha256"] = _digest(archive_raw)
    updated["report.json"] = report_raw
    updated["source-manifest.json"] = manifest_raw
    updated["terminal.json"] = _canonical(terminal)
    updated["sources.zip"] = archive_raw
    return updated


def test_maintained_worker_journal_parses_and_seals_without_real_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs, request_raw, admission_raw, closure, files = _run_receipt(tmp_path, monkeypatch)
    response = _parse(files, request_raw, admission_raw, closure)
    assert response.status == "completed"
    assert response.request_sha256 == _digest(request_raw)
    assert response.sources_archive_sha256 == _digest(files["sources.zip"])
    assert response.source_closure_digests == tuple(sorted(closure.items()))
    artifact = seal_generation_result(inputs, response)
    assert artifact.complete_generation
    assert len(artifact.require_importable()) == len(inputs.documents)


def test_admitted_phase_runtime_factory_is_forwarded_without_request_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    forwarded: dict[str, object] = {}

    def runtime_factory(*_args):
        raise AssertionError("the forwarding fake must not construct a runtime")

    _run_receipt(
        tmp_path,
        monkeypatch,
        runtime_factory=runtime_factory,
        forwarded=forwarded,
    )
    assert forwarded["runtime_factory"] is runtime_factory


def test_protocol_mutations_refuse_whole_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs, request_raw, admission_raw, closure, files = _run_receipt(tmp_path, monkeypatch)
    mutated_request = dict(json.loads(request_raw))
    mutated_request["attempt_id"] = "protocol-other-1"
    with pytest.raises(RepresentationValidationError, match="worker_request_identity_mismatch"):
        _parse(files, _canonical(mutated_request), admission_raw, closure)

    with pytest.raises(RepresentationValidationError, match="worker_admission_identity_mismatch"):
        parse_verified_worker_response(
            request_raw=request_raw,
            report_raw=files["report.json"],
            terminal_raw=files["terminal.json"],
            declaration_raw=files["declaration.json"],
            source_manifest_raw=files["source-manifest.json"],
            sources_archive_raw=files["sources.zip"],
            expected_controller_admission_sha256="sha256:" + "9" * 64,
            expected_source_closure=closure,
        )

    report = json.loads(files["report.json"])
    report["record_count"] = report["record_count"] - 1
    with pytest.raises(RepresentationValidationError, match="worker_count_mismatch"):
        _parse(_relink(files, report=_canonical(report)), request_raw, admission_raw, closure)

    terminal = json.loads(files["terminal.json"])
    terminal["status"] = "failed"
    bad_terminal = dict(files)
    bad_terminal["terminal.json"] = _canonical(terminal)
    with pytest.raises(RepresentationValidationError, match="worker_receipt_not_complete"):
        _parse(bad_terminal, request_raw, admission_raw, closure)

    report = json.loads(files["report.json"])
    report["embeddings"][0]["vector"] = report["embeddings"][0]["vector"][:-1]
    with pytest.raises(RepresentationValidationError, match="invalid_worker_embedding_vector"):
        _parse(_relink(files, report=_canonical(report)), request_raw, admission_raw, closure)

    dirty = replace(inputs, _read_current=lambda: make_w5_verified_pin(generation=2, run_id=2))
    response = _parse(files, request_raw, admission_raw, closure)
    with pytest.raises(RepresentationValidationError, match="generation_publication_advanced"):
        seal_generation_result(dirty, response)


@pytest.mark.parametrize("archive_kind", ["compressed", "symlink", "duplicate"])
def test_archive_members_are_bounded_and_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_kind: str
):
    _inputs_value, request_raw, admission_raw, closure, files = _run_receipt(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        info = zipfile.ZipInfo("sources/fixture.py")
        if archive_kind == "symlink":
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        elif archive_kind == "duplicate":
            info.compress_type = zipfile.ZIP_STORED
        else:
            info.compress_type = zipfile.ZIP_DEFLATED
        zipped.writestr(info, b"fixture")
        if archive_kind == "duplicate":
            duplicate = zipfile.ZipInfo("sources/fixture.py")
            duplicate.compress_type = zipfile.ZIP_STORED
            with pytest.warns(UserWarning, match="Duplicate name"):
                zipped.writestr(duplicate, b"again")
        zipped.writestr("inputs/request.json", request_raw)
        zipped.writestr("inputs/admission.json", admission_raw)
    invalid = _relink(files, archive=archive.getvalue())
    with pytest.raises(RepresentationValidationError, match="invalid_worker_archive"):
        _parse(invalid, request_raw, admission_raw, closure)
