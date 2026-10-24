"""Pure orchestration owner for the named D12 integration owner's E1 and build-authority dataflow (ADR 0089).

The real owner function comes from pytest's normal fixed-path collector API,
``pytest.Module.from_parent(session, path=ROOT / d12.NODE_FILE).obj``: the session's configured import mode imports
only that known RepoMap test module. Nothing collects or runs the int suite or loads its conftest. Before each call
every external interface is faked: resource run, boundary, client, owned containers, server, inventory and hash
helpers, buildx query, base check, labels, scratch, context staging and the explore and report writers, while
``build_candidate`` is a counting trap. The actual cleanup coordinator and zero-count custody run. The owner's only
filesystem write is its recipe text under ``tmp_path``. Unit orchestration evidence only: no E1, build or Docker.
"""

from __future__ import annotations

from pathlib import Path
import traceback
from types import SimpleNamespace
from typing import Any

import pytest

import d12_dependency_preflight as preflight
from repomap_test_support import d12_core_image as d12

ROOT = Path(__file__).resolve().parents[5]
IDENTITY: dict[str, Any] = {"source_sha256": "a" * 64, "recipe_sha256": "b" * 64, "dockerfile_sha256": "c" * 64,
                            "context_file_count": 3}
SERVER_IMAGE, UUID_HEX = "sha256:" + "1" * 64, "e" * 32
ZERO = dict.fromkeys(preflight.COUNTS, 0)
NO_ADMISSION, MIXED, GUARD = "no runner admission", "mixed build and exploration admission", "not the current build"
BEFORE_E1 = ["boundary", "run", "buildx", "bases", "scratch", "context", "containers", "server", "inventory", "hashes"]
CUSTODY = ["cleanup server-1", "baseline"]
LIBPQ_FILE = {"role": "libpq", "owner": "libpq5", "resolved": "/usr/lib/a/libpq.so.5.17", "sha256": "e" * 64}


class BuildTrap(Exception):
    """Raised by the trapping ``build_candidate`` instead of any build."""


class ImageNotFound(Exception):
    """Named like the SDK error that ``d12.image_present`` treats as absence."""


def _admission(platform: str = "linux/arm64") -> d12.D12Admission:
    return d12.D12Admission(platform=platform, node_id=d12.NODE_ID, **IDENTITY)


def _absent(reference: str) -> Any:
    raise ImageNotFound(reference)


@pytest.fixture
def real_owner(request) -> Any:
    """The one fixed RepoMap test module through pytest's own collector API; never a copy, loader or second run."""
    module = pytest.Module.from_parent(request.session, path=ROOT / d12.NODE_FILE).obj
    assert Path(module.__file__).resolve() == (ROOT / d12.NODE_FILE).resolve(), module.__file__
    plugins = [str(getattr(p, "__file__", "")) for p in request.config.pluginmanager.get_plugins()]
    assert not [p for p in plugins if p.endswith("src/test/int/python/conftest.py")], "int conftest stays unloaded"
    function = module.test_d12_core_image_refresh_candidate_round_trip
    assert function.__name__ == d12.NODE_ID.rsplit("::", 1)[1] and function.__module__ == module.__name__
    return module


