"""Literal evaluator path scopes, preserving a caller's directory-only suffix."""
from __future__ import annotations

from dataclasses import dataclass

from common_lore_index.retrieval.lexical_policy import normalize_lexical_path_prefix


@dataclass(frozen=True, slots=True)
class EvaluationPathPrefix:
    raw: str
    canonical: str
    descendants_only: bool

    def matches(self, relative_path: str) -> bool:
        return relative_path.startswith(self.canonical + "/") or (
            not self.descendants_only and relative_path == self.canonical
        )


def evaluation_path_prefix(value: str | None) -> EvaluationPathPrefix | None:
    """Admit canonical segments or exactly one trailing directory separator."""
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("evaluation source prefix must be text")
    canonical = normalize_lexical_path_prefix(value)
    if value not in (canonical, canonical + "/"):
        raise ValueError("evaluation source prefix must preserve literal segments")
    return EvaluationPathPrefix(value, canonical, value.endswith("/"))


def source_path_matches_prefix(relative_path: str, prefix: str | None) -> bool:
    scope = evaluation_path_prefix(prefix)
    return scope is None or scope.matches(relative_path)
