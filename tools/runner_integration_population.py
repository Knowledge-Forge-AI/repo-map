"""Exact collection accounting for measured and abrupt integration legs."""
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from runner_integration_obligations import (
    AbruptDeclaration,
    MAINTAINED_ABRUPT_DECLARATIONS,
    validate_declarations,
)
from runner_unit_environment import RecordingPytestPlugin


class PopulationPartitionError(RuntimeError):
    pass


class EmptyRequiredLegError(PopulationPartitionError):
    pass


class DuplicatePopulationNodeError(PopulationPartitionError):
    pass


def _exact_nodeid(nodeid: object) -> str:
    return str(nodeid)


def _base_nodeid(nodeid: str) -> str:
    if "[" in nodeid and nodeid.endswith("]"):
        return nodeid.split("[", 1)[0]
    return nodeid


def _ordered_unique(label: str, values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(_exact_nodeid(value) for value in values)
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in result:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise DuplicatePopulationNodeError(
            f"{label} contains duplicate node IDs: {tuple(duplicates)!r}"
        )
    return result


@dataclass(frozen=True, slots=True)
class SealedPopulationPartition:
    all_nodes: tuple[str, ...]
    m_nodes: tuple[str, ...]
    a_nodes: tuple[str, ...]
    deferred_nodes: tuple[str, ...]
    collected_nodes: tuple[str, ...]
    suite: str
    is_scoped: bool

    @property
    def total_count(self) -> int:
        return len(self.all_nodes)
    @property
    def m_count(self) -> int:
        return len(self.m_nodes)
    @property
    def a_count(self) -> int:
        return len(self.a_nodes)

    def validate_partition(self) -> None:
        collected = _ordered_unique("collected population", self.collected_nodes)
        deferred = _ordered_unique("deferred population", self.deferred_nodes)
        deferred_set = set(deferred)
        expected_deferred = tuple(node for node in collected if node in deferred_set)
        if deferred != expected_deferred:
            raise PopulationPartitionError("deferred IDs do not preserve collection order")
        eligible = tuple(node for node in collected if node not in deferred_set)
        if self.all_nodes != eligible:
            raise PopulationPartitionError(
                "eligible population does not equal collected population minus "
                "deferred build-profile nodes"
            )
        for label, nodes in (
            ("eligible population", self.all_nodes),
            ("measured leg", self.m_nodes),
            ("abrupt leg", self.a_nodes),
        ):
            _ordered_unique(label, nodes)
        if deferred_set.difference(collected):
            raise PopulationPartitionError("deferred node is absent from collection")
        m_set = set(self.m_nodes)
        a_set = set(self.a_nodes)
        all_set = set(self.all_nodes)
        if overlap := m_set.intersection(a_set):
            raise PopulationPartitionError(
                f"measured and abrupt legs overlap: {tuple(sorted(overlap))!r}"
            )
        if m_set.union(a_set) != all_set:
            raise PopulationPartitionError("measured and abrupt legs are not exhaustive")
        if self.m_nodes != tuple(node for node in self.all_nodes if node in m_set):
            raise PopulationPartitionError("measured IDs do not preserve eligible order")
        if self.a_nodes != tuple(node for node in self.all_nodes if node in a_set):
            raise PopulationPartitionError("abrupt IDs do not preserve eligible order")


def _declaration_nodes(declarations: Sequence[AbruptDeclaration]) -> tuple[str, ...]:
    validate_declarations(declarations)
    return _ordered_unique("abrupt declarations", tuple(d.nodeid for d in declarations))


def partition_population(
    collected_nodeids: Sequence[str],
    *,
    suite: str = "int",
    declarations: Sequence[AbruptDeclaration] = MAINTAINED_ABRUPT_DECLARATIONS,
    scoped: bool = False,
    deferred_nodes: Sequence[str] = (),
    collected_nodes: Sequence[str] | None = None,
) -> SealedPopulationPartition:
    """Seal an exact population into measured and abrupt obligations."""
    supplied = _ordered_unique("eligible or collected population", collected_nodeids)
    deferred = _ordered_unique("deferred population", deferred_nodes)
    if collected_nodes is not None:
        collected = _ordered_unique("raw collected population", collected_nodes)
        deferred_set = set(deferred)
        expected_eligible = tuple(node for node in collected if node not in deferred_set)
        if supplied != expected_eligible:
            raise PopulationPartitionError(
                "eligible node IDs do not match raw collection minus deferred IDs"
            )
    else:
        collected = supplied
    collected_set = set(collected)
    if missing_deferred := tuple(node for node in deferred if node not in collected_set):
        raise PopulationPartitionError(
            f"deferred node IDs are absent from collection: {missing_deferred!r}"
        )
    deferred_set = set(deferred)
    eligible = tuple(node for node in collected if node not in deferred_set)

    declared = _declaration_nodes(declarations)
    declared_set = set(declared)
    declared_bases = {_base_nodeid(node) for node in declared}

    missing = tuple(node for node in declared if node not in set(eligible))
    if missing and not scoped:
        raise PopulationPartitionError(
            f"stale or missing abrupt declarations: {missing!r}"
        )
    unknown_parameter_cases = tuple(
        node
        for node in eligible
        if node not in declared_set and _base_nodeid(node) in declared_bases
    )
    if unknown_parameter_cases:
        raise PopulationPartitionError(
            "unknown or unresolved abrupt parameter cases: "
            f"{unknown_parameter_cases!r}"
        )

    a_nodes = tuple(node for node in eligible if node in declared_set)
    m_nodes = tuple(node for node in eligible if node not in declared_set)
    if not scoped and suite in {"int", "staging"}:
        if not m_nodes:
            raise EmptyRequiredLegError("required measured leg M is empty")
        if not a_nodes:
            raise EmptyRequiredLegError("required abrupt leg A is empty")

    partition = SealedPopulationPartition(
        all_nodes=eligible,
        m_nodes=m_nodes,
        a_nodes=a_nodes,
        deferred_nodes=deferred,
        collected_nodes=collected,
        suite=suite,
        is_scoped=bool(scoped),
    )
    partition.validate_partition()
    return partition


def _selection_violations(config: Any) -> tuple[str, ...]:
    option = getattr(config, "option", config)
    violations: list[str] = []
    for name in (
        "keyword",
        "markexpr",
        "deselect",
        "ignore",
        "ignore_glob",
        "lf",
        "failedfirst",
        "newfirst",
        "sw",
        "stepwise",
        "stepwise_skip",
        "testmon",
    ):
        value = getattr(option, name, None)
        if value not in (None, "", False, (), [], {}):
            violations.append(name)
    invocation = getattr(getattr(config, "invocation_params", None), "args", ()) or ()
    selector_flags = (
        "-k",
        "--keyword",
        "--deselect",
        "--ignore",
        "--ignore-glob",
        "-m",
        "--markexpr",
    )
    for argument in invocation:
        if argument in selector_flags or any(
            argument.startswith(flag + "=") for flag in selector_flags
        ):
            violations.append(str(argument))
    positional = getattr(option, "file_or_dir", ()) or ()
    if isinstance(positional, str):
        positional = (positional,)
    for argument in positional:
        text = str(argument)
        if "::" in text or text.endswith(".py"):
            violations.append(f"file_or_dir:{text}")
    return tuple(dict.fromkeys(violations))


def _require_no_full_gate_selectors(config: Any, *, full_population: bool) -> None:
    if not full_population:
        return
    violations = _selection_violations(config)
    if violations:
        raise PopulationPartitionError(
            "full integration population forbids pytest selectors: "
            f"{violations!r}"
        )


class _PopulationPlugin(RecordingPytestPlugin):
    def __init__(self, *, suite: str, full_population: bool) -> None:
        super().__init__(suite=suite, full_population=full_population)
        self.executed_nodeids: list[str] = []
        self.completed_nodeids: list[str] = []
        self.teardown_completed_nodeids = self.completed_nodeids
        self.teardown_failed = False

    def pytest_runtest_protocol(self, item, nextitem) -> None:
        super().pytest_runtest_protocol(item, nextitem)
        nodeid = _exact_nodeid(item.nodeid)
        if nodeid in self.executed_nodeids:
            raise PopulationPartitionError(f"test executed more than once: {nodeid}")
        self.executed_nodeids.append(nodeid)

    def pytest_runtest_logreport(self, report) -> None:
        super().pytest_runtest_logreport(report)
        if getattr(report, "when", None) != "teardown":
            return
        nodeid = _exact_nodeid(report.nodeid)
        if getattr(report, "failed", False):
            self.teardown_failed = True
        if nodeid in self.completed_nodeids:
            raise PopulationPartitionError(
                f"teardown completion reported more than once: {nodeid}"
            )
        self.completed_nodeids.append(nodeid)


class ItemCollectorPlugin(_PopulationPlugin):
    def __init__(self, *, suite: str = "int", full_population: bool = True) -> None:
        super().__init__(suite=suite, full_population=full_population)
        self.collected_nodeids: tuple[str, ...] = ()
        self.original_collected_nodeids: tuple[str, ...] = ()
        self.eligible_nodeids: tuple[str, ...] = ()
        self.deferred_nodeids: tuple[str, ...] = ()
        self._collection_config: Any = None
        self._collection_modified = False

    def pytest_collection_modifyitems(self, session, config, items) -> None:
        if self._collection_modified:
            raise PopulationPartitionError("collection was modified more than once")
        _require_no_full_gate_selectors(config, full_population=self._full_population)
        raw = _ordered_unique("raw pytest collection", tuple(item.nodeid for item in items))
        self.collected_nodeids = raw
        self.original_collected_nodeids = raw
        self._collection_config = config
        super().pytest_collection_modifyitems(session, config, items)
        eligible = _ordered_unique(
            "eligible pytest collection", tuple(item.nodeid for item in items)
        )
        deferred_set = set(raw).difference(eligible)
        self.deferred_nodeids = tuple(node for node in raw if node in deferred_set)
        self.eligible_nodeids = eligible
        self._collection_modified = True

    def pytest_collection_finish(self, session) -> None:
        if not self._collection_modified:
            raise PopulationPartitionError("collection finish occurred before collection sealing")
        final = _ordered_unique(
            "final pytest collection",
            tuple(item.nodeid for item in getattr(session, "items", ())),
        )
        if final != self.eligible_nodeids:
            raise PopulationPartitionError(
                "pytest collection changed after build-debt sealing: "
                f"expected={self.eligible_nodeids!r}, actual={final!r}"
            )
        _require_no_full_gate_selectors(
            self._collection_config, full_population=self._full_population
        )


class LegPartitionPytestPlugin(_PopulationPlugin):
    def __init__(
        self,
        partition: SealedPopulationPartition,
        leg: str,
        *,
        suite: str | None = None,
        full_population: bool | None = None,
        abrupt_context: Any | None = None,
    ) -> None:
        partition.validate_partition()
        if leg not in {"M", "A"}:
            raise ValueError("leg must be exactly 'M' or 'A'")
        active_suite = partition.suite if suite is None else suite
        if active_suite != partition.suite:
            raise ValueError("leg plugin suite does not match sealed partition")
        expected_full = not partition.is_scoped
        if full_population is not None and bool(full_population) != expected_full:
            raise ValueError("full_population cannot override sealed scope")
        super().__init__(suite=active_suite, full_population=expected_full)
        self.partition = partition
        self.leg = leg
        self.abrupt_context = abrupt_context
        self.target_nodeids = partition.m_nodes if leg == "M" else partition.a_nodes
        self.selected_nodeids: tuple[str, ...] = ()
        self._collection_config: Any = None
        self._collection_modified = False

    def pytest_collection_modifyitems(self, session, config, items) -> None:
        if self._collection_modified:
            raise PopulationPartitionError("collection was modified more than once")
        _require_no_full_gate_selectors(config, full_population=self._full_population)
        raw = _ordered_unique("raw pytest collection", tuple(item.nodeid for item in items))
        if raw != self.partition.collected_nodes:
            raise PopulationPartitionError(
                "raw pytest collection drifted from sealed population: "
                f"expected={self.partition.collected_nodes!r}, actual={raw!r}"
            )
        self._collection_config = config
        super().pytest_collection_modifyitems(session, config, items)
        eligible = _ordered_unique(
            "eligible pytest collection", tuple(item.nodeid for item in items)
        )
        if eligible != self.partition.all_nodes:
            raise PopulationPartitionError(
                "eligible pytest collection drifted from sealed population: "
                f"expected={self.partition.all_nodes!r}, actual={eligible!r}"
            )
        targets = set(self.target_nodeids)
        selected = [item for item in items if _exact_nodeid(item.nodeid) in targets]
        deselected = [item for item in items if _exact_nodeid(item.nodeid) not in targets]
        items[:] = selected
        hook = getattr(getattr(config, "hook", None), "pytest_deselected", None)
        if deselected and hook is not None:
            hook(items=deselected)
        if not selected and not self.partition.is_scoped:
            raise EmptyRequiredLegError(f"required leg {self.leg} is empty")
        self.selected_nodeids = tuple(item.nodeid for item in selected)
        self._collection_modified = True

    def pytest_collection_finish(self, session) -> None:
        if not self._collection_modified:
            raise PopulationPartitionError("collection finish occurred before leg selection")
        final = _ordered_unique(
            "final leg collection",
            tuple(item.nodeid for item in getattr(session, "items", ())),
        )
        if final != self.selected_nodeids:
            raise PopulationPartitionError(
                "pytest collection changed after leg selection: "
                f"expected={self.selected_nodeids!r}, actual={final!r}"
            )

    def pytest_runtest_protocol(self, item, nextitem) -> None:
        super().pytest_runtest_protocol(item, nextitem)
        if self.leg == "A" and self.abrupt_context is not None:
            self.abrupt_context.select_test(item.nodeid)
__all__ = (
    "DuplicatePopulationNodeError",
    "EmptyRequiredLegError",
    "ItemCollectorPlugin",
    "LegPartitionPytestPlugin",
    "PopulationPartitionError",
    "SealedPopulationPartition",
    "partition_population",
)
