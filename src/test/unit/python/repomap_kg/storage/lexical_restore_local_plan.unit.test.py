"""Unit contracts for LocalRuntimePlan lexical restore reconciliation."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from common_lore_index.runtime._lexical_restore import (
    reconcile_restored_graph_lexical_roles,
)
from common_lore_index.runtime.local import setup_local_runtime
from common_lore_index.runtime.plan import LocalRuntimePlan, build_local_runtime_plan


def _local_plan(tmp_path: Path) -> LocalRuntimePlan:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    return build_local_runtime_plan(home)


def _unused_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
    pytest.fail("forwarding-only unit test unexpectedly executed command transport")


def test_local_plan_refuses_three_positional_reconciler_before_callback_body(
    tmp_path: Path,
) -> None:
    plan = _local_plan(tmp_path)
    database = plan.graph_databases[0]
    called: list[tuple[object, ...]] = []

    def unsupported(plan_arg: object, database_arg: str, runner_arg: object) -> None:
        called.append((plan_arg, database_arg, runner_arg))

    with pytest.raises(TypeError, match="purge_restored_lexical"):
        reconcile_restored_graph_lexical_roles(
            plan,
            database,
            _unused_runner,
            unsupported,
        )

    assert called == []


def test_local_plan_does_not_inspect_mock_side_effect_to_skip_purge(
    tmp_path: Path,
) -> None:
    plan = _local_plan(tmp_path)
    database = plan.graph_databases[0]
    called: list[tuple[object, ...]] = []

    def unsupported(plan_arg: object, database_arg: str, runner_arg: object) -> None:
        called.append((plan_arg, database_arg, runner_arg))

    reconciler = Mock(side_effect=unsupported)
    with pytest.raises(TypeError, match="purge_restored_lexical"):
        reconcile_restored_graph_lexical_roles(
            plan,
            database,
            _unused_runner,
            reconciler,
        )

    assert called == []
    assert reconciler.call_args is not None
    assert reconciler.call_args.kwargs["purge_restored_lexical"] is True


def test_local_plan_rejects_unsupported_callable_wrapper_without_fallback(
    tmp_path: Path,
) -> None:
    plan = _local_plan(tmp_path)
    database = plan.graph_databases[0]
    called: list[tuple[object, ...]] = []

    class UnsupportedWrapper:
        def __call__(self, plan_arg: object, database_arg: str, runner_arg: object) -> None:
            called.append((plan_arg, database_arg, runner_arg))

    with pytest.raises(TypeError, match="purge_restored_lexical"):
        reconcile_restored_graph_lexical_roles(
            plan,
            database,
            _unused_runner,
            UnsupportedWrapper(),
        )

    assert called == []


@pytest.mark.parametrize("purge_restored_rows", [True, False])
def test_local_plan_forwards_exact_purge_value(
    tmp_path: Path,
    purge_restored_rows: bool,
) -> None:
    plan = _local_plan(tmp_path)
    database = plan.graph_databases[0]
    received: list[bool] = []

    def reconciler(
        _plan: object,
        _database: str,
        _runner: object,
        *,
        purge_restored_lexical: bool,
    ) -> None:
        received.append(purge_restored_lexical)

    reconcile_restored_graph_lexical_roles(
        plan,
        database,
        _unused_runner,
        reconciler,
        purge_restored_rows=purge_restored_rows,
    )

    assert received == [purge_restored_rows]
