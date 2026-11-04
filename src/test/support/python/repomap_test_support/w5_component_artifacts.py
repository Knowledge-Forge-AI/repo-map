"""Coherent public artifact fixtures, synthesized without inference or stores."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from repomap_test_support.w5_semantic_support import (
    make_w5_sample_nodes_and_evidence, make_w5_verified_pin,
)
from retrieval_evaluation_attempts import admit_attempt
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_generator_inputs import build_worker_request, prepare_public_generation_input
from retrieval_semantic_generator_kernel import QUERY_PREFIX, SemanticMode
from retrieval_semantic_generator_worker_contracts import RESPONSE_SCHEMA, REQUEST_SCHEMA, CONTROLLER_ADMISSION_SCHEMA
from retrieval_semantic_pair_artifacts import MEMBER_NAMES, digest_bytes
from retrieval_semantic_pair_v2_report import build_pair_report_v2
from retrieval_semantic_representation import validate_canonical_node_representations


FIXTURE_SOURCE = b"raise RuntimeError('archived fixture source must never execute')\n"
PROFILE = "sha256:" + "4" * 64
IDENTITY_FIELDS = (
    "input_identity", "representation_report_identity", "publication_identity",
    "artifact_profile_identity",
)


def encoded(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def make_request(generation: int) -> dict[str, object]:
    pin = make_w5_verified_pin(generation=generation)
    nodes, evidence = make_w5_sample_nodes_and_evidence(generation=generation)
    representation = validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
    inputs = prepare_public_generation_input(
        representation, (), read_current=lambda: pin,
        read_representations=lambda: representation,
    )
    return build_worker_request(inputs, attempt_id=f"w5-semantic-g{generation}", artifact_profile_identity=PROFILE)


def make_model_receipt(root: Path, request: Mapping[str, object], *, admission_admitted: bool = True):
    """Use real journal framing and explicit synthetic vectors, never a runtime."""
    from retrieval_semantic_generator_worker_protocol import parse_worker_request

    request_raw = encoded(request)
    _value, records = parse_worker_request(request_raw)
    closure = {"fixture_worker.py": digest_bytes(FIXTURE_SOURCE)}
    identity = {name: request[name] for name in IDENTITY_FIELDS}
    admission = {
        "schema": CONTROLLER_ADMISSION_SCHEMA, "phase": "public-artifact-fixture",
        "operator_authority_sha256": "sha256:" + "a" * 64,
        "gate_references": {"synthetic": "sha256:" + "b" * 64},
        "bounded_component_execution_admitted": admission_admitted,
        "request_sha256": digest_bytes(request_raw), **identity,
        "candidate_closure_digests": closure,
        "scope": "inert synthetic fixture; no model execution authority",
    }
    admission_raw = encoded(admission)
    declaration = {
        "schema": REQUEST_SCHEMA, "attempt_id": request["attempt_id"],
        "request_sha256": digest_bytes(request_raw),
        "controller_admission_sha256": digest_bytes(admission_raw),
        "candidate_closure_digests": closure,
        "public_input_trust": "external evaluator current-store admission required",
        **identity,
    }
    journal = admit_attempt(root, declaration, {"fixture_worker.py": FIXTURE_SOURCE}, input_files={
        "request.json": request_raw, "admission.json": admission_raw,
    })
    count = len(records)
    report = {
        "schema": RESPONSE_SCHEMA, "request_sha256": digest_bytes(request_raw),
        "controller_admission_sha256": digest_bytes(admission_raw), **identity,
        "status": "complete", "partial": False, "record_count": count,
        "embedding_count": count,
        "document_count": sum(record.mode is SemanticMode.DOCUMENT for record in records),
        "query_count": sum(record.mode is SemanticMode.QUERY for record in records),
        "embeddings": [{
            "record_id": record.record_id, "mode": SemanticMode(record.mode).value,
            "vector": [1.0] + [0.0] * 383, "token_count_before_limit": 20,
            "token_count_used": 20, "overflow_chunks": 0, "truncated": False,
        } for record in records],
        "cost": {
            "input_records": count,
            "input_bytes": sum(len(record.record_id.encode()) + len(record.text.encode()) for record in records),
            "model_input_bytes": sum(len(((QUERY_PREFIX if record.mode is SemanticMode.QUERY else "") + record.text).encode()) for record in records),
            "token_count_before_limit": 20 * count, "token_count_used": 20 * count,
            "overflow_chunks": 0, "truncated_records": 0,
            "load_seconds": 0.1, "inference_seconds": 0.2, "total_seconds": 0.3,
        },
        "elapsed_seconds": 0.3,
        "claim": "fixed CPU component only; no learned quality, native ANN or production acceptance",
    }
    journal.finish("completed", report)
    members = {name: (journal.directory / name).read_bytes() for name in (
        "declaration.json", "report.json", "source-manifest.json", "sources.zip", "terminal.json",
    )}
    digests = {name: digest_bytes(raw) for name, raw in (
        ("admission", admission_raw), ("request", request_raw),
        ("declaration", members["declaration.json"]), ("report", members["report.json"]),
        ("source_manifest", members["source-manifest.json"]),
        ("sources_archive", members["sources.zip"]), ("terminal", members["terminal.json"]),
    )}
    return journal.directory, digests, closure, report, {"request.json":request_raw,"admission.json":admission_raw}


@dataclass(frozen=True)
class ComponentPair:
    journals: Mapping[int, Path]
    results: Mapping[int, Path]
    models: Mapping[int, Path]
    paired: Path


def make_component_pair(root: Path, *, recorded: bool = True, admission_admitted: bool = True) -> ComponentPair:
    journals, results, models = {}, {}, {}
    for generation in (1, 2):
        template, result_path = make_pair_artifacts(root / "templates", generation)
        request = make_request(generation)
        model, digests, closure, report, input_files = make_model_receipt(root / "models", request, admission_admitted=admission_admitted)
        plan = json.loads((template / "declaration.json").read_bytes())
        plan.update({name:request[name] for name in IDENTITY_FIELDS})
        plan.update(controller_admission_sha256=digests["admission"], source_closure=closure)
        declaration = {**plan, "component_source_closure":closure,
                       "candidate_closure_digests":{
                           "tools/fixture_worker.py":digest_bytes(FIXTURE_SOURCE),
                           "tools/public_fixture_extra.py":digest_bytes(b"# canonical source census is a superset\n"),
                       }}
        journal = admit_attempt(root / "journals", declaration, {
            "tools/fixture_worker.py":FIXTURE_SOURCE,
            "tools/public_fixture_extra.py":b"# canonical source census is a superset\n",
        }, input_files=input_files)
        for line in (template / "observations.jsonl").read_bytes().splitlines():
            journal.append(json.loads(line))
        legacy = {"generation":generation,"status":"failed","failure_code":"fixture_failed","component":digests}
        if recorded:
            legacy["component_counts"] = {name:report[name] for name in (
                "record_count","embedding_count","document_count","query_count",
            )}
        journal.finish("failed", legacy)
        result = json.loads(result_path.read_bytes())
        result["plan"] = plan
        result["raw_journal"] = {
            name:{"sha256":digest_bytes((journal.directory/name).read_bytes()),"length":(journal.directory/name).stat().st_size}
            for name in MEMBER_NAMES
        }
        result_path.write_bytes(encoded(result))
        journals[generation], results[generation], models[generation] = journal.directory, result_path, model
    paired = root / "paired-v2.json"
    paired.write_bytes(encoded(build_pair_report_v2(journals, results)))
    return ComponentPair(journals, results, models, paired)


__all__ = ["ComponentPair", "FIXTURE_SOURCE", "encoded", "make_component_pair", "make_model_receipt", "make_request"]
