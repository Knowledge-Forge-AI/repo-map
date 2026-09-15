"""Shared value models and literal entry constructors for FIX1 catalog."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TypeAlias


Scalar: TypeAlias = bool | int | str | tuple[str, ...]
ParameterTuple: TypeAlias = tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One literal semantic case declared before any observation."""

    semantic_group: str
    condition_id: str
    case_id: str
    authority_id: str
    product_owner_id: str
    product_entrypoint: str
    evidence_executor_id: str
    pytest_node_id: str | None
    fixed_runner_id: str
    fixed_argv_shape: tuple[str, ...]
    operation_kind: str
    parameter_schema: tuple[str, ...]
    parameter_values: ParameterTuple
    expected_contract_category: str
    observation_schema: tuple[str, ...]
    cleanup_contract: str
    process_boundary_contract: str
    validity_rule: str
    repetition_ids: tuple[str, ...] = ("once",)
    shared_executor_contract: str | None = None


_BASE_OBSERVATION = (
    "primary_result_category",
    "secondary_limitations",
    "host_process_count",
    "nested_psql_intent_count",
    "cleanup_disposition",
)
_GROUP_G_OBSERVATION = _BASE_OBSERVATION + ("execution_parameter_digest",)
_OWNER_ROOT = "src/main/python/repomap_kg"
_TOOL_ROOT = "tools"


def _entry(
    group: str,
    condition: str,
    case: str,
    owner: str,
    operation: str,
    parameters: ParameterTuple,
    expected: str,
    *,
    executor: str | None = None,
    observation: tuple[str, ...] = _BASE_OBSERVATION,
    cleanup: str = "none",
    process: str = "no_host_child",
    validity: str = "all_observed_fields_required",
    repetitions: tuple[str, ...] = ("once",),
    fixed_argv_shape: tuple[str, ...] | None = None,
    pytest_node_id: str | None = None,
) -> CatalogEntry:
    executor_id = executor or f"fix1.executor.{group.lower()}"
    owner_digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]
    return CatalogEntry(
        semantic_group=group,
        condition_id=condition,
        case_id=case,
        authority_id=f"fix1.authority.{group.lower()}.{case.lower()}",
        product_owner_id=f"fix1.owner.{owner_digest}",
        product_entrypoint=owner,
        evidence_executor_id=executor_id,
        pytest_node_id=pytest_node_id,
        fixed_runner_id=f"{executor_id}.runner",
        fixed_argv_shape=fixed_argv_shape
        or ("in-process", executor_id, case),
        operation_kind=operation,
        parameter_schema=tuple(name for name, _ in parameters),
        parameter_values=parameters,
        expected_contract_category=expected,
        observation_schema=observation,
        cleanup_contract=cleanup,
        process_boundary_contract=process,
        validity_rule=validity,
        repetition_ids=repetitions,
    )


def _numbered_group(
    group: str,
    prefix: str,
    count: int,
    owner: str,
    operation: str,
    expected: str,
    *,
    condition_modulus: int,
) -> tuple[CatalogEntry, ...]:
    return tuple(
        _entry(
            group,
            f"{prefix}-condition-{index % condition_modulus:02d}",
            f"{prefix}-{index:04d}",
            owner,
            operation,
            (("schedule_index", index), ("condition_slot", index % condition_modulus)),
            expected,
        )
        for index in range(1, count + 1)
    )


REQUIRED_MANIFEST_GROUPS = tuple(
    [chr(value) for value in range(ord("A"), ord("K") + 1)]
    + ["PARENT_SETTLEMENT", "COMPLETE_GATE", "FOCUSED_SELECTION"]
)
