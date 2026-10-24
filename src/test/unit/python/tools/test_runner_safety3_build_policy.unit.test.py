from __future__ import annotations

import argparse
import functools
import hashlib
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

import d12_dependency_preflight as preflight
import run_tests
import runner_arguments
import test_sandbox
import repomap_test_support.test_cov5k_r2_fix1_executors as fix1_executors
from repomap_test_support.test_cov5k_r2_fix1_catalog import build_closed_catalog
from repomap_test_support import d12_core_image as d12
from repomap_test_support.build_profile_debt import (
    DEFERRED_BUILD_PROFILE_NODE_IDS,
    enforce_build_profile_authority,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_CURRENT_CANONICAL_COMMAND_DOCS = (
    Path("README.md"),
    Path("docs/contrib/refactor-roadmap.md"),
    Path("docs/contrib/skills/repo-map-testing-standards/SKILL.md"),
    Path("docs/contrib/testing-standards.md"),
    Path("docs/testing/containerized-smoke-test-design.md"),
    Path("docs/testing/test-runner-policy.md"),
)


def _documented_runner_commands(text: str) -> tuple[str, ...]:
    command = "python3 tools/run_tests.py"
    blocks = tuple(block for block in text.split("\n\n") if command in block)
    return tuple(block[block.index(command) :] for block in blocks)


def test_safety3_canonical_staging_applies_closed_build_deselection() -> None:
    plugin = run_tests.RecordingPytestPlugin(suite="staging", full_population=True)
    items = [
        SimpleNamespace(
            nodeid=node_id,
            get_closest_marker=lambda name: object()
            if name == "requires_build_profile"
            else None,
        )
        for node_id in DEFERRED_BUILD_PROFILE_NODE_IDS
    ]
    ordinary = SimpleNamespace(
        nodeid="src/test/int/python/ordinary.int.test.py::test_ordinary",
        get_closest_marker=lambda _name: None,
    )
    items.append(ordinary)
    deselected = []
    config = SimpleNamespace(
        hook=SimpleNamespace(
            pytest_deselected=lambda *, items: deselected.extend(items)
        )
    )

    plugin.pytest_collection_modifyitems(None, config, items)

    assert items == [ordinary]
    assert len(deselected) == len(DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert plugin.deferred_build_count == 12


def test_safety3_deferred_build_debt_is_exact_and_visible() -> None:
    assert len(DEFERRED_BUILD_PROFILE_NODE_IDS) == 12
    assert any(node.endswith("[K07]") for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("scale15" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("scale14_postgres_storage" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("fix1_rehearsal" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)


def test_safety3_direct_build_debt_execution_fails_without_authority(
) -> None:
    with pytest.raises(RuntimeError, match="build-profile authority"):
        enforce_build_profile_authority()


def test_safety3_k07_producer_boundary_refuses_before_creating_dockerfile(
    tmp_path: Path,
) -> None:
    entry = next(
        item for item in build_closed_catalog() if item.condition_id == "K07"
    )
    temporary = tmp_path / "temporary"
    temporary.mkdir()

    with pytest.raises(RuntimeError, match="build-profile authority"):
        fix1_executors.execute_group_k(tmp_path, temporary, entry)

    assert not temporary.joinpath("K07", "Dockerfile").exists()


def test_safety3_ambient_environment_cannot_authorize_build_debt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOMAP_TEST_BUILD_PROFILE_AUTHORIZED", "1")

    with pytest.raises(RuntimeError, match="build-profile authority"):
        enforce_build_profile_authority()


@pytest.mark.parametrize(
    "arguments",
    (
        ["-m", "requires_build_profile"],
        ["-mrequires_build_profile"],
        ["--markexpr", "requires_build_profile"],
        ["--markexpr=requires_build_profile"],
    ),
)
def test_safety3_runner_rejects_forwarded_marker_override(
    arguments: list[str],
) -> None:
    with pytest.raises(RuntimeError, match="canonical marker selection"):
        run_tests.build_pytest_args(("unit", "int"), arguments)


def test_safety3_manifest_paths_are_repository_visible() -> None:
    for node_id in DEFERRED_BUILD_PROFILE_NODE_IDS:
        path = Path(node_id.split("::", 1)[0])
        assert path.is_file(), node_id


def test_safety3_current_canonical_staging_examples_are_executable() -> None:
    for path in _CURRENT_CANONICAL_COMMAND_DOCS:
        document = _REPOSITORY_ROOT / path
        commands = _documented_runner_commands(document.read_text(encoding="utf-8"))
        canonical_staging = tuple(
            command
            for command in commands
            if "--suite staging" in command
        )
        assert canonical_staging, document
        for command in canonical_staging:
            profiles = tuple(
                profile
                for profile in ("heavy", "exhaustive")
                if f"--hygiene-profile {profile}" in command
            )
            assert len(profiles) == 1, document
            assert "--declared-complete-gates 1" in command, document
            assert "--smoke-image-reference" not in command, document


# ADR 0087 D12-A: the one optional owner stays outside this debt and every ordinary population.
_BASE_DEBT_FILE_SHA256 = "673f848528bf7f39eb14d0309e3a19d4591e406cb9bfcb5611213ae584db43be"


class _Item:
    def __init__(self, nodeid, *markers):
        self.nodeid, self.markers = nodeid, set(markers)

    def get_closest_marker(self, name):
        return object() if name in self.markers else None


def _config(*args):
    deselected: list = []
    return SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
                           deselected=deselected, rootpath=_REPOSITORY_ROOT, args=list(args),
                           invocation_params=SimpleNamespace(dir=_REPOSITORY_ROOT))


def _conftest(request):
    return next(p for p in request.config.pluginmanager.get_plugins()
                if str(getattr(p, "__file__", "")).endswith("src/test/conftest.py"))


def test_safety3_d12_optional_owner_is_visibly_deselected_and_required(request, monkeypatch):
    conftest, lines = _conftest(request), list[str]()
    reporter = SimpleNamespace(write_line=lines.append)
    config, optional, other = _config(), _Item(d12.NODE_ID, d12.MARKER), _Item("src/test/int/python/x.int.test.py::t")
    items = [other, optional]
    conftest.pytest_collection_modifyitems(None, config, items)
    assert items == [other] and config.deselected == [optional]
    assert getattr(config, d12.POPULATION_ATTR) == {  # raw IDs rebuild from positions; separate from debt
        "excluded": [{"nodeid": d12.NODE_ID, "raw_index": 1}], "count": 1, "raw_count": 2,
        "reason": d12.DESELECTION_REASON}
    conftest.pytest_terminal_summary(reporter, 0, config)
    assert lines == [f"D12 optional core-image owners deselected: 1 {d12.NODE_ID} ({d12.DESELECTION_REASON})"]
    for root in ("src/test/int/python", "src/test/int/python/repomap_kg/runtime", d12.NODE_FILE):
        conftest.pytest_collection_modifyitems(None, _config(root), [_Item(d12.NODE_ID, d12.MARKER)])
        with pytest.raises(d12.D12ProfileError, match="must collect exactly its one named node"):
            conftest.pytest_collection_modifyitems(None, _config(root), [other])
    quiet = _config("src/test/unit/python", f"{d12.NODE_FILE}::test_other")
    conftest.pytest_collection_modifyitems(None, quiet, [other])
    conftest.pytest_terminal_summary(reporter, 0, quiet)
    assert quiet.deselected == [] and len(lines) == 1
    for items, environ, message in (
        ([_Item("other::t", d12.MARKER)], None, "disagree"), ([_Item(d12.NODE_ID)], None, "disagree"),
        ([_Item(d12.NODE_ID, d12.MARKER, "requires_build_profile")], None, "deferred build debt"),
        ([_Item(d12.NODE_ID, d12.MARKER), other], "linux/arm64", "exactly the one named node"),
        ([other], "linux/arm64", "exactly the one named node"),
        ([_Item(d12.NODE_ID, d12.MARKER)], "linux/s390x", "exactly the one named node"),
    ):
        monkeypatch.delenv(d12.ENV_PROFILE, raising=False)
        if environ:
            monkeypatch.setenv(d12.ENV_PROFILE, environ)
        with pytest.raises(d12.D12ProfileError, match=message):
            conftest.pytest_collection_modifyitems(None, _config(), items)
    monkeypatch.setenv(d12.ENV_PROFILE, "linux/amd64")
    selected = [_Item(d12.NODE_ID, d12.MARKER)]
    profiled = _config("src/test/int/python")
    conftest.pytest_collection_modifyitems(None, profiled, selected)
    assert len(selected) == 1 and getattr(profiled, d12.POPULATION_ATTR)["excluded"] == []


def test_safety3_d12_leaves_old_build_profile_debt_and_refusals_unchanged(request):
    debt_file = _REPOSITORY_ROOT / "src/test/support/python/repomap_test_support/build_profile_debt.py"
    assert hashlib.sha256(debt_file.read_bytes()).hexdigest() == _BASE_DEBT_FILE_SHA256
    assert len(DEFERRED_BUILD_PROFILE_NODE_IDS) == 12 and d12.NODE_ID not in DEFERRED_BUILD_PROFILE_NODE_IDS
    assert d12.MARKER != "requires_build_profile"
    with pytest.raises(RuntimeError, match="TEST-HYGIENE3C remains deferred"):
        enforce_build_profile_authority()
    conftest = _conftest(request)
    with pytest.raises(RuntimeError, match="TEST-HYGIENE3C"):
        conftest.pytest_runtest_setup(_Item(DEFERRED_BUILD_PROFILE_NODE_IDS[0], "requires_build_profile"))
    with pytest.raises(d12.D12ProfileError, match="no runner admission"):
        conftest.pytest_runtest_setup(_Item(d12.NODE_ID, d12.MARKER))
    conftest.pytest_runtest_setup(_Item("plain::t"))


# ADR 0087/0088: the cross-invocation budget is the locked write-ahead ledger, never a process flag.
_HOLD, _SOURCE, _RECIPE = "STOP_PENDING_OPERATOR_DISPOSITION", "a" * 64, "b" * 64


def _budget(path, **overrides):
    data = {"phase": "p", "maximum_total": 2, "maximum_per_platform": 1, "attempts": [], "owned_by": "parent"}
    path.write_text(json.dumps({**data, **overrides}))
    path.chmod(0o600)
    return path


def _entry(attempt, platform="linux/arm64", source=_SOURCE, **extra):
    return {"attempt": attempt, "platform": platform, "source_sha256": source, "recipe_sha256": _RECIPE, **extra}


def test_safety3_d12_budget_reserves_once_then_consumes_that_reservation_once(tmp_path):
    ledger = _budget(tmp_path / "BUILD-BUDGET.json")
    reserved = d12.record_budget(ledger, "append", "linux/arm64", _SOURCE, _RECIPE)
    assert reserved["attempt"] == 1 and len(str(reserved["reservation_id"])) == 32
    consumed = d12.record_budget(ledger, "consume", "linux/arm64", _SOURCE, _RECIPE, consumer="/reports/one")
    assert (consumed["consumed_by"], consumed["reservation_id"]) == ("/reports/one", reserved["reservation_id"])
    d12.record_budget(ledger, "append", "linux/amd64", "c" * 64, _RECIPE)
    data = json.loads(ledger.read_text())
    assert [entry["platform"] for entry in data["attempts"]] == ["linux/arm64", "linux/amd64"]
    assert data["owned_by"] == "parent" and ledger.stat().st_mode & 0o777 == 0o600
    assert [path.name for path in tmp_path.iterdir()] == ["BUILD-BUDGET.json"]  # atomic replace, no residue


@pytest.mark.parametrize("overrides, action, platform, message", [
    ({}, "consume", "linux/arm64", "no unused write-ahead"),  # empty
    ({"maximum_total": 0, "parent_admission_state": _HOLD}, "append", "linux/arm64", f"parent state: {_HOLD}"),
    ({"maximum_total": 0, "parent_admission_state": _HOLD}, "consume", "linux/arm64", f"parent state: {_HOLD}"),
    # A hold state refuses even at the approved bounds; only the parent's written release removes it.
    ({"parent_admission_state": _HOLD}, "append", "linux/arm64",
     f"is held or not at the approved bounds; parent state: {_HOLD}"),
    ({"parent_admission_state": _HOLD, "attempts": [_entry(1)]}, "consume", "linux/arm64", f"parent state: {_HOLD}"),
    ({"maximum_total": 3}, "append", "linux/arm64", "approved bounds"),
    ({"maximum_per_platform": 2}, "append", "linux/arm64", "approved bounds"),
    ({"attempts": [_entry(1, source="0" * 64)]}, "consume", "linux/arm64", "no unused write-ahead"),  # stale
    ({"attempts": [_entry(1, consumed_at="t")]}, "consume", "linux/arm64", "no unused write-ahead"),  # reused
    ({"attempts": [_entry(1)]}, "append", "linux/arm64", "exhausted for linux/arm64"),
    ({"attempts": [_entry(1), _entry(2)]}, "consume", "linux/arm64", "duplicate, foreign or misnumbered"),
    ({"attempts": [_entry(1, "linux/s390x")]}, "append", "linux/amd64", "duplicate, foreign or misnumbered"),
    ({"attempts": [_entry(2)]}, "consume", "linux/arm64", "duplicate, foreign or misnumbered"),
    ({"attempts": [_entry(1), _entry(2, "linux/amd64"), _entry(3, "linux/amd64")]}, "append", "linux/amd64",
     "duplicate, foreign or misnumbered"),
])
def test_safety3_d12_budget_refusals_leave_the_ledger_bytes_unchanged(tmp_path, overrides, action, platform, message):
    ledger = _budget(tmp_path / "BUILD-BUDGET.json", **overrides)
    before = ledger.read_bytes()
    with pytest.raises(d12.D12ProfileError, match=message):
        d12.record_budget(ledger, action, platform, _SOURCE, _RECIPE)
    assert ledger.read_bytes() == before and [path.name for path in tmp_path.iterdir()] == ["BUILD-BUDGET.json"]


def test_safety3_d12_budget_refuses_missing_or_unreadable_ledgers(tmp_path):
    (tmp_path / "torn.json").write_text("{")
    for name in ("absent.json", "torn.json"):
        with pytest.raises(d12.D12ProfileError, match="missing or unreadable"):
            d12.record_budget(tmp_path / name, "consume", "linux/arm64", _SOURCE, _RECIPE)
    with pytest.raises(d12.D12ProfileError, match="exact digests"):
        d12.record_budget(tmp_path / "torn.json", "append", "linux/arm64", "short", _RECIPE)


def test_safety3_d12_budget_races_serialize_to_one_reservation_and_one_consumption(tmp_path):
    ledger = _budget(tmp_path / "BUILD-BUDGET.json")

    def race(action):
        barrier, outcomes = threading.Barrier(8), []

        def contender():
            barrier.wait()
            try:
                d12.record_budget(ledger, action, "linux/arm64", _SOURCE, _RECIPE, consumer=action)
                outcomes.append("admitted")
            except d12.D12ProfileError:
                outcomes.append("refused")
        threads = [threading.Thread(target=contender) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return sorted(outcomes)
    assert race("append") == ["admitted"] + ["refused"] * 7
    assert race("consume") == ["admitted"] + ["refused"] * 7
    attempts = json.loads(ledger.read_text())["attempts"]
    assert len(attempts) == 1 and attempts[0]["consumed_by"] == "consume"


def _docker(host: str, builder: str):  # read-only query doubles; no live Docker in unit tests
    return lambda command, **_: subprocess.CompletedProcess(command, 0, host if command[1] == "version" else builder)


_OFFERED = "Platforms: linux/arm64*, linux/amd64\nBuildKit version: v0.33.1\n"
_MANIFEST: dict[str, object] = {"amd64": {"libpq5": "17.6-1"}, "arm64": {"libpq5": "17.6-1"}}  # synthetic, populated


def test_safety3_d12_preflight_refuses_every_platform_until_the_inner_daemon_is_proved():
    assert preflight.classify("linux/amd64", "arm64", ["linux/arm64"]) == "non_executable"
    assert preflight.classify("linux/amd64", "arm64", ["linux/arm64", "linux/amd64"]) == "emulated"
    # The fresh inner sandbox daemon builds the candidate; a native host or host builder listing is only a forecast.
    for platform, host, forecast in (("linux/arm64", "arm64", "native"), ("linux/amd64", "x86_64", "native"),
                                     ("linux/amd64", "arm64", "emulated")):
        with pytest.raises(d12.D12ProfileError, match="fresh inner build daemon are unproved") as refused:
            preflight.preflight(platform, run=_docker(host, _OFFERED), manifest=_MANIFEST, libpq_version=170010)
        observed = str(refused.value)
        for fact in (f'"host_forecast": "{forecast}"', '"inner_daemon_execution": "unproved"', '"consumed": false'):
            assert fact in observed, observed
    for builder, message in ((_OFFERED.replace(", linux/amd64", ""), "not executable"),
                             ("Platforms: linux/amd64\n", "no BuildKit")):
        with pytest.raises(d12.D12ProfileError, match=message):
            preflight.preflight("linux/amd64", run=_docker("arm64", builder), manifest=_MANIFEST, libpq_version=170010)
    with pytest.raises(d12.D12ProfileError, match="does not cover linux/arm64"):
        preflight.preflight("linux/arm64", run=_docker("arm64", _OFFERED), manifest={}, libpq_version=None)


@pytest.mark.parametrize("platform, host", [("linux/arm64", "aarch64"), ("linux/amd64", "x86_64")])
def test_safety3_d12_facade_refuses_a_native_buildkit_host_before_admission(tmp_path, monkeypatch, platform, host):
    builder = f"Platforms: {platform}*\nBuildKit version: v0.33.1\n"
    monkeypatch.setattr(preflight, "preflight", functools.partial(
        preflight.preflight, run=_docker(host, builder), manifest=_MANIFEST, libpq_version=170010))
    admitted: list[object] = []
    monkeypatch.setattr(d12, "admit_profile", lambda *args, **kwargs: admitted.append(args))
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: False)
    ledger = _budget(tmp_path / "BUILD-BUDGET.json", attempts=[_entry(1, platform)])
    before = ledger.read_bytes()
    parser = argparse.ArgumentParser()
    runner_arguments.add_runner_arguments(parser, hygiene_profiles=("ordinary", "heavy"),
                                          default_report_root=tmp_path, parse_jobs=runner_arguments.parse_jobs)
    args = parser.parse_args(["--suite", "int", "--no-coverage", "--d12-core-image-profile", platform,
                              "--report-dir", str(tmp_path / "report"), "--d12-core-image-source-sha256", _SOURCE,
                              "--d12-core-image-budget-ledger", str(ledger)])
    with pytest.raises(d12.D12ProfileError, match="fresh inner build daemon are unproved") as refused:
        runner_arguments.validate_pgvector_forwarded_selections(args, [d12.NODE_ID], repo_root=_REPOSITORY_ROOT)
    assert admitted == [], f"admission was invoked after a native BuildKit forecast: {admitted}"
    assert '"host_forecast": "native"' in str(refused.value) and ledger.read_bytes() == before
    assert [path.name for path in tmp_path.iterdir()] == ["BUILD-BUDGET.json"], "nothing reserved or reported"
