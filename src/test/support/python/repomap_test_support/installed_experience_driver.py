"""Ordered installed-experience steps, outcome classification, cleanup and bundle custody.

Each owner records its recipe rows once, in order. An action only gathers
observed facts from child outputs and filesystem witnesses; the driver compares
them with the owner's frozen intent and classifies the row. After a required
failure the remaining rows are ``not-reached``; the terminal ``X01`` cleanup row
always runs. ``KeyboardInterrupt``/``SystemExit`` record the row and the owned
cleanup, then propagate unchanged without a verdict. Bundles reuse the unchanged
first-use location rule (``default_bundle_base``) below ``installed-experience``.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from installed_experience_bundle import owner_base, write_owner_bundle
from installed_experience_domains import FAILURE_CODES, SCHEMA_OBSERVATION, InstalledError, observation_name
from installed_experience_records import decode_intent, encode_observation
from installed_experience_validation import exit_holds
from installed_experience_reconcile import Verdict, sha256_hex
from installed_experience_source_identity import (
    Preparation, candidate_census_sha256, fixture_census_sha256, owner_intent,
)
from repomap_test_support.first_use_workload_driver import default_bundle_base, new_attempt
from repomap_test_support.installed_environment import ChildExecutionFailure


@dataclass
class Observed:
    """What one action witnessed; facts map a key to ``(value, source)``."""

    facts: dict[str, tuple[Any, str]] = field(default_factory=dict)
    exit: int | None = None
    stderr_class: str = "not-captured"
    origin_classes: dict[str, int] | None = None
    projection: dict[str, Any] | None = None
    failure_code: str | None = None
    unknown: bool = False


Action = Callable[[], Observed]


class CleanupRegistry:
    """Exact owned roots, removed only after children are reaped; never swept."""

    def __init__(self) -> None:
        self.roots: list[Path] = []
        self.retained: list[Path] = []

    def own(self, path: Path) -> Path:
        self.roots.append(path)
        return path

    def retain(self, path: Path) -> None:
        """An unproved worker workspace: reported, never deleted or accepted."""
        self.retained.append(path)

    def run(self) -> str:
        state = "removed"
        for root in reversed(self.roots):
            if any(held == root or held.is_relative_to(root) or root.is_relative_to(held)
                   for held in self.retained):
                state = "retained-reported"
                continue
            if not remove_owned_root(root):
                state = "retained-reported"
        if self.retained:
            state = "retained-reported"
        self.roots.clear()
        return state


def _safe_ancestors(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current = current / part
        details = os.lstat(current)
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            return False
    return True


def remove_owned_root(root: Path) -> bool:
    """Remove one exact owned root; symlink leaves are unlinked, never followed."""
    try:
        details = os.lstat(root)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        if not _safe_ancestors(root) or details.st_uid != os.geteuid():
            return False
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            os.unlink(root)
        else:
            if not shutil.rmtree.avoids_symlink_attacks:
                return False
            shutil.rmtree(root)
    except OSError:
        return False
    return not os.path.lexists(root)


class OwnerRun:
    """One owner's ordered rows against its frozen intent."""

    def __init__(self, owner: str, intent: bytes, registry: CleanupRegistry | None = None,
                 attempt: str | None = None) -> None:
        decoded = decode_intent(intent)
        if decoded["owner"] != owner:
            raise InstalledError("binding-mismatch")
        self.owner, self.intent, self.attempt = owner, intent, attempt or new_attempt()
        self.rows = {row["id"]: row for row in decoded["scenarios"]}
        self.order = [row["id"] for row in decoded["scenarios"]]
        self.registry = registry or CleanupRegistry()
        self.observations: list[tuple[str, bytes]] = []
        self.mismatches: dict[str, list[str]] = {}
        self.primary: str | None = None

    def _encode(self, scenario: str, outcome: str, observed: Observed, cleanup: str) -> bytes:
        row = self.rows[scenario]
        payload = {
            "schema": SCHEMA_OBSERVATION, "owner": self.owner, "attempt": self.attempt,
            "intent": sha256_hex(self.intent), "scenario": scenario, "seq": len(self.observations) + 1,
            "env_class": row["env_class"], "family": row["family"], "exit": observed.exit,
            "outcome": outcome, "stderr_class": observed.stderr_class,
            "facts": {key: {"value": value, "source": source}
                      for key, (value, source) in sorted(observed.facts.items())
                      if key in row["expected"] and (type(value) is not str
                          or (type(row["expected"][key]) is str and value == row["expected"][key]))},
            "origin_classes": observed.origin_classes, "projection": observed.projection,
            "cleanup": cleanup,
            "failure_code": observed.failure_code if outcome in ("failed", "unknown") else None,
        }
        try:
            return encode_observation(payload)
        except InstalledError as error:
            code = observed.failure_code if observed.failure_code in FAILURE_CODES else (
                "unbounded-output" if error.category == "bound-exceeded" else "witness-failed")
            payload.update(outcome="unknown" if observed.unknown else "failed", facts={}, origin_classes=None, projection=None,
                           exit=None, stderr_class="not-captured",
                           failure_code=code)
            return encode_observation(payload)

    def classify(self, scenario: str, observed: Observed) -> str:
        row = self.rows[scenario]
        if observed.unknown:
            observed.failure_code = observed.failure_code or "child-deadline"
            return "unknown"
        if observed.failure_code is not None:
            if observed.failure_code not in FAILURE_CODES:
                observed.failure_code = "call-failed"
            return "failed"
        if not exit_holds(row, observed.exit):
            observed.failure_code = "child-signalled" if observed.exit is not None and observed.exit < 0 else "child-exit-nonzero"
            return "failed"
        extra = sorted(set(observed.facts) - set(row["expected"]))
        wrong = sorted(key for key, value in row["expected"].items()
                       if key not in observed.facts or type(observed.facts[key][0]) is not type(value)
                       or observed.facts[key][0] != value)
        if extra or wrong:
            self.mismatches[scenario] = sorted(wrong + (["undeclared-fact"] if extra else []))
            observed.failure_code = "fact-unobserved"
            return "failed"
        return "passed" if row["expectation"] == "pass" else "expected-refusal"

    def step(self, scenario: str, action: Action) -> str:
        """Record one row once; a required failure makes later rows ``not-reached``."""
        if scenario != self.order[len(self.observations)]:
            raise InstalledError("order-violation")
        if self.primary is not None:
            self.observations.append((observation_name(len(self.observations) + 1),
                                      self._encode(scenario, "not-reached", Observed(), "not-applicable")))
            return "not-reached"
        try:
            observed = action()
            outcome = self.classify(scenario, observed)
        except (KeyboardInterrupt, SystemExit) as error:
            if "installed-child-workspace-unproved" in getattr(error, "__notes__", ()):
                for root in self.registry.roots:
                    self.registry.retain(root)
            interrupted = Observed(failure_code="interrupted", unknown=True)
            self.observations.append((observation_name(len(self.observations) + 1),
                                      self._encode(scenario, "unknown", interrupted, "not-applicable")))
            self.registry.run()
            raise
        except ChildExecutionFailure as error:
            observed = Observed(failure_code=error.code, unknown=error.unknown)
            outcome = self.classify(scenario, observed)
        except InstalledError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            observed = Observed(failure_code=code if code in FAILURE_CODES else "call-failed")
            outcome = "failed"
        if observed.unknown:
            for root in self.registry.roots:
                self.registry.retain(root)
        self.observations.append((observation_name(len(self.observations) + 1),
                                  self._encode(scenario, outcome, observed, "not-applicable")))
        if outcome not in ("passed", "expected-refusal"):
            self.primary = scenario
        return outcome

    def finish(self, temporary: Path) -> tuple[Path, Verdict]:
        """Run the terminal cleanup row, then write intent, rows, index and verdict."""
        for scenario in self.order[len(self.observations):-1]:
            self.step(scenario, lambda: Observed(failure_code="prerequisite-failed"))
        state = self.registry.run()
        observed = Observed(facts={"cleanup": (state, "filesystem")})
        outcome = self.classify("X01", observed)
        self.observations.append((observation_name(len(self.observations) + 1),
                                  self._encode("X01", outcome, observed, state)))
        base = owner_base(default_bundle_base(temporary), self.owner)
        return write_owner_bundle(base, self.owner, self.attempt, self.intent, self.observations)


