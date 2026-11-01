"""Unit tests for PostgreSQL cloe_lexical alias splitting, policy resolution, and pre-open capture (Unit 1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.retrieval.lexical_aliases import (
    ALIAS_SPLIT_RULE_VERSION,
    build_alias_tokens_text,
    split_identifier_and_path_tokens,
)
from common_lore_index.retrieval.lexical_capture import capture_lexical_generation_plan
from common_lore_index.retrieval.lexical_policy import (
    LEXICAL_POLICY_VERSION,
    PublicationFence,
    build_lexical_generation_policy,
    resolve_graph_privacy_for_lexical,
)
from common_lore_index.retrieval.projection_policy import ExclusionReason
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    build_mixed_v1_projection_policy,
    materialize_mixed_v1_working_copy,
)


def _make_binding(
    alias: str,
    root_path: Path,
    *,
    source_kind: str = "folder",
    role: str = "primary",
    privacy: str = "public-dev",
    evidence_retention: str = "full-authorized",
    include_paths: tuple[str, ...] = (),
    exclude_paths: tuple[str, ...] = (),
) -> OpsGraphSourceBindingConfig:
    b_id = (
        binding_id_for_alias(alias)
        if alias in {"core", "companion", "feeds", "mailbox"}
        else "bind1:" + (alias.encode("ascii").hex() * 64)[:64]
    )
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=b_id,
        source_definition_id="src1:" + ("a" * 64),
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root_path),
        root_path_expanded=str(root_path),
        repository_name=alias,
        logical_root=alias,
        privacy=privacy,
        evidence_retention=evidence_retention,
        extractor_profile="default",
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        selection_policy_id="sel1:" + ("a" * 64),
        resolution_policy="pinned",
        enabled=True,
        role=role,
    )


def _make_graph(
    bindings: tuple[OpsGraphSourceBindingConfig, ...],
    *,
    privacy: str = "public-dev",
    explicit: bool = True,
) -> OpsGraphConfig:
    return OpsGraphConfig(
        id=MIXED_V1_GRAPH_ID,
        name=MIXED_V1_GRAPH_ID,
        root_path=str(bindings[0].root_path),
        root_path_expanded=str(bindings[0].root_path_expanded),
        repository_name=MIXED_V1_GRAPH_ID,
        privacy=privacy,
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        database="repomap_mixed_v1",
        source_bindings=bindings,
        explicit_source_bindings=explicit,
    )


def test_identifier_and_path_alias_splitter_determinism() -> None:
    """Alias splitter extracts snake_case, camelCase, dot, and path segments deterministically."""
    assert ALIAS_SPLIT_RULE_VERSION == "identifier-path-split-v1"
    tokens = split_identifier_and_path_tokens(
        "pkg/router_table/RouteDispatchTable.py::verifyHTTP2Token_v1"
    )
    assert "route" in tokens
    assert "dispatch" in tokens
    assert "table" in tokens
    assert "verify" in tokens
    assert "http" in tokens
    assert "token" in tokens
    alias_text = build_alias_tokens_text(
        source_relative_path="pkg/pipeline.py",
        chunk_text="class RetrievalExecutionPipeline:\n    def execute_step(self):\n        pass\n",
    )
    assert "retrieval" in alias_text
    assert "execution" in alias_text
    assert "pipeline" in alias_text
    assert "execute" in alias_text


def test_lexical_policy_matches_mixed_v1_freeze_digest_and_excludes_private_bindings(
    tmp_path: Path,
) -> None:
    """Mixed-privacy private-ops graph is refused, while public-dev graph resolves admitted bindings."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    bindings = (
        _make_binding("core", wc / "core"),
        _make_binding("companion", wc / "companion", role="companion"),
        _make_binding(
            "feeds",
            wc / "feeds",
            source_kind="feed_archive",
            role="feeds",
            evidence_retention="metadata-only",
        ),
        _make_binding(
            "mailbox",
            wc / "mailbox",
            source_kind="email_archive",
            role="mailbox",
            privacy="private-memory",
            evidence_retention="redacted-hash",
        ),
    )
    mixed_graph = _make_graph(bindings, privacy="private-ops", explicit=True)
    assert resolve_graph_privacy_for_lexical(mixed_graph) == ("private-ops", "private-ops")
    mixed_pol = build_lexical_generation_policy(mixed_graph)
    assert mixed_pol.admitted_binding_ids == ()
    assert (
        mixed_pol.excluded_binding_reasons[binding_id_for_alias("core")]
        == ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value
    )

    graph = _make_graph(bindings, privacy="public-dev", explicit=True)
    orig_priv, res_priv = resolve_graph_privacy_for_lexical(graph)
    assert (orig_priv, res_priv) == ("public-dev", "public-dev")

    lex_pol = build_lexical_generation_policy(graph)
    assert lex_pol.policy_version == LEXICAL_POLICY_VERSION
    ref_pol = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID)
    assert lex_pol.body_policy.selected_binding_ids == ref_pol.selected_binding_ids
    assert lex_pol.policy_digest != ref_pol.policy_digest()
    assert set(lex_pol.admitted_binding_ids) == {
        binding_id_for_alias("core"),
        binding_id_for_alias("companion"),
    }
    assert (
        lex_pol.excluded_binding_reasons[binding_id_for_alias("mailbox")]
        == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value
    )
    assert (
        lex_pol.excluded_binding_reasons[binding_id_for_alias("feeds")]
        == ExclusionReason.RETENTION_NOT_AUTHORIZED.value
    )

    # Subset build shares graph policy_digest while scoping admitted_binding_ids (B3)
    sub_pol = build_lexical_generation_policy(
        graph, selected_binding_ids=(binding_id_for_alias("core"),)
    )
    assert sub_pol.policy_digest == lex_pol.policy_digest
    assert sub_pol.admitted_binding_ids == (binding_id_for_alias("core"),)
    assert sub_pol.body_policy.selected_binding_ids == frozenset({binding_id_for_alias("core")})


