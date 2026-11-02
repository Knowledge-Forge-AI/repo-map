"""Fixture-bound native W4 comparator over actual public source bytes."""

from __future__ import annotations

from collections.abc import Sequence

from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    MatchSurface,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    QUERY_CONTRACT_VERSION,
    unavailable_envelope,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_context_catalog import ContextEvaluationTask
from retrieval_evaluation_context_manifest import (
    ContextNativeView,
    materialize_context_native_view,
    validate_context_native_identity,
    validate_materialized_context_native_view,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_native import (
    build_git_grep_argv,
    parse_git_grep_z_output,
    probe_git_version,
    resolve_git_executable,
    run_git_grep_process,
)


def _failed_native_result(
    *,
    requested_mode: QueryMode,
    scope: QueryScope,
    reason: str,
    view: ContextNativeView,
    elapsed_ns: int,
    stdout_bytes: int = 0,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    envelope = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=requested_mode,
        effective_mode=requested_mode,
        match_surface=MatchSurface.NONE,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.FAILED,
        scope_complete=False,
        provenance={
            "adapter_id": "native_context_fixture",
            "backend": "native_filesystem",
            "failure_reason": reason,
            "source_manifest_sha256": view.manifest_sha256,
        },
    ).validate()
    return ExecutionState.FAILED, envelope, elapsed_ns, ByteLayerAccounting(stdout_bytes)


def execute_context_native_task(
    task: ContextEvaluationTask,
    view: ContextNativeView,
    *,
    graph_id: str,
    selected_binding_ids: Sequence[str],
    git_executable: str | None = None,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    """Run real bounded Git grep; never substitutes graph navigation or identity."""
    requested_mode = QueryMode.LITERAL_CAPTURED_TEXT
    trusted_graph_id = view.identity.get("graph_id")
    trusted_binding_ids = tuple(
        sorted({binding_id for binding_id, _ in view.path_to_binding.values()})
    )
    if not isinstance(trusted_graph_id, str) or not trusted_graph_id:
        trusted_graph_id = graph_id
    scope = QueryScope(
        graph_id=trusted_graph_id,
        backend="native_filesystem",
        selected_binding_ids=trusted_binding_ids,
    )
    provenance = {
        "adapter_id": "native_context_fixture",
        "backend": "native_filesystem",
        "source_manifest_sha256": view.manifest_sha256,
        "canonical_identity_claimed": False,
    }
    try:
        validate_materialized_context_native_view(view)
    except (OSError, TypeError, ValueError):
        return _failed_native_result(
            requested_mode=requested_mode,
            scope=scope,
            reason="native_manifest_mismatch",
            view=view,
            elapsed_ns=0,
        )
    if graph_id != trusted_graph_id or set(selected_binding_ids) != set(trusted_binding_ids):
        return _failed_native_result(
            requested_mode=requested_mode,
            scope=scope,
            reason="native_identity_selection_mismatch",
            view=view,
            elapsed_ns=0,
        )
    if task.expand_depth > 0 or task.mode == "graph_investigation":
        return (
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="native_filesystem_has_no_typed_graph_relationships",
                provenance=provenance,
            ),
            0,
            ByteLayerAccounting(0),
        )
    if not isinstance(task.query, str) or not task.query:
        return _failed_native_result(
            requested_mode=requested_mode,
            scope=scope,
            reason="native_query_missing",
            view=view,
            elapsed_ns=0,
        )

    executable = git_executable or resolve_git_executable()
    argv = build_git_grep_argv(
        task.query,
        view.selected_relative_paths,
        git_executable=executable,
        fixed_strings=True,
        ignore_case=False,
    )
    result = run_git_grep_process(argv, cwd=view.view_root)
    if result.status.startswith("failed"):
        return _failed_native_result(
            requested_mode=requested_mode,
            scope=scope,
            reason=result.status,
            view=view,
            elapsed_ns=result.elapsed_ns,
            stdout_bytes=len(result.stdout_bytes),
        )
    try:
        locators = parse_git_grep_z_output(
            result.stdout_bytes, path_to_binding=view.path_to_binding
        )
    except (UnicodeError, ValueError):
        return _failed_native_result(
            requested_mode=requested_mode,
            scope=scope,
            reason="malformed_native_output",
            view=view,
            elapsed_ns=result.elapsed_ns,
            stdout_bytes=len(result.stdout_bytes),
        )
    unique = {loc.identity_key(): loc for loc in locators}
    ordered = sorted(unique.values(), key=lambda loc: loc.identity_key())
    hits = tuple(
        QueryHit(locator=loc, match_surface=MatchSurface.CAPTURED_TEXT, rank=index)
        for index, loc in enumerate(ordered, start=1)
    )
    envelope = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=requested_mode,
        effective_mode=requested_mode,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=hits,
        scope_complete=True,
        provenance={**provenance, "git_version": probe_git_version(executable)},
    ).validate()
    return (
        ExecutionState.COMPLETED,
        envelope,
        result.elapsed_ns,
        ByteLayerAccounting(len(result.stdout_bytes)),
    )


__all__ = [
    "ContextNativeView",
    "execute_context_native_task",
    "materialize_context_native_view",
    "validate_context_native_identity",
    "validate_materialized_context_native_view",
]