def preparation(candidate: Any, incumbent: Any = None) -> Preparation:
    """Shared wheel bindings, observed from the built bytes before any owner intent."""
    from repomap_test_support.installed_candidate import inventory_sha256, wheel_inventory

    inventory = wheel_inventory(candidate.wheel)
    data = candidate.wheel.read_bytes()
    return Preparation(
        candidate_input_sha256=candidate.input_sha256, candidate_input_count=candidate.input_count,
        wheel_sha256=sha256_hex(data), wheel_bytes=len(data),
        wheel_member_count=len(inventory.names), inventory_sha256=inventory_sha256(inventory.names),
        incumbent_wheel_sha256=None if incumbent is None else sha256_hex(incumbent.wheel.read_bytes()),
    )


def intent_for(owner: str, prepared: Preparation, source_values: dict[str, dict[str, Any]]) -> bytes:
    """Freeze one owner's intent from preparation and source-computed values only."""
    return owner_intent(
        owner, prepared, source_values, fixture_digest=fixture_census_sha256(),
        candidate_census=candidate_census_sha256(), python=platform.python_version(),
        platform=platform.machine().lower(),
    )


def pure_environment(root: Path, candidate: Any, env_class: str = "pure-local") -> Any:
    """Prerequisite: install the wheel, project the verified SDK dependency, ``pip check``."""
    from repomap_test_support.installed_environment import create_environment, install_wheel, pip_check
    from repomap_test_support.installed_projection import (
        project_sdk_distribution, requirement_from_wheel,
    )

    env = create_environment(root, env_class)
    installed = install_wheel(env, candidate.wheel)
    if installed.returncode != 0:
        raise AssertionError("installed-environment prerequisite: install failed")
    if env_class != "provisioned-server":
        distribution, version_tag = candidate.wheel.name.split("-")[:2]
        name, version = requirement_from_wheel(candidate.wheel, f"{distribution}-{version_tag}.dist-info")
        project_sdk_distribution(name, version, env.purelib)
        if pip_check(env).returncode != 0:
            raise AssertionError("installed-environment prerequisite: pip check failed")
    return env


