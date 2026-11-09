"""Independent, public-safe witnesses from call returns, never resource reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from first_use_workload_domains import MAX_COUNTER


@dataclass(frozen=True)
class ReturnedPublication:
    outcome: str
    generation: int | None


def _generation(value: object) -> int:
    if type(value) is not int or not 0 < value <= MAX_COUNTER:
        raise AssertionError("first-use-refresh-return-invalid")
    return value


def local_cli_publication(payload: Mapping[str, Any]) -> ReturnedPublication:
    if payload.get("result") != "success" or payload.get("storage_backend") != "sqlite":
        raise AssertionError("first-use-refresh-return-invalid")
    return ReturnedPublication("published", _generation(payload.get("accepted_generation")))


def local_inprocess_publication(result: Any) -> ReturnedPublication:
    if type(result.reconciled) is not bool:
        raise AssertionError("first-use-refresh-return-invalid")
    outcome = "reconciled_replay" if result.reconciled else "published"
    return ReturnedPublication(outcome, _generation(result.generation))


def server_publication(result: Any) -> ReturnedPublication:
    if (result.result, result.error_category, result.publication_state) != (
        "success", None, "committed",
    ):
        raise AssertionError("first-use-refresh-return-invalid")
    # This existing Server result exposes commit state, not a generation.
    return ReturnedPublication(result.publication_state, None)


def revocation_result(count: object) -> str | None:
    if type(count) is not int or not 0 <= count <= MAX_COUNTER:
        raise AssertionError("first-use-revoke-return-invalid")
    return "revoked" if count else None


__all__ = [
    "ReturnedPublication", "local_cli_publication", "local_inprocess_publication",
    "revocation_result", "server_publication",
]
