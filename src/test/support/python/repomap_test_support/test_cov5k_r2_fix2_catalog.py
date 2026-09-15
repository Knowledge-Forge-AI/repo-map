"""Closed typed qualification catalog superseding the FIX1 authority model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias, get_args

from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry as Fix1CatalogEntry, build_closed_catalog as build_fix1_catalog,
)


Scalar: TypeAlias = bool | int | str | tuple[str, ...]
ParameterTuple: TypeAlias = tuple[tuple[str, Scalar], ...]
ExecutorReadiness: TypeAlias = Literal[
    "real_configured_product",
    "deterministic_failure_seam_around_real_owner",
    "real_external_tool",
    "exact_pytest_node",
    "complete_gate_runner",
    "focused_selection_runner",
]


@dataclass(frozen=True, slots=True)
class OwnerBinding:
    """Literal owner and callgraph identity independent of display labels."""

    product_owner_id: str
    source_path: str
    symbol: str
    callgraph_proof: str
    runtime_symbol: str | None = None

    @property
    def registered_runtime_symbol(self) -> str:
        return self.symbol if self.runtime_symbol is None else self.runtime_symbol


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One independently identified, fully executable qualification case."""

    semantic_group: str
    condition_id: str
    case_id: str
    authority_id: str
    owner: OwnerBinding
    evidence_executor_id: str
    executor_source_path: str
    executor_symbol: str
    executor_readiness: ExecutorReadiness
    pytest_node_id: str | None
    fixed_runner_id: str
    fixed_argv_shape: tuple[str, ...]
    operation_kind: str
    parameter_schema: tuple[str, ...]
    parameter_values: ParameterTuple
    expected_contract_category: str
    expected_execution_disposition: str | None
    observation_schema: tuple[str, ...]
    cleanup_contract: str
    process_boundary_contract: str
    validity_rule: str

    @property
    def product_owner_id(self) -> str:
        return self.owner.product_owner_id

    @property
    def product_entrypoint(self) -> str:
        if self.owner.source_path.startswith("tool:"):
            return self.owner.source_path
        return f"{self.owner.source_path}:{self.owner.symbol}"


