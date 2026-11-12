"""Synthetic public-text study inputs and raw seven-member protocol artifacts (study section 18.6).

Test support only: no model, database or network operation, and nothing here
claims model origin. The study input comes from the public fixture projection
through the maintained preparation, census, v1 and dual-arm builders. The raw
members (request, controller admission, declaration, report, source manifest,
sources archive, terminal) are written for the exact request bytes through the
real attempt-journal framing, with explicit synthetic vectors and tokens; only
the unchanged parser turns them into a ``VerifiedWorkerResponse``. No accepted
response or production artifact is fabricated.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any

from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_component_artifacts import FIXTURE_SOURCE, encoded
from repomap_test_support.w5_semantic_support import (
    InMemoryStoreReadbackCell, make_w5_accepted_pub_mapping, make_w5_calibration_task,
)
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_schema import TASK_CATALOG_SCHEMA_VERSION
from retrieval_public_text_census import build_public_text_census, retained_task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope, SpanRow
from retrieval_public_text_descriptors import prepare_public_text_generation
from retrieval_public_text_request import STUDY_PHASE, DualArmInput, build_dual_arm_input
from retrieval_public_text_tasks import TASK_PINS_SCHEMA, SelectedTaskSet, load_selected_calibration_tasks, parse_task_pins
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_kernel import QUERY_PREFIX, SemanticMode
from retrieval_semantic_generator_output_parser import parse_verified_worker_response
from retrieval_semantic_generator_output_receipt import VerifiedWorkerResponse
from retrieval_semantic_generator_worker_contracts import CONTROLLER_ADMISSION_SCHEMA, REQUEST_SCHEMA, RESPONSE_SCHEMA
from retrieval_semantic_generator_worker_protocol import parse_worker_request
from retrieval_semantic_pair_artifacts import JOURNAL_SCHEMA, JournalArtifact, digest_bytes, load_journal
from retrieval_semantic_primitives import AcceptedEvidenceRecord, AcceptedNodeRecord
from retrieval_semantic_provenance import AcceptedStoreReadback, verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

KEY = "python.function:pkg.alpha:boundary_fn"
TASK_IDS = {1: "cal-01", 2: "cal-23"}
STUDY_IDENTITY = "sha256:" + "5" * 64
ARTIFACT_PROFILE = "sha256:" + "a" * 64
MODEL_MEMBERS = ("declaration.json", "report.json", "source-manifest.json", "sources.zip", "terminal.json")
IDENTITY_FIELDS = ("input_identity", "representation_report_identity", "publication_identity",
                   "artifact_profile_identity")
# The unchanged parser requires this exact worker claim; it is not a model-origin claim.
_CLAIM = "fixed CPU component only; no learned quality, native ANN or production acceptance"


class SyntheticStudy:
    """One synthetic generation over the public fixture; ``build`` reruns every maintained owner."""

    def __init__(self, root: Path, *, generation: int = 1, markers: Sequence[str] = ("CANARY-PRIVATE-HOME-7731",),
                 registered_tasks: SelectedTaskSet | None = None):
        if type(generation) is not int or generation not in (1, 2):
            raise ValueError("synthetic generation must be 1 or 2")
        if registered_tasks is None:
            inputs, self.policy = build_fixture_projection(spool_dir=root / "spool")
        else:
            if type(registered_tasks) is not SelectedTaskSet:
                raise TypeError("selected task set required")
            from repomap_test_support.w5_public_text_registered_fixture import build_registered_fixture_projection
            inputs, self.policy = build_registered_fixture_projection(spool_dir=root / "spool")
        reference = replace(inputs.accepted_reference, run_id=generation, accepted_generation=generation)
        inputs = replace(inputs, accepted_reference=reference)
        publication = make_w5_accepted_pub_mapping(inputs.receipt, run_id=generation, generation=generation)
        self.cell = InMemoryStoreReadbackCell(
            AcceptedStoreReadback("mixed-v1", "repo1:mixed-v1", "sqlite", publication, inputs.receipt, inputs))
        self.pin = verify_publication_provenance_from_adapter(self.cell, policy=self.policy)
        self.generation = generation
        core = next(item.binding_id for item in self.policy.bindings.values() if item.alias == "core")
        meta = {"binding_id": core, "snapshot_id": self.pin.snapshot_by_binding()[core][1],
                "source_relative_path": "pkg/alpha.py"}
        self.core = core
        run = generation  # the synthetic publication's run id; graph key version stays 1
        self.node = AcceptedNodeRecord(KEY, "Function", "boundary_fn", 1, run)
        self.evidence = AcceptedEvidenceRecord(KEY, "ev1:alpha80", run, 1, "core/pkg/alpha.py", meta, "defined_by")
        self.rows = (SpanRow(KEY, "ev1:alpha80", run, 1, "core/pkg/alpha.py", meta, "defined_by", 80, 81),)
        self.scope = PrivateMarkerScope.create(tuple(markers))
        if registered_tasks is not None:
            self.tasks = registered_tasks
            return
        rule = "ranked_positive" if generation == 1 else "direct_handoff"
        task = make_w5_calibration_task(task_id=TASK_IDS[generation], graph_id="mixed-v1", generation=generation,
                                        selected_bindings=(core,), grading_rule=rule)
        raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "synthetic",
                          "tasks": [task.to_dict()]}).encode("ascii")
        catalog = root / f"catalog-g{generation}.json"
        catalog.write_bytes(raw)
        pins = parse_task_pins(json.dumps({
            "catalog_file_sha256": hashlib.sha256(raw).hexdigest(), "held_out_decoded": False,
            "historical_semantic_catalog_identity": "sha256:" + "8" * 64, "original_manifest_sha256": "3" * 64,
            "schema": TASK_PINS_SCHEMA,
            "tasks": [{"generation": generation, "task_id": task.task_id, "task_sha256": retained_task_sha256(task)}],
        }).encode("utf-8"))
        self.tasks = load_selected_calibration_tasks(catalog, pins)

    def representations(self) -> Any:
        return validate_canonical_node_representations(
            self.pin, accepted_nodes=(self.node,), accepted_evidence=(self.evidence,))

    def build(self) -> DualArmInput:
        prepared = prepare_public_text_generation(
            publication_pin=self.pin, readback_adapter=self.cell, policy=self.policy, scope=self.scope,
            read_representations=self.representations, read_v1_evidence=lambda: (self.evidence,),
            read_span_rows=lambda: self.rows)
        tasks = self.tasks.for_generation(self.generation)
        census = build_public_text_census(
            tasks, retained_task_digests=self.tasks.retained_digests(self.generation), policy=self.policy,
            publication_pin=self.pin, observed_backend="sqlite", frozen_policy_digest=self.pin.policy_digest,
            preparation=prepared)
        v1 = prepare_public_generation_input(self.representations(), tasks, read_current=lambda: self.pin,
                                             read_representations=self.representations)
        return build_dual_arm_input(
            generation=self.generation, attempt_id=f"w5-semantic-g{self.generation}", study_identity=STUDY_IDENTITY,
            v1_input=v1, preparation=prepared, census=census, tasks=self.tasks, publication_pin=self.pin,
            artifact_profile_identity=ARTIFACT_PROFILE)


def _unit(index: int) -> list[float]:
    vector = [0.0] * 384
    vector[index % 384] = 1.0
    return vector


@dataclass(frozen=True)
class SyntheticRawComponent:
    """The seven raw protocol members of one synthetic worker run; bytes only, never a parsed claim."""

    request_raw: bytes = field(repr=False)
    admission_raw: bytes = field(repr=False)
    members: Mapping[str, bytes] = field(repr=False)
    closure: Mapping[str, str]
    digests: Mapping[str, str]
    counts: Mapping[str, int]

    def parse(self) -> VerifiedWorkerResponse:
        """Only the unchanged parser creates the response."""
        return parse_verified_worker_response(
            request_raw=self.request_raw, report_raw=self.members["report.json"],
            terminal_raw=self.members["terminal.json"], declaration_raw=self.members["declaration.json"],
            source_manifest_raw=self.members["source-manifest.json"], sources_archive_raw=self.members["sources.zip"],
            expected_controller_admission_sha256=self.digests["admission"], expected_source_closure=dict(self.closure))


def synthetic_admission(request_raw: bytes, closure: Mapping[str, str]) -> bytes:
    """A synthetic-functional controller admission for exactly this request and worker closure."""
    request = json.loads(request_raw)
    return encoded({
        "schema": CONTROLLER_ADMISSION_SCHEMA, "phase": STUDY_PHASE + "-synthetic-functional",
        "operator_authority_sha256": "sha256:" + "a" * 64, "gate_references": {"synthetic": "sha256:" + "b" * 64},
        "bounded_component_execution_admitted": True, "request_sha256": digest_bytes(request_raw),
        **{name: request[name] for name in IDENTITY_FIELDS},
        "candidate_closure_digests": dict(closure), "scope": "inert synthetic fixture; no model execution authority",
    })


def synthetic_raw_component(root: Path, request_raw: bytes, *, truncated: frozenset[int] = frozenset(),
                            mutate: Callable[[dict[str, Any]], None] | None = None,
                            source_files: Mapping[str, bytes] | None = None,
                            admission_raw: bytes | None = None) -> SyntheticRawComponent:
    """Write the raw members for exactly ``request_raw``; ``truncated`` record indexes exceed 512 tokens.

    The functional driver passes the actual flat worker ``source_files`` and the
    actual admission bytes; unit callers keep the one toy worker source.
    """
    _parsed, records = parse_worker_request(request_raw)
    request = json.loads(request_raw)
    identity = {name: request[name] for name in IDENTITY_FIELDS}
    sources = {"fixture_worker.py": FIXTURE_SOURCE} if source_files is None else dict(source_files)
    closure = {name: digest_bytes(raw) for name, raw in sorted(sources.items())}
    if admission_raw is None:
        admission_raw = synthetic_admission(request_raw, closure)
    common = {"request_sha256": digest_bytes(request_raw), "controller_admission_sha256": digest_bytes(admission_raw),
              **identity}
    journal = admit_attempt(root, {
        "schema": REQUEST_SCHEMA, "attempt_id": request["attempt_id"], "candidate_closure_digests": closure,
        "public_input_trust": "external evaluator current-store admission required", **common,
    }, sources, input_files={"request.json": request_raw, "admission.json": admission_raw})
    rows = []
    for index, record in enumerate(records):
        before = 600 if index in truncated else 20 + index
        rows.append({"record_id": record.record_id, "mode": SemanticMode(record.mode).value, "vector": _unit(index),
                     "token_count_before_limit": before, "token_count_used": min(before, 512),
                     "overflow_chunks": 1 if before > 512 else 0, "truncated": before > 512})
    partial = any(row["truncated"] for row in rows)
    report: dict[str, Any] = {
        "schema": RESPONSE_SCHEMA, **common, "status": "partial" if partial else "complete", "partial": partial,
        "record_count": len(rows), "embedding_count": len(rows),
        "document_count": sum(row["mode"] == "document" for row in rows),
        "query_count": sum(row["mode"] == "query" for row in rows), "embeddings": rows,
        "cost": {
            "input_records": len(records),
            "input_bytes": sum(len(r.record_id.encode()) + len(r.text.encode()) for r in records),
            "model_input_bytes": sum(len(((QUERY_PREFIX if SemanticMode(r.mode) is SemanticMode.QUERY else "")
                                          + r.text).encode()) for r in records),
            "token_count_before_limit": sum(row["token_count_before_limit"] for row in rows),
            "token_count_used": sum(row["token_count_used"] for row in rows),
            "overflow_chunks": sum(row["overflow_chunks"] for row in rows),
            "truncated_records": sum(1 for row in rows if row["truncated"]),
            "load_seconds": 0.5, "inference_seconds": 1.25, "total_seconds": 2.0,
        },
        "elapsed_seconds": 3.0, "claim": _CLAIM,
    }
    if mutate is not None:
        mutate(report)
    journal.finish("completed", report)
    members = {name: (journal.directory / name).read_bytes() for name in MODEL_MEMBERS}
    digests = {"admission": digest_bytes(admission_raw), "request": digest_bytes(request_raw),
               "declaration": digest_bytes(members["declaration.json"]), "report": digest_bytes(members["report.json"]),
               "source_manifest": digest_bytes(members["source-manifest.json"]),
               "sources_archive": digest_bytes(members["sources.zip"]),
               "terminal": digest_bytes(members["terminal.json"])}
    counts = {name: report[name] for name in ("record_count", "embedding_count", "document_count", "query_count")}
    return SyntheticRawComponent(request_raw, admission_raw, members, closure, digests, counts)


def component_journal(root: Path, component: SyntheticRawComponent, *, generation: int, arms: Sequence[str],
                      task_ids: Sequence[str]) -> JournalArtifact:
    """A real canonical component journal (unchanged ``admit_attempt``/``load_journal``) for those members."""
    request = json.loads(component.request_raw)
    journal = admit_attempt(root, {
        "schema": JOURNAL_SCHEMA, "attempt_id": request["attempt_id"], "generation": generation, "arms": list(arms),
        "task_ids": list(task_ids), "repetitions": 3, "input_identity": request["input_identity"],
        "controller_admission_sha256": component.digests["admission"], "source_closure": dict(component.closure),
        "component_source_closure": dict(component.closure),
        "candidate_closure_digests": {"tools/fixture_worker.py": digest_bytes(FIXTURE_SOURCE)},
    }, {"tools/fixture_worker.py": FIXTURE_SOURCE},
        input_files={"request.json": component.request_raw, "admission.json": component.admission_raw})
    journal.append({"event": "public_text_synthetic_component"})
    journal.finish("completed", {"component": dict(component.digests), "component_counts": dict(component.counts)})
    return load_journal(journal.directory)


__all__ = [
    "ARTIFACT_PROFILE", "KEY", "MODEL_MEMBERS", "STUDY_IDENTITY", "SyntheticRawComponent", "SyntheticStudy",
    "TASK_IDS", "component_journal", "synthetic_admission", "synthetic_raw_component",
]
