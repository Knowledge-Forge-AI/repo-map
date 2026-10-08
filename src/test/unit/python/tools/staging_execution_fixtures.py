from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace


import go_runner_coverage
import runner_integration_execution as execution
from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
from test_report import CoverageFileRecord, CoverageSummary, TestRecord as _TestRecord
from test_report import GoCoverageSummary


M_NODE = "src/test/int/python/pkg/synthetic.int.test.py::test_measured"
A_NODES = tuple(declaration.nodeid for declaration in MAINTAINED_ABRUPT_DECLARATIONS)
INVOCATION = "e" * 32
IDENTITY = {"commit": "c" * 40, "source_sha256": "d" * 64}


@dataclass
class FakeSession:
    cleaned: bool = False
    session_dir: Path = Path("/tmp/fake-session")
    bootstrap_dir: Path = Path("/tmp/fake-bootstrap")

    def cleanup(self) -> None:
        self.cleaned = True


class FakeAbruptContext:
    def __init__(self, *, nodeids, invocation_id, source_sha256, verify_source):
        self.nodeids = tuple(nodeids)
        self.invocation_id = invocation_id
        self.source_sha256 = source_sha256
        self.verify_source = verify_source
        self.records: dict[str, dict[str, object]] = {}
        self.selected: list[str] = []

    def select_test(self, nodeid: str) -> None:
        self.selected.append(nodeid)

    @contextmanager
    def bind_session(self, session):
        yield self


class FakeLegPlugin:
    instances: list["FakeLegPlugin"] = []

    def __init__(self, partition, leg, *, suite, full_population):
        self.partition = partition
        self.leg = leg
        self.test_records: tuple[_TestRecord, ...] = ()
        self.executed_nodeids: list[str] = []
        self.completed_nodeids: list[str] = []
        self.teardown_failed = False
        self.abrupt_context = None
        type(self).instances.append(self)


def _summary() -> CoverageSummary:
    return CoverageSummary(
        suite_name="int",
        line_hard_threshold=80.0,
        branch_hard_threshold=80.0,
        line_warn_threshold=85.0,
        branch_warn_threshold=85.0,
        total_lines=100,
        covered_lines=100,
        line_percent=100.0,
        total_branches=100,
        covered_branches=100,
        branch_percent=100.0,
        files=(
            CoverageFileRecord(
                path=Path("src/main/python/repomap_kg/synthetic.py"),
                executable_lines=100,
                covered_lines=100,
                line_percent=100.0,
                total_branches=100,
                covered_branches=100,
                branch_percent=100.0,
            ),
        ),
    )


def _go_summary() -> GoCoverageSummary:
    return GoCoverageSummary(
        suite_name="int",
        hard_threshold=80.0,
        total_statements=100,
        covered_statements=100,
        statement_percent=100.0,
        branch_status="N/A",
        diagnostic_category="passed",
    )


def _args(tmp_path: Path, *, no_coverage: bool = False, report: bool = False):
    return SimpleNamespace(
        suite="int",
        no_coverage=no_coverage,
        report=report,
        report_dir=tmp_path / "reports",
    )


