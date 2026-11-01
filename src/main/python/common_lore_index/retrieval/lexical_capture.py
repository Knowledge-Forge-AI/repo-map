"""Pre-open privacy-gated capture of lexical documents, chunks, and omissions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat

from common_lore_index.artifacts import FileSystemArtifactStore, PortableSnapshotManifest
from common_lore_index.artifacts._store_common import ArtifactErrorCode, ArtifactIntegrityError
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.retrieval.lexical_aliases import build_alias_tokens_text
from common_lore_index.retrieval.lexical_policy import (
    LEXICAL_ALIAS_SPLIT_VERSION, LEXICAL_NORMALIZATION_FLAGS, LEXICAL_RANKING_FUNCTION,
    LEXICAL_REPRESENTATION_VERSION, LEXICAL_TEXT_CONFIG, LexicalGenerationPolicy, PublicationFence,
)
from common_lore_index.retrieval.projection_chunks import build_file_chunks, frame_digest
from common_lore_index.retrieval.projection_policy import (
    ExclusionReason, ResolvedBindingPolicy, SUPPORTED_TEXT_FORMATS,
    _is_email_role_or_path, _is_feed_role_or_path, evaluate_artifact_pre_open,
)
from common_lore_index.retrieval.projection_text import normalize_and_bound_text
from common_lore_index.retrieval.query_contracts import OmissionRecord

_SKIPPED_VCS_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__"})


@dataclass(frozen=True)
class LexicalFileCandidate:
    """Discovered local filesystem entry evaluated before opening file bytes."""
    binding_id: str
    source_relative_path: str
    absolute_path: Path
    is_regular_file: bool
    is_symlink: bool
    overlaps_private_root: bool
    stat_size_bytes: int


@dataclass(frozen=True)
class LexicalCapturedChunk:
    """One chunk prepared for insertion into cloe_lexical.chunks."""
    chunk_id: str
    binding_id: str
    binding_revision: int
    snapshot_id: str
    source_relative_path: str
    chunk_ordinal: int
    start_line: int
    end_line: int
    byte_length: int
    chunk_sha256: str
    chunk_text: str
    alias_tokens_text: str
    artifact_privacy: str


@dataclass(frozen=True)
class LexicalCapturedDocument:
    """One normalized file document and its chunks prepared for cloe_lexical."""
    document_ordinal: int
    binding_id: str
    binding_revision: int
    snapshot_id: str
    source_relative_path: str
    file_content_sha256: str
    normalized_byte_length: int
    line_count: int
    chunk_count: int
    normalized_text: str
    artifact_privacy: str
    evidence_retention: str
    chunks: tuple[LexicalCapturedChunk, ...]


@dataclass(frozen=True)
class LexicalCapturePlan:
    """Complete deterministic lexical capture payload before PostgreSQL population."""
    lexical_generation_id: str
    repository_id: int
    run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    extraction_receipt_id: str
    graph_candidate_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    representation_version: str
    text_config_regconfig: str
    ranking_function: str
    normalization_flags: int
    alias_split_rule_version: str
    policy_digest: str
    resolved_graph_privacy: str
    binding_policy_digests: Mapping[str, str]
    admitted_binding_ids: tuple[str, ...]
    excluded_binding_ids: tuple[str, ...]
    documents: tuple[LexicalCapturedDocument, ...]
    omissions: tuple[OmissionRecord, ...]
    aggregate_input_bytes: int
    aggregate_projected_bytes: int
    publication_receipt_json: str = "{}"

    @property
    def projected_document_count(self) -> int: return len(self.documents)
    @property
    def projected_chunk_count(self) -> int: return sum(len(doc.chunks) for doc in self.documents)
    @property
    def omitted_record_count(self) -> int: return len(self.omissions)


def _overlaps_any_private_root(target: Path, private_roots: Sequence[Path]) -> bool:
    if not private_roots: return False
    try: resolved = target.resolve(strict=False)
    except OSError: return True
    for priv in private_roots:
        try:
            priv_res = priv.resolve(strict=False)
            if resolved == priv_res or priv_res in resolved.parents: return True
        except OSError: return True
    return False


def _matches_any_prefix(rel_path: str, prefixes: Sequence[str]) -> bool:
    return any((p := raw.strip("/")) and (rel_path == p or rel_path.startswith(p + "/")) for raw in prefixes)


def _discover_binding_files(
    binding: OpsGraphSourceBindingConfig, root_dir: Path, private_roots: Sequence[Path],
) -> list[LexicalFileCandidate]:
    if not root_dir.exists() or root_dir.is_symlink() or not root_dir.is_dir(): return []
    discovered: list[LexicalFileCandidate] = []
    for cur_root, dirs, files in os.walk(root_dir, topdown=True, followlinks=False):
        cur_path, kept_dirs = Path(cur_root), []
        for d in sorted(dirs):
            if d in _SKIPPED_VCS_DIRS: continue
            d_path = cur_path / d
            rel_d = d_path.relative_to(root_dir).as_posix()
            if binding.exclude_paths and _matches_any_prefix(rel_d, binding.exclude_paths): continue
            if d_path.is_symlink():
                discovered.append(LexicalFileCandidate(binding.binding_id, rel_d, d_path, False, True, False, 0))
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs
        for fname in sorted(files):
            fpath = cur_path / fname
            rel_f = fpath.relative_to(root_dir).as_posix()
            if (binding.include_paths and not _matches_any_prefix(rel_f, binding.include_paths)) or (
                binding.exclude_paths and _matches_any_prefix(rel_f, binding.exclude_paths)
            ):
                continue
            try: lstat_res = os.lstat(fpath)
            except OSError: continue
            is_sym = stat.S_ISLNK(lstat_res.st_mode)
            is_reg = stat.S_ISREG(lstat_res.st_mode) and not is_sym
            discovered.append(LexicalFileCandidate(
                binding.binding_id, rel_f, fpath, is_reg, is_sym,
                _overlaps_any_private_root(fpath, private_roots), int(lstat_res.st_size) if is_reg else 0,
            ))
    discovered.sort(key=lambda item: item.source_relative_path)
    return discovered


def _evaluate_candidate_pre_open(
    *, cand: LexicalFileCandidate, resolved_b: ResolvedBindingPolicy,
    max_input_bytes: int, max_files: int, max_agg_bytes: int, cur_files: int, cur_agg_bytes: int,
) -> ExclusionReason | None:
    if cand.overlaps_private_root: return ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN
    if cand.is_symlink or not cand.is_regular_file: return ExclusionReason.UNSUPPORTED_SOURCE_FORMAT
    rel = cand.source_relative_path
    if _is_email_role_or_path(resolved_b.role, resolved_b.source_kind, resolved_b.alias, rel):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN
    if _is_feed_role_or_path(resolved_b.role, resolved_b.source_kind, resolved_b.alias, rel):
        return ExclusionReason.FEED_BODY_FORBIDDEN
    if PurePosixPath(rel).suffix.lower() not in SUPPORTED_TEXT_FORMATS:
        return ExclusionReason.UNSUPPORTED_SOURCE_FORMAT
    if cand.stat_size_bytes > max_input_bytes: return ExclusionReason.ARTIFACT_OVERSIZED
    if cur_files >= max_files or (cur_agg_bytes + cand.stat_size_bytes) > max_agg_bytes:
        return ExclusionReason.AGGREGATE_BUDGET_EXCEEDED
    return None


def _read_bounded_regular_file(
    path: Path, *, max_input_bytes: int, private_roots: Sequence[Path],
) -> tuple[bytes | None, ExclusionReason | None]:
    if _overlaps_any_private_root(path, private_roots): return None, ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN
    try: fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError: return None, ExclusionReason.UNSUPPORTED_SOURCE_FORMAT
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode): return None, ExclusionReason.UNSUPPORTED_SOURCE_FORMAT
        if st.st_size > max_input_bytes: return None, ExclusionReason.ARTIFACT_OVERSIZED
        chunks, total = [], 0
        while buf := os.read(fd, 65536):
            total += len(buf)
            if total > max_input_bytes: return None, ExclusionReason.ARTIFACT_OVERSIZED
            chunks.append(buf)
        return b"".join(chunks), None
    except OSError: return None, ExclusionReason.ARTIFACT_CORRUPT
    finally: os.close(fd)


def _build_captured_chunks(
    *, file_proj_id: str, binding_id: str, binding_revision: int, snapshot_id: str,
    source_relative_path: str, normalized_text: str, artifact_privacy: str,
    policy_digest: str, publication_bundle_id: str, max_chunk_lines: int, max_chunk_bytes: int,
) -> tuple[LexicalCapturedChunk, ...]:
    raw_chunks = build_file_chunks(
        file_projection_id=file_proj_id, binding_id=binding_id,
        source_relative_path=source_relative_path, normalized_text=normalized_text,
        artifact_privacy=artifact_privacy, policy_digest=policy_digest,
        publication_bundle_id=publication_bundle_id,
        max_chunk_lines=max_chunk_lines, max_chunk_bytes=max_chunk_bytes,
    )
    captured: list[LexicalCapturedChunk] = []
    for c in raw_chunks:
        start_line, end_line = (0, 0) if c.is_empty_file_record else (max(1, c.start_line), max(1, c.start_line, c.end_line))
        pchunk_id = frame_digest("pchunk1", (
            policy_digest, publication_bundle_id, binding_id, str(binding_revision), snapshot_id,
            source_relative_path, str(c.chunk_index), str(start_line), str(end_line), c.content_digest,
        ))
        captured.append(LexicalCapturedChunk(
            pchunk_id, binding_id, binding_revision, snapshot_id, source_relative_path,
            c.chunk_index, start_line, end_line, c.byte_length, c.content_digest,
            c.content_text, build_alias_tokens_text(source_relative_path=source_relative_path, chunk_text=c.content_text), artifact_privacy,
        ))
    return tuple(captured)


def _append_normalized_document(
    *, documents: list[LexicalCapturedDocument], omissions: list[OmissionRecord],
    raw_bytes: bytes, b_id: str, rev: int, snap_id: str, rel_path: str,
    art_priv: str, retention: str, lexical_policy: LexicalGenerationPolicy,
    fence: PublicationFence, content_digest_override: str | None = None,
) -> tuple[int, int] | None:
    body_policy = lexical_policy.body_policy
    norm_res, norm_reason = normalize_and_bound_text(raw_bytes, max_projected_bytes=body_policy.max_projected_file_bytes)
    if norm_reason is not None or norm_res is None:
        r_code = (norm_reason or ExclusionReason.INVALID_UTF8).value
        omissions.append(OmissionRecord(b_id, rel_path, r_code, f"artifact {rel_path} rejected during normalization: {r_code}").validate())
        return None
    if norm_res.truncated:
        omissions.append(OmissionRecord(b_id, rel_path, "oversize_projected_file_truncated", f"projected prefix bounded to {norm_res.projected_byte_length} of {norm_res.normalized_byte_length} bytes").validate())
    content_sha256 = content_digest_override or norm_res.representation_digest
    file_proj_id = frame_digest("lexdoc1", (lexical_policy.policy_digest, fence.publication_bundle_id, b_id, str(rev), snap_id, rel_path, content_sha256))
    captured_chunks = _build_captured_chunks(
        file_proj_id=file_proj_id, binding_id=b_id, binding_revision=rev, snapshot_id=snap_id,
        source_relative_path=rel_path, normalized_text=norm_res.normalized_text,
        artifact_privacy=art_priv, policy_digest=lexical_policy.policy_digest,
        publication_bundle_id=fence.publication_bundle_id, max_chunk_lines=body_policy.max_chunk_lines,
        max_chunk_bytes=body_policy.max_chunk_bytes,
    )
    line_cnt = 0 if norm_res.projected_byte_length == 0 else max(1, norm_res.projected_line_count)
    documents.append(LexicalCapturedDocument(
        len(documents), b_id, rev, snap_id, rel_path, content_sha256,
        norm_res.projected_byte_length, line_cnt, len(captured_chunks),
        norm_res.normalized_text, art_priv, retention, captured_chunks,
    ))
    return norm_res.raw_byte_length, norm_res.projected_byte_length


def _capture_from_retained_manifest(
    *, manifest: PortableSnapshotManifest, store: FileSystemArtifactStore,
    lexical_policy: LexicalGenerationPolicy, fence: PublicationFence,
) -> tuple[list[LexicalCapturedDocument], list[OmissionRecord], int, int]:
    body_policy = lexical_policy.body_policy
    bindings_by_id = {b.binding_id: b for b in manifest.bindings}
    resolved_by_id = dict(body_policy.bindings)
    omissions: list[OmissionRecord] = []
    documents: list[LexicalCapturedDocument] = []
    aggregate_input_bytes, aggregate_projected_bytes, projected_files_count = 0, 0, 0
    for b_id in sorted(resolved_by_id):
        resolved_b = resolved_by_id[b_id]
        if b_id in lexical_policy.excluded_binding_reasons:
            r_code = lexical_policy.excluded_binding_reasons[b_id]
            omissions.append(OmissionRecord(b_id, None, r_code, f"binding {b_id} ({resolved_b.alias}) excluded before file open: {r_code}").validate())
        elif b_id not in bindings_by_id:
            omissions.append(OmissionRecord(b_id, None, "binding_absent_from_publication_vector", f"binding {b_id} is not present in accepted snapshot_vector").validate())
    for entry in sorted(manifest.entries, key=lambda item: (item.binding_id, item.source_relative_path)):
        b_id = entry.binding_id
        if b_id in lexical_policy.excluded_binding_reasons or b_id not in resolved_by_id:
            continue
        binding, resolved_b = bindings_by_id[b_id], resolved_by_id[b_id]
        pre_reason, _fmt = evaluate_artifact_pre_open(body_policy, binding, entry)
        if pre_reason is not None:
            omissions.append(OmissionRecord(b_id, entry.source_relative_path, pre_reason.value, f"artifact {entry.source_relative_path} excluded pre-open: {pre_reason.value}").validate())
            continue
        if projected_files_count >= body_policy.max_projected_files or (aggregate_input_bytes + entry.reference.size_bytes) > body_policy.max_aggregate_input_bytes:
            raise ValueError(f"{ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value}: lexical capture exceeded aggregate file or byte budget")
        try:
            raw_bytes = store.read(entry.reference.with_store_version(None), max_bytes=body_policy.max_input_artifact_bytes)
        except ArtifactIntegrityError as error:
            reason = ExclusionReason.ARTIFACT_MISSING if error.code == ArtifactErrorCode.ARTIFACT_MISSING else ExclusionReason.ARTIFACT_CORRUPT
            omissions.append(OmissionRecord(b_id, entry.source_relative_path, reason.value, f"artifact {entry.source_relative_path} rejected on open: {reason.value}").validate())
            continue
        art_priv = entry.reference.privacy.value if entry.reference.privacy.value in {"public-dev", "public", "raw_source"} else resolved_b.resolved_binding_privacy
        appended = _append_normalized_document(
            documents=documents, omissions=omissions, raw_bytes=raw_bytes, b_id=b_id,
            rev=binding.revision, snap_id=binding.snapshot_id, rel_path=entry.source_relative_path,
            art_priv=art_priv, retention=resolved_b.resolved_evidence_retention,
            lexical_policy=lexical_policy, fence=fence, content_digest_override=entry.reference.content_digest,
        )
        if appended is not None:
            aggregate_input_bytes += appended[0]
            aggregate_projected_bytes += appended[1]
            projected_files_count += 1
    return documents, omissions, aggregate_input_bytes, aggregate_projected_bytes


def capture_lexical_generation_plan(
    *, graph: OpsGraphConfig, lexical_policy: LexicalGenerationPolicy,
    fence: PublicationFence, repository_id: int, extraction_receipt_id: str,
    graph_candidate_id: str, binding_roots_override: Mapping[str, Path] | None = None,
    private_roots: Sequence[Path] = (), manifest: PortableSnapshotManifest | None = None,
    store: FileSystemArtifactStore | None = None, publication_receipt_json: str = "{}",
) -> LexicalCapturePlan:
    """Capture eligible public-dev bindings into a deterministic LexicalCapturePlan."""
    body_policy = lexical_policy.body_policy
    if lexical_policy.resolved_graph_privacy != "public-dev":
        raise ValueError(f"refusing lexical capture for non-public graph privacy {lexical_policy.resolved_graph_privacy!r}")
    if fence.run_id is None or fence.run_id <= 0:
        raise ValueError("lexical capture requires a positive published run_id")
    if manifest is not None and store is not None:
        documents, omissions, aggregate_input_bytes, aggregate_projected_bytes = _capture_from_retained_manifest(
            manifest=manifest, store=store, lexical_policy=lexical_policy, fence=fence,
        )
    else:
        vector_by_binding = {b_id: (rev, snap_id) for b_id, rev, snap_id in fence.snapshot_vector}
        raw_by_id = {b.binding_id: b for b in graph.effective_source_bindings}
        resolved_by_id = dict(body_policy.bindings)
        omissions, documents = [], []
        all_candidates: list[tuple[OpsGraphSourceBindingConfig, LexicalFileCandidate]] = []
        for b_id in sorted(resolved_by_id):
            resolved_b, raw_b = resolved_by_id[b_id], raw_by_id[b_id]
            if b_id in lexical_policy.excluded_binding_reasons:
                reason_code = lexical_policy.excluded_binding_reasons[b_id]
                omissions.append(OmissionRecord(b_id, None, reason_code, f"binding {b_id} ({resolved_b.alias}) excluded before file open: {reason_code}").validate())
                continue
            if b_id not in vector_by_binding:
                omissions.append(OmissionRecord(b_id, None, "binding_absent_from_publication_vector", f"binding {b_id} is not present in accepted snapshot_vector").validate())
                continue
            root_str = str(binding_roots_override[b_id]) if (binding_roots_override and b_id in binding_roots_override) else raw_b.root_path_expanded
            if not root_str:
                omissions.append(OmissionRecord(b_id, None, ExclusionReason.ARTIFACT_MISSING.value, f"binding {b_id} has no local filesystem root_path_expanded").validate())
                continue
            all_candidates.extend((raw_b, cand) for cand in _discover_binding_files(raw_b, Path(root_str), private_roots))
        aggregate_input_bytes, aggregate_projected_bytes, projected_files_count = 0, 0, 0
        for raw_b, cand in all_candidates:
            b_id, resolved_b, (rev, snap_id) = raw_b.binding_id, resolved_by_id[raw_b.binding_id], vector_by_binding[raw_b.binding_id]
            pre_reason = _evaluate_candidate_pre_open(
                cand=cand, resolved_b=resolved_b, max_input_bytes=body_policy.max_input_artifact_bytes,
                max_files=body_policy.max_projected_files, max_agg_bytes=body_policy.max_aggregate_input_bytes,
                cur_files=projected_files_count, cur_agg_bytes=aggregate_input_bytes,
            )
            if pre_reason is not None:
                if pre_reason == ExclusionReason.AGGREGATE_BUDGET_EXCEEDED:
                    raise ValueError(f"{ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value}: lexical capture exceeded aggregate file or byte budget")
                omissions.append(OmissionRecord(b_id, cand.source_relative_path, pre_reason.value, f"artifact {cand.source_relative_path} excluded pre-open: {pre_reason.value}").validate())
                continue
            raw_bytes, open_reason = _read_bounded_regular_file(cand.absolute_path, max_input_bytes=body_policy.max_input_artifact_bytes, private_roots=private_roots)
            if open_reason is not None or raw_bytes is None:
                r_code = (open_reason or ExclusionReason.UNSUPPORTED_SOURCE_FORMAT).value
                omissions.append(OmissionRecord(b_id, cand.source_relative_path, r_code, f"artifact {cand.source_relative_path} rejected on open: {r_code}").validate())
                continue
            if aggregate_input_bytes + len(raw_bytes) > body_policy.max_aggregate_input_bytes:
                raise ValueError(f"{ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value}: lexical capture exceeded aggregate input byte ceiling")
            appended = _append_normalized_document(
                documents=documents, omissions=omissions, raw_bytes=raw_bytes, b_id=b_id,
                rev=rev, snap_id=snap_id, rel_path=cand.source_relative_path,
                art_priv=resolved_b.resolved_binding_privacy, retention=resolved_b.resolved_evidence_retention,
                lexical_policy=lexical_policy, fence=fence,
            )
            if appended is not None:
                aggregate_input_bytes += appended[0]
                aggregate_projected_bytes += appended[1]
                projected_files_count += 1
    doc_digests = tuple(f"{d.binding_id}:{d.source_relative_path}:{d.file_content_sha256}:{len(d.chunks)}" for d in documents)
    omission_digests = tuple(f"{o.binding_id}:{o.source_relative_path or ''}:{o.reason_code}" for o in omissions)
    lexical_generation_id = frame_digest("lexgen1", (
        LEXICAL_REPRESENTATION_VERSION, LEXICAL_TEXT_CONFIG, LEXICAL_RANKING_FUNCTION, str(LEXICAL_NORMALIZATION_FLAGS),
        LEXICAL_ALIAS_SPLIT_VERSION, lexical_policy.policy_digest, str(repository_id), str(fence.run_id),
        fence.publication_bundle_id, fence.snapshot_manifest_id, extraction_receipt_id, graph_candidate_id,
        *doc_digests, *omission_digests,
    ))
    return LexicalCapturePlan(
        lexical_generation_id, repository_id, int(fence.run_id), fence.publication_bundle_id,
        fence.snapshot_manifest_id, extraction_receipt_id, graph_candidate_id, fence.snapshot_vector,
        LEXICAL_REPRESENTATION_VERSION, LEXICAL_TEXT_CONFIG, LEXICAL_RANKING_FUNCTION,
        LEXICAL_NORMALIZATION_FLAGS, LEXICAL_ALIAS_SPLIT_VERSION, lexical_policy.policy_digest,
        lexical_policy.resolved_graph_privacy, lexical_policy.binding_policy_digests,
        lexical_policy.admitted_binding_ids, lexical_policy.excluded_binding_ids,
        tuple(documents), tuple(omissions), aggregate_input_bytes, aggregate_projected_bytes,
        publication_receipt_json=publication_receipt_json,
    )


__all__ = ["LexicalCapturePlan", "LexicalCapturedChunk", "LexicalCapturedDocument", "LexicalFileCandidate", "capture_lexical_generation_plan"]