_OWNER_BINDINGS = {
    "src/main/python/repomap_kg/cli/dispatch.py:dispatch_command": OwnerBinding(
        "repomap.cli.dispatch",
        "src/main/python/repomap_kg/cli/dispatch.py",
        "dispatch_command",
        "subprocess CLI enters dispatch_command before the administrative owner",
    ),
    "tool:psql": OwnerBinding(
        "postgresql.psql",
        "tool:psql",
        "psql",
        "process-boundary recorder observes the exact psql invocation",
    ),
    "src/test/support/python/repomap_test_support/"
    "resource_test_images.py:TestImageManager.build_ephemeral_image": OwnerBinding(
        "repomap.test-image-manager.build-ephemeral",
        "src/test/support/python/repomap_test_support/resource_test_images.py",
        "TestImageManager.build_ephemeral_image",
        "repository-owned managed ephemeral image boundary",
    ),
    "tool:docker:start": OwnerBinding(
        "docker.engine.start", "tool:docker:start", "start", "recorded Docker CLI boundary"
    ),
    "tool:docker:stop": OwnerBinding(
        "docker.engine.stop", "tool:docker:stop", "stop", "recorded Docker CLI boundary"
    ),
    "tool:docker:rm": OwnerBinding(
        "docker.engine.remove", "tool:docker:rm", "rm", "recorded Docker CLI boundary"
    ),
    "tool:docker:stats": OwnerBinding(
        "docker.engine.stats", "tool:docker:stats", "stats", "recorded Docker CLI boundary"
    ),
    "tools/actual_refresh_failure_causality.py:FailureCausalityAuthority": OwnerBinding(
        "scale28.failure-causality",
        "tools/actual_refresh_failure_causality.py",
        "FailureCausalityAuthority",
        "executor records and freezes through FailureCausalityAuthority",
        "FailureCausalityAuthority.record_code",
    ),
    "tools/process_rss_monitor.py:ProcessRssMonitor": OwnerBinding(
        "scale28.process-rss-monitor",
        "tools/process_rss_monitor.py",
        "ProcessRssMonitor",
        "executor constructs ProcessRssMonitor and consumes its run result",
        "ProcessRssMonitor.run",
    ),
    "tools/scale28_preparation_authority.py:HybridPreparationAuthority": OwnerBinding(
        "scale28.hybrid-preparation-authority",
        "tools/scale28_preparation_authority.py",
        "HybridPreparationAuthority",
        "executor enters HybridPreparationAuthority, whose attempt factory constructs PreparationWorkerAttempt",
        "HybridPreparationAuthority.prepare",
    ),
    "tools/run_tests.py:main": OwnerBinding(
        "repomap.test-runner",
        "tools/run_tests.py",
        "main",
        "fixed external runner executes tools/run_tests.py and parses its manifest",
    ),
    "tools/scale14_actual_refresh_supervisor.py:ActualRefreshSupervisor": OwnerBinding(
        "scale14.actual-refresh-supervisor",
        "tools/scale14_actual_refresh_supervisor.py",
        "ActualRefreshSupervisor",
        "configured executor constructs and enters ActualRefreshSupervisor",
    ),
    "tools/scale15_actual_path_readback.py:read_scale15_terminal_state": OwnerBinding(
        "scale15.terminal-state-readback",
        "tools/scale15_actual_path_readback.py",
        "read_scale15_terminal_state",
        "driver executor calls read_scale15_terminal_state through a deterministic I/O seam",
    ),
    "tools/scale15_actual_path_readback.py:read_terminal_backend_summary": OwnerBinding(
        "scale15.backend-summary-readback",
        "tools/scale15_actual_path_readback.py",
        "read_terminal_backend_summary",
        "terminal executor calls read_terminal_backend_summary with its enacted deadline",
    ),
    "tools/scale28_backend_observer_session.py:BackendObserverSession": OwnerBinding(
        "scale28.backend-observer-session",
        "tools/scale28_backend_observer_session.py",
        "BackendObserverSession",
        "observer executor opens, runs, and closes BackendObserverSession",
        "BackendObserverSession.run",
    ),
    "src/test/support/python/repomap_test_support/test_cov5k_r2_fix2_process_recorder.py:ProcessBoundaryRecorder": OwnerBinding(
        "test-cov5k.process-boundary-recorder",
        "src/test/support/python/repomap_test_support/test_cov5k_r2_fix2_process_recorder.py",
        "ProcessBoundaryRecorder",
        "Group H executor enters the exact process-boundary recorder operation",
        "ProcessBoundaryRecorder.run",
    ),
    "tools/scale28_hybrid_startup.py:prepare_parent_startup_authorities": OwnerBinding(
        "scale28.parent-startup-authorities",
        "tools/scale28_hybrid_startup.py",
        "prepare_parent_startup_authorities",
        "configured campaign executor calls prepare_parent_startup_authorities",
    ),
    "tools/scale28_hybrid_startup.py:prepare_startup_resources": OwnerBinding(
        "scale28.startup-resources",
        "tools/scale28_hybrid_startup.py",
        "prepare_startup_resources",
        "configured executor calls prepare_startup_resources and validates its result",
    ),
    "tools/scale28_preparation_worker.py:PreparationWorkerAttempt": OwnerBinding(
        "scale28.preparation-worker-attempt",
        "tools/scale28_preparation_worker.py",
        "PreparationWorkerAttempt",
        "executor constructs PreparationWorkerAttempt and observes run or failure",
    ),
    "tools/scale28_runtime_identity.py:Scale28RuntimeIdentity": OwnerBinding(
        "scale28.runtime-identity-record",
        "tools/scale28_runtime_identity.py",
        "Scale28RuntimeIdentity",
        "runtime executor validates the typed runtime identity record",
    ),
    "tools/scale28_runtime_identity.py:capture_runtime_identity": OwnerBinding(
        "scale28.runtime-identity-capture",
        "tools/scale28_runtime_identity.py",
        "capture_runtime_identity",
        "runtime executor invokes capture_runtime_identity with frozen source commit",
    ),
}