def _install_fakes(monkeypatch, *, collection_exit=0, failure_leg=None,
                   incomplete_leg=None, interrupt_leg=None, teardown_leg=None,
                   source_values=None, go_tmp=None, report=False):
    FakeLegPlugin.instances = []
    run_order: list[str] = []
    coverage_env: list[tuple[str, str | None]] = []
    sessions: list[FakeSession] = []
    raw = (M_NODE, *A_NODES)

    def fake_run(_pytest_module, _pytest_args, plugin):
        run_order.append(plugin.leg)
        nodes = plugin.partition.m_nodes if plugin.leg == "M" else plugin.partition.a_nodes
        status = "failed" if plugin.leg == failure_leg else "passed"
        plugin.test_records = tuple(
            _TestRecord(node, node.split("::", 1)[0], status, 0.01, "assertion" if status == "failed" else "")
            for node in nodes
        )
        plugin.executed_nodeids.extend(nodes)
        plugin.completed_nodeids.extend(nodes)
        if plugin.leg == teardown_leg:
            plugin.teardown_failed = True
        if plugin.leg == "A" and plugin.abrupt_context is not None:
            _populate_roles(plugin.abrupt_context, nodes)
        if plugin.leg == interrupt_leg:
            raise KeyboardInterrupt("synthetic interruption")
        return 1 if status == "failed" else 0

    def fake_coverage_run(_coverage, _pytest_module, _pytest_args, plugin, **_kwargs):
        coverage_env.append((plugin.leg, os.environ.get("GOCOVERDIR")))
        if plugin.leg == incomplete_leg:
            code = fake_run(_pytest_module, _pytest_args, plugin)
            return code, SimpleNamespace(_instrumentation_error=RuntimeError("missing shard"))
        return fake_run(_pytest_module, _pytest_args, plugin), SimpleNamespace()

    class Session(FakeSession):
        def __init__(self, **_kwargs):
            index = len(sessions)
            super().__init__(
                session_dir=Path(f"/tmp/fake-session-{index}"),
                bootstrap_dir=Path(f"/tmp/fake-bootstrap-{index}"),
            )
            sessions.append(self)

    monkeypatch.setattr(execution, "candidate_identity", lambda _root: IDENTITY.copy())
    monkeypatch.setattr(execution, "uuid4", lambda: SimpleNamespace(hex=INVOCATION))
    monkeypatch.setattr(execution, "LegPartitionPytestPlugin", FakeLegPlugin)
    monkeypatch.setattr(execution, "AbruptRunnerContext", FakeAbruptContext)
    monkeypatch.setattr(execution, "ChildCoverageSession", Session)
    monkeypatch.setattr(execution, "coverage_diagnostics", lambda _session: ())
    monkeypatch.setattr(
        go_runner_coverage,
        "evaluate_go_integration_gate",
        lambda *_: (_go_summary(), True),
    )
    if source_values is not None:
        values = iter(source_values)
        monkeypatch.setattr(execution, "candidate_identity", lambda _root: next(values))
    if go_tmp is not None:
        monkeypatch.setattr(
            "repomap_test_support.test_scratch.establish_run",
            lambda: SimpleNamespace(go_tmp=go_tmp),
        )

    def fake_discovery(_args, _pytest_args, **_kwargs):
        run_order.append("collect")
        if collection_exit != 0:
            raise RuntimeError("population collection did not complete")
        from runner_integration_population import partition_population
        return partition_population(
            raw,
            suite=_args.suite,
            scoped=False,
            deferred_nodes=(),
            collected_nodes=raw,
        )

    def environment(_suites, _args):
        return null_context()

    return run_order, coverage_env, sessions, fake_run, fake_coverage_run, environment, fake_discovery


@contextmanager
def null_context():
    yield


def _populate_roles(context: FakeAbruptContext, nodes: tuple[str, ...]) -> None:
    declarations = {item.nodeid: item for item in MAINTAINED_ABRUPT_DECLARATIONS}
    for index, node in enumerate(nodes):
        declaration = declarations[node]
        context.records[node] = {
            "nodeid": node,
            "role": declaration.role,
            "invocation_id": context.invocation_id,
            "source_sha256": context.source_sha256,
            "launch_id": f"launch-{index}",
            "pid": 1000 + index,
            "parent_pid": 900,
            "started_ns": 1,
            "checkpoint": declaration.checkpoint,
            "returncode": declaration.expected_returncode,
            "settled_ns": 2,
            "cleanup": True,
            "measurement": "unavailable",
        }


def _execute(monkeypatch, tmp_path: Path, *, no_coverage=False, report=False, staging=False, coverage_summary=None, report_writer=None, **kwargs):
    if "go_tmp" not in kwargs:
        kwargs["go_tmp"] = tmp_path / "go"
        kwargs["go_tmp"].mkdir()
    run_order, coverage_env, sessions, fake_run, fake_cov, environment, fake_discovery = _install_fakes(
        monkeypatch, report=report, **kwargs
    )
    args = _args(tmp_path, no_coverage=no_coverage, report=report)
    if staging:
        args.suite = "staging"
    result = execution.execute_staging_decision_b(
        args,
        ("int",),
        [],
        source_root=tmp_path,
        test_support_root=tmp_path,
        repo_root=tmp_path,
        pytest_module=SimpleNamespace(),
        pytest_args=[],
        pytest_environment_for_fn=environment,
        run_pytest_fn=fake_run,
        import_coverage_fn=lambda: object(),
        run_pytest_with_coverage_fn=fake_cov,
        coverage_policy=None,
        collect_coverage_summary_fn=lambda *_args, **_kwargs: coverage_summary or _summary(),
        report_coverage_fn=lambda _coverage: True,
        write_html_report_fn=report_writer or (lambda **_kwargs: tmp_path / "index.html"),
        forwarded_selection_args_fn=lambda _args: (),
        discovery_fn=fake_discovery,
    )
    path = args.report_dir / args.suite / "latest" / "staging_contract_report.json"
    return result, path, run_order, coverage_env, sessions
