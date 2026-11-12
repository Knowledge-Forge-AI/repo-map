"""Real SQLite and PostgreSQL public-text capture, span closure, integrity and publication drift.

The corpus is a run-owned synthetic working copy; learned mixed-v1 inputs are
never read or changed. No model, vector or runtime boundary is mocked.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, sqlite_graph_database_path
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.portable_refresh import execute_portable_refresh
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState, publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_public_text_readback import load_postgres_span_rows, load_sqlite_span_rows
from repomap_test_support.w5_semantic_store_support import (
    load_postgres_accepted_nodes_and_evidence, load_sqlite_accepted_nodes_and_evidence,
    make_postgres_readback_adapter, make_sqlite_readback_adapter,
)
from retrieval_public_text_contracts import (
    DESCRIPTOR_SET_CHANGED, EXCERPT_CREDENTIAL_SHAPE_EXCLUDED, EXCERPT_PRIVACY_REFUSED, PUBLICATION_REVALIDATION_FAILED,
    SPAN_LINK_MISMATCH, PrivateMarkerScope, PublicTextRefusal,
)
from retrieval_public_text_descriptors import prepare_public_text_generation, require_unchanged_recomputation
from retrieval_semantic_provenance import verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

GRAPH = "public-text-synth"
ALIASES = ("core", "companion", "feeds")
CANARY = "CANARY-PRIVATE-HOME-7731"
SOURCES = {
    "core/pkg/alpha.py": (
        '"""Synthetic public-text core module."""\n\n\n'
        "def alpha_entry(value):\n    total = value + 1\n    return total\n\n\n"
        "class AlphaWidget:\n    def describe(self):\n        return 'alpha widget'\n"
    ),
        "companion/tools/helper.py": (
        '"""Synthetic companion helper."""\n\n\n'
        "def helper_sum(left, right):\n    result = left + right\n    return result\n"
    ),
    "feeds/feed_item.py": "def feed_title(item):\n    return item\n",
    "core/pkg/credentials.py": (
        "def assignment_boundary():\n    " + " = ".join(("password", repr("PUBLIC_TEST_VALUE"))) + "\n    return password\n\n\n"
        "def url_boundary():\n    return 'https://user:" + "PUBLIC_TEST_VALUE" + "@host.invalid/path'\n\n\n"
        "def scheme_boundary():\n    return 'postgres://user:" + "PUBLIC_TEST_VALUE" + "@db.invalid/app'\n\n\n"
        "def compound_boundary():\n    aws_secret_access_key = 'PUBLIC_TEST_VALUE'\n    return aws_secret_access_key\n\n\n"
        "def pem_boundary():\n    return '-----BEGIN PRIVATE KEY-----'\n"
    ),
}
CREDENTIAL_FUNCTIONS = ("assignment_boundary", "url_boundary", "scheme_boundary", "compound_boundary", "pem_boundary")


def _working_copy(root: Path) -> Path:
    for rel, text in SOURCES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root


class _Backend:
    def __init__(self, published: PublishedCorpusState, *, adapter: Callable[[], Any], nodes: Callable[[], Any],
                 spans: Callable[[], Any], execute_sql: Callable[[str], None], refresh: Callable[[], object]) -> None:
        self.published, self.adapter, self.nodes, self.spans = published, adapter, nodes, spans
        self.execute_sql, self.refresh = execute_sql, refresh
        self.policy = published.policy
        self.pin = verify_publication_provenance_from_adapter(adapter, policy=self.policy)

    def _report(self) -> Any:
        _publication, nodes, evidence = self.nodes()
        return validate_canonical_node_representations(self.pin, accepted_nodes=nodes, accepted_evidence=evidence)

    def prepare(self, scope: PrivateMarkerScope):
        return prepare_public_text_generation(
            publication_pin=self.pin, readback_adapter=self.adapter, policy=self.policy, scope=scope,
            read_representations=self._report, read_v1_evidence=lambda: self.nodes()[2], read_span_rows=self.spans,
        )


def _expected_model_text(descriptor: dict[str, Any], excerpt: bytes) -> bytes:
    text = json.dumps({
        "v": "canonical-node-public-text-v2", "canonical_key": descriptor["canonical_key"], "kind": descriptor["kind"],
        "display_name": descriptor["display_name"], "source_relative_path": descriptor["source_relative_path"],
        "excerpt": excerpt.decode("utf-8"),
    }, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


def _exercise(backend: _Backend, working_copy: Path, tmp_path: Path) -> None:
    scope = PrivateMarkerScope.create((str(tmp_path), CANARY))
    first = backend.prepare(scope)
    public = first.to_dict()
    diagnostic = {k: public[k] for k in ("document_count", "v1_verified_pair_count", "exclusion_counts")}
    assert first.documents, diagnostic
    assert any(r.startswith("public_text_body_policy_denied:") for r in public["exclusion_counts"]), diagnostic
    assert EXCERPT_CREDENTIAL_SHAPE_EXCLUDED in public["exclusion_counts"], diagnostic
    assert EXCERPT_PRIVACY_REFUSED not in public["exclusion_counts"], diagnostic
    assert any("assignment_boundary" in row.canonical_key for row in backend._report().verified_entries)
    for name in CREDENTIAL_FUNCTIONS:
        assert any(name in row.canonical_key and row.reason == EXCERPT_CREDENTIAL_SHAPE_EXCLUDED
                   for row in first.exclusions), (name, diagnostic)
        assert all(name not in doc.descriptor["canonical_key"] for doc in first.documents)
    assert all("PUBLIC_TEST_VALUE" not in doc.model_text and "PRIVATE KEY" not in doc.model_text
               for doc in first.documents)
    text = json.dumps(public, sort_keys=True)
    assert str(tmp_path) not in text and CANARY not in text and "alpha widget" not in text
    alias_by_binding = {binding_id: item.alias for binding_id, item in backend.policy.bindings.items()}
    pin = backend.pin
    digests: set[str] = set()
    for document in first.documents:
        descriptor = document.descriptor.to_dict()
        alias = alias_by_binding[descriptor["source_binding_id"]]
        assert alias in {"core", "companion"}
        raw = (working_copy / alias / descriptor["source_relative_path"]).read_bytes()
        assert descriptor["artifact_content_digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
        lines = raw.split(b"\n")
        prefix = b"".join(line + b"\n" for line in lines[: descriptor["start_line"] - 1])
        excerpt = b"".join(line + b"\n" for line in lines[descriptor["start_line"] - 1: descriptor["end_line"]])
        assert (descriptor["span_start_byte"], descriptor["excerpt_bytes"]) == (len(prefix), len(excerpt))
        assert descriptor["excerpt_digest"] == "sha256:" + hashlib.sha256(excerpt).hexdigest()
        expected = _expected_model_text(descriptor, excerpt)
        assert document.model_text.encode("utf-8") == expected
        assert descriptor["input_digest"] == "sha256:" + hashlib.sha256(expected).hexdigest()
        reference = descriptor["accepted_reference"]
        assert reference == dict(first.accepted_reference) and len(reference) == 11
        assert (reference["snapshot_manifest_id"], reference["extraction_receipt_id"], reference["run_id"],
                reference["accepted_generation"], reference["backend"]) == (
            pin.snapshot_manifest_id, pin.extraction_receipt_id, pin.run_id, pin.generation, pin.backend)
        digests.add(descriptor["artifact_content_digest"])
    measured = first.measurements
    ledger = measured["excerpt_ledger"]
    refused_raw = (working_copy / "core/pkg/credentials.py").read_bytes()
    refused_digest = "sha256:" + hashlib.sha256(refused_raw).hexdigest()
    assert refused_digest not in digests
    verified_digests = digests | {refused_digest}
    assert ledger["verified_objects"] == len(verified_digests) == measured["excerpt_reads"]["read"]["attempts"]
    assert measured["excerpt_reads"]["read"]["source_payload_bytes"] == ledger["verified_object_bytes"]
    assert measured["projection"]["read"]["source_payload_bytes"] == measured["projection_aggregate_input_bytes_read"]
    assert measured["projection"]["read"]["metadata_payload_bytes"] > 0

    second = backend.prepare(scope)
    require_unchanged_recomputation(first, second, scope=scope)

    target = next(d.descriptor for d in first.documents if d.descriptor["end_line"] > d.descriptor["start_line"])
    key = target["evidence_key"].replace("'", "''")
    backend.execute_sql(
        f"UPDATE canonical_evidence SET end_line = start_line WHERE evidence_key = '{key}' AND run_id = {backend.pin.run_id}"
    )
    drifted = backend.prepare(scope)
    assert any(item.reason == SPAN_LINK_MISMATCH and item.canonical_key == target["canonical_key"]
               for item in drifted.exclusions), drifted.to_dict()["exclusion_counts"]
    with pytest.raises(PublicTextRefusal) as changed:
        require_unchanged_recomputation(first, drifted, scope=scope)
    assert changed.value.code == DESCRIPTOR_SET_CHANGED

    entry = next(e for e in backend.published.manifest.entries if e.source_relative_path == "pkg/alpha.py")
    object_path = backend.published.store.object_path(entry.reference)
    original = object_path.read_bytes()
    object_path.write_bytes(original.replace(b"alpha widget", b"omega widget"))
    corrupted = backend.prepare(scope)
    reasons = {item.reason for item in corrupted.exclusions}
    assert "public_text_projection_excluded:artifact_corrupt" in reasons, corrupted.to_dict()["exclusion_counts"]
    assert all(d.descriptor["artifact_content_digest"] != entry.reference.content_digest for d in corrupted.documents)
    object_path.write_bytes(original)

    (working_copy / "core/pkg/alpha.py").write_bytes(SOURCES["core/pkg/alpha.py"].encode("utf-8") + b"\n# advanced\n")
    backend.refresh()
    with pytest.raises(PublicTextRefusal) as advanced:
        backend.prepare(scope)
    assert advanced.value.code == PUBLICATION_REVALIDATION_FAILED


def test_sqlite_public_text_capture_span_integrity_and_publication_drift(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working_copy, graph_id=GRAPH, declared_aliases=ALIASES)
    published = publish_and_load_sqlite_corpus(home, graph_id=GRAPH, selected_aliases=ALIASES)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    db_path = sqlite_graph_database_path(config, next(g for g in config.graphs if g.id == GRAPH))

    def execute_sql(sql: str) -> None:
        with sqlite3.connect(db_path) as connection:
            assert connection.execute(sql).rowcount >= 1

    backend = _Backend(
        published, adapter=make_sqlite_readback_adapter(published),
        nodes=lambda: load_sqlite_accepted_nodes_and_evidence(published),
        spans=lambda: load_sqlite_span_rows(published), execute_sql=execute_sql,
        refresh=lambda: refresh_local_graph(config, GRAPH),
    )
    _exercise(backend, working_copy, tmp_path)


def test_postgresql_public_text_capture_span_integrity_and_publication_drift(tmp_path: Path) -> None:
    working_copy = _working_copy(tmp_path / "wc")
    with temporary_postgres() as pg_db:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working_copy, graph_id=GRAPH, host=pg_db.host, port=pg_db.port,
            database=pg_db.database, user=pg_db.user, password=pg_db.password, declared_aliases=ALIASES,
        )
        published = publish_and_load_postgres_corpus(
            home, graph_id=GRAPH, selected_aliases=ALIASES, psql_command=pg_db.psql_command,
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = next(g for g in config.graphs if g.id == GRAPH)

        def execute_sql(sql: str) -> None:
            pg_db.psql_scalar(sql.replace("UPDATE canonical_evidence", "UPDATE public.canonical_evidence") + ";")

        backend = _Backend(
            published, adapter=make_postgres_readback_adapter(published, psql_command=pg_db.psql_command),
            nodes=lambda: load_postgres_accepted_nodes_and_evidence(published, psql_command=pg_db.psql_command),
            spans=lambda: load_postgres_span_rows(published, psql_command=pg_db.psql_command),
            execute_sql=execute_sql,
            refresh=lambda: execute_portable_refresh(config, graph, graph.database or config.postgres.database, authority=None),
        )
        _exercise(backend, working_copy, tmp_path)
