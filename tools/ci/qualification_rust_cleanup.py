"""Private cleanup adapter for preserving native qualification evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ci.qualification_rust_accounting import AccountingGap
from ci.qualification_rust_runtime import RuntimeGap
from common_lore_index.extractors.contracts.vocabulary import ContractError


class CleanupController(Protocol):
    def close(self) -> None:
        ...

    def audit_snapshot(self) -> object:
        ...


def close_native_controller(controller: CleanupController,
                            original: RuntimeGap | None) -> None:
    """Close without hiding a structured native refusal or cleanup audit."""
    try:
        controller.close()
        return
    except Exception as error:
        cleanup: dict[str, Any] = {
            "cleanup_incomplete": True,
            "qualified": False,
            "cleanup_error": error.code if isinstance(error, ContractError) else "cleanup_exception",
        }
    try:
        audit = controller.audit_snapshot()
    except Exception:
        audit = None
    if isinstance(audit, Mapping):
        cleanup["cleanup_audit"] = dict(audit)
    if original is None:
        raise RuntimeGap("cleanup_incomplete", cleanup) from None
    evidence = dict(original.evidence)
    evidence.update(cleanup)
    raise RuntimeGap(original.code, evidence) from None


def native_failure(controller: CleanupController, error: Exception,
                   audited: Mapping[str, Any] | None, preflights: Mapping[str, Any],
                   containment: Mapping[str, Any]) -> RuntimeGap:
    """Preserve closed primary evidence before any cleanup adapter can fail."""

    evidence = dict(error.evidence) if isinstance(error, (RuntimeGap, AccountingGap)) else {}
    code = error.code if isinstance(error, (RuntimeGap, ContractError, AccountingGap)) else "bounded_operation_failed"
    evidence["primary_category"] = ("runtime_gap" if isinstance(error, RuntimeGap) else
                                    "contract_error" if isinstance(error, ContractError) else
                                    "accounting_gap" if isinstance(error, AccountingGap) else "unexpected_exception")
    try:
        current = controller.audit_snapshot()
    except Exception:
        current = None
    if isinstance(current, Mapping):
        evidence["audit"] = dict(current)
    if isinstance(audited, Mapping):
        evidence["costs"], evidence["counters"] = audited.get("costs"), audited.get("counters")
        evidence["counter_scope"] = "source_controller_only"
    evidence["preflights"], evidence["containment"] = dict(preflights), dict(containment)
    return RuntimeGap(code, evidence)
