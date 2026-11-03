"""Mechanical execution gate, separate from calibration relevance or ANN speed."""

from __future__ import annotations

from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_experiment_contracts import ExperimentRefusal


def require_admitted_vector_execution(
    *,
    exact: ExecutionState,
    hybrid: ExecutionState,
    hnsw: ExecutionState,
    lexical: ExecutionState,
) -> None:
    """Require actual execution for a supported, admitted public query.

    SeqScan may leave native HNSW NOT_RUN. Relevance may be poor and lexical
    applicability may be unavailable; neither is rewritten into a success.
    """
    if exact != ExecutionState.COMPLETED:
        raise ExperimentRefusal("admitted_exact_query_not_executed")
    if lexical == ExecutionState.COMPLETED and hybrid != ExecutionState.COMPLETED:
        raise ExperimentRefusal("admitted_hybrid_query_not_executed")
    if lexical == ExecutionState.FAILED or hybrid == ExecutionState.FAILED:
        raise ExperimentRefusal("calibration_execution_failed")
    if hnsw not in (ExecutionState.COMPLETED, ExecutionState.NOT_RUN):
        raise ExperimentRefusal("admitted_hnsw_execution_failed")