@pytest.fixture
def world(real_owner, tmp_path, monkeypatch) -> SimpleNamespace:
    """Fake every external interface of the real owner and record each call in order."""
    w = SimpleNamespace(events=[], contexts=[], builds=[], explored=[], reports={}, refuse=False, api=170006)
    client = SimpleNamespace(info=lambda: {"Architecture": "aarch64"}, images=SimpleNamespace(get=_absent))
    boundary = SimpleNamespace(client=client, projection=lambda: dict(ZERO))
    run = SimpleNamespace(ledger=SimpleNamespace(identity=SimpleNamespace(run_id="t-unit-run")))
    server = SimpleNamespace(attrs={"Image": SERVER_IMAGE},
                             exec_run=lambda command: SimpleNamespace(output=b"postgres (PostgreSQL) 16.15"))

    def step(name: str, result: Any = None) -> Any:
        def record(*_args: Any, **_kwargs: Any) -> Any:
            w.events.append(name)
            return result
        return record

    class Containers:
        def __init__(self, run_: Any, client_: Any) -> None:
            assert run_ is run and client_ is client, "owned containers bind the faked run and client"
            w.events.append("containers")

        def cleanup(self, identity: str) -> None:
            w.events.append(f"cleanup {identity}")

        def verify_baseline(self) -> None:
            w.events.append("baseline")

    def bases(client_: Any, platform: str, references: Any) -> dict[str, dict[str, object]]:
        w.events.append("bases")
        return {reference: {"id": SERVER_IMAGE, "platform": platform} for reference in references}

    def stage_context(repo_root: Path, destination: Path, binding: Any) -> Path:
        w.events.append("context")
        w.contexts.append(binding)
        return destination

    def explore(owner: Any, client_: Any, admission: Any, **_kwargs: Any) -> dict[str, object]:
        w.events.append("explore")
        w.explored.append(admission)
        if w.refuse:
            raise preflight.PreflightRefusal("E1 exploration refused; nothing built or consumed: unit refusal")
        observed = {"api": w.api, "library": {"path": LIBPQ_FILE["resolved"], "sha256": LIBPQ_FILE["sha256"]}}
        return {"result": "observed", "steps": {"libpq_runtime": observed, "candidate": {"libpq_version": w.api}}}

    def build_candidate(**kwargs: Any) -> Any:
        w.builds.append(kwargs["admission"])
        raise BuildTrap("build trap reached")

    def write_report(name: str, payload: dict[str, object]) -> Path:
        w.reports[name] = payload
        return tmp_path / f"{name}.json"

    owner_fakes: dict[str, Any] = {
        "active_resource_run": step("run", run), "establish_run": step("scratch", SimpleNamespace(tmp=tmp_path)),
        "subprocess": SimpleNamespace(run=step("buildx", SimpleNamespace(stdout="Platforms: linux/arm64\n"))),
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=UUID_HEX)),
        "ownership_labels": lambda identity, **_options: {"org.repomap.unit": "owned"},
        "CurrentRunDockerContainers": Containers, "_start_server": step("server", ("server-1", server)),
        "_inventory": step("inventory", {"packages": [["libpq5", "17.6-1.pgdg120+1", "arm64"]], "files": [LIBPQ_FILE]}),
        "_hashes": step("hashes", {})}
    support_fakes: dict[str, Any] = {
        "locate_run_boundary": step("boundary", boundary), "verify_bases": bases, "stage_context": stage_context,
        "build_candidate": build_candidate, "write_report": write_report, "_ADMISSION": None}
    for name, value in owner_fakes.items():
        monkeypatch.setattr(real_owner, name, value)
    for name, value in support_fakes.items():
        monkeypatch.setattr(d12, name, value)
    monkeypatch.setattr(preflight, "explore", explore)
    monkeypatch.setattr(preflight, "_EXPLORATION", None)
    w.scratch = tmp_path / f"d12-{UUID_HEX[:12]}"
    w.scratch.mkdir()  # the owner's scratch directory; real context staging would have created it
    return w


def _call(real_owner: Any) -> Exception | None:
    try:
        real_owner.test_d12_core_image_refresh_candidate_round_trip()
    except Exception as error:
        return error
    return None


def _where(error: BaseException | None) -> str:
    """Exception plus its frame chain, so a control's failure names where it refused."""
    if error is None:
        return "no exception"
    frames = " > ".join(f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(error.__traceback__))
    return f"{type(error).__name__}: {str(error)[:300]} at {frames}"


def test_e1_observes_reports_returns_and_runs_custody_without_build_authority(real_owner, world, monkeypatch,
                                                                             tmp_path):
    exploration = _admission()
    monkeypatch.setattr(preflight, "_EXPLORATION", exploration)
    error = _call(real_owner)
    assert error is None and world.builds == [], f"{_where(error)}; build-helper calls {len(world.builds)}"
    assert world.events == [*BEFORE_E1, "explore", *CUSTODY], world.events
    assert world.contexts[0] is exploration and world.explored[0] is exploration, (world.contexts, world.explored)
    assert len(world.contexts) == len(world.explored) == 1 and d12._ADMISSION is None
    freeze = world.reports["freeze"]
    assert freeze["admission"] == vars(exploration), freeze["admission"]
    assert freeze["labels"]["org.repomap.d12.recipe_sha256"] == IDENTITY["recipe_sha256"], freeze["labels"]
    assert world.reports["cleanup"] == {"candidate_image_id": None, "server": "removed", "containers":
                                        "baseline_verified", "budget": ZERO, "zero_build": ZERO, "primary": None}, \
        world.reports["cleanup"]
    assert sorted(world.reports) == ["cleanup", "freeze"], sorted(world.reports)
    dockerfile = world.scratch / "Dockerfile"
    assert dockerfile.read_text(encoding="utf-8") == d12.recipe_text(), "the recipe text is the only owner write"
    assert sorted(tmp_path.rglob("*")) == [world.scratch, dockerfile], sorted(tmp_path.rglob("*"))


