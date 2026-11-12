"""Synthetic raw delivery through the unchanged ComponentExchange admission/response boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.w5_public_text_artifacts import SyntheticStudy
from repomap_test_support.w5_public_text_functional import FunctionalDeliveryRefusal, SyntheticDelivery
import retrieval_semantic_bridge_transport as transport
import retrieval_semantic_bridge_transport_io as transport_io
import retrieval_semantic_experiment_bridge as bridge
from retrieval_public_text_request import encode_dual_arm_request
from retrieval_public_text_sources import worker_closure
from retrieval_semantic_experiment_bridge import ComponentExchange
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_generator_output_parser import parse_verified_worker_response

REPO = Path(__file__).resolve().parents[5]


@pytest.fixture()
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "sandbox-scratch").resolve()
    root.mkdir()
    for module in (bridge, transport, transport_io):
        monkeypatch.setattr(module, "SANDBOX_SCRATCH_ROOT", str(root))
    return root


def _publish(tmp_path: Path, generation: int = 1) -> tuple[ComponentExchange, bytes]:
    request_raw = encode_dual_arm_request(SyntheticStudy(tmp_path / f"study-{generation}", generation=generation).build())
    exchange = ComponentExchange.publish_request(attempt_id=f"w5-semantic-g{generation}",
                                                 request=json.loads(request_raw),
                                                 expected_source_closure=worker_closure(REPO).digests)
    return exchange, request_raw


def test_admission_then_response_cross_the_real_exchange_and_unchanged_parser(scratch: Path, tmp_path: Path) -> None:
    worker = worker_closure(REPO)
    delivery = SyntheticDelivery(tmp_path / "model", worker)
    exchange, request_raw = _publish(tmp_path)
    assert exchange.request_raw == request_raw and exchange.directory.parent.parent == scratch
    admission_sha = delivery.admit(exchange)
    bound = exchange.await_controller_admission(timeout_seconds=2)
    assert bound.admission_sha256 == admission_sha and (bound.directory / "admission.json").read_bytes() == bound.admission_raw
    assert bound.admission_ack_line.startswith("CLOE_W5_COMPONENT_ADMISSION_ACK ")
    delivery.respond(bound)
    files = bound.await_response(timeout_seconds=2)
    assert files["request.json"] == request_raw and files["admission.json"] == bound.admission_raw
    response = parse_verified_worker_response(
        request_raw=request_raw, report_raw=files["report.json"], terminal_raw=files["terminal.json"],
        declaration_raw=files["declaration.json"], source_manifest_raw=files["source-manifest.json"],
        sources_archive_raw=files["sources.zip"], expected_controller_admission_sha256=bound.admission_sha256,
        expected_source_closure=dict(worker.digests))
    assert response.attempt_id == "w5-semantic-g1" and response.record_count > 0
    with pytest.raises(FunctionalDeliveryRefusal, match="repeated"):
        delivery.respond(bound)


def test_response_is_refused_before_a_bound_admission_and_admission_is_single_use(scratch: Path,
                                                                                  tmp_path: Path) -> None:
    delivery = SyntheticDelivery(tmp_path / "model", worker_closure(REPO))
    exchange, _raw = _publish(tmp_path)
    with pytest.raises(FunctionalDeliveryRefusal, match="before_bound_admission"):
        delivery.respond(exchange)
    delivery.admit(exchange)
    with pytest.raises(FunctionalDeliveryRefusal):
        delivery.admit(exchange)
    with pytest.raises(FunctionalDeliveryRefusal, match="before_bound_admission"):
        delivery.respond(exchange)


def test_tampered_marker_or_missing_response_never_becomes_success(scratch: Path, tmp_path: Path) -> None:
    delivery = SyntheticDelivery(tmp_path / "model", worker_closure(REPO))
    exchange, _raw = _publish(tmp_path)
    delivery.admit(exchange)
    marker = exchange.directory / "controller.admission.ready.json"
    value = json.loads(marker.read_bytes())
    value["request_sha256"] = "sha256:" + "0" * 64
    marker.chmod(0o600)
    marker.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(ExperimentRefusal, match="controller_admission"):
        exchange.await_controller_admission(timeout_seconds=1)
    second, _raw2 = _publish(tmp_path, generation=2)
    delivery.admit(second)
    bound = second.await_controller_admission(timeout_seconds=2)
    with pytest.raises(ExperimentRefusal, match="component_response_timeout"):
        bound.await_response(timeout_seconds=0.2)


def test_a_foreign_worker_closure_is_refused_before_any_file_is_written(scratch: Path, tmp_path: Path) -> None:
    worker = worker_closure(REPO)
    foreign = type(worker)("worker", worker.files, {**worker.digests, "retrieval_semantic_generator_pins.json":
                                                    "sha256:" + "0" * 64}, worker.identity)
    exchange, _raw = _publish(tmp_path)
    with pytest.raises(FunctionalDeliveryRefusal, match="worker_closure_mismatch"):
        SyntheticDelivery(tmp_path / "model", foreign).admit(exchange)
    assert not (exchange.directory / "controller.admission.json").exists()
    with pytest.raises(FunctionalDeliveryRefusal, match="configuration"):
        SyntheticDelivery(Path("relative"), worker)
