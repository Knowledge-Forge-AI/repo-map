"""Bounded W4 fixture preparation shared by scoped evaluators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from repomap_test_support.context_fixture import build_sqlite_context_fixture
from retrieval_evaluation_context_native import (
    ContextNativeView,
    materialize_context_native_view,
)


@dataclass(frozen=True)
class ContextEvaluationPreparation:
    """Actual SQLite fixture identity and its explicit native source view."""

    sqlite_path: Path
    sqlite_adapter: SqliteContextReadAdapter
    graph_id: str
    repository_id: str
    configured_binding_ids: tuple[str, ...]
    accepted_publication: dict[str, Any]
    accepted_identity: dict[str, Any]
    native_view: ContextNativeView

    def input_files(self) -> dict[str, bytes]:
        """Return generated native files for pre-admission input custody."""
        return self.native_view.input_files()


def prepare_context_v1_evaluation(
    fixture_root: Path,
    *,
    graph_id: str = "polyglot-ctx",
    include_private_binding: bool = False,
) -> ContextEvaluationPreparation:
    """Build the real SQLite fixture and materialize only eligible native roots."""
    sqlite_path, _config, graph, _binding, sqlite_adapter = build_sqlite_context_fixture(
        fixture_root,
        graph_id=graph_id,
        include_private_binding=include_private_binding,
    )
    with sqlite_adapter:
        identity = sqlite_adapter.read_initial_identity(WorkLedger(backend="sqlite"))
    if identity.get("status") != "ok":
        raise ValueError("SQLite accepted publication is unavailable for W4 preparation")
    accepted_publication = identity.get("accepted_publication")
    if not isinstance(accepted_publication, dict):
        raise ValueError("SQLite accepted publication is not a mapping")
    accepted_identity = {
        **identity,
        "backend": sqlite_adapter.backend,
    }
    native_view = materialize_context_native_view(
        fixture_root / "native-view",
        bindings=graph.source_bindings,
        accepted_identity=accepted_identity,
    )
    configured_binding_ids = tuple(
        str(binding.binding_id) for binding in graph.source_bindings
    )
    return ContextEvaluationPreparation(
        sqlite_path=sqlite_path,
        sqlite_adapter=sqlite_adapter,
        graph_id=str(graph.id),
        repository_id=str(sqlite_adapter.repository_id),
        configured_binding_ids=configured_binding_ids,
        accepted_publication=dict(accepted_publication),
        accepted_identity=dict(accepted_identity),
        native_view=native_view,
    )


__all__ = ["ContextEvaluationPreparation", "prepare_context_v1_evaluation"]