_K_OWNER_OVERRIDE = {
    **{f"K0{index}": "src/main/python/repomap_kg/cli/dispatch.py:dispatch_command" for index in range(1, 6)},
    "K06": "tool:psql",
}

_A_SCENARIO_IDS = {
    "A01": 101,
    "A02": 205,
    "A03": 309,
    "A04": 412,
    "A05": 518,
    "A06": 623,
    "A07": 731,
    "A08": 846,
    "A09": 954,
    "A10": 1067,
}


_EXECUTOR_MODULE = {
    "A": "test_cov5k_r2_fix2_preparation",
    "PARENT_SETTLEMENT": "test_cov5k_r2_fix2_preparation",
    "B": "test_cov5k_r2_fix2_preparation",
    "C": "test_cov5k_r2_fix2_runtime",
    "D": "test_cov5k_r2_fix2_runtime",
    "E": "test_cov5k_r2_fix2_runtime",
    "F": "test_cov5k_r2_fix2_observer",
    "G": "test_cov5k_r2_fix2_observer",
    "H": "test_cov5k_r2_fix2_process_recorder",
    "I": "test_cov5k_r2_fix2_observer",
    "J": "test_cov5k_r2_fix2_observer",
    "K": "test_cov5k_r2_fix2_administrative",
    "COMPLETE_GATE": "test_cov5k_r2_fix2_gate_executor",
    "FOCUSED_SELECTION": "test_cov5k_r2_fix2_gate_executor",
}

_FOCUSED_NODES = (
    "src/test/unit/python/tools/scale18_process_rss.unit.test.py",
    "src/test/unit/python/tools/scale28_backend_observer_lifetime.unit.test.py",
    "src/test/unit/python/tools/scale28_preparation_authority.unit.test.py",
    "src/test/unit/python/tools/scale28_preparation_contracts.unit.test.py",
    "src/test/unit/python/tools/scale15_actual_path_readback.unit.test.py",
    "src/test/unit/python/tools/scale28_r1_runtime_identity.unit.test.py",
    "src/test/unit/python/tools/test_cov4_failure_causality.unit.test.py",
    "src/test/unit/python/tools/scale28_fix12_preparation_campaigns.unit.test.py",
    "src/test/unit/python/repomap_kg/cli/core.unit.test.py",
    "src/test/unit/python/repomap_test_support/test_cov5k_r2_fix2_authority.unit.test.py",
)


def _readiness(entry: Fix1CatalogEntry) -> ExecutorReadiness:
    if entry.pytest_node_id is not None:
        return "exact_pytest_node"
    if entry.semantic_group == "COMPLETE_GATE":
        return "complete_gate_runner"
    if entry.semantic_group == "FOCUSED_SELECTION":
        return "focused_selection_runner"
    if entry.semantic_group == "K":
        return "real_external_tool"
    if entry.semantic_group in {"C", "D", "E"}:
        return "deterministic_failure_seam_around_real_owner"
    return "real_configured_product"


def _owner_key(entry: Fix1CatalogEntry) -> str:
    if entry.semantic_group in {"A", "B", "PARENT_SETTLEMENT"}:
        return "tools/scale28_preparation_authority.py:HybridPreparationAuthority"
    if entry.semantic_group == "H":
        return (
            "src/test/support/python/repomap_test_support/"
            "test_cov5k_r2_fix2_process_recorder.py:ProcessBoundaryRecorder"
        )
    if entry.operation_kind == "runtime_driver_read":
        if dict(entry.parameter_values)["driver"] == "psql":
            return "tool:psql"
    return _K_OWNER_OVERRIDE.get(entry.condition_id, entry.product_entrypoint)


def _expected_disposition(entry: Fix1CatalogEntry) -> str | None:
    if entry.semantic_group != "K":
        return None
    # K01 reaches its disposable dump and completes. K11 now deliberately
    # omits the exact smoke image input, so its build-free runner route refuses
    # during controlled admission rather than constructing an image.
    if entry.condition_id in {"K02", "K03", "K04", "K05", "K11"}:
        return "controlled_preflight_refusal"
    return "completed"


