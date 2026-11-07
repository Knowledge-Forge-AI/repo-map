"""Orchestration for building and publishing a PostgreSQL cloe_lexical generation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import Any
import uuid

from common_lore_index.artifacts import (
    FileSystemArtifactStore,
    PortableSnapshotManifest,
    PublicationExpectation,
    PublisherBundleValidator,
)
from common_lore_index.coordinator._portable_semantic_adapter import (
    WORKER_CAPABILITY_IDENTITY,
)
from common_lore_index.ops._portable_retention import (
    _retained_manifest_reference,
    _retained_result,
)
from common_lore_index.ops.config_local import local_graph_binding
from common_lore_index.ops.config_records import OpsConfig, OpsGraphConfig
from common_lore_index.ops.portable_refresh import portable_attempts_parent
from common_lore_index.retrieval.lexical_capture import (
    LexicalCapturePlan,
    capture_lexical_generation_plan,
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
from common_lore_index.retrieval.query_contracts import OmissionRecord
from common_lore_index.runtime.database_role_contract import (
    read_configured_postgres_password,
)
from common_lore_index.runtime.postgres_route import execution_postgres
from common_lore_index.storage.lexical_driver import (
    DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
    DEFAULT_QUERY_STATEMENT_TIMEOUT_MS,
    LexicalConnectionFactory,
    LexicalConnectionParameters,
    LexicalStorageError,
    lexical_connection_scope,
    open_psycopg_lexical_connection,
)
from common_lore_index.storage.lexical_build_lease import cleanup_owned_lexical_generation
from common_lore_index.storage.lexical_lifecycle import (
    AcceptedGraphPublicationRecord,
    PublishedLexicalGeneration,
    publish_lexical_generation,
    read_accepted_graph_publication,
)
from common_lore_index.storage.lexical_probe import (
    LexicalCapabilityReport,
    probe_lexical_runtime,
)


def _load_retained_portable_capture(
    config: OpsConfig,
    graph: OpsGraphConfig,
    accepted_pub: AcceptedGraphPublicationRecord,
    *,
    portable_store_root: Path | str | None = None,
) -> tuple[PortableSnapshotManifest, FileSystemArtifactStore]:
    receipt = accepted_pub.receipt
    if receipt is None or receipt.portable is None:
        raise LexicalStorageError(
            "cloe_lexical_retained_artifacts_unavailable",
            "accepted publication is missing full portable receipt",
        )
    portable = receipt.portable
    token = hashlib.sha256(
        f"{receipt.attempt.job_id}\0{receipt.attempt.attempt}".encode("utf-8")
    ).hexdigest()
    attempts_dir = (
        Path(portable_store_root)
        if portable_store_root is not None
        else portable_attempts_parent(config, None)
    )
    attempt_root = attempts_dir / token
    result_path = attempt_root / "portable-result.json"
    try:
        refs = _retained_result(result_path, portable.snapshot_manifest_id)
        if refs is None:
            raise LookupError("retained portable-result.json not found")
        receipt_ref, bundle_ref = (
            refs[0].with_store_version(None),
            refs[1].with_store_version(None),
        )
        store = FileSystemArtifactStore(attempt_root / "objects")
        manifest_ref = _retained_manifest_reference(result_path, portable.snapshot_manifest_id)
        if manifest_ref is None:
            raise LookupError("retained manifest reference missing from portable-result.json")
        manifest = PortableSnapshotManifest.from_bytes(
            store.read(manifest_ref.with_store_version(None))
        )
        expectation = PublicationExpectation(
            request_id=receipt.attempt.job_id,
            job_id=receipt.attempt.job_id,
            attempt=receipt.attempt.attempt,
            graph_id=graph.id,
            candidate_id=portable.candidate_id,
            snapshot_manifest_id=manifest.manifest_id,
            snapshot_vector=manifest.snapshot_vector,
            source_generation=manifest.source_generation,
            config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            extractor_capability_identity=manifest.extractor_capability_identity,
            resolver_identity=manifest.resolver_identity,
            canonicalizer_identity=manifest.canonicalizer_identity,
            semantic_contract_identity=manifest.semantic_contract_identity,
            quality_rule_identity=manifest.quality_rule_identity,
            mutating_owner_count=1,
            worker_capability_identity=WORKER_CAPABILITY_IDENTITY,
            expected_privacy=manifest.effective_privacy.value,
        )
        validated = PublisherBundleValidator().validate_bundle_stream(
            store=store,
            bundle_reference=bundle_ref,
            receipt_reference=receipt_ref,
            expectation=expectation,
            stage_id=portable.stage_id,
            spool_dir=attempt_root / "workspace",
        )
        validated.close()
        return manifest, store
    except Exception as error:
        raise LexicalStorageError(
            "cloe_lexical_retained_artifacts_unavailable",
            f"failed to load or validate retained portable artifacts for graph {graph.id!r}",
        ) from error


@dataclass(frozen=True)
class LexicalBuildOutcome:
    """Result of a cloe ops lexical-build execution."""

    graph_id: str
    database: str
    result: str
    refusal_code: str | None
    published: PublishedLexicalGeneration | None
    probe: LexicalCapabilityReport | None
    policy_digest: str
    admitted_binding_ids: tuple[str, ...]
    excluded_binding_ids: tuple[str, ...]
    omissions: tuple[OmissionRecord, ...]
    aggregate_input_bytes: int
    aggregate_projected_bytes: int
    plan: LexicalCapturePlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "lexical-build",
            "storage_backend": "postgresql",
            "graph_id": self.graph_id,
            "database": self.database,
            "result": self.result,
            "refusal_code": self.refusal_code,
            "policy_digest": self.policy_digest,
            "admitted_binding_ids": list(self.admitted_binding_ids),
            "excluded_binding_ids": list(self.excluded_binding_ids),
            "aggregate_input_bytes": self.aggregate_input_bytes,
            "aggregate_projected_bytes": self.aggregate_projected_bytes,
            "omissions": [om.to_dict() for om in self.omissions],
            "published": self.published.to_dict() if self.published is not None else None,
            "capabilities": self.probe.to_dict() if self.probe is not None else None,
        }


def resolve_ops_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    """Locate a configured graph by id or raise ValueError."""
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise ValueError(f"unknown graph_id: {graph_id!r}")


def lexical_connection_parameters(
    config: OpsConfig,
    graph: OpsGraphConfig,
    *,
    statement_timeout_ms: int = DEFAULT_QUERY_STATEMENT_TIMEOUT_MS,
    read_only: bool = False,
) -> LexicalConnectionParameters:
    """Resolve owner PostgreSQL connection parameters for cloe_lexical."""
    routed_pg = execution_postgres(config)
    database = graph.database or routed_pg.database
    password = read_configured_postgres_password(config)
    user = routed_pg.user
    return LexicalConnectionParameters(
        host=routed_pg.host,
        port=routed_pg.port,
        database=database,
        user=user,
        password=password,
        statement_timeout_ms=statement_timeout_ms,
        read_only=read_only,
    )


def build_and_publish_lexical_generation(
    config: OpsConfig,
    graph_id: str,
    *,
    connection_factory: LexicalConnectionFactory = open_psycopg_lexical_connection,
    private_roots: Sequence[Path] = (),
    selected_binding_ids: Sequence[str] | None = None,
    authorize_body: bool = False,
    portable_store_root: Path | str | None = None,
    recheck_config_fn: Callable[[], OpsConfig] | None = None,
    max_projected_files: int = PRODUCTION_MAX_PROJECTED_FILES,
    max_aggregate_input_bytes: int = PRODUCTION_MAX_AGGREGATE_INPUT_BYTES,
    max_input_artifact_bytes: int = PRODUCTION_MAX_INPUT_ARTIFACT_BYTES,
    max_projected_file_bytes: int = PRODUCTION_MAX_PROJECTED_FILE_BYTES,
    max_chunk_lines: int = PRODUCTION_MAX_CHUNK_LINES,
    max_chunk_bytes: int = PRODUCTION_MAX_CHUNK_BYTES,
) -> LexicalBuildOutcome:
    """Probe capabilities, capture public-dev files, and publish a cloe_lexical generation."""
    if not authorize_body:
        raise ValueError("body-authorization-required: authorize_body=True is required to build cloe_lexical")
    clean_selected = tuple(
        b.strip() for b in (selected_binding_ids or ()) if isinstance(b, str) and b.strip()
    )
    if not clean_selected:
        raise ValueError("binding-selection-required: selected_binding_ids must be non-empty")
    graph = resolve_ops_graph(config, graph_id)
    params = lexical_connection_parameters(
        config,
        graph,
        statement_timeout_ms=DEFAULT_BUILD_STATEMENT_TIMEOUT_MS,
        read_only=False,
    )
    lexical_policy = build_lexical_generation_policy(
        graph,
        selected_binding_ids=clean_selected,
        max_projected_files=max_projected_files,
        max_aggregate_input_bytes=max_aggregate_input_bytes,
        max_input_artifact_bytes=max_input_artifact_bytes,
        max_projected_file_bytes=max_projected_file_bytes,
        max_chunk_lines=max_chunk_lines,
        max_chunk_bytes=max_chunk_bytes,
    )
    def _refused(
        ref_code: str,
        *,
        omissions: tuple[OmissionRecord, ...] = (),
        probe_res: LexicalCapabilityReport | None = None,
    ) -> LexicalBuildOutcome:
        return LexicalBuildOutcome(
            graph_id=graph.id, database=params.database, result="refused",
            refusal_code=ref_code, published=None, probe=probe_res,
            policy_digest=lexical_policy.policy_digest, admitted_binding_ids=(),
            excluded_binding_ids=lexical_policy.excluded_binding_ids, omissions=omissions,
            aggregate_input_bytes=0, aggregate_projected_bytes=0,
        )

    if lexical_policy.resolved_graph_privacy != "public-dev":
        return _refused(ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value)
    if not lexical_policy.admitted_binding_ids:
        reasons = [
            lexical_policy.excluded_binding_reasons[b_id]
            for b_id in clean_selected
            if b_id in lexical_policy.excluded_binding_reasons
        ] or list(lexical_policy.excluded_binding_reasons.values())
        ref_code = reasons[0] if reasons else ExclusionReason.BINDING_NOT_SELECTED.value
        omissions = tuple(
            OmissionRecord(b_id, None, r_code, f"binding {b_id} excluded from lexical build ({r_code})").validate()
            for b_id, r_code in sorted(lexical_policy.excluded_binding_reasons.items())
        )
        return _refused(ref_code, omissions=omissions)

    repo_identity = local_graph_binding(graph).repository_identity
    builder_owner_id = f"builder:{uuid.uuid4().hex}"
    plan: LexicalCapturePlan | None = None
    try:
        with lexical_connection_scope(params, connection_factory=connection_factory) as conn:
            probe = probe_lexical_runtime(conn).require_ready()
            accepted_pub = read_accepted_graph_publication(
                conn, repository_identity=repo_identity,
                repository_name=graph.repository_name, root_path=f"graph:{graph.id}",
            )
            if accepted_pub is None:
                raise LexicalStorageError(
                    "cloe_lexical_no_accepted_publication",
                    f"graph {graph.id!r} has no accepted portable graph publication",
                )
            manifest, store = _load_retained_portable_capture(
                config, graph, accepted_pub, portable_store_root=portable_store_root
            )
            try:
                plan = capture_lexical_generation_plan(
                    graph=graph, lexical_policy=lexical_policy,
                    fence=accepted_pub.to_publication_fence(),
                    repository_id=accepted_pub.repository_id,
                    extraction_receipt_id=accepted_pub.extraction_receipt_id,
                    graph_candidate_id=accepted_pub.graph_candidate_id,
                    private_roots=private_roots, manifest=manifest, store=store,
                    publication_receipt_json=accepted_pub.publication_receipt_json,
                )
            except ValueError as error:
                if ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value in str(error):
                    return _refused(ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value, probe_res=probe)
                raise
            plan = replace(
                plan,
                lexical_generation_id=(
                    "lexgen1:"
                    + hashlib.sha256(
                        f"{plan.lexical_generation_id}\0{builder_owner_id}".encode("utf-8")
                    ).hexdigest()
                ),
            )

            def _recheck_live_policy_digest() -> str:
                latest_cfg = recheck_config_fn() if recheck_config_fn is not None else config
                latest_graph = resolve_ops_graph(latest_cfg, graph_id)
                return build_lexical_generation_policy(
                    latest_graph,
                    selected_binding_ids=clean_selected,
                    max_projected_files=max_projected_files,
                    max_aggregate_input_bytes=max_aggregate_input_bytes,
                    max_input_artifact_bytes=max_input_artifact_bytes,
                    max_projected_file_bytes=max_projected_file_bytes,
                    max_chunk_lines=max_chunk_lines,
                    max_chunk_bytes=max_chunk_bytes,
                ).policy_digest

            published = publish_lexical_generation(
                conn,
                plan,
                builder_owner_id=builder_owner_id,
                live_policy_recheck=_recheck_live_policy_digest,
            )
            conn.commit()
    except Exception:
        if plan is not None:
            try:
                with lexical_connection_scope(params, connection_factory=connection_factory) as clean_conn:
                    cleanup_owned_lexical_generation(
                        clean_conn,
                        repository_id=plan.repository_id,
                        lexical_generation_id=plan.lexical_generation_id,
                        builder_owner_id=builder_owner_id,
                    )
            except Exception as cleanup_error:
                raise LexicalStorageError(
                    "cloe_lexical_cleanup_failed",
                    "lexical build failed and owned-generation cleanup also failed",
                ) from cleanup_error
        raise
    return LexicalBuildOutcome(
        graph_id=graph.id,
        database=params.database,
        result="published",
        refusal_code=None,
        published=published,
        probe=probe,
        policy_digest=lexical_policy.policy_digest,
        admitted_binding_ids=lexical_policy.admitted_binding_ids,
        excluded_binding_ids=lexical_policy.excluded_binding_ids,
        omissions=plan.omissions,
        aggregate_input_bytes=plan.aggregate_input_bytes,
        aggregate_projected_bytes=plan.aggregate_projected_bytes,
        plan=plan,
    )


__all__ = [
    "LexicalBuildOutcome",
    "build_and_publish_lexical_generation",
    "lexical_connection_parameters",
    "resolve_ops_graph",
]