def json_object(stdout: str) -> dict[str, Any] | None:
    """Parse one child's JSON stdout privately; never exported."""
    import json

    try:
        payload = json.loads(stdout)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def observed_code(stdout: str, stderr: str, codes: tuple[str, ...]) -> str:
    """The closed refusal code a child printed, or the first ``ERROR:`` token, else ``other``."""
    for code in codes:
        if code in stderr or code in stdout:
            return code
    first = stderr.splitlines()[0] if stderr else ""
    return first.removeprefix("ERROR: ").split(":", 1)[0].strip() or "other"


def guarded_argv(env: Any, *args: str) -> list[str]:
    """``<env>/bin/python -I <stdlib-only guard> <cli args>``; ``-I`` keeps its directory off ``sys.path``."""
    from repomap_test_support import sqlite_local_guard

    return [str(env.python), "-I", str(Path(sqlite_local_guard.__file__)), *args]


def guard_extra(log: Path, *, block: bool = True) -> dict[str, str]:
    from repomap_test_support import sqlite_local_guard

    extra = {sqlite_local_guard.GUARD_LOG_ENV: str(log)}
    if block:
        extra[sqlite_local_guard.BLOCK_PSYCOPG_ENV] = "1"
    return extra


def guard_events(log: Path) -> list[dict[str, Any]]:
    import json

    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


BLOCKER_PROBE = (
    "import os, runpy, sys\n"
    "guard = runpy.run_path(sys.argv[1])\n"
    "guard['_install_psycopg_blocker']()\n"
    "try:\n    import psycopg\nexcept ModuleNotFoundError:\n    print('blocked')\n"
)


def blocker_probe(env: Any, log: Path) -> str | None:
    """Deliberate installed import through the stdlib-only blocker; the log is the witness."""
    from repomap_test_support import sqlite_local_guard
    from repomap_test_support.installed_environment import run_child

    result = run_child(env, (str(env.python), "-I", "-c", BLOCKER_PROBE,
                             str(Path(sqlite_local_guard.__file__))), extra=guard_extra(log, block=False))
    events = [event for event in guard_events(log) if event.get("detail") == "psycopg"]
    if result.returncode != 0 or not events:
        return None
    return str(events[-1]["kind"])


def publish_tiny(env: Any, home: Path, log: Path, graph_id: str) -> int | None:
    """Setup used by the mcp and migration owners: init, then one guarded refresh."""
    from repomap_test_support.installed_environment import run_child

    init = run_child(env, (str(env.wrapper("cloe")), "ops", "sqlite-init", "--repo-map-home", str(home),
                           "--graph", graph_id, "--json"))
    if init.returncode != 0:
        return None
    refresh = run_child(env, guarded_argv(env, "ops", "refresh-graph", "--repo-map-home", str(home),
                                          "--graph", graph_id, "--json"), extra=guard_extra(log))
    payload = json_object(refresh.stdout) if refresh.returncode == 0 else None
    generation = None if payload is None else payload.get("accepted_generation")
    return generation if type(generation) is int else None


__all__ = [
    "Action", "BLOCKER_PROBE", "CleanupRegistry", "Observed", "OwnerRun", "blocker_probe",
    "guard_events", "guard_extra", "guarded_argv", "intent_for", "json_object", "observed_code",
    "preparation", "publish_tiny", "pure_environment", "remove_owned_root",
]