def _parameters(entry: Fix1CatalogEntry) -> ParameterTuple:
    if entry.semantic_group in {"A", "PARENT_SETTLEMENT"}:
        return (("scenario_id", _A_SCENARIO_IDS[entry.condition_id]),)
    if entry.semantic_group == "COMPLETE_GATE":
        return (
            ("suite", "staging"),
            ("environment_class", "capable_isolated_cpython313"),
            ("timeout_seconds", 1800),
        )
    if entry.semantic_group == "FOCUSED_SELECTION":
        index = int(entry.case_id.rsplit("-", 1)[1]) - 1
        return (
            ("pytest_node_id", _FOCUSED_NODES[index]),
            ("environment_class", "capable_isolated_cpython313"),
            ("timeout_seconds", 300),
        )
    return entry.parameter_values


def _executor_module(entry: Fix1CatalogEntry) -> str:
    if entry.pytest_node_id is not None:
        return "test_cov5k_r2_fix2_gate_executor"
    if entry.semantic_group == "F" and entry.operation_kind == "process_containment_companion":
        return "test_cov5k_r2_fix2_runtime"
    return _EXECUTOR_MODULE[entry.semantic_group]


def _executor_symbol(entry: Fix1CatalogEntry) -> str:
    if entry.pytest_node_id is not None:
        return "execute_former_failure_node"
    return f"execute_{entry.operation_kind}"


def build_closed_catalog() -> tuple[CatalogEntry, ...]:
    """Return 1,698 frozen cases with no placeholder or missing executor."""

    entries: list[CatalogEntry] = []
    for ordinal, old in enumerate(build_fix1_catalog(), start=1):
        owner_key = _owner_key(old)
        owner = _OWNER_BINDINGS[owner_key]
        module = _executor_module(old)
        executor_symbol = _executor_symbol(old)
        entries.append(
            CatalogEntry(
                semantic_group=old.semantic_group,
                condition_id=old.condition_id,
                case_id=old.case_id,
                authority_id=f"TEST-COV5K-R2-AUTH-{ordinal:04d}",
                owner=owner,
                evidence_executor_id=f"fix2.{module}.{executor_symbol}",
                executor_source_path=(
                    "src/test/support/python/repomap_test_support/" f"{module}.py"
                ),
                executor_symbol=executor_symbol,
                executor_readiness=_readiness(old),
                pytest_node_id=old.pytest_node_id,
                fixed_runner_id=f"fix2.runner.{ordinal:04d}",
                fixed_argv_shape=old.fixed_argv_shape,
                operation_kind=old.operation_kind,
                parameter_schema=tuple(name for name, _ in _parameters(old)),
                parameter_values=_parameters(old),
                expected_contract_category=old.expected_contract_category,
                expected_execution_disposition=_expected_disposition(old),
                observation_schema=(
                    tuple(
                        "forced_tail_stdout_closed"
                        if field == "descriptor_settled"
                        else field
                        for field in old.observation_schema
                    )
                    + (
                        "raw_worker_outcomes",
                        "raw_worker_categories",
                        "raw_worker_boundaries",
                        "parent_observed_attempt_facts",
                        "child_local_exception_states",
                        "wire_failure_notice_states",
                        "public_projection_facts",
                        "interpreted_evidence_origins",
                        "scenario_injection_intents",
                        "canonical_attempt_outcomes",
                        "canonical_attempt_categories",
                        "scenario_contract_categories",
                        "authority_attempt_failures",
                        "authority_attempt_count",
                        "parent_observed_failure_pair",
                        "retry_observed",
                        "maximum_attempts",
                        "observed_contract_category",
                        "attempt_elapsed_ms",
                        "activation_observed",
                    )
                    if old.semantic_group in {"A", "PARENT_SETTLEMENT"}
                    else old.observation_schema
                ),
                cleanup_contract=old.cleanup_contract,
                process_boundary_contract=old.process_boundary_contract,
                validity_rule=old.validity_rule,
            )
        )
    return tuple(entries)


def entry_by_case(case_id: str) -> CatalogEntry:
    """Resolve one literal display case without deriving authority from it."""

    return next(entry for entry in build_closed_catalog() if entry.case_id == case_id)


ALLOWED_READINESS = frozenset(get_args(ExecutorReadiness))
