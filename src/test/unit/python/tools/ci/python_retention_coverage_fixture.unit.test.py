"""Literal coverage declarations prove source and collector ownership statically."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ci.python_retention_dependencies import build_dependency_graph
from ci.python_retention_dynamic import apply_dynamic_boundaries
from ci.python_retention_dynamic_coverage import CASES, CAPABILITY_CASES
from ci.python_retention_dynamic_history import SCHEMA
from ci.python_retention_cohort_evidence import evaluate_cohorts

OWNER = "src/test/unit/python/tools/coverage_json_export.unit.test.py"
REPO = Path(__file__).resolve().parents[6]
TARGETS = {"runner_coverage": "", "runner_coverage_reports": "",
           "test_report": "def write_html_report(): pass\n", "runner_coverage_execution": ""}


def setup(root: Path, source: str | None = None) -> tuple[list[str], list[dict]]:
    owner = root / OWNER
    owner.parent.mkdir(parents=True)
    owner.write_text(source if source is not None else (REPO / OWNER).read_text())
    paths = [OWNER]
    for module, content in TARGETS.items():
        path = root / "src/main/python" / (module + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        paths.append(path.relative_to(root).as_posix())
    graph = build_dependency_graph(root, paths)
    records = []
    digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()
    for case, spec in CASES.items():
        ops = [op for op in graph["dynamic_operations"][OWNER] if op["symbol"] == spec["symbol"]]
        chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
        for index, op in enumerate(ops):
            targets = [dict(module=m, symbol="write_html_report" if m == "test_report" else "",
                            path=f"src/main/python/{m}.py", sha256=digest(f"src/main/python/{m}.py"))
                       for m in ("runner_coverage", "runner_coverage_reports", "test_report")
                       if m != "test_report" or case == "uncovered_branch"]
            records.append(dict(id=f"{case}-{index}", owner=OWNER, test=OWNER,
                                owner_sha256=digest(OWNER), test_sha256=digest(OWNER),
                                recipe="literal_coverage_fixture", supersedes=None, targets=targets,
                                **{k: op[k] for k in ("symbol", "kind", "fingerprint")},
                                parameters={"schema": "literal-coverage-fixture-v1", "case": case,
                                            "temporary_root": "pytest.tmp_path", **spec, "chain": chain}))
    return paths, records


def apply(root: Path, paths: list[str], records: list[dict]) -> dict:
    inventory = root / "tools/ci/python_retention_inventory.json"
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(json.dumps(dict(dynamic_schema=SCHEMA, dynamic_boundaries=records)))
    return apply_dynamic_boundaries(root, paths, build_dependency_graph(root, paths))


def test_actual_literal_coverage_owners_resolve_without_execution(tmp_path: Path) -> None:
    paths, records = setup(tmp_path)
    graph = apply(tmp_path, paths, records)
    assert OWNER not in graph["errors"]
    assert OWNER not in graph["dynamic_uncertainty"]
    assert len(graph["resolved_dynamic_dependencies"]) == 6
    assert "src/main/python/test_report.py" in graph["dependencies"][OWNER]


@pytest.mark.parametrize("before,after", [
    ("return 2", "return 7"),
    ('tmp_path / "sample.py"', 'tmp_path / "foreign.py"'),
    ('source = tmp_path /', 'source = Path("/foreign") /'),
    ('str(source), "exec"', '"wrong.py", "exec"'),
    ('"choose(True)\\n"', '"choose(False)\\n"'),
    ('"exec"), namespace)', '"exec"), {})'),
    ('data_file=None', 'data_file="old.coverage"'),
    ('collector.stop()', 'collector.save()'),
    ('request.addfinalizer(lambda: collector.get_data().close(force=True))', 'pass'),
    ('close(force=True)', 'close(force=False)'),
    ('output = tmp_path / "retained"', 'collector.load()\n    output = tmp_path / "retained"'),
    ('assert 4 in measured["missing_lines"]', 'assert 3 in measured["missing_lines"]'),
    ('staging_obligations=obligations', 'staging_obligations=None'),
    ('assert "Staging evidence: not qualified"', 'assert "Staging evidence: qualified"'),
    ('import coverage', 'import foreign as coverage'),
    ('import coverage', 'import coverage\nfrom foreign import exec'),
    ('import coverage', 'import coverage\ncoverage.Coverage = foreign'),
    ('source.read_text()', 'source.read_text() + "extra()"'),
    ('source.write_text(', 'source.write_bytes('),
    ('namespace: dict[str, object] = {}', 'namespace: dict[str, object] = dict(globals())'),
    ('collector.start()', 'exec("foreign()")\n    collector.start()'),
])
def test_semantic_mutations_fail_after_refreshing_source_and_operations(
    tmp_path: Path, before: str, after: str,
) -> None:
    source = (REPO / OWNER).read_text()
    assert before in source
    # Mutate the declared fixture, not an earlier independent cleanup test.
    prefix, fixture = source.split("def test_raw_coverage_export_preserves_uncovered_branch", 1)
    if before in fixture:
        fixture = fixture.replace(before, after, 1)
    else:
        prefix = prefix.replace(before, after, 1)
    mutated = prefix + "def test_raw_coverage_export_preserves_uncovered_branch" + fixture
    paths, records = setup(tmp_path, mutated)
    graph = apply(tmp_path, paths, records)
    assert OWNER in graph["errors"]
    assert OWNER in graph["dynamic_uncertainty"]


@pytest.mark.parametrize("fault", ["partial", "duplicate", "stale", "target-drift",
                                   "missing-target", "foreign-target", "parameters", "symlink"])
def test_declaration_and_target_fail_closed(tmp_path: Path, fault: str) -> None:
    paths, records = setup(tmp_path)
    if fault == "partial":
        records.pop(0)
    elif fault == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif fault == "stale":
        records[0]["owner_sha256"] = "0" * 64
    elif fault == "target-drift":
        (tmp_path / "src/main/python/runner_coverage.py").write_text("changed = True\n")
    elif fault == "missing-target":
        (tmp_path / "src/main/python/runner_coverage.py").unlink()
        paths.remove("src/main/python/runner_coverage.py")
    elif fault == "foreign-target":
        records[0]["targets"][0]["path"] = "src/main/python/runner_coverage_reports.py"
    elif fault == "parameters":
        records[0]["parameters"]["source_utf8"] = "arbitrary()\n"
    else:
        target = tmp_path / "src/main/python/runner_coverage.py"
        target.unlink()
        target.symlink_to(tmp_path / "src/main/python/runner_coverage_reports.py")
    graph = apply(tmp_path, paths, records)
    assert OWNER in graph["errors"]
    assert OWNER in graph["dynamic_uncertainty"]


def test_generated_source_never_lends_target_governance(tmp_path: Path) -> None:
    paths, records = setup(tmp_path)
    apply(tmp_path, paths, records)
    cohort = dict(id="fixture", root="test_owners", governing_profile="clean_test_owners",
                  members=[OWNER], admission="admitted", rationale="closed literal coverage probe")
    check = dict(status="passed", paths=[OWNER], analyzed_paths=[OWNER], checks={
        name: dict(status="passed", completed=True, findings=[])
        for name in ("ruff", "mypy", "file_length")})
    result = evaluate_cohorts([cohort], {"test_owners": check}, tmp_path, paths, [])
    assert result["regressions"] == ["fixture"]
    governed = evaluate_cohorts([cohort], {"test_owners": check}, tmp_path, paths,
                               [p for p in paths if p != OWNER])
    assert governed["regressions"] == [], governed


CAPABILITY_OWNER = "src/test/unit/python/tools/test_runner_coverage_capability.unit.test.py"
CAPABILITY_TARGETS = {
    "runner_coverage": "",
    "runner_coverage_capability": "",
}


def capability_setup(root: Path, source: str | None = None) -> tuple[list[str], list[dict]]:
    owner = root / CAPABILITY_OWNER
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text(source if source is not None else (REPO / CAPABILITY_OWNER).read_text())
    paths = [CAPABILITY_OWNER]
    for module in CAPABILITY_TARGETS:
        path = root / "tools" / (module + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        src_path = REPO / "tools" / (module + ".py")
        path.write_text(src_path.read_text())
        paths.append(path.relative_to(root).as_posix())
    graph = build_dependency_graph(root, paths)
    records = []
    digest = lambda p: hashlib.sha256((root / p).read_bytes()).hexdigest()
    spec = CAPABILITY_CASES["capability_mod"]
    ops = [op for op in graph["dynamic_operations"].get(CAPABILITY_OWNER, []) if op["symbol"] == spec["symbol"]]
    chain = [{k: op[k] for k in ("kind", "fingerprint")} for op in ops]
    targets = [
        dict(module=m, symbol="", path=f"tools/{m}.py", sha256=digest(f"tools/{m}.py"))
        for m in ("runner_coverage", "runner_coverage_capability")
    ]
    for index, op in enumerate(ops):
        records.append(dict(
            id=f"capability_mod-{index}",
            owner=CAPABILITY_OWNER,
            test=CAPABILITY_OWNER,
            owner_sha256=digest(CAPABILITY_OWNER),
            test_sha256=digest(CAPABILITY_OWNER),
            recipe="literal_coverage_fixture",
            supersedes=None,
            targets=targets,
            symbol=op["symbol"],
            kind=op["kind"],
            fingerprint=op["fingerprint"],
            parameters={
                "schema": "literal-coverage-fixture-v1",
                "case": "capability_mod",
                "symbol": spec["symbol"],
                "filename": spec["filename"],
                "source_utf8": spec["source_utf8"],
                "chain": chain,
            },
        ))
    return paths, records


def test_actual_capability_coverage_owner_resolves_without_execution(tmp_path: Path) -> None:
    paths, records = capability_setup(tmp_path)
    graph = apply(tmp_path, paths, records)
    assert CAPABILITY_OWNER not in graph["errors"]
    assert CAPABILITY_OWNER not in graph["dynamic_uncertainty"]
    assert len(graph["resolved_dynamic_dependencies"]) == 2
    assert "tools/runner_coverage.py" in graph["dependencies"][CAPABILITY_OWNER]
    assert "tools/runner_coverage_capability.py" in graph["dependencies"][CAPABILITY_OWNER]


@pytest.mark.parametrize("before,after", [
    ('sample = self.source_root / "sample.py"', 'sample = self.source_root / "foreign.py"'),
    ('str(sample), "exec"', 'str(self.source_root / "foreign.py"), "exec"'),
    ('sample.read_text(), str(sample)', '"pass", str(sample)'),
    ('exec(compile(sample.read_text(), str(sample), "exec"), {})', 'exec(compile(sample.read_text(), str(sample), "exec"), {"fake": 1})'),
    ('exec(compile(sample.read_text(), str(sample), "exec"), {})', 'exec(compile(sample.read_text(), str(sample), "exec"), dict(globals()))'),
    ('self.assertIs(coverage.Coverage.current(), incoming_collector)',
     'self.assertIsNotNone(coverage.Coverage.current())'),
    ('self.assertIs(caught.exception, failure)', 'self.assertIsNotNone(caught.exception)'),
    ('self.assertEqual(list(self.data_dir.glob(".coverage.valid.*")), [])', 'pass'),
    ('self.assertIn(self._after_sentinel.__code__.co_firstlineno + 2, measured)', 'pass'),
    ('env.pop("COVERAGE_PROCESS_START", None)', 'pass'),
    ('"ChildCoverageCapabilityUnitTests."', '"ForeignTests."'),
    ('real_stop(collector)', 'collector.save()'),
    ('cov.start()', 'cov.stop()'),
    ('finally:\n            cov.stop()', 'finally:\n            cov.save()'),
    ('cov.save()', 'cov.stop()'),
    ('finally:\n            cov.stop()', 'finally:\n            pass'),
    ('cov.start()\n        try:', 'try:\n            cov.start()'),
    ('cov.save()', 'cov.save()\n        exec("pass", {})'),
    ('"def fn():\\n    return 42\\n"', '"def fn():\\n    return 999\\n"'),
])
def test_capability_semantic_mutations_fail_after_refreshing_source_and_operations(
    tmp_path: Path, before: str, after: str,
) -> None:
    source = (REPO / CAPABILITY_OWNER).read_text()
    assert before in source
    paths, records = capability_setup(tmp_path, source.replace(before, after, 1))
    graph = apply(tmp_path, paths, records)
    assert CAPABILITY_OWNER in graph["errors"] or CAPABILITY_OWNER in graph["dynamic_uncertainty"]


@pytest.mark.parametrize("fault", ["partial", "duplicate", "stale", "stale-test", "target-substitution",
                                   "target-drift", "missing-target", "parameters-source",
                                   "parameters-filename", "parameters-chain", "forged-target",
                                   "extra-parameter", "missing-chain"])
def test_capability_declaration_and_target_fail_closed(tmp_path: Path, fault: str) -> None:
    paths, records = capability_setup(tmp_path)
    if fault == "partial":
        records.pop(0)
    elif fault == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif fault == "stale":
        records[0]["owner_sha256"] = "0" * 64
    elif fault == "stale-test":
        records[0]["test_sha256"] = "0" * 64
    elif fault == "target-substitution":
        records[0]["targets"][0]["module"] = "test_report"
        records[0]["targets"][0]["path"] = "tools/test_report.py"
    elif fault == "target-drift":
        (tmp_path / "tools/runner_coverage.py").write_text("changed = True\n")
    elif fault == "missing-target":
        (tmp_path / "tools/runner_coverage_capability.py").unlink()
        paths.remove("tools/runner_coverage_capability.py")
    elif fault == "parameters-source":
        records[0]["parameters"]["source_utf8"] = "arbitrary()\n"
    elif fault == "parameters-filename":
        records[0]["parameters"]["filename"] = "wrong.py"
    elif fault == "parameters-chain":
        records[0]["parameters"]["chain"] = []
    elif fault == "forged-target":
        foreign = "tools/foreign.py"
        (tmp_path / foreign).write_text("value = 1\n")
        paths.append(foreign)
        records[0]["targets"][0].update(
            module="foreign", path=foreign,
            sha256=hashlib.sha256((tmp_path / foreign).read_bytes()).hexdigest())
    elif fault == "extra-parameter":
        records[0]["parameters"]["owner"] = CAPABILITY_OWNER
    elif fault == "missing-chain":
        records.clear()
    graph = apply(tmp_path, paths, records)
    assert CAPABILITY_OWNER in graph["errors"] or CAPABILITY_OWNER in graph["dynamic_uncertainty"]
