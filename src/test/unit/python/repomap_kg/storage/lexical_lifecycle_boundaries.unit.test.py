"""Bounded unit proofs for cloe_lexical lifecycle and privacy boundaries."""

from __future__ import annotations

from typing import Any

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_capture import (
    LexicalCapturePlan,
    LexicalCapturedChunk,
    LexicalCapturedDocument,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import CapabilityState
from common_lore_index.storage.lexical_driver import LexicalStorageError
from common_lore_index.storage.lexical_lifecycle import publish_lexical_generation
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.current: Any = None
        self.description: Any = (("value",),)
        self.rowcount = 1

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.connection.executed.append((sql, params))
        if "SELECT pg_try_advisory_xact_lock" in sql:
            self.current = (True,)
            return
        if "SET lease_expires_at = clock_timestamp()" in sql:
            self.current = ("owned-building-generation",)
            return
        if self.connection.responses:
            self.current = self.connection.responses.pop(0)
            if isinstance(self.current, Exception):
                raise self.current

    def fetchone(self) -> Any:
        return self.current

    def fetchall(self) -> list[Any]:
        if isinstance(self.current, list):
            return self.current
        return []


class _Connection:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.executed: list[tuple[str, Any]] = []
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def rollback(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _plan(policy_digest: str = "sha256:" + "1" * 64) -> LexicalCapturePlan:
    chunk = LexicalCapturedChunk(
        "pchunk1:" + "2" * 64,
        "bind1:" + "3" * 64,
        1,
        "snap1:" + "4" * 64,
        "pkg/example.py",
        0,
        1,
        1,
        8,
        "sha256:" + "5" * 64,
        "needle=1\n",
        "pkg example needle 1",
        "public-dev",
    )
    document = LexicalCapturedDocument(
        0,
        chunk.binding_id,
        1,
        chunk.snapshot_id,
        chunk.source_relative_path,
        "sha256:" + "6" * 64,
        8,
        1,
        1,
        chunk.chunk_text,
        "public-dev",
        "full-authorized",
        (chunk,),
    )
    return LexicalCapturePlan(
        "lexgen1:" + "7" * 64,
        10,
        3,
        "bundle1:" + "8" * 64,
        "snapmanifest1:" + "9" * 64,
        "receipt1:" + "a" * 64,
        "cand1:" + "b" * 64,
        ((chunk.binding_id, 1, chunk.snapshot_id),),
        "cloe-lexical-pg-fts-v1",
        "pg_catalog.simple",
        "ts_rank_cd(weight={0.1,0.2,0.4,1.0},normalization=32)",
        32,
        "identifier-path-split-v1",
        policy_digest,
        "public-dev",
        {chunk.binding_id: "sha256:" + "c" * 64},
        (chunk.binding_id,),
        (),
        (document,),
        (),
        8,
        8,
    )


def _fence_row(
    *,
    run_id: int = 3,
    advisory_ok: bool = True,
    no_competing: bool = True,
    counts_valid: bool = True,
) -> tuple[Any, ...]:
    return (
        run_id,
        "portable-worker-v1",
        "bundle1:" + "8" * 64,
        "snapmanifest1:" + "9" * 64,
        "receipt1:" + "a" * 64,
        "cand1:" + "b" * 64,
        '[["bind1:' + "3" * 64 + '",1,"snap1:' + "4" * 64 + '" ]]',
        True,
        "{}",
        advisory_ok,
        no_competing,
        counts_valid,
    )


def test_publish_fence_rejects_competing_expired_and_newer_publication() -> None:
    """An owner cannot activate when the commit fence reports unsafe state."""
    cases = (
        ("cloe_lexical_concurrent_build_active", _fence_row(no_competing=False), None),
        ("cloe_lexical_count_verification_failed", _fence_row(counts_valid=False), None),
        (
            "cloe_lexical_policy_digest_mismatch",
            _fence_row(),
            lambda: "sha256:" + "d" * 64,
        ),
        ("cloe_lexical_publication_fence_mismatch", _fence_row(run_id=4), None),
    )
    for code, fence, policy_recheck in cases:
        connection = _Connection([None] * 3 + [fence])
        with pytest.raises(LexicalStorageError) as error:
            publish_lexical_generation(
                connection,
                _plan(),
                live_policy_recheck=policy_recheck,
            )
        assert error.value.code == code
        assert not any(
            "INSERT INTO cloe_lexical.authority" in sql
            for sql, _params in connection.executed
        )


def test_privacy_refusals_require_body_authorization_and_selected_bindings(
    tmp_path: Any,
) -> None:
    """Explicit body authorization still refuses each disallowed selected binding."""
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "home",
        working_copy,
        host="127.0.0.1",
        port=55433,
        database="unused_fixture_database",
        user="unused_fixture_owner",
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    core_id = binding_id_for_alias("core")
    companion_id = binding_id_for_alias("companion")
    feeds_id = binding_id_for_alias("feeds")
    mailbox_id = binding_id_for_alias("mailbox")

    refused_graph = build_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        selected_binding_ids=(core_id, companion_id),
        authorize_body=True,
        connection_factory=lambda _params: pytest.fail("private graph policy opened a database"),
    )
    assert refused_graph.result == "refused"
    assert refused_graph.refusal_code == "graph_privacy_not_authorized"

    config_path = home / "repomap.rpl.toml"
    public_graph = config_path.read_text().replace('privacy = "private-memory"', 'privacy = "public-dev"', 1)
    config_path.write_text(public_graph)
    retention_refusal = build_graph_lexical_generation(
        config, MIXED_V1_GRAPH_ID, selected_binding_ids=(feeds_id,), authorize_body=True,
        connection_factory=lambda _params: pytest.fail("metadata-only feed opened a database"),
    )
    assert retention_refusal.refusal_code == "retention_not_authorized"
    config_path.write_text(public_graph.replace('evidence_retention = "metadata-only"',
                                              'evidence_retention = "full-authorized"'))
    refused_feed = build_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        selected_binding_ids=(feeds_id,),
        authorize_body=True,
        connection_factory=lambda _params: pytest.fail("feed body policy opened a database"),
    )
    assert refused_feed.result == "refused"
    assert refused_feed.refusal_code == "feed_body_forbidden"

    refused_mailbox = query_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        LexicalQueryRequest(query="body", selected_binding_ids=(mailbox_id,)),
        authorize_body=True,
        connection_factory=lambda _params: pytest.fail("mailbox body policy opened a database"),
    )
    assert refused_mailbox.capability_state == CapabilityState.REFUSED
    assert refused_mailbox.refusal_code == "email_body_forbidden"
    assert refused_mailbox.omissions[0].reason_code == "email_body_forbidden"
