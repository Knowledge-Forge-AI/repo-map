"""Ops-layer service entrypoints for PostgreSQL cloe_lexical build, query, and revoke."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path

from common_lore_index.ops.config import load_ops_config
from common_lore_index.ops.config_local import (
    load_graph_registry_config_home,
    local_graph_binding,
)
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.resource_view import ResourceObserver, begin, note_lexical_limits
from common_lore_index.ops.resource_view._lexical_views import (
    finish_lexical_query,
    finish_lexical_revoke,
    note_lexical_query_controls,
    note_lexical_revoke,
)
from common_lore_index.ops.resource_view._projections import finish_lexical
from common_lore_index.ops.lexical_publication import (
    LexicalBuildOutcome,
    build_and_publish_lexical_generation,
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.retrieval.lexical_envelopes import (
    LexicalQueryRequest,
    build_lexical_query_envelope,
    resolve_lexical_query_scope,
)
from common_lore_index.retrieval.lexical_policy import (
    PRODUCTION_MAX_AGGREGATE_INPUT_BYTES,
    PRODUCTION_MAX_CHUNK_BYTES,
    PRODUCTION_MAX_CHUNK_LINES,
    PRODUCTION_MAX_INPUT_ARTIFACT_BYTES,
    PRODUCTION_MAX_PROJECTED_FILE_BYTES,
    PRODUCTION_MAX_PROJECTED_FILES,
    build_lexical_generation_policy,
)
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.query_contracts import QueryEnvelope
from common_lore_index.storage.lexical_driver import (
    DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
    DEFAULT_QUERY_STATEMENT_TIMEOUT_MS,
    LIMITED_LEXICAL_ROLES,
    LexicalConnectionFactory,
    LexicalRoleDeniedError,
    lexical_connection_scope,
    open_psycopg_lexical_connection,
)
from common_lore_index.storage.lexical_query_sql import (
    DEFAULT_MAX_OCCURRENCES_PER_FILE,
    execute_single_statement_lexical_query,
)
from common_lore_index.storage.lexical_revoke import (
    LexicalRevocationOutcome,
    revoke_lexical_generations,
)

_PRIVACY_EXCLUSION_CODES = frozenset(
    {
        ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value,
        ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value,
        ExclusionReason.RETENTION_NOT_AUTHORIZED.value,
        ExclusionReason.EMAIL_BODY_FORBIDDEN.value,
        ExclusionReason.FEED_BODY_FORBIDDEN.value,
        ExclusionReason.UNRESOLVED_INHERIT_POLICY.value,
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _fresh_ops_config(config: OpsConfig) -> OpsConfig:
    """Reload OpsConfig from disk when config_path is set; fail closed on reload error."""
    cfg_path = getattr(config, "config_path", None)
    if cfg_path is None:
        return config
    p = Path(cfg_path)
    if p.is_dir():
        reloaded = load_graph_registry_config_home(p)
        if not isinstance(reloaded, OpsConfig):
            raise ValueError("postgres-home-required: lexical commands require PostgreSQL OpsConfig")
        return reloaded
    if p.is_file():
        if p.name == "config.toml" and (p.parent / "graphs.toml").is_file():
            reloaded = load_graph_registry_config_home(p.parent)
            if not isinstance(reloaded, OpsConfig):
                raise ValueError("postgres-home-required: lexical commands require PostgreSQL OpsConfig")
            return reloaded
        return load_ops_config(p)
    raise ValueError(f"configured config_path does not exist: {p}")


def build_graph_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    *,
    connection_factory: LexicalConnectionFactory = open_psycopg_lexical_connection,
    private_roots: Sequence[Path] = (),
    selected_binding_ids: Sequence[str] | None = None,
    authorize_body: bool = False,
    portable_store_root: Path | str | None = None,
    max_projected_files: int = PRODUCTION_MAX_PROJECTED_FILES,
    max_aggregate_input_bytes: int = PRODUCTION_MAX_AGGREGATE_INPUT_BYTES,
    max_input_artifact_bytes: int = PRODUCTION_MAX_INPUT_ARTIFACT_BYTES,
    max_projected_file_bytes: int = PRODUCTION_MAX_PROJECTED_FILE_BYTES,
    max_chunk_lines: int = PRODUCTION_MAX_CHUNK_LINES,
    max_chunk_bytes: int = PRODUCTION_MAX_CHUNK_BYTES,
    resource_observer: ResourceObserver | None = None,
) -> LexicalBuildOutcome:
    """Build and publish a cloe_lexical generation for a configured PostgreSQL graph."""
    begin(resource_observer, "lexical_build", "postgresql")
    note_lexical_limits(
        resource_observer, max_projected_files=max_projected_files,
        max_aggregate_input_bytes=max_aggregate_input_bytes,
        max_input_artifact_bytes=max_input_artifact_bytes,
        max_projected_file_bytes=max_projected_file_bytes,
        max_chunk_lines=max_chunk_lines, max_chunk_bytes=max_chunk_bytes,
        statement_timeout_ms=DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
    )
    live_config = _fresh_ops_config(config)
    return finish_lexical(resource_observer, build_and_publish_lexical_generation(
        live_config,
        graph_id,
        connection_factory=connection_factory,
        private_roots=private_roots,
        selected_binding_ids=selected_binding_ids,
        authorize_body=authorize_body,
        portable_store_root=portable_store_root,
        recheck_config_fn=lambda: _fresh_ops_config(config),
        max_projected_files=max_projected_files,
        max_aggregate_input_bytes=max_aggregate_input_bytes,
        max_input_artifact_bytes=max_input_artifact_bytes,
        max_projected_file_bytes=max_projected_file_bytes,
        max_chunk_lines=max_chunk_lines,
        max_chunk_bytes=max_chunk_bytes,
    ))


def query_graph_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    request: LexicalQueryRequest,
    *,
    authorize_body: bool = False,
    connection_factory: LexicalConnectionFactory = open_psycopg_lexical_connection,
    publication_bundle_id: str | None = None,
    snapshot_manifest_id: str | None = None,
    max_occurrences_per_file: int = DEFAULT_MAX_OCCURRENCES_PER_FILE,
    statement_timeout_ms: int = DEFAULT_QUERY_STATEMENT_TIMEOUT_MS,
    resource_observer: ResourceObserver | None = None,
) -> QueryEnvelope:
    """Execute a single-statement fenced lexical query and return a validated QueryEnvelope.

    With an observer, only the returned service envelope is projected (never a
    CLI presentation); no SQL, source read or query/hit copy is added.
    """
    if resource_observer is not None:
        begin(resource_observer, "lexical_query", "postgresql")
        note_lexical_query_controls(
            resource_observer, limit=getattr(request, "limit", None),
            max_occurrences_per_file=max_occurrences_per_file,
            statement_timeout_ms=statement_timeout_ms,
        )
    envelope, immediate = _query_graph_lexical_generation(
        config, graph_id, request, authorize_body=authorize_body,
        connection_factory=connection_factory, publication_bundle_id=publication_bundle_id,
        snapshot_manifest_id=snapshot_manifest_id,
        max_occurrences_per_file=max_occurrences_per_file,
        statement_timeout_ms=statement_timeout_ms,
    )
    return envelope if resource_observer is None else finish_lexical_query(
        resource_observer, envelope, immediate=immediate,
    )


def _query_graph_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    request: LexicalQueryRequest,
    *,
    authorize_body: bool,
    connection_factory: LexicalConnectionFactory,
    publication_bundle_id: str | None,
    snapshot_manifest_id: str | None,
    max_occurrences_per_file: int,
    statement_timeout_ms: int,
) -> tuple[QueryEnvelope, bool]:
    if not authorize_body:
        raise ValueError("body-authorization-required: authorize_body=True is required to query cloe_lexical")
    request.validate()
    live_config = _fresh_ops_config(config)
    graph = resolve_ops_graph(live_config, graph_id)
    params = lexical_connection_parameters(
        live_config,
        graph,
        statement_timeout_ms=statement_timeout_ms,
        read_only=True,
    )
    if params.user in LIMITED_LEXICAL_ROLES:
        raise LexicalRoleDeniedError(
            f"limited PostgreSQL role {params.user!r} is forbidden from accessing cloe_lexical"
        )
    lexical_policy = build_lexical_generation_policy(graph)
    resolution = resolve_lexical_query_scope(
        graph_id=graph.id,
        lexical_policy=lexical_policy,
        request=request,
        publication_bundle_id=publication_bundle_id,
        snapshot_manifest_id=snapshot_manifest_id,
    )
    if resolution.immediate_envelope is not None:
        return resolution.immediate_envelope, True

    repo_identity = local_graph_binding(graph).repository_identity
    expected_binding_digests_json = _canonical_json(
        dict(sorted(lexical_policy.binding_policy_digests.items()))
    )
    privacy_excluded = {
        b_id: r_code
        for b_id, r_code in sorted(lexical_policy.excluded_binding_reasons.items())
        if r_code in _PRIVACY_EXCLUSION_CODES
    }
    privacy_excluded_json = _canonical_json(privacy_excluded)

    with lexical_connection_scope(
        params, connection_factory=connection_factory, read_only=True
    ) as conn:
        raw_row = execute_single_statement_lexical_query(
            conn,
            repository_identity=repo_identity,
            repository_name=graph.repository_name,
            root_path=f"graph:{graph.id}",
            expected_policy_digest=lexical_policy.policy_digest,
            expected_binding_policy_digests_json=expected_binding_digests_json,
            privacy_excluded_bindings_json=privacy_excluded_json,
            admitted_binding_ids=resolution.admitted_binding_ids,
            omission_binding_ids=resolution.omission_binding_ids,
            path_prefixes=request.effective_path_prefixes(),
            query_style=request.query_style,
            query_text=request.query,
            limit=request.limit,
            offset=request.offset,
            max_occurrences_per_file=max_occurrences_per_file,
        )
        conn.rollback()

    return build_lexical_query_envelope(
        resolution=resolution,
        lexical_policy=lexical_policy,
        request=request,
        raw_row=raw_row,
    ), False


def revoke_graph_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    *,
    reason: str = "operator_revoked",
    purge_rows: bool = True,
    dry_run: bool = False,
    confirmed: bool = True,
    connection_factory: LexicalConnectionFactory = open_psycopg_lexical_connection,
    resource_observer: ResourceObserver | None = None,
) -> LexicalRevocationOutcome:
    """Revoke active cloe_lexical generations and purge derived body rows for a graph.

    With an observer, only returned aggregate effects after completion are
    projected; confirmation, transaction, purge and dry-run behavior is unchanged.
    """
    if resource_observer is not None:
        begin(resource_observer, "lexical_revoke", "postgresql")
        note_lexical_revoke(
            resource_observer, dry_run=dry_run,
            statement_timeout_ms=DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
        )
    outcome = _revoke_graph_lexical_generation(
        config, graph_id, reason=reason, purge_rows=purge_rows, dry_run=dry_run,
        confirmed=confirmed, connection_factory=connection_factory,
    )
    return outcome if resource_observer is None else finish_lexical_revoke(resource_observer, outcome)


def _revoke_graph_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    *,
    reason: str,
    purge_rows: bool,
    dry_run: bool,
    confirmed: bool,
    connection_factory: LexicalConnectionFactory,
) -> LexicalRevocationOutcome:
    if not dry_run and not confirmed:
        raise ValueError("revoke-confirmation-required: pass dry_run=True or confirmed=True")
    if dry_run and confirmed:
        raise ValueError("revoke-conflicting-flags: cannot set both dry_run=True and confirmed=True")
    live_config = _fresh_ops_config(config)
    graph = resolve_ops_graph(live_config, graph_id)
    params = lexical_connection_parameters(
        live_config,
        graph,
        statement_timeout_ms=DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
        read_only=dry_run,
    )
    repo_identity = local_graph_binding(graph).repository_identity
    with lexical_connection_scope(
        params, connection_factory=connection_factory, read_only=dry_run
    ) as conn:
        summary = revoke_lexical_generations(
            conn,
            repository_identity=repo_identity,
            repository_name=graph.repository_name,
            root_path=f"graph:{graph.id}",
            reason=reason,
            purge_rows=purge_rows and not dry_run,
            dry_run=dry_run,
        )
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    return replace(summary, graph_id=graph.id)


__all__ = [
    "LexicalBuildOutcome",
    "LexicalRevocationOutcome",
    "build_graph_lexical_generation",
    "query_graph_lexical_generation",
    "revoke_graph_lexical_generation",
]
