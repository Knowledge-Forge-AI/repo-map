"""Census against a real current PostgreSQL publication, with SQLite as an independent control.

Tasks are run-owned synthetic calibration tasks bound to retained digests; the
learned mixed-v1 catalog, fixtures and golds are never read or changed.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

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
from retrieval_evaluation_admission_w5 import admit_w5_task
from retrieval_public_text_contracts import PUBLICATION_REVALIDATION_FAILED, PrivateMarkerScope, PublicTextRefusal
from retrieval_public_text_census import build_public_text_census, retained_task_sha256
from retrieval_public_text_descriptors import prepare_public_text_generation
from retrieval_semantic_generator_inputs import _query_decision
from retrieval_semantic_provenance import RepresentationValidationError, verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

GRAPH = "public-text-census"
ALIASES = ("core", "companion", "feeds")
CANARY = "CANARY-PRIVATE-HOME-7731"
SOURCES = {
    "core/pkg/census_core.py": "def census_core(value):\n    doubled = value * 2\n    return doubled\n",
    "companion/tools/census_helper.py": "def census_helper(item):\n    return [item]\n",
    "feeds/census_feed.py": "def census_feed(entry):\n    return entry\n",
}


def _working_copy(root: Path) -> Path:
    for rel, text in SOURCES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root


def _digest(task: Any) -> str:
    data = json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _tasks() -> tuple[Any, ...]:
    def task(task_id: str, aliases: tuple[str, ...], **changes: Any) -> Any:
        base = make_w5_calibration_task(
            task_id=task_id, graph_id=GRAPH, selected_bindings=tuple(binding_id_for_alias(a, GRAPH) for a in aliases),
            grading_rule=changes.pop("grading_rule", "ranked_positive"),
        )
        return replace(base, **changes).validate()

    return (
        task("cal-ranked", ("core", "companion")),
        task("cal-feeds", ("core", "feeds")),
        task("cal-mailbox", ("core", "mailbox"), grading_rule="safety_refusal"),
        task("cal-enumeration", ("core",), requested_mode="current_literal_enumeration", grading_rule="absent_answer",
             gold_targets=()),
    )


def _prepare_and_census(published: PublishedCorpusState, adapter: Any, loader: Any, spans: Any, backend: str,
                        tmp_path: Path, tasks: tuple[Any, ...] | None = None) -> tuple[Any, Any, Any]:
    policy = published.policy
    pin = verify_publication_provenance_from_adapter(adapter, policy=policy)

    def report() -> Any:
        _publication, nodes, evidence = loader()
        return validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)

    scope = PrivateMarkerScope.create((str(tmp_path), CANARY))
    prepared = prepare_public_text_generation(
        publication_pin=pin, readback_adapter=adapter, policy=policy, scope=scope, read_representations=report,
        read_v1_evidence=lambda: loader()[2], read_span_rows=spans,
    )
    tasks = _tasks() if tasks is None else tasks
    census = build_public_text_census(
        tasks, retained_task_digests={t.task_id: retained_task_sha256(t) for t in tasks}, policy=policy, publication_pin=pin,
        observed_backend=backend, frozen_policy_digest=pin.policy_digest, preparation=prepared,
    )
    return pin, prepared, census


def _assert_old_pin_refuses(pin: Any, published: PublishedCorpusState, adapter: Any, loader: Any, spans: Any,
                            backend: str, tmp_path: Path) -> None:
    """After generation 2 is accepted, the original generation-1 pin refuses both owners."""
    policy = published.policy
    with pytest.raises(PublicTextRefusal) as prepared:
        prepare_public_text_generation(
            publication_pin=pin, readback_adapter=adapter, policy=policy,
            scope=PrivateMarkerScope.create((str(tmp_path), CANARY)),
            read_representations=lambda: validate_canonical_node_representations(
                pin, accepted_nodes=loader()[1], accepted_evidence=loader()[2]),
            read_v1_evidence=lambda: loader()[2], read_span_rows=spans,
        )
    assert prepared.value.code == PUBLICATION_REVALIDATION_FAILED
    tasks = _tasks()
    with pytest.raises(PublicTextRefusal) as census:
        build_public_text_census(
            tasks, retained_task_digests={t.task_id: retained_task_sha256(t) for t in tasks}, policy=policy, publication_pin=pin,
            observed_backend=backend, frozen_policy_digest=pin.policy_digest,
        )
    assert census.value.code == PUBLICATION_REVALIDATION_FAILED


def _assert_census(pin: Any, prepared: Any, census: Any, policy: Any, backend: str, tmp_path: Path) -> dict[str, Any]:
    public = census.to_dict()
    rows = {row["task_id"]: row for row in public["tasks"]}
    assert {k: (v["public_text_state"], v["public_text_reason"]) for k, v in rows.items()} == {
        "cal-ranked": ("admitted", None),
        "cal-feeds": ("refused", "retention_not_authorized"),
        "cal-mailbox": ("refused", "binding_privacy_not_authorized"),
        "cal-enumeration": ("unavailable", "unsupported_semantic_query_mode"),
    }, public["tasks"]
    assert rows["cal-feeds"]["v1_evaluator_state"] == "admitted" and rows["cal-feeds"]["v1_learned_state"] == "admitted"
    for task, record in zip(_tasks(), census.tasks, strict=True):
        direct = admit_w5_task(task, policy=policy, publication_pin=pin, observed_backend=backend,
                               frozen_policy_digest=pin.policy_digest)
        assert json.dumps(dict(record.v1_evaluator), sort_keys=True) == json.dumps(direct.to_dict(), sort_keys=True)
        learned = _query_decision(task, pin)
        assert (record.v1_learned_state, record.v1_learned_reason, record.task_sha256) == (
            learned.state, learned.reason, learned.task_sha256)
    assert public["status"] == "ready" and public["document_count"] == len(prepared.documents) > 0, public
    assert public["privacy_scope_id"] == prepared.privacy_scope_id
    text = json.dumps(public, sort_keys=True)
    for value in (str(tmp_path), CANARY, "doubled = value", _tasks()[0].question, "primary class definition"):
        assert value not in text
    return public


def test_postgresql_census_is_digest_bound_and_reports_document_only_generations(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    with temporary_postgres() as pg_db:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working_copy, graph_id=GRAPH, host=pg_db.host, port=pg_db.port,
            database=pg_db.database, user=pg_db.user, password=pg_db.password, declared_aliases=ALIASES,
        )
        published = publish_and_load_postgres_corpus(
            home, graph_id=GRAPH, selected_aliases=ALIASES, psql_command=pg_db.psql_command,
        )
        adapter = make_postgres_readback_adapter(published, psql_command=pg_db.psql_command)
        pin, prepared, census = _prepare_and_census(
            published, adapter, lambda: load_postgres_accepted_nodes_and_evidence(published, psql_command=pg_db.psql_command),
            lambda: load_postgres_span_rows(published, psql_command=pg_db.psql_command), "postgresql", tmp_path,
        )
        public = _assert_census(pin, prepared, census, published.policy, "postgresql", tmp_path)
        assert public["backend"] == "postgresql"
        (working_copy / "core/pkg/census_core.py").write_text(
            "def census_core(value):\n    tripled = value * 3\n    return tripled\n", encoding="utf-8",
        )
        second = publish_and_load_postgres_corpus(
            home, graph_id=GRAPH, selected_aliases=ALIASES, psql_command=pg_db.psql_command,
        )
        task2 = replace(_tasks()[-1], task_id="cal-g2-enumeration", generation=2).validate()
        pin2, prepared2, census2 = _prepare_and_census(
            second, make_postgres_readback_adapter(second, psql_command=pg_db.psql_command),
            lambda: load_postgres_accepted_nodes_and_evidence(second, psql_command=pg_db.psql_command),
            lambda: load_postgres_span_rows(second, psql_command=pg_db.psql_command),
            "postgresql", tmp_path, (task2,),
        )
        only = census2.to_dict()
        assert pin.generation == 1 and pin2.generation == 2 and pin2.run_id > pin.run_id
        assert pin2.snapshot_manifest_id != pin.snapshot_manifest_id
        with pytest.raises(RepresentationValidationError) as stale:
            pin.revalidate_current()
        assert stale.value.code == "stale_publication_receipt"
        _assert_old_pin_refuses(
            pin, published, adapter,
            lambda: load_postgres_accepted_nodes_and_evidence(second, psql_command=pg_db.psql_command),
            lambda: load_postgres_span_rows(second, psql_command=pg_db.psql_command), "postgresql", tmp_path,
        )
        assert only["status"] == "document_only" and only["ranked_public_text_queries"] == 0
        assert only["generation"] == 2 and only["document_count"] == len(prepared2.documents) > 0
        assert only["tasks"][0]["requested_mode"] == "current_literal_enumeration"
        assert only["tasks"][0]["v1_evaluator_state"] == "admitted"
        assert only["tasks"][0]["public_text_reason"] == "unsupported_semantic_query_mode"


def test_sqlite_census_control_matches_the_same_closed_states(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working_copy, graph_id=GRAPH, declared_aliases=ALIASES)
    published = publish_and_load_sqlite_corpus(home, graph_id=GRAPH, selected_aliases=ALIASES)
    pin, prepared, census = _prepare_and_census(
        published, make_sqlite_readback_adapter(published), lambda: load_sqlite_accepted_nodes_and_evidence(published),
        lambda: load_sqlite_span_rows(published), "sqlite", tmp_path,
    )
    public = _assert_census(pin, prepared, census, published.policy, "sqlite", tmp_path)
    assert public["backend"] == "sqlite"
    (working_copy / "core/pkg/census_core.py").write_text(
        "def census_core(value):\n    return value * 3\n", encoding="utf-8",
    )
    second = publish_and_load_sqlite_corpus(home, graph_id=GRAPH, selected_aliases=ALIASES)
    task2 = replace(_tasks()[-1], task_id="cal-g2-enumeration", generation=2).validate()
    pin2, prepared2, census2 = _prepare_and_census(
        second, make_sqlite_readback_adapter(second), lambda: load_sqlite_accepted_nodes_and_evidence(second),
        lambda: load_sqlite_span_rows(second), "sqlite", tmp_path, (task2,),
    )
    assert pin.generation == 1 and pin2.generation == 2 and pin2.run_id > pin.run_id
    assert pin2.snapshot_manifest_id != pin.snapshot_manifest_id
    assert census2.to_dict()["status"] == "document_only" and census2.to_dict()["ranked_public_text_queries"] == 0
    assert prepared2.documents
    with pytest.raises(RepresentationValidationError) as stale:
        pin.revalidate_current()
    assert stale.value.code == "stale_publication_receipt"
    _assert_old_pin_refuses(
        pin, published, make_sqlite_readback_adapter(published), lambda: load_sqlite_accepted_nodes_and_evidence(second),
        lambda: load_sqlite_span_rows(second), "sqlite", tmp_path,
    )
