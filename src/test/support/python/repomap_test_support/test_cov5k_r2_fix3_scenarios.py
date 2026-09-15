from __future__ import annotations

from dataclasses import dataclass

from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix1_catalog_values import ParameterTuple, Scalar


@dataclass(frozen=True, slots=True)
class ScenarioProgram:
    schema: str
    scenario_id: str
    owner_identity: str
    seam_identity: str
    input_action: ParameterTuple
    expected_product_event_classes: tuple[str, ...]
    cleanup_contract: str
    process_boundary_contract: str


def scenario_program(
    *,
    owner_identity: str,
    seam_identity: str,
    input_action: ParameterTuple,
    expected_product_event_classes: tuple[str, ...],
    cleanup_contract: str,
    process_boundary_contract: str,
) -> ScenarioProgram:
    """Freeze a scenario independently of case and display identity."""

    schema = "test-cov5k-r2-fix3-scenario-v1"
    material = {
        "schema": schema,
        "owner_identity": owner_identity,
        "seam_identity": seam_identity,
        "input_action": input_action,
        "expected_product_event_classes": expected_product_event_classes,
        "cleanup_contract": cleanup_contract,
        "process_boundary_contract": process_boundary_contract,
    }
    return ScenarioProgram(
        schema,
        canonical_digest(material),
        owner_identity,
        seam_identity,
        input_action,
        expected_product_event_classes,
        cleanup_contract,
        process_boundary_contract,
    )


def integer_parameter(value: Scalar) -> int:
    if not isinstance(value, (int, str)):
        raise TypeError("integer parameter must be int or str")
    return int(value)
