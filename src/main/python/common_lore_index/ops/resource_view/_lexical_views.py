"""Lexical query and revoke observer hooks.

Query projects the service envelope it returned, never a CLI presentation.
Revoke projects returned aggregate effect counts after actual completion.
Neither hook issues SQL, reads source bodies or copies query/hit/identity text.
"""

from __future__ import annotations

from collections.abc import Sized
from typing import Any, TypeVar

from ._contracts import Basis, Enforcement, Operation, ResourceLimit, ResourceMetric, Unit, UnavailableReason
from ._observer import ResourceObserver
from ._observer_reporting import _finish_times
from ._slots import OUTCOMES_BY_OPERATION

_Result = TypeVar("_Result")
_QUERY_CONTROLS = (
    ("query_result_limit", Unit.COUNT, Enforcement.OWNER_ENFORCED),
    ("query_max_occurrences_per_file", Unit.COUNT, Enforcement.OWNER_ENFORCED),
    ("lexical_query_statement_timeout", Unit.MILLISECONDS, Enforcement.DATABASE_STATEMENT_TIMEOUT),
)
_QUERY_OUTCOMES = OUTCOMES_BY_OPERATION[Operation.LEXICAL_QUERY.value] - {"not_recorded", "unclassified"}
_REVOKE_EFFECTS = (
    ("revoked_authority_rows", "authority_rows_removed", False),
    ("purged_documents", "purged_document_count", True),
    ("purged_chunks", "purged_chunk_count", True),
    ("purged_omissions", "purged_omission_count", True),
)


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _aggregate(name: str, value: object) -> ResourceMetric:
    checked = _count(value)
    if checked is None:
        return ResourceMetric.unavailable(
            name, Unit.COUNT, Basis.OWNER_AGGREGATE, UnavailableReason.INVALID_OWNER_VALUE,
        )
    return ResourceMetric.measured(name, checked, Unit.COUNT, Basis.OWNER_AGGREGATE)


def _not_selected(name: str) -> ResourceMetric:
    return ResourceMetric.unavailable(
        name, Unit.COUNT, Basis.OWNER_AGGREGATE, UnavailableReason.NOT_SELECTED,
    )


def _guard(observer: object | None, hook: Any, *args: object) -> None:
    if observer is None or type(observer) is not ResourceObserver:
        return
    try:
        hook(observer, *args)
    except Exception:
        observer._degrade()


def _note_query(observer: Any, controls: tuple[object, object, object]) -> None:
    if not observer._active():
        return
    if observer._operation != Operation.LEXICAL_QUERY or "query_noted" in observer._view_facts:
        raise ValueError("lexical query controls are invalid or repeated")
    observer._view_facts["query_noted"] = True
    for (name, unit, enforcement), value in zip(_QUERY_CONTROLS, controls):
        checked = _count(value)
        if checked is not None:
            observer._add_limit(ResourceLimit(name, checked, unit, enforcement, None))


def _finish_query(observer: Any, envelope: object, immediate: bool) -> None:
    if not observer._active():
        return
    if observer._operation != Operation.LEXICAL_QUERY or observer._outcome_recorded:
        raise ValueError("lexical query finish is invalid")
    _finish_times(observer)
    state = getattr(envelope, "capability_state", None)
    state = getattr(state, "value", state)
    # available and not_run stay distinct; available is not a completeness claim.
    observer._outcome = state if isinstance(state, str) and state in _QUERY_OUTCOMES else "unclassified"
    for name, attribute in (("query_hits_returned", "hits"), ("query_omissions_returned", "omissions")):
        returned = getattr(envelope, attribute, None)
        observer._add_metric(_aggregate(name, len(returned) if isinstance(returned, Sized) else None))
    # An immediate envelope proves no statement ran; the SQL path stays unknown.
    applies = False if immediate is True else None
    for name, _, _ in _QUERY_CONTROLS:
        if name in observer._limits:
            observer._replace_limit(name, applies_this_call=applies)
    observer._outcome_recorded = True


def _note_revoke(observer: Any, dry_run: object, statement_timeout_ms: object) -> None:
    if not observer._active():
        return
    if observer._operation != Operation.LEXICAL_REVOKE or "dry_run" in observer._view_facts:
        raise ValueError("lexical revoke mode is invalid or repeated")
    if not isinstance(dry_run, bool):
        raise ValueError("lexical revoke mode is invalid")
    observer._view_facts["dry_run"] = dry_run
    timeout = _count(statement_timeout_ms)
    if timeout is not None:
        # The revoke timeout is the owner's constant, never operator configuration.
        observer._add_limit(ResourceLimit(
            "lexical_revoke_statement_timeout", timeout, Unit.MILLISECONDS,
            Enforcement.DATABASE_STATEMENT_TIMEOUT, None,
        ))


def _finish_revoke(observer: Any, summary: object) -> None:
    if not observer._active():
        return
    if observer._operation != Operation.LEXICAL_REVOKE or observer._outcome_recorded:
        raise ValueError("lexical revoke finish is invalid")
    dry_run = observer._view_facts.get("dry_run")
    if not isinstance(dry_run, bool):
        raise ValueError("lexical revoke mode was not noted")
    _finish_times(observer)
    names = ("revoked_generations",) + tuple(name for name, _, _ in _REVOKE_EFFECTS)
    if dry_run:
        # Preview candidate counts are not measured purges.
        observer._outcome = "preview"
        for name in names:
            observer._add_metric(_not_selected(name))
        observer._outcome_recorded = True
        return
    observer._outcome = "revoked"
    revoked = getattr(summary, "revoked_generation_ids", None)
    observer._add_metric(_aggregate(
        "revoked_generations", len(revoked) if isinstance(revoked, tuple) else None,
    ))
    purge_rows = getattr(summary, "purge_rows", None)
    for name, attribute, purge_only in _REVOKE_EFFECTS:
        if purge_only and purge_rows is False:
            # Literal zeros with purging disabled mean "not selected", not measured work.
            observer._add_metric(_not_selected(name))
        elif purge_only and purge_rows is not True:
            observer._add_metric(_aggregate(name, None))
        else:
            observer._add_metric(_aggregate(name, getattr(summary, attribute, None)))
    observer._outcome_recorded = True


def note_lexical_query_controls(
    observer: object | None, *, limit: object, max_occurrences_per_file: object,
    statement_timeout_ms: object,
) -> None:
    _guard(observer, _note_query, (limit, max_occurrences_per_file, statement_timeout_ms))


def finish_lexical_query(observer: object | None, envelope: _Result, *, immediate: bool) -> _Result:
    _guard(observer, _finish_query, envelope, immediate)
    return envelope


def note_lexical_revoke(
    observer: object | None, *, dry_run: object, statement_timeout_ms: object,
) -> None:
    _guard(observer, _note_revoke, dry_run, statement_timeout_ms)


def finish_lexical_revoke(observer: object | None, summary: _Result) -> _Result:
    _guard(observer, _finish_revoke, summary)
    return summary


__all__ = (
    "finish_lexical_query", "finish_lexical_revoke", "note_lexical_query_controls",
    "note_lexical_revoke",
)
