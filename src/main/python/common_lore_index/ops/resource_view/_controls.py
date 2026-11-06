"""Existing owner controls projected as bounded resource-view rows."""

from __future__ import annotations

from collections.abc import Mapping

from common_lore_index.artifacts._manifest_records import DEFAULT_ARTIFACT_LIMITS

from ._contracts import Enforcement, ResourceLimit, Unit


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _read(source: object, name: str) -> object:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def manifest_limits(*, applies_this_call: bool | None = True) -> tuple[ResourceLimit, ResourceLimit]:
    """Return caps only after a manifest has actually been constructed."""
    return (
        ResourceLimit(
            "manifest_max_artifacts", DEFAULT_ARTIFACT_LIMITS.max_artifacts,
            Unit.COUNT, Enforcement.POST_CAPTURE_VALIDATION, applies_this_call,
        ),
        ResourceLimit(
            "manifest_max_total_bytes", DEFAULT_ARTIFACT_LIMITS.max_total_bytes,
            Unit.BYTES, Enforcement.POST_CAPTURE_VALIDATION, applies_this_call,
        ),
    )


def sealing_io_limit() -> ResourceLimit:
    return ResourceLimit("sealing_io_limit", None, Unit.BYTES, Enforcement.ABSENT, None)


def worker_limits(capability: object, leaf_limits: object) -> tuple[ResourceLimit, ...]:
    """Read the exact controls selected for the worker invocation."""
    deadline = _integer(_read(leaf_limits, "process_deadline_seconds"))
    rows: list[ResourceLimit] = []
    if deadline is not None:
        rows.append(
            ResourceLimit(
                "worker_process_deadline", deadline, Unit.SECONDS,
                Enforcement.PARENT_SUPERVISED, True,
            )
        )
    for name, unit in (
        ("max_artifact_bytes", Unit.BYTES),
        ("max_bundle_bytes", Unit.BYTES),
    ):
        value = _integer(_read(capability, name))
        if value is not None:
            rows.append(
                ResourceLimit(
                    f"worker_{name}", value, unit,
                    Enforcement.DECLARED_TO_WORKER, True,
                )
            )
    return tuple(rows)


def lexical_limits(
    controls: Mapping[str, object] | None,
    *,
    applies_this_call: bool | None = None,
) -> tuple[ResourceLimit, ...]:
    """Project the six generation limits and statement timeout supplied by the owner."""
    if controls is None:
        return ()
    definitions = (
        ("max_projected_files", Unit.COUNT, Enforcement.OWNER_ENFORCED),
        ("max_aggregate_input_bytes", Unit.BYTES, Enforcement.OWNER_ENFORCED),
        ("max_input_artifact_bytes", Unit.BYTES, Enforcement.OWNER_ENFORCED),
        ("max_projected_file_bytes", Unit.BYTES, Enforcement.OWNER_ENFORCED),
        ("max_chunk_lines", Unit.COUNT, Enforcement.OWNER_ENFORCED),
        ("max_chunk_bytes", Unit.BYTES, Enforcement.OWNER_ENFORCED),
        (
            "lexical_build_statement_timeout", Unit.MILLISECONDS,
            Enforcement.DATABASE_STATEMENT_TIMEOUT,
        ),
    )
    rows: list[ResourceLimit] = []
    for name, unit, enforcement in definitions:
        value = _integer(controls.get(name))
        if value is not None:
            rows.append(
                ResourceLimit(name, value, unit, enforcement, applies_this_call)
            )
    return tuple(rows)


def context_limit(
    name: str, value: object, unit: str, *, applies_this_call: bool | None = True
) -> ResourceLimit | None:
    """Build one context limit, omitting malformed owner values."""
    checked = _integer(value)
    if checked is None:
        return None
    return ResourceLimit(name, checked, unit, Enforcement.OWNER_ENFORCED, applies_this_call)


__all__ = (
    "context_limit", "lexical_limits", "manifest_limits", "sealing_io_limit",
    "worker_limits",
)
