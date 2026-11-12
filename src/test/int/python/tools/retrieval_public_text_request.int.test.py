"""Real dual-arm requests from accepted SQLite and PostgreSQL publications.

The corpus and tasks are run-owned synthetic public fixtures bound to a
synthetic hash-pinned catalog; the learned mixed-v1 catalog is never read here.
No model, worker, vector or pgvector boundary is involved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    binding_id_for_alias, write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState, publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_public_text_readback import load_postgres_span_rows, load_sqlite_span_rows
from repomap_test_support.w5_semantic_store_support import (
    load_postgres_accepted_nodes_and_evidence, load_sqlite_accepted_nodes_and_evidence,
    make_postgres_readback_adapter, make_sqlite_readback_adapter,
)
from repomap_test_support.w5_semantic_support import make_w5_calibration_task
from retrieval_evaluation_schema import TASK_CATALOG_SCHEMA_VERSION
from retrieval_public_text_census import build_public_text_census, retained_task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_descriptors import prepare_public_text_generation
from retrieval_public_text_request import (
    ARM_PTX, ARM_V1, DualArmRequestRefusal, build_dual_arm_input, encode_dual_arm_request,
)
from retrieval_public_text_tasks import TASK_PINS_SCHEMA, load_selected_calibration_tasks, parse_task_pins
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_worker import parse_worker_request
from retrieval_semantic_provenance import verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

GRAPH = "public-text-request"
ALIASES = ("core", "companion", "feeds")
CANARY = "CANARY-PRIVATE-HOME-7731"
STUDY = "sha256:" + "5" * 64
PROFILE = "sha256:" + "a" * 64
SOURCES = {
    "core/pkg/request_core.py": "def request_core(value):\n    doubled = value * 2\n    return doubled\n",
    "companion/tools/request_helper.py": "def request_helper(item):\n    return [item]\n",
    "feeds/request_feed.py": "def request_feed(entry):\n    return entry\n",
}


@dataclass
class _State:
    published: PublishedCorpusState
    adapter: Callable[[], Any]
    loader: Callable[[], Any]
    spans: Callable[[], Any]
    backend: str


def _working_copy(root: Path) -> Path:
    for rel, text in SOURCES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root


def _selected(tmp_path: Path) -> Any:
    bindings = tuple(binding_id_for_alias(a, GRAPH) for a in ("core", "companion"))
    ranked = make_w5_calibration_task(task_id="cal-ranked", graph_id=GRAPH, selected_bindings=bindings)
    enumeration = replace(
        make_w5_calibration_task(task_id="cal-enumeration", graph_id=GRAPH, selected_bindings=bindings[:1],
                                 grading_rule="absent_answer", gold_targets=()),
        requested_mode="current_literal_enumeration").validate()
    second = replace(enumeration, task_id="cal-g2-enumeration", generation=2).validate()
    tasks = (ranked, enumeration, second)
    raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "synthetic-request",
                      "tasks": [task.to_dict() for task in tasks]}, indent=2).encode("ascii")
    path = tmp_path / "catalog.json"
    path.write_bytes(raw)
    pins = parse_task_pins(json.dumps({
        "catalog_file_sha256": hashlib.sha256(raw).hexdigest(), "held_out_decoded": False,
        "historical_semantic_catalog_identity": "sha256:" + "8" * 64, "original_manifest_sha256": "3" * 64,
        "schema": TASK_PINS_SCHEMA,
        "tasks": [{"generation": t.generation, "task_id": t.task_id, "task_sha256": retained_task_sha256(t)} for t in tasks],
    }).encode("utf-8"))
    return load_selected_calibration_tasks(path, pins)


def _parts(state: _State, tasks: Any, scope: PrivateMarkerScope, generation: int) -> dict[str, Any]:
    policy = state.published.policy
    pin = verify_publication_provenance_from_adapter(state.adapter, policy=policy)

    def report() -> Any:
        _publication, nodes, evidence = state.loader()
        return validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)

    prepared = prepare_public_text_generation(
        publication_pin=pin, readback_adapter=state.adapter, policy=policy, scope=scope, read_representations=report,
        read_v1_evidence=lambda: state.loader()[2], read_span_rows=state.spans)
    selected = tasks.for_generation(generation)
    census = build_public_text_census(
        selected, retained_task_digests=tasks.retained_digests(generation), policy=policy, publication_pin=pin,
        observed_backend=state.backend, frozen_policy_digest=pin.policy_digest, preparation=prepared)
    def current() -> Any:
        return verify_publication_provenance_from_adapter(state.adapter, policy=policy)

    v1 = prepare_public_generation_input(report(), selected, read_current=current, read_representations=report)
    return {"generation": generation, "attempt_id": f"w5-semantic-g{generation}", "study_identity": STUDY,
            "v1_input": v1, "preparation": prepared, "census": census, "tasks": tasks, "publication_pin": pin,
            "artifact_profile_identity": PROFILE}


def _check(value: Any, parts: dict[str, Any], backend: str, tmp_path: Path, *, queries: int) -> None:
    pin, prepared, v1 = parts["publication_pin"], parts["preparation"], parts["v1_input"]
    counts = value.manifest()["partitions"]
    assert counts == {"v1.document": len(v1.documents), "ptx.document": len(prepared.documents),
                      "v1.query": queries, "ptx.query": queries}, counts
    assert counts["v1.document"] > 0 and counts["ptx.document"] > 0
    request, records = parse_worker_request(encode_dual_arm_request(value))
    assert records == value.records and request["publication_identity"] == digest_json(pin.to_dict())
    assert value.publication_identity == prepared.publication_identity == parts["census"].publication_identity
    assert pin.backend == backend == prepared.backend == parts["census"].backend
    assert all(doc.descriptor["backend"] == backend for doc in prepared.documents)
    v1_texts = {r.record_id: r.text for r in v1.records}
    for record, layout in zip(value.records, value.layout, strict=True):
        if layout.arm == ARM_V1:
            assert record.text.encode("utf-8") == v1_texts[layout.v1_record_id].encode("utf-8")
        else:
            assert layout.arm == ARM_PTX
    public = json.dumps(value.manifest(), sort_keys=True) + repr(value)
    for private in (str(tmp_path), CANARY, "doubled = value", "Locate RetrievalPipeline"):
        assert private not in public


def _exercise(first: _State, second: Callable[[], _State], working_copy: Path, tmp_path: Path) -> None:
    tasks = _selected(tmp_path)
    scope = PrivateMarkerScope.create((str(tmp_path), CANARY))
    parts = _parts(first, tasks, scope, 1)
    value = build_dual_arm_input(**parts)
    _check(value, parts, first.backend, tmp_path, queries=1)
    assert [r.task_id for r in value.layout if r.task_id] == ["cal-ranked", "cal-ranked"]
    assert build_dual_arm_input(**_parts(first, tasks, scope, 1)).input_identity == value.input_identity
    (working_copy / "core/pkg/request_core.py").write_text(
        "def request_core(value):\n    tripled = value * 3\n    return tripled\n", encoding="utf-8")
    advanced = second()
    with pytest.raises(DualArmRequestRefusal) as stale:
        build_dual_arm_input(**parts)
    assert stale.value.code == "request_current_mismatch"
    parts2 = _parts(advanced, tasks, scope, 2)
    assert parts2["publication_pin"].generation == 2 and parts2["census"].status == "document_only"
    value2 = build_dual_arm_input(**parts2)
    _check(value2, parts2, advanced.backend, tmp_path, queries=0)
    assert all(r.mode.value == "document" for r in value2.layout) and value2.input_identity != value.input_identity


def test_sqlite_dual_arm_request_from_real_publications(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working_copy, graph_id=GRAPH, declared_aliases=ALIASES)

    def state() -> _State:
        published = publish_and_load_sqlite_corpus(home, graph_id=GRAPH, selected_aliases=ALIASES)
        return _State(published, make_sqlite_readback_adapter(published),
                      lambda: load_sqlite_accepted_nodes_and_evidence(published),
                      lambda: load_sqlite_span_rows(published), "sqlite")

    _exercise(state(), state, working_copy, tmp_path)


def test_postgresql_dual_arm_request_from_real_publications(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    with temporary_postgres() as pg_db:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working_copy, graph_id=GRAPH, host=pg_db.host, port=pg_db.port,
            database=pg_db.database, user=pg_db.user, password=pg_db.password, declared_aliases=ALIASES,
        )
        psql = pg_db.psql_command

        def state() -> _State:
            published = publish_and_load_postgres_corpus(
                home, graph_id=GRAPH, selected_aliases=ALIASES, psql_command=psql)
            return _State(published, make_postgres_readback_adapter(published, psql_command=psql),
                          lambda: load_postgres_accepted_nodes_and_evidence(published, psql_command=psql),
                          lambda: load_postgres_span_rows(published, psql_command=psql), "postgresql")

        _exercise(state(), state, working_copy, tmp_path)
