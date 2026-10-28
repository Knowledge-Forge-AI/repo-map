"""ADR 0102 observer lifecycle and E1 hook with Docker-free doubles: every failure path, custody and sizing.

No real Docker, image, container or network is used; the retained ARM observation is test-only source data.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

import pytest

import d12_dependency_preflight as preflight
import d12_native_python_observer as observer
from repomap_kg.runtime import python_payload as payload
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d12_native_python_proof as proof
from repomap_test_support import resource_run
from src.test.unit.python.tools.d12_native_python_fixture_helpers import (
    AMD, ARM, CONTAINER_ID, ROOT, World, capture, raw_and_inner,
)

class _Identity(TypedDict):
    source_sha256: str
    recipe_sha256: str
    dockerfile_sha256: str
    context_file_count: int


IDENTITY: _Identity = {"source_sha256": "a" * 64, "recipe_sha256": "b" * 64, "dockerfile_sha256": "c" * 64,
            "context_file_count": 3}
PROBE = ["projection", "info", "image", "create", "registered", "container", "start", "wait"]
CUSTODY = ["cleanup", "verify_baseline", "projection"]


def _observe(world: World, *, platform: str = ARM, required: bool = False, env: dict[str, str] | None = None,
             **options: Any) -> dict[str, Any]:
    record = observer.new_record(platform)
    environ = {proof.RAW_OVERRIDE_ENV: proof.CONFIGS["arm64"]} if env is None else env
    return observer.observe_component(record, client=world.client, owner=world.owner, run=world.run,
                                      boundary=world.boundary, platform=platform, environ=environ,
                                      require_override=required, repo_root=options.pop("repo_root", ROOT), **options)


def _public(record: dict[str, Any]) -> str:
    text = json.dumps(record, sort_keys=True)
    assert CONTAINER_ID not in text and "/home/" not in text and "private-secret" not in text, text[:400]
    return text


def test_observes_once_on_the_exact_config_and_succeeds_only_after_complete_custody() -> None:
    world = World()
    record = _observe(world, required=True)
    assert record["status"] == "observed" and record["reasons"] == [] and record["stage"] == "validate"
    assert world.events == [*PROBE, *CUSTODY], world.events
    [(image, command, role, options)] = world.created
    assert image == proof.CONFIGS["arm64"] and role == observer.ROLE and command[:3] == ["-I", "-B", "-c"]
    assert options == {"entrypoint": ["python3"], "network_mode": "none", "environment": {}}
    assert record["provenance"]["config"] == image and record["override"]["selected"] is True
    assert record["cleanup"] == {"verified": True, "container_created": True, "ledger_containers": 1, "removed": 1,
                                 "engine_absent": True, "baseline_verified": True}
    assert record["operations"]["delta"] == {} and record["operations"]["before"] == record["operations"]["after"]
    raw, inner = raw_and_inner()
    assert record["raw_report"] == raw["report"] and record["trimmed_report"] == inner["trimmed_report"]
    assert record["summary"]["baseline_import_count"] == 77 and record["qualification"] == proof.NON_QUALIFICATION
    assert record["container"]["stderr"] == proof.integrity(world.stderr) and "stderr_text" not in record
    assert record["payload_source_sha256"] == hashlib.sha256(Path(payload.__file__).read_bytes()).hexdigest()
    assert record["defaults"] == proof.default_states() and record["summary"]["default_enrolled"] is True
    _public(record)


def _attrs(world: World, **change: Any) -> None:
    world.attrs.update(change)


@pytest.mark.parametrize("setup, stage, created, events", [
    (lambda w: setattr(w, "daemon", "x86_64"), "daemon", False, ["projection", "info"]),
    (lambda w: _attrs(w, Id=proof.MANIFESTS["arm64"]), "image", False, ["projection", "info", "image"]),
    (lambda w: _attrs(w, RepoDigests=["python@sha256:" + "0" * 64]), "image", False, ["projection", "info", "image"]),
    (lambda w: w.fail.update(create=RuntimeError("Engine refused")), "create", False, PROBE[:4]),
    (lambda w: setattr(w, "network", "bridge"), "create", True, PROBE[:6]),
    (lambda w: w.fail.update(start=RuntimeError("start")), "execute", True, PROBE[:7]),
    (lambda w: w.fail.update(wait=TimeoutError("read timed out")), "execute", True, PROBE),
    (lambda w: setattr(w, "stdout", b"x" * (proof.CAPTURE_LIMIT + 1)), "capture", True, PROBE),
    (lambda w: setattr(w, "stdout", capture(raw_and_inner()[0])), "capture", True, PROBE),
    (lambda w: setattr(w, "status", 1), "validate", True, PROBE),
    (lambda w: setattr(w, "status", "0"), "validate", True, PROBE),
    (lambda w: setattr(w, "stdout", capture(raw_and_inner()[0], {**raw_and_inner()[1], "entry_delta": 0})),
     "validate", True, PROBE),
])
def test_every_probe_failure_is_a_retained_component_refusal_with_exact_cleanup(
        setup: Any, stage: str, created: bool, events: list[str]) -> None:
    world = World()
    setup(world)
    record = _observe(world)
    assert record["status"] == "refused" and record["stage"] == stage, record["reasons"]
    assert len(record["reasons"]) == 1 and record["reasons"][0].startswith(f"{stage}: "), record["reasons"]
    ledgered = bool(world.ledger.rows)
    assert world.events == [*events, *(["cleanup"] if ledgered else []), "verify_baseline", "projection"]
    assert record["cleanup"]["verified"] is True and record["cleanup"]["container_created"] is created
    assert record["cleanup"]["ledger_containers"] == int(ledgered) and not world.engine
    assert record["operations"]["delta"] == {} and "summary" not in record
    if stage == "daemon":
        assert "provenance" not in record and "container" not in record, "refusal precedes image access"
    if stage in ("capture", "validate") and world.stdout.startswith(proof.RAW_PREFIX.encode()):
        assert record["raw_report"] == raw_and_inner()[0]["report"], "the raw observation is retained"
    _public(record)


@pytest.mark.parametrize("rollback, close", [(True, "observe_removed"), (False, "cleanup")])
def test_a_post_ledger_create_failure_closes_only_the_sole_adopted_record(rollback: bool, close: str) -> None:
    world = World()
    world.rollback = rollback
    world.fail["registered"] = RuntimeError(f"readback {CONTAINER_ID}")
    record = _observe(world)
    assert record["status"] == "refused" and record["stage"] == "create" and len(record["reasons"]) == 1
    assert world.events == [*PROBE[:5], close, "verify_baseline", "projection"], world.events
    assert record["cleanup"]["verified"] is True and record["cleanup"]["container_created"] is False
    assert not world.engine and world.ledger.rows[CONTAINER_ID].cleanup_result.value == "removed"
    _public(record)


def test_an_uncaught_inner_failure_keeps_one_redacted_error_record() -> None:
    message = f"3.12.15 under /tmp/x for {CONTAINER_ID}"
    world = World(status=1, stdout=capture(extra=proof.ERROR_PREFIX + json.dumps(
        {"type": "AssertionError", "message": message}) + "\n"))
    record = _observe(world)
    assert record["stage"] == "capture" and record["status"] == "refused" and "raw_report" not in record
    assert record["inner_error"] == {"type": "AssertionError", "message": "3.12.15 under <path> for <id>"}
    assert world.events == [*PROBE, *CUSTODY] and not world.engine
    _public(record)


@pytest.mark.parametrize("setup, reason", [
    (lambda w: w.fail.update(cleanup=RuntimeError(f"remove {CONTAINER_ID} at /home/runner/x")), "cleanup: "),
    (lambda w: setattr(w.owner, "cleanup", lambda identity: w.events.append("cleanup")), "cleanup: "),
    (lambda w: w.fail.update(verify_baseline=RuntimeError("baseline changed")), "cleanup: "),
    (lambda w: setattr(w, "on_wait", lambda x: x.counts.update(unmanaged_pull_count=1)), "operations: "),
    (lambda w: setattr(w, "on_wait", lambda x: x.counts.update(extra_field=0)), "operations: "),
    (lambda w: setattr(w, "on_wait", lambda x: x.counts.update(unmanaged_build_count=True)), "operations: "),
])
def test_a_successful_probe_never_survives_cleanup_or_operation_failures(setup: Any, reason: str) -> None:
    world = World()
    setup(world)
    record = _observe(world)
    assert "summary" in record and record["status"] == "refused", record
    assert [item for item in record["reasons"] if item.startswith(reason)], record["reasons"]
    _public(record)


@pytest.mark.parametrize("setup, message", [
    (lambda w: setattr(w.owner, "ledger", copy.copy(w.ledger)), "not bound to the live run ledger"),
    (lambda w: setattr(w.boundary, "projection", lambda: {"managed_external_base_pull_count": 0}), "lacks operation"),
])
def test_boundary_and_owner_binding_refuse_before_any_docker_access(setup: Any, message: str) -> None:
    world = World()
    setup(world)
    record = _observe(world)
    assert record["status"] == "refused" and record["stage"] == "boundary" and message in record["reasons"][0]
    assert "info" not in world.events and not world.created


def test_held_default_override_and_envelope_refuse_before_image_access(monkeypatch: pytest.MonkeyPatch,
                                                                       tmp_path: Path) -> None:
    world = World()
    record = _observe(world, required=True, env={proof.RAW_OVERRIDE_ENV: proof.CONFIGS["amd64"]})
    assert record["stage"] == "override" and "image" not in world.events
    target = tmp_path / proof.ENVELOPE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / proof.ENVELOPE_PATH).read_bytes().replace(b"3.12.16", b"3.12.99", 1))
    assert _observe(World(), repo_root=tmp_path)["stage"] == "envelope"
    world = World(daemon="x86_64")  # ADR 0103: the admitted AMD default passes; the ARM image double then refuses
    assert _observe(world, platform=AMD)["stage"] == "image" and "image" in world.events
    monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", {**payload.PYTHON_PAYLOAD_EXCLUSIONS, "amd64": None})
    world = World()
    assert _observe(world)["stage"] == "defaults" and "image" not in world.events
    assert _observe(World(daemon="x86_64"), platform=AMD)["stage"] == "defaults"


@pytest.mark.parametrize("arch, value, reason", [
    ("amd64", "missing", "default is missing"),
    ("arm64", ("_ssl",), "default is malformed"),
    ("amd64", payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"]._replace(python_config=proof.CONFIGS["arm64"]), "foreign"),
])
def test_missing_malformed_or_foreign_defaults_refuse_before_image_access(
        monkeypatch: pytest.MonkeyPatch, arch: str, value: Any, reason: str) -> None:
    doubled: dict[str, Any] = {**payload.PYTHON_PAYLOAD_EXCLUSIONS, arch: value}
    if value == "missing":
        del doubled[arch]
    monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", doubled)  # an isolated double of the source map
    world = World()
    record = _observe(world)
    assert record["stage"] == "defaults" and reason in record["reasons"][0] and "image" not in world.events
    assert record["status"] == "refused" and record["cleanup"]["verified"] is True


@pytest.mark.parametrize("abort", [KeyboardInterrupt(), SystemExit(3)])
def test_control_aborts_keep_the_partial_record_clean_up_exactly_and_propagate(abort: BaseException) -> None:
    world = World()
    world.fail["wait"] = abort
    record = observer.new_record(ARM)
    with pytest.raises(type(abort)):
        observer.observe_component(record, client=world.client, owner=world.owner, run=world.run,
                                   boundary=world.boundary, platform=ARM, environ={}, require_override=False)
    assert world.events == [*PROBE, *CUSTODY] and not world.engine
    assert record["status"] == "refused" and record["stage"] == "execute"
    assert record["reasons"][0].startswith("execute aborted: ") and record["cleanup"]["verified"] is True


def test_overflow_keeps_a_compact_refusal_with_integrity_facts() -> None:
    raw = raw_and_inner()[0]["report"]
    record = _observe(World(), record_limit=20_000)
    assert record["status"] == "refused" and record["overflow"]["limit"] == 20_000
    compact = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    assert record["raw_report"] == {"omitted": True, **proof.integrity(compact)}
    assert observer.nested_size(record) <= 20_000 and record["reasons"][-1].startswith("bound: ")
    tiny = observer.bound_record({**observer.new_record(ARM), "reasons": ["x" * 5000]}, limit=1_000)
    assert observer.nested_size(tiny) <= 1_000 and tiny["status"] == "refused"


def test_retained_arm_record_fits_the_indented_report_part_total_and_cleanup_reserve(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = _observe(World())
    raw = raw_and_inner()[0]["report"]
    closure = {"contract": {"result": "refused"}, "baseline": copy.deepcopy(raw["baseline"]), "retained": None,
               "exclusion": None, "baseline_unresolved": [], "baseline_failed": ["_tkinter"]}
    report = {**preflight.LABELS, "admission": {"platform": ARM, **IDENTITY}, "bindings": {"run_id": "r"},
              "availability": {}, "bases": {}, "refusals": ["closure: unconfigured baseline"], "result": "refused",
              "steps": {"closure": closure, observer.SLOT: record, "capacity": {"free_bytes": 1}}}
    monkeypatch.setenv(d12.ENV_REPORT_DIR, str(tmp_path))
    d12.write_report("freeze", {"budget": {}})
    part = d12.write_report("exploration", report).stat().st_size
    assert part <= d12.REPORT_PART_LIMIT and observer.nested_size(record) <= proof.RECORD_LIMIT
    assert part + 4096 + d12.REPORT_CLEANUP_RESERVE <= d12.REPORT_TOTAL_LIMIT
    d12.write_report("cleanup", {"containers": "baseline_verified"})
    saved = json.loads((tmp_path / "exploration.json").read_text(encoding="utf-8"))
    assert saved["steps"][observer.SLOT] == json.loads(json.dumps(record))


def _explore(monkeypatch: pytest.MonkeyPatch, world: World, *, current: bool = True,
             closure_baseline: Any = "raw") -> tuple[list[dict[str, Any]], BaseException | None]:
    admission = d12.D12Admission(platform=ARM, node_id=d12.NODE_ID, **IDENTITY)
    monkeypatch.setattr(preflight, "_EXPLORATION", admission if current else None)
    monkeypatch.setattr(d12, "locate_run_boundary", lambda: world.boundary)
    monkeypatch.setattr(resource_run, "active_resource_run", lambda: world.run)
    monkeypatch.setenv(proof.RAW_OVERRIDE_ENV, proof.CONFIGS["arm64"])
    baseline = copy.deepcopy(raw_and_inner()[0]["report"]["baseline"]) if closure_baseline == "raw" else (
        closure_baseline)

    def engine(steps: dict[str, Any], *_args: Any) -> None:
        world.events.append("engine")
        steps["engine"], steps["identity"] = {"classification": {ARM: "native"}}, {"python": proof.CONFIGS["arm64"]}

    def closure(steps: dict[str, Any], _container: Any, _platform: str) -> None:
        world.events.append("closure")
        steps["closure"] = {"baseline": baseline}
        raise preflight.PreflightRefusal("unconfigured Python payload exclusion baseline for arm64")

    def create(_owner: Any, _client: Any, _image: str, _command: Any, **options: Any) -> tuple[str, Any]:
        world.events.append(str(options["role"]))
        return "legacy", SimpleNamespace(start=lambda: None)

    def trust(_steps: dict[str, Any], _container: Any) -> dict[str, bytes]:
        world.events.append("trust")
        return {}

    monkeypatch.setattr(preflight, "engine_facts", engine)
    monkeypatch.setattr(preflight, "trust_facts", trust)
    monkeypatch.setattr(preflight, "closure_facts", closure)
    reports: list[dict[str, Any]] = []
    try:
        preflight.explore(world.owner, world.client, admission, bases={}, availability={}, inspected=None,
                          server_inventory={"packages": [["libpq5", "17.6", "arm64"]], "files": []}, create=create,
                          bindings={"run_id": "r"}, statvfs=lambda _p: SimpleNamespace(f_bavail=1, f_frsize=1),
                          write_report=lambda _n, p: reports.append(json.loads(json.dumps(p, default=str))))
    except BaseException as error:
        return reports, error
    return reports, None


def test_e1_hook_runs_after_engine_before_trust_and_survives_the_legacy_refusal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    [report], error = _explore(monkeypatch, world)
    assert isinstance(error, preflight.PreflightRefusal) and "nothing built or consumed" in str(error)
    assert world.events.index("engine") < world.events.index("info") < world.events.index("d12-explore-trust")
    assert world.events.index("cleanup") < world.events.index("d12-explore-trust"), "custody precedes legacy work"
    assert report["refusals"] == ["closure: unconfigured Python payload exclusion baseline for arm64"]
    component = report["steps"][observer.SLOT]
    assert component["status"] == "observed" and component["override"]["required"] is True, component["reasons"]
    assert component["closure_cross_check"] == {"result": "consistent", "fields": []}
    _public(component)


def test_e1_component_failures_and_conflicts_stay_out_of_the_legacy_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    conflicting = {**raw_and_inner()[0]["report"]["baseline"], "digest": "0" * 64, "entries": 1}
    [report], _error = _explore(monkeypatch, World(), closure_baseline=conflicting)
    component = report["steps"][observer.SLOT]
    assert component["status"] == "refused" and component["closure_cross_check"]["fields"] == ["entries", "digest"]
    assert report["refusals"] == ["closure: unconfigured Python payload exclusion baseline for arm64"]
    world = World(daemon="x86_64")
    [report], _error = _explore(monkeypatch, world)
    assert report["steps"][observer.SLOT]["stage"] == "daemon" and "trust" in world.events and "closure" in world.events
    assert report["refusals"] == ["closure: unconfigured Python payload exclusion baseline for arm64"]
    monkeypatch.setattr(d12, "locate_run_boundary", lambda: (_ for _ in ()).throw(d12.D12ProfileError("unbound")))
    found = observer.observe_exploration({}, world.client, world.owner, preflight._EXPLORATION,
                                         exploration=preflight._EXPLORATION)
    assert found is not None and found["reasons"] == ["boundary: D12ProfileError: unbound"]


def test_e1_abort_writes_the_partial_slot_once_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    world.fail["wait"] = KeyboardInterrupt()
    [report], error = _explore(monkeypatch, world)
    assert isinstance(error, KeyboardInterrupt) and "trust" not in world.events and not world.engine
    slot = report["steps"][observer.SLOT]
    assert slot["stage"] == "execute" and slot["status"] == "refused" and slot["cleanup"]["verified"] is True
    assert slot["closure_cross_check"] == {"result": "not_run", "fields": []}, "A6 absence is explicit"


def test_non_exploration_admissions_never_run_the_component(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    [report], _error = _explore(monkeypatch, world, current=False)
    assert observer.SLOT not in report["steps"] and "info" not in world.events and not world.created
    assert observer.observe_exploration({}, None, None, object(), exploration=None) is None


def test_explore_source_hooks_after_engine_and_cross_checks_after_closure_only() -> None:
    tree = ast.parse(Path(str(preflight.__file__)).read_bytes())
    explore = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "explore")
    body = [ast.unparse(s) for s in next(n for n in explore.body if isinstance(n, ast.Try)).body]
    hook = "observer.observe_exploration(steps, client, owner, admission, exploration=_EXPLORATION)"
    assert body[:2] == ["engine_facts(steps, client, admission, inspected, bases)", hook]
    closure = next(i for i, line in enumerate(body) if line.startswith("closure = observe('closure'"))
    assert body[closure + 1] == "observer.cross_check(steps)" and ast.unparse(tree).count("observer.") == 2
