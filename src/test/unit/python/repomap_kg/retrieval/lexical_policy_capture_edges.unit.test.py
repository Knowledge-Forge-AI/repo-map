"""Cohesive unit proofs for lexical policy and pre-open capture edge cases."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.retrieval.lexical_capture import (
    LexicalFileCandidate,
    _discover_binding_files,
    _evaluate_candidate_pre_open,
    _overlaps_any_private_root,
    _read_bounded_regular_file,
    capture_lexical_generation_plan,
)
from common_lore_index.retrieval.lexical_policy import (
    PublicationFence,
    _evaluate_resolved_binding_exclusion,
    build_lexical_generation_policy,
    normalize_lexical_path_prefix,
)
from common_lore_index.retrieval.projection_policy import ExclusionReason, ResolvedBindingPolicy
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
)


def _make_binding(
    alias: str,
    root_path: Path,
    *,
    source_kind: SourceKind = SourceKind.FOLDER,
    role: str = "primary",
    privacy: str = "public-dev",
    evidence_retention: str = "full-authorized",
    include_paths: tuple[str, ...] = (),
    exclude_paths: tuple[str, ...] = (),
) -> OpsGraphSourceBindingConfig:
    binding_id = (
        binding_id_for_alias(alias)
        if alias in {"core", "companion", "feeds", "mailbox"}
        else "bind1:" + (alias.encode("ascii").hex() * 64)[:64]
    )
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=binding_id,
        source_definition_id="src1:" + "a" * 64,
        alias=alias,
        revision=1,
        source_kind=source_kind,
        root_path=str(root_path),
        root_path_expanded=str(root_path),
        repository_name=alias,
        logical_root=alias,
        privacy=privacy,
        evidence_retention=evidence_retention,
        extractor_profile="default",
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        selection_policy_id="sel1:" + "a" * 64,
        resolution_policy="pinned",
        enabled=True,
        role=role,
    )


def _make_graph(
    bindings: tuple[OpsGraphSourceBindingConfig, ...],
    *,
    privacy: str = "public-dev",
) -> OpsGraphConfig:
    first = bindings[0]
    return OpsGraphConfig(
        id=MIXED_V1_GRAPH_ID,
        name=MIXED_V1_GRAPH_ID,
        root_path=first.root_path,
        root_path_expanded=first.root_path_expanded,
        repository_name=MIXED_V1_GRAPH_ID,
        privacy=privacy,
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        database="repomap_mixed_v1",
        source_bindings=bindings,
        explicit_source_bindings=True,
    )


def _resolved(binding: OpsGraphSourceBindingConfig) -> ResolvedBindingPolicy:
    return ResolvedBindingPolicy(
        binding.binding_id,
        binding.alias,
        binding.role,
        "folder",
        "public-dev",
        "public-dev",
        binding.privacy,
        binding.privacy,
        binding.evidence_retention,
        binding.evidence_retention,
    )


def _fence(binding_id: str) -> PublicationFence:
    return PublicationFence(
        run_id=1,
        publication_bundle_id="bundle1:" + "1" * 64,
        snapshot_manifest_id="manifest1:" + "2" * 64,
        snapshot_vector=((binding_id, 1, "snap1:" + "3" * 64),),
    ).validate()


def test_lexical_path_prefix_and_publication_fence_reject_invalid_values() -> None:
    invalid_path: Any = 123
    with pytest.raises(ValueError, match="string"):
        normalize_lexical_path_prefix(invalid_path)

    invalid_fences = (
        PublicationFence(
            run_id=True,
            publication_bundle_id="b",
            snapshot_manifest_id="m",
            snapshot_vector=(("b", 1, "s"),),
        ),
        PublicationFence(
            run_id=1,
            publication_bundle_id="",
            snapshot_manifest_id="m",
            snapshot_vector=(("b", 1, "s"),),
        ),
        PublicationFence(
            run_id=1,
            publication_bundle_id="b",
            snapshot_manifest_id="m",
            snapshot_vector=(),
        ),
    )
    for fence in invalid_fences:
        with pytest.raises(ValueError):
            fence.validate()


def test_lexical_policy_reclassification_and_binding_exclusion(tmp_path: Path) -> None:
    core = _make_binding("core", tmp_path / "core")
    disabled = replace(_make_binding("companion", tmp_path / "companion"), enabled=False)
    feeds = _make_binding("feeds", tmp_path / "feed.atom", role="feeds")
    mailbox = _make_binding("mailbox", tmp_path / "mail.mbox", role="mailbox")

    assert _evaluate_resolved_binding_exclusion(_resolved(core), disabled) == ExclusionReason.BINDING_NOT_SELECTED
    inherit = ResolvedBindingPolicy(
        core.binding_id,
        "core",
        "primary",
        "folder",
        "inherit",
        "inherit",
        "public-dev",
        "public-dev",
        "full-authorized",
        "full-authorized",
    )
    assert _evaluate_resolved_binding_exclusion(inherit, core) == ExclusionReason.UNRESOLVED_INHERIT_POLICY
    assert _evaluate_resolved_binding_exclusion(_resolved(feeds), feeds) == ExclusionReason.FEED_BODY_FORBIDDEN
    assert _evaluate_resolved_binding_exclusion(_resolved(mailbox), mailbox) == ExclusionReason.EMAIL_BODY_FORBIDDEN

    graph = _make_graph((core, disabled, feeds, mailbox))
    policy = build_lexical_generation_policy(graph, selected_binding_ids=(core.binding_id,))
    assert policy.is_binding_admitted(core.binding_id) is True
    assert policy.refusal_code_for_binding(core.binding_id) == ExclusionReason.BINDING_NOT_SELECTED.value
    assert policy.refusal_code_for_binding("bind1:unknown") == ExclusionReason.BINDING_NOT_SELECTED.value
    assert policy.check_reclassification_against_published(
        published_policy_digest=policy.policy_digest,
        published_admitted_binding_ids=(core.binding_id,),
        published_binding_digests=policy.binding_policy_digests,
    ) == ("ok", None)
    assert policy.check_reclassification_against_published(
        published_policy_digest="sha256:0",
        published_admitted_binding_ids=(core.binding_id,),
        published_binding_digests=policy.binding_policy_digests,
    ) == ("stale", "lexical_policy_digest_changed")
    assert policy.check_reclassification_against_published(
        published_policy_digest=policy.policy_digest,
        published_admitted_binding_ids=(core.binding_id,),
        published_binding_digests={core.binding_id: "sha256:0"},
    ) == ("stale", f"lexical_binding_policy_digest_changed:{core.binding_id}")
    assert policy.check_reclassification_against_published(
        published_policy_digest=policy.policy_digest,
        published_admitted_binding_ids=(disabled.binding_id,),
        published_binding_digests=policy.binding_policy_digests,
    )[0] == "stale"
    assert policy.check_reclassification_against_published(
        published_policy_digest=policy.policy_digest,
        published_admitted_binding_ids=(mailbox.binding_id,),
        published_binding_digests=policy.binding_policy_digests,
    ) == ("refused", ExclusionReason.EMAIL_BODY_FORBIDDEN.value)
    private_policy = build_lexical_generation_policy(_make_graph((core,), privacy="private-ops"))
    assert private_policy.check_reclassification_against_published(
        published_policy_digest=private_policy.policy_digest,
        published_admitted_binding_ids=(),
        published_binding_digests={},
    ) == ("refused", ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value)


def test_lexical_capture_walk_and_candidate_preopen_guards(tmp_path: Path) -> None:
    root = tmp_path / "walk"
    private_root = tmp_path / "private"
    (root / "inc").mkdir(parents=True)
    (root / "skip_dir").mkdir()
    (root / ".git").mkdir()
    private_root.mkdir()
    (root / "inc" / "empty.py").write_text("", encoding="utf-8")
    (root / "inc" / "big.py").write_text("x = 1\n" * 40, encoding="utf-8")
    (root / "outside.py").write_text("y = 2\n", encoding="utf-8")
    (root / "skip_dir" / "gone.py").write_text("z = 3\n", encoding="utf-8")
    (root / ".git" / "hook.py").write_text("g = 4\n", encoding="utf-8")
    os.symlink(root / "inc", root / "inc_link")

    core = _make_binding("core", root, include_paths=("inc",), exclude_paths=("skip_dir",))
    resolved = _resolved(core)
    assert _overlaps_any_private_root(root, ()) is False
    assert _overlaps_any_private_root(private_root / "a.py", (private_root,)) is True
    assert _discover_binding_files(core, tmp_path / "missing", ()) == []
    assert _discover_binding_files(core, root / "inc_link", ()) == []

    private_candidate = LexicalFileCandidate(core.binding_id, "a.py", private_root / "a.py", True, False, True, 10)
    oversized_candidate = LexicalFileCandidate(core.binding_id, "a.py", root / "a.py", True, False, False, 200)
    assert _evaluate_candidate_pre_open(
        cand=private_candidate,
        resolved_b=resolved,
        max_input_bytes=100,
        max_files=5,
        max_agg_bytes=500,
        cur_files=0,
        cur_agg_bytes=0,
    ) == ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN
    assert _evaluate_candidate_pre_open(
        cand=oversized_candidate,
        resolved_b=resolved,
        max_input_bytes=100,
        max_files=5,
        max_agg_bytes=500,
        cur_files=0,
        cur_agg_bytes=0,
    ) == ExclusionReason.ARTIFACT_OVERSIZED
    assert _read_bounded_regular_file(
        private_root / "a.py", max_input_bytes=100, private_roots=(private_root,)
    ) == (None, ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN)
    assert _read_bounded_regular_file(
        tmp_path / "no_file.py", max_input_bytes=100, private_roots=()
    ) == (None, ExclusionReason.UNSUPPORTED_SOURCE_FORMAT)
    assert _read_bounded_regular_file(root, max_input_bytes=100, private_roots=()) == (
        None,
        ExclusionReason.UNSUPPORTED_SOURCE_FORMAT,
    )
    assert _read_bounded_regular_file(
        root / "inc" / "big.py", max_input_bytes=4, private_roots=()
    ) == (None, ExclusionReason.ARTIFACT_OVERSIZED)


def test_lexical_capture_fence_preserves_empty_document_and_refuses_private_graph(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    (root / "inc").mkdir(parents=True)
    (root / "inc" / "empty.py").write_text("", encoding="utf-8")
    core = _make_binding("core", root, include_paths=("inc",))
    graph = _make_graph((core,))
    policy = build_lexical_generation_policy(graph)
    plan = capture_lexical_generation_plan(
        graph=graph,
        lexical_policy=policy,
        fence=_fence(core.binding_id),
        repository_id=1,
        extraction_receipt_id="receipt1:" + "4" * 64,
        graph_candidate_id="cand1:" + "5" * 64,
    )
    empty_doc = next(doc for doc in plan.documents if doc.source_relative_path == "inc/empty.py")
    assert empty_doc.line_count == 0
    assert empty_doc.chunks[0].start_line == 0

    private_graph = _make_graph((core,), privacy="private-ops")
    private_policy = build_lexical_generation_policy(private_graph)
    with pytest.raises(ValueError, match="non-public graph privacy"):
        capture_lexical_generation_plan(
            graph=graph,
            lexical_policy=private_policy,
            fence=_fence(core.binding_id),
            repository_id=1,
            extraction_receipt_id="receipt1:" + "4" * 64,
            graph_candidate_id="cand1:" + "5" * 64,
        )
