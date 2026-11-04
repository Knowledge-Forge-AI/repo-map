"""Public-safe exact-rational projection without file locators."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_pair_artifacts import refuse


def _identity(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise refuse("pair_v2_rational_identity")
    task_id, arm_id, repetition = value.get("task_id"), value.get("arm_id"), value.get("repetition")
    if (
        type(task_id) is not str or not task_id
        or type(arm_id) is not str or not arm_id
        or type(repetition) is not int or repetition < 1
    ):
        raise refuse("pair_v2_rational_identity")
    return {"task_id": task_id, "arm_id": arm_id, "repetition": repetition}


def _measurement(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise refuse("pair_v2_rational_measurement")
    numerator, denominator = value.get("numerator"), value.get("denominator")
    if type(numerator) is not int or type(denominator) is not int or numerator < 0 or denominator < 1:
        raise refuse("pair_v2_rational_measurement")
    result: dict[str, object] = {"numerator": numerator, "denominator": denominator}
    kind = value.get("kind")
    if kind is not None:
        if type(kind) is not str or kind not in {"score", "rrf"}:
            raise refuse("pair_v2_rational_measurement")
        result["kind"] = kind
    for field in ("arm_id",):
        item = value.get(field)
        if item is not None:
            if type(item) is not str or not item:
                raise refuse("pair_v2_rational_measurement")
            result[field] = item
    for field in ("fused_rank", "ordinal_rank"):
        item = value.get(field)
        if item is not None:
            if type(item) is not int or item < 1:
                raise refuse("pair_v2_rational_measurement")
            result[field] = item
    return result


def rational_projection(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if type(value) is not list:
        raise refuse("pair_v2_rational")
    records: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise refuse("pair_v2_rational")
        measurement = _measurement(raw.get("measurement"))
        identity = raw.get("cell_identity")
        source = raw.get("source")
        if type(source) is not str:
            raise refuse("pair_v2_rational_source")
        records.append(
            {
                "cell_identity": _identity(identity),
                "source": source if source in {"journal", "result_v2.cell"} else "not_recorded",
                "measurement": measurement,
            }
        )
    return records


__all__ = ["rational_projection"]
