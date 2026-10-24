"""Pure owner for the one-owner D12 core-image profile (ADR 0087, D12-A)."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_test_support import d12_core_image as d12
from repomap_test_support.build_profile_debt import DEFERRED_BUILD_PROFILE_NODE_IDS
from repomap_test_support.resource_ledger import CleanupResult, FinalPresence
import d12_dependency_preflight as preflight
import runner_arguments
from runner_unit_environment import pytest_environment_for

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_REPORTS = REPO_ROOT / ".test-reports"
GOOD = ["--suite", "int", "--no-coverage", "--d12-core-image-profile", "linux/arm64",
        "--report-dir", "/tmp/d12-report", "--d12-core-image-source-sha256", "a" * 64]
HOLD = "STOP_PENDING_OPERATOR_DISPOSITION"
BUILDX_INSPECT = ("Name: default\nDriver: docker\n\nNodes:\nName: default\nStatus: running\n"
                  "Platforms:        linux/arm64, linux/amd64*, linux/amd64/v2, linux/riscv64\nLabels:\n")


def _parse(argv):
    parser = argparse.ArgumentParser()
    runner_arguments.add_runner_arguments(parser, hygiene_profiles=("ordinary", "heavy"),
                                          default_report_root=DEFAULT_REPORTS,
                                          parse_jobs=runner_arguments.parse_jobs)
    return parser.parse_args(argv)


def _admittable(source: str, ledger: Path | None = None):
    return _parse([*GOOD[:-1], source, *(["--d12-core-image-budget-ledger", str(ledger)] if ledger else [])])


@pytest.fixture(autouse=True)
def _fresh_profile_state(monkeypatch):
    monkeypatch.setattr(d12, "_ADMISSION", None)
    for name in (d12.ENV_PROFILE, d12.ENV_REPORT_DIR):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("extra, missing", [
    (["--suite", "staging"], "--suite int"), (["--suite", "unit"], "--suite int"),
    (["--jobs", "2"], "--jobs 1"), (["--pg-test-profile", "pgvector"], "--pg-test-profile core"),
    (["--threshold", "1"], "no --threshold"), (["--report"], "no --report"),
    (["--declared-complete-gates", "1"], "no declared complete gates"),
    (["--d12-core-image-source-sha256", "abc"], "frozen --d12-core-image-source-sha256"),
])
def test_noncanonical_runner_shapes_refuse_before_docker_work(extra, missing):
    with pytest.raises(d12.D12ProfileError, match=missing):
        runner_arguments.validate_runner_options(_parse([*GOOD, *extra]), ("int",))
    for argv, message in (([a for a in GOOD if a != "--no-coverage"], "--no-coverage"),
                          (GOOD[:-2], "frozen --d12-core-image-source-sha256")):
        with pytest.raises(d12.D12ProfileError, match=message):
            d12.validate_options(_parse(argv))
    with pytest.raises(SystemExit):
        _parse([*GOOD[:3], "--d12-core-image-profile", "linux/riscv64"])


@pytest.mark.parametrize("forwarded", [
    [], ["src/test/int/python"], [d12.NODE_ID, "-k", "round"], ["-m", d12.MARKER, d12.NODE_ID],
    [d12.NODE_ID, d12.NODE_ID], [d12.NODE_FILE], [d12.NODE_ID, "-p", "no:cacheprovider"],
    [d12.NODE_ID, DEFERRED_BUILD_PROFILE_NODE_IDS[0]],
])
def test_selection_requires_exactly_the_named_node(forwarded):
    with pytest.raises(d12.D12ProfileError, match="exactly the one named node"):
        d12.validate_selection(_parse(GOOD), forwarded, repo_root=REPO_ROOT)


def test_selection_refuses_ambient_environment_default_reports_and_unprofiled_use():
    d12.validate_selection(_parse(GOOD), [d12.NODE_ID], repo_root=REPO_ROOT)
    for environ in ({d12.ENV_PROFILE: "linux/arm64"}, {d12.ENV_REPORT_DIR: "/tmp/x"}):
        with pytest.raises(d12.D12ProfileError, match="ambient environment"):
            d12.validate_selection(_parse(["--suite", "int"]), [], repo_root=REPO_ROOT, environ=environ)
    with pytest.raises(d12.D12ProfileError, match="explicit unused --report-dir"):
        d12.validate_selection(_parse([*GOOD[:5], *GOOD[7:]]), [d12.NODE_ID], repo_root=REPO_ROOT)
    plain = ["--suite", "int", "--no-coverage"]
    for argv, forwarded in ((plain, [d12.NODE_ID]), (plain, [f"./{d12.NODE_FILE}"]),
                            (plain, [d12.NODE_FILE + "::test_other"]), ([*plain, *GOOD[-2:]], []),
                            ([*plain, "--d12-core-image-budget-ledger", "/tmp/ledger.json"], [])):
        with pytest.raises(d12.D12ProfileError, match="requires --d12-core-image-profile"):
            d12.validate_selection(_parse(argv), forwarded, repo_root=REPO_ROOT)


def _ledger(path: Path, **overrides) -> Path:
    data = {"phase": "p", "maximum_total": 2, "maximum_per_platform": 1, "attempts": [], "owned_by": "parent"}
    path.write_text(json.dumps({**data, **overrides}))
    return path


def test_host_consumes_one_matching_entry_before_the_sandbox_records_admission(tmp_path):
    identity = d12.frozen_identity(REPO_ROOT, "linux/arm64")
    source, recipe = identity["source_sha256"], identity["recipe_sha256"]
    ledger = _ledger(tmp_path / "BUILD-BUDGET.json")
    host: dict[str, Any] = dict(repo_root=REPO_ROOT, sandbox_active=lambda: False)
    for args, message in ((_admittable(source), "--d12-core-image-budget-ledger on the host"),
                          (_admittable("0" * 64, ledger), "stale source"),
                          (_admittable(source, ledger), "no unused write-ahead budget entry")):
        with pytest.raises(d12.D12ProfileError, match=message):
            d12.admit_profile(args, [d12.NODE_ID], **host)
    d12.record_budget(ledger, "append", "linux/arm64", "c" * 64, recipe)
    with pytest.raises(d12.D12ProfileError, match="no unused write-ahead"):
        d12.admit_profile(_admittable(source, ledger), [d12.NODE_ID], **host)
    ledger = _ledger(tmp_path / "fresh.json")
    d12.record_budget(ledger, "append", "linux/arm64", source, recipe)
    assert d12.admit_profile(_admittable(source, ledger), [d12.NODE_ID], **host) is None
    consumed = json.loads(ledger.read_text())["attempts"]
    assert len(consumed) == 1 and consumed[0]["consumed_at"] and d12._ADMISSION is None
    assert consumed[0]["consumed_by"] == str(Path("/tmp/d12-report").resolve())  # bound to this invocation
    before = ledger.read_bytes()
    with pytest.raises(d12.D12ProfileError, match="no unused write-ahead"):
        d12.admit_profile(_admittable(source, ledger), [d12.NODE_ID], **host)
    assert ledger.read_bytes() == before
    hold = _ledger(tmp_path / "hold.json", maximum_total=0, parent_admission_state=HOLD)
    with pytest.raises(d12.D12ProfileError, match=f"approved bounds; parent state: {HOLD}"):
        d12.admit_profile(_admittable(source, hold), [d12.NODE_ID], **host)
    admitted = d12.admit_profile(_admittable(source), [d12.NODE_ID], repo_root=REPO_ROOT, sandbox_active=lambda: True)
    assert admitted == d12.current_admission() and (admitted.platform, admitted.node_id) == ("linux/arm64", d12.NODE_ID)
    assert admitted.recipe_sha256 == recipe != d12.recipe_digest("linux/amd64")
    with pytest.raises(d12.D12ProfileError, match="already admitted"):
        d12.admit_profile(_admittable(source), [d12.NODE_ID], repo_root=REPO_ROOT, sandbox_active=lambda: True)
    assert d12.admit_profile(_parse(["--suite", "int"]), [], repo_root=REPO_ROOT,
                             sandbox_active=lambda: pytest.fail("not probed without profile")) is None


def test_runner_facade_admits_before_dispatch_and_scopes_population_environment(tmp_path, monkeypatch):
    preflights: list[str] = []  # stands in for a positive inner-daemon preflight, which is unimplemented
    monkeypatch.setattr(runner_arguments, "d12_platform_preflight", preflights.append)
    with pytest.raises(d12.D12ProfileError):
        runner_arguments.validate_pgvector_forwarded_selections(_parse(GOOD), [d12.NODE_ID, "-x"], repo_root=REPO_ROOT)
    with pytest.raises(d12.D12ProfileError, match="stale source"):
        runner_arguments.validate_pgvector_forwarded_selections(_parse(GOOD), [d12.NODE_ID], repo_root=REPO_ROOT)
    identity = d12.frozen_identity(REPO_ROOT, "linux/arm64")
    ledger = _ledger(tmp_path / "ledger.json")
    d12.record_budget(ledger, "append", "linux/arm64", identity["source_sha256"], identity["recipe_sha256"])
    runner_arguments.validate_pgvector_forwarded_selections(
        _admittable(identity["source_sha256"], ledger), [d12.NODE_ID], repo_root=REPO_ROOT)
    assert d12._ADMISSION is None and "consumed_at" in json.loads(ledger.read_text())["attempts"][0]
    assert preflights == ["linux/arm64", "linux/arm64"], preflights  # after selection validation only
    with pytest_environment_for(("int",), _parse([*GOOD, "--pg-container-port", "55433"])):
        assert os.environ[d12.ENV_PROFILE] == "linux/arm64"
        assert os.environ[d12.ENV_REPORT_DIR] == "/tmp/d12-report/d12-core-image/linux-arm64"
    assert d12.ENV_PROFILE not in os.environ and d12.ENV_REPORT_DIR not in os.environ
    with pytest_environment_for(("int",), _parse(["--suite", "int"])):
        assert d12.ENV_PROFILE not in os.environ


def test_host_preflight_refuses_an_unfrozen_or_non_executable_platform_without_consuming(tmp_path, monkeypatch):
    builder = "Platforms: linux/arm64*, linux/amd64\nBuildKit version: v0.33.1\n"  # read-only query doubles
    docker = lambda command, **_: subprocess.CompletedProcess(
        command, 0, "arm64" if command[1] == "version" else builder)
    monkeypatch.setattr(runner_arguments, "d12_platform_preflight", lambda p: preflight.preflight(p, run=docker))
    identity = d12.frozen_identity(REPO_ROOT, "linux/arm64")
    ledger = _ledger(tmp_path / "ledger.json")
    d12.record_budget(ledger, "append", "linux/arm64", identity["source_sha256"], identity["recipe_sha256"])
    before = ledger.read_bytes()
    with pytest.raises(d12.D12ProfileError, match="does not cover linux/arm64"):
        runner_arguments.validate_pgvector_forwarded_selections(
            _admittable(identity["source_sha256"], ledger), [d12.NODE_ID], repo_root=REPO_ROOT)
    assert ledger.read_bytes() == before and d12._ADMISSION is None, "a refused preflight consumed nothing"


def _git_context(root: Path) -> Path:
    for name, text in (("pyproject.toml", "[project]\n"), ("README.md", "r\n"),
                       ("src/main/python/pkg/a.py", "A = 1\n"), ("src/main/go/go.mod", "module m\n"),
                       ("src/main/resources/x.sql", "SELECT 1;\n"), ("docs/out.md", "outside\n")):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_identity_freeze_detects_source_recipe_and_staging_races(tmp_path, monkeypatch):
    repo = _git_context(tmp_path / "repo")
    names = d12.context_files(repo)
    assert "docs/out.md" not in names and "src/main/python/pkg/a.py" in names
    admission = d12.D12Admission("linux/arm64", d12.NODE_ID, d12.digest_files(repo, names),
                                 d12.recipe_digest("linux/arm64"), "d" * 64, len(names))
    assert d12.digest_files(d12.stage_context(repo, tmp_path / "ok", admission), names) == admission.source_sha256
    os.chmod(repo / "src/main/python/pkg/a.py", 0o755)
    with pytest.raises(d12.D12ProfileError, match="stale source"):
        d12.stage_context(repo, tmp_path / "mode", admission)
    os.chmod(repo / "src/main/python/pkg/a.py", 0o644)
    (repo / "src/main/python/pkg/b.py").write_text("B = 2\n")
    with pytest.raises(d12.D12ProfileError, match="stale source"):
        d12.stage_context(repo, tmp_path / "added", admission)
    (repo / "src/main/python/pkg/b.py").unlink()
    original_recipe = d12.recipe_text
    monkeypatch.setattr(d12, "recipe_text", lambda: "FROM scratch\n")
    with pytest.raises(d12.D12ProfileError, match="stale recipe"):
        d12.stage_context(repo, tmp_path / "recipe", admission)
    monkeypatch.setattr(d12, "recipe_text", original_recipe)
    monkeypatch.setattr(d12.shutil, "copy2", lambda source, target: Path(target).write_text("drift\n"))
    with pytest.raises(d12.D12ProfileError, match="staged build context differs"):
        d12.stage_context(repo, tmp_path / "staged", admission)
    (repo / "README.md").unlink()
    (repo / "README.md").symlink_to(repo / "pyproject.toml")
    with pytest.raises(d12.D12ProfileError, match="not a regular file"):
        d12.digest_files(repo, names)


def test_builder_platform_strings_feed_native_emulated_or_blocked_classification():
    offered = d12.offered_platforms(BUILDX_INSPECT)
    assert offered == ["linux/arm64", "linux/amd64", "linux/amd64/v2", "linux/riscv64"]
    assert d12.platform_availability("linux/arm64", "aarch64", [])["execution"] == "native"
    assert d12.platform_availability("linux/amd64", "aarch64", offered)["execution"] == "emulated"
    for platform, architecture, inspect in (("linux/amd64", "aarch64", BUILDX_INSPECT.replace("linux/amd64*, ", "")),
                                            ("linux/arm64", "x86_64", ""), ("linux/amd64", "aarch64", "")):
        with pytest.raises(d12.D12ProfileError, match="platform blocked"):
            d12.platform_availability(platform, architecture, d12.offered_platforms(inspect))


class ImageNotFound(Exception):
    pass


def _images(table: dict[str, Any], removed: list | None = None, remove_error: Exception | None = None):
    def get(reference):
        if reference not in table:
            raise ImageNotFound(reference)
        return SimpleNamespace(attrs=table[reference])

    def remove(image, **kwargs):
        if remove_error:
            raise remove_error
        assert removed is not None
        removed.append((image, kwargs))
    return SimpleNamespace(images=SimpleNamespace(get=get, remove=remove), removed=removed)


def test_pinned_bases_are_frozen_per_platform_without_pulling_missing_variants():
    index = next(iter(d12.BASE_CONFIG_DIGESTS))
    pg, py = f"postgres:16.15-trixie@{index}", "python:3@sha256:" + "b" * 64
    config = d12.BASE_CONFIG_DIGESTS[index]

    def attrs(reference, arch="arm64", image_id=None):
        return {"Os": "linux", "Architecture": arch, "Id": image_id or config["linux/arm64"],
                "RepoDigests": [reference.split(":")[0] + "@" + reference.split("@")[1]]}
    bases = d12.verify_bases(_images({pg: attrs(pg), py: attrs(py, image_id="sha256:" + "c" * 64)}),
                             "linux/arm64", (pg, py))
    assert bases[pg] == {"id": config["linux/arm64"], "platform": "linux/arm64", "config_digest_verified": True}
    assert bases[py]["config_digest_verified"] is False
    assert d12.verify_bases(_images({pg: attrs(pg, image_id=index)}), "linux/arm64", (pg,))[pg]["id"] == index
    for table, platform, message in (
        ({}, "linux/arm64", "is not local; no extra pull"),
        ({pg: attrs(pg)}, "linux/amd64", "is linux/arm64, not linux/amd64"),
        ({pg: attrs(pg, image_id=config["linux/amd64"])}, "linux/arm64", "base identity mismatch"),
        ({pg: {**attrs(pg), "RepoDigests": ["postgres@sha256:" + "e" * 64]}}, "linux/arm64", "pinned digest"),
    ):
        with pytest.raises(d12.D12ProfileError, match=message):
            d12.verify_bases(_images(table), platform, (pg,))


class _Boundary:
    def __init__(self, spent: int = 0):
        self.spent = spent
        self.opened: list[str] = []
        self.completed: list[tuple[str, tuple[str, ...]]] = []

    def projection(self):
        return {"managed_system_candidate_image_build_count": self.spent}

    @contextmanager
    def managed_system_candidate_build(self, *, request):
        self.opened.append(request)
        self.spent += 1
        yield "ticket"

    def complete_operation(self, ticket, *, image_ids):
        self.completed.append((ticket, image_ids))


def _build(tmp_path, boundary, *, returncode=0, iid="sha256:" + "a" * 64, stdout="out"):
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if iid:
            (tmp_path / "candidate.iid").write_text(iid)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="err")

    admission = d12.D12Admission("linux/amd64", d12.NODE_ID, "s" * 64, "r" * 64, "d" * 64, 1)
    result = d12.build_candidate(boundary=boundary, admission=admission, context=tmp_path,
                                 dockerfile=tmp_path / "Dockerfile", tag="t:1", labels={"k": "v"}, runner=runner)
    return result, commands


def test_one_run_spends_at_most_one_accounted_build(tmp_path):
    boundary = _Boundary()
    (image_id, log), commands = _build(tmp_path, boundary)
    assert image_id == "sha256:" + "a" * 64 and log == "outerr"
    assert commands[0][:4] == ["docker", "build", "--pull=false", "--platform"] and "linux/amd64" in commands[0]
    assert {"--rm", "--force-rm", "TARGETARCH=amd64"} <= set(commands[0]) and commands[0][-1] == str(tmp_path)
    assert boundary.opened == ["d12-core-image:linux/amd64:" + "r" * 16]
    assert boundary.completed == [("ticket", (image_id,))]
    with pytest.raises(d12.D12ProfileError, match="already spent"):
        _build(tmp_path, boundary)  # the run-wide boundary already counts this run's build
    assert len(boundary.opened) == 1
    (_, long_log), _ = _build(tmp_path, _Boundary(), stdout="é" * d12.LOG_EXCERPT_BYTES)
    assert len(long_log.encode()) <= d12.LOG_EXCERPT_BYTES and long_log.endswith("err")
    for kwargs, message in (({"returncode": 1}, "failed with status 1"), ({"iid": ""}, "no exact image ID")):
        failing = _Boundary()
        (tmp_path / "candidate.iid").unlink(missing_ok=True)
        with pytest.raises(d12.D12ProfileError, match=message):
            _build(tmp_path, failing, **kwargs)
        assert failing.spent == 1 and failing.completed == []  # counted on entry: no retry in this run


def test_budget_cli_refuses_an_unfrozen_identity_before_appending(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    repo = _git_context(tmp_path / "repo")
    ledger = _ledger(tmp_path / "BUILD-BUDGET.json")
    assert d12.main(["identity", "--platform", "linux/arm64", "--repo-root", str(repo)]) == 0
    identity = json.loads(capsys.readouterr().out)
    stale = ["budget-append", "--platform", "linux/arm64", "--repo-root", str(repo), "--ledger", str(ledger),
             "--expect-source", "0" * 64, "--expect-recipe", identity["recipe_sha256"]]
    with pytest.raises(d12.D12ProfileError, match="does not match the checkout"):
        d12.main(stale)
    assert json.loads(ledger.read_text())["attempts"] == []
    stale[stale.index("0" * 64)] = identity["source_sha256"]
    assert d12.main(stale) == 0
    assert json.loads(ledger.read_text())["attempts"][0]["source_sha256"] == identity["source_sha256"]


def test_report_parts_stay_bound_and_under_the_aggregate_evidence_ceiling(tmp_path, monkeypatch):
    with pytest.raises(d12.D12ProfileError, match="unbound"):
        d12.write_report("freeze", {})
    monkeypatch.setenv(d12.ENV_REPORT_DIR, str(tmp_path / "r"))
    monkeypatch.setattr(d12, "REPORT_TOTAL_LIMIT", 120)
    monkeypatch.setattr(d12, "REPORT_CLEANUP_RESERVE", 0)
    assert d12.write_report("freeze", {"a": "x" * 50}).is_file()
    assert d12.write_report("freeze", {"a": "x" * 60}).is_file()
    with pytest.raises(d12.D12ProfileError, match="evidence ceiling"):
        d12.write_report("build", {"a": "x" * 60})
    with pytest.raises(d12.D12ProfileError, match="evidence ceiling"):
        d12.write_report("huge", {"a": "x" * (d12.REPORT_PART_LIMIT + 1)})
    monkeypatch.setattr(d12, "REPORT_CLEANUP_RESERVE", 60)
    with pytest.raises(d12.D12ProfileError, match="evidence ceiling"):
        d12.write_report("result", {"a": "x"})  # only cleanup may use the final reserve
    assert d12.write_report("cleanup", {"a": "x"}).is_file()


def test_run_boundary_binding_refuses_unbound_or_ambiguous_identity(monkeypatch):
    from repomap_test_support import resource_docker_mediation, resource_run
    from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary

    with pytest.raises(d12.D12ProfileError, match="unbound identity"):
        d12.locate_run_boundary()
    authority: Any = SimpleNamespace(installed=True)
    ledger = object()
    monkeypatch.setattr(resource_docker_mediation, "installed_authorities", lambda: (authority,))
    monkeypatch.setattr(resource_run, "active_resource_run", lambda: SimpleNamespace(ledger=ledger))
    first = object.__new__(RunWideDockerBoundary)
    first.authority, first.ledger = authority, ledger
    assert d12.locate_run_boundary() is first
    second = object.__new__(RunWideDockerBoundary)
    second.authority, second.ledger = authority, ledger
    with pytest.raises(d12.D12ProfileError, match="not uniquely bound"):
        d12.locate_run_boundary()
    del second
    authority.installed = False
    with pytest.raises(d12.D12ProfileError, match="not uniquely bound"):
        d12.locate_run_boundary()


def _ledger_double(before=False):
    events: list = []
    record = SimpleNamespace(created_before_run=before, creation_observed=True)
    return SimpleNamespace(events=events, get=lambda kind, identity: record,
                           mark_cleanup_attempted=lambda kind, identity: events.append("attempted"),
                           mark_cleanup_result=lambda kind, identity, result: events.append(CleanupResult(result)),
                           mark_final_presence=lambda kind, identity, value: events.append(FinalPresence(value)))


def test_candidate_cleanup_removes_only_the_exact_owned_image():
    image = "sha256:" + "c" * 64
    client, ledger = _images({}, removed=[]), _ledger_double()
    proof = d12.remove_candidate_image(client, ledger, image, "t:1")
    assert proof["removed"] and client.removed == [(image, {"force": False, "noprune": False})]
    assert ledger.events == ["attempted", CleanupResult.REMOVED, FinalPresence.ABSENT]
    foreign, foreign_client = _ledger_double(before=True), _images({}, removed=[])
    with pytest.raises(d12.D12ProfileError, match="not owned"):
        d12.remove_candidate_image(foreign_client, foreign, image, "t:1")
    assert foreign_client.removed == [] and foreign.events == []
    for client, error in ((_images({"t:1": {}}, removed=[]), d12.D12ProfileError),
                          (_images({}, remove_error=OSError("busy")), OSError)):
        ledger = _ledger_double()
        with pytest.raises(error):
            d12.remove_candidate_image(client, ledger, image, "t:1")
        assert ledger.events == ["attempted", CleanupResult.FAILED]