def test_lexical_capture_pre_open_exclusions_and_chunking(tmp_path: Path) -> None:
    """Capture plan enforces pre-open privacy/format/symlink/private-root exclusions and chunk bounds."""
    core_dir = tmp_path / "core"
    priv_dir = tmp_path / "private_secret"
    core_dir.mkdir()
    priv_dir.mkdir()
    (core_dir / "valid.py").write_text(
        "def alpha_beta():\n    return 'ok'\n", encoding="utf-8"
    )
    (core_dir / "secret.eml").write_text("From: x@y\n\nBody\n", encoding="utf-8")
    (core_dir / "feed.rss").write_text("<rss></rss>\n", encoding="utf-8")
    (core_dir / "binary.bin").write_bytes(b"\x00\x01\x02")
    (core_dir / "nul_in_py.py").write_bytes(b"x = 1\x00\n")
    (core_dir / "bad_utf8.py").write_bytes(b"x = '\xff\xfe'\n")
    (core_dir / "trunc.md").write_text("line text\n" * 50, encoding="utf-8")
    os.symlink(core_dir / "valid.py", core_dir / "link.py")

    b_core = _make_binding("core", core_dir)
    b_priv = _make_binding("mailbox", priv_dir, privacy="private-memory")
    graph = _make_graph((b_core, b_priv))
    lex_pol = build_lexical_generation_policy(
        graph,
        max_projected_file_bytes=64,
        max_chunk_lines=10,
        max_chunk_bytes=128,
    )
    fence = PublicationFence(
        run_id=7,
        publication_bundle_id="bundle1:" + ("1" * 64),
        snapshot_manifest_id="manifest1:" + ("2" * 64),
        snapshot_vector=((b_core.binding_id, 1, "snap1:" + ("3" * 64)),),
    ).validate()

    plan = capture_lexical_generation_plan(
        graph=graph,
        lexical_policy=lex_pol,
        fence=fence,
        repository_id=1,
        extraction_receipt_id="receipt1:" + ("4" * 64),
        graph_candidate_id="cand1:" + ("5" * 64),
        private_roots=(priv_dir,),
    )
    assert plan.projected_document_count == 2
    doc_paths = [d.source_relative_path for d in plan.documents]
    assert doc_paths == ["trunc.md", "valid.py"]
    omission_map = {
        (o.binding_id, o.source_relative_path): o.reason_code for o in plan.omissions
    }
    assert (
        omission_map[(b_priv.binding_id, None)]
        == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value
    )
    assert (
        omission_map[(b_core.binding_id, "secret.eml")]
        == ExclusionReason.EMAIL_BODY_FORBIDDEN.value
    )
    assert (
        omission_map[(b_core.binding_id, "feed.rss")]
        == ExclusionReason.FEED_BODY_FORBIDDEN.value
    )
    assert (
        omission_map[(b_core.binding_id, "link.py")]
        == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value
    )
    assert (
        omission_map[(b_core.binding_id, "nul_in_py.py")]
        == ExclusionReason.NUL_BYTE_REJECTED.value
    )
    assert (
        omission_map[(b_core.binding_id, "bad_utf8.py")]
        == ExclusionReason.INVALID_UTF8.value
    )
    assert (
        omission_map[(b_core.binding_id, "trunc.md")]
        == "oversize_projected_file_truncated"
    )

    with pytest.raises(ValueError, match="positive integer"):
        PublicationFence(
            run_id=0,
            publication_bundle_id="b",
            snapshot_manifest_id="m",
            snapshot_vector=(("b", 1, "s"),),
        ).validate()

    # Aggregate budget overflow fails closed instead of silently truncating (B7)
    tight_pol = build_lexical_generation_policy(graph, max_projected_files=1)
    with pytest.raises(ValueError, match="aggregate_budget_exceeded"):
        capture_lexical_generation_plan(
            graph=graph,
            lexical_policy=tight_pol,
            fence=fence,
            repository_id=1,
            extraction_receipt_id="receipt1:" + ("4" * 64),
            graph_candidate_id="cand1:" + ("5" * 64),
            private_roots=(priv_dir,),
        )

    # Migration 31-001 is non-destructive and verifies owner + marker + default privileges (M1, B6)
    mig_sql = Path(
        "src/main/resources/rdbms/2026/10/31-001-cloe-lexical-create-derived-schema.sql"
    ).read_text(encoding="utf-8")
    mig_non_comment = "\n".join(
        line for line in mig_sql.splitlines() if not line.strip().startswith("--")
    )
    assert "DROP SCHEMA" not in mig_non_comment.upper()
    assert "cloe-lexical-schema:1" in mig_sql
    assert "CREATE TABLE IF NOT EXISTS cloe_lexical.generations" in mig_sql
    assert "ALTER DEFAULT PRIVILEGES" in mig_sql