def test_e1_refusal_is_reported_after_owned_cleanup_and_never_reaches_the_build(real_owner, world, monkeypatch):
    exploration = _admission()
    monkeypatch.setattr(preflight, "_EXPLORATION", exploration)
    world.refuse = True
    error = _call(real_owner)
    assert isinstance(error, preflight.PreflightRefusal) and world.builds == [], \
        f"{_where(error)}; build-helper calls {len(world.builds)}"
    assert world.events == [*BEFORE_E1, "explore", *CUSTODY], world.events
    assert world.contexts == [exploration] and world.explored[0] is exploration, world.contexts
    cleanup = world.reports["cleanup"]
    assert (cleanup["server"], cleanup["containers"], cleanup["zero_build"]) == ("removed", "baseline_verified",
                                                                                ZERO), cleanup
    assert "E1 exploration refused" in str(cleanup["primary"]) and "error" not in cleanup, cleanup


@pytest.mark.parametrize("api", [160013, 170007])
def test_e1_numeric_oracle_refuses_an_api_not_bound_to_the_server_libpq_and_custody_still_runs(real_owner, world,
                                                                                               monkeypatch, api):
    # ADR 0091: the owner's own oracle, independent of the explore double, after the report and before the return.
    monkeypatch.setattr(preflight, "_EXPLORATION", _admission())
    world.api = api  # neither is the server's packaged 17.6 libpq5
    error = _call(real_owner)
    assert isinstance(error, AssertionError) and world.builds == [], _where(error)
    assert world.events == [*BEFORE_E1, "explore", *CUSTODY], world.events
    cleanup = world.reports["cleanup"]
    assert str(cleanup["primary"]).startswith("AssertionError") and cleanup["zero_build"] == ZERO, cleanup


@pytest.mark.parametrize("state, message", [("none", NO_ADMISSION), ("lost", NO_ADMISSION), ("mixed", MIXED)])
def test_missing_lost_or_mixed_admission_refuses_before_any_resource_call(real_owner, world, monkeypatch, state,
                                                                         message):
    if state != "none":
        monkeypatch.setattr(preflight, "_EXPLORATION", _admission())
    if state == "lost":  # the exploration slot is cleared after admission; the build slot stayed empty
        monkeypatch.setattr(preflight, "_EXPLORATION", None)
    if state == "mixed":  # both slots filled, as a direct support call bypassing the runner could
        monkeypatch.setattr(d12, "_ADMISSION", _admission())
    error = _call(real_owner)
    assert isinstance(error, d12.D12ProfileError) and message in str(error), _where(error)
    assert world.events == [] and world.builds == [] and world.reports == {}, (world.events, world.builds)


def test_build_mode_passes_its_actual_current_admission_to_the_build_trap(real_owner, world, monkeypatch):
    built = _admission()
    monkeypatch.setattr(d12, "_ADMISSION", built)
    error = _call(real_owner)
    assert isinstance(error, BuildTrap) and len(world.builds) == 1, f"{_where(error)}; builds {len(world.builds)}"
    assert world.builds[0] is built and world.contexts == [built] and world.contexts[0] is built, world.builds
    assert world.explored == [] and world.events == [*BEFORE_E1, *CUSTODY], world.events
    cleanup = world.reports["cleanup"]
    assert "zero_build" not in cleanup and cleanup["budget"] == ZERO and cleanup["server"] == "removed", cleanup
    assert str(cleanup["primary"]).startswith("BuildTrap") and cleanup["containers"] == "baseline_verified", cleanup


@pytest.mark.parametrize("argument, e1_message", [("none", GUARD), ("exploration", NO_ADMISSION),
                                                  ("foreign", NO_ADMISSION)])
def test_build_authority_guard_returns_only_the_current_build_admission(real_owner, monkeypatch, argument,
                                                                         e1_message):
    built, exploration = _admission(), _admission()
    assert exploration == built and exploration is not built, "equal fields, distinct authority"
    refused = {"none": None, "exploration": exploration, "foreign": _admission("linux/amd64")}[argument]
    monkeypatch.setattr(preflight, "_EXPLORATION", None)
    monkeypatch.setattr(d12, "_ADMISSION", built)
    assert real_owner._build_authority(built) is built, "ordinary build mode passes its admission unchanged"
    with pytest.raises(d12.D12ProfileError, match=GUARD):
        real_owner._build_authority(refused)
    monkeypatch.setattr(d12, "_ADMISSION", None)  # E1: exploration only, the build slot empty
    monkeypatch.setattr(preflight, "_EXPLORATION", exploration)
    with pytest.raises(d12.D12ProfileError, match=e1_message):
        real_owner._build_authority(refused)
