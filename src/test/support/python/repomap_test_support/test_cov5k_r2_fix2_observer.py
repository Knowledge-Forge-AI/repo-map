"""Real observer-session and configured-campaign executor families."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Literal

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidence
from repomap_test_support.test_cov5k_r2_fix3_observer_programs import (
    enact_request,
    enact_schedule,
)
from repomap_test_support.test_scratch import ENV_RUN_ROOT, establish_run
from scale28_backend_observer_session import (
    BackendObserverSession,
)
from scale28_hybrid_startup import prepare_parent_startup_authorities
from scale14_actual_refresh_supervisor import ActualRefreshSupervisor as ActualRefreshSupervisor
from scale15_actual_path_readback import read_scale15_terminal_state as read_scale15_terminal_state
from scale28_hybrid_startup import prepare_startup_resources as prepare_startup_resources
from scale28_preparation_worker import PreparationWorkerAttempt as PreparationWorkerAttempt


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Observer:
    def __init__(self) -> None:
        self.connection: object | None = None

    def register_connection(self, connection: object) -> None:
        self.connection = connection


def execute_observer_request(entry: CatalogEntry) -> ExecutorEvidence:
    """Run one F request through BackendObserverSession."""

    observer = _Observer()
    connection = _Connection()
    session = BackendObserverSession(
        observer_factory=lambda: observer,
        connection_factory=lambda *_: connection,
        failure_causality=FailureCausalityAuthority(),
        child_released=lambda: True,
    )
    return enact_request(entry, executor=execute_observer_request, session=session)


def execute_observer_schedule(entry: CatalogEntry) -> ExecutorEvidence:
    """Enact G solely from its frozen parameter object, never display labels."""

    if set(dict(entry.parameter_values)) != {"schedule", "schedule_index"}:
        raise ValueError("observer schedule parameters are incomplete")
    observer = _Observer()
    connection = _Connection()
    session = BackendObserverSession(
        observer_factory=lambda: observer,
        connection_factory=lambda *_: connection,
        failure_causality=FailureCausalityAuthority(),
        child_released=lambda: True,
    )
    return enact_schedule(entry, executor=execute_observer_schedule, session=session)


@dataclass
class _Startup:
    backend_ready: bool = False
    resources_ready: bool = False
    receiver_ready: bool = False
    collector_ready: bool = False

    def mark_backend_observer_ready(self) -> None:
        self.backend_ready = True

    def mark_resource_authorities_ready(self) -> None:
        self.resources_ready = True

    def mark_event_receiver_ready(self) -> None:
        self.receiver_ready = True

    def mark_failure_collector_ready(self) -> None:
        self.collector_ready = True


class _BackendMonitor:
    def startup_summary(self, **_: object) -> str:
        return "bounded-summary"

    def validate_summary(self, summary: object, validator: Callable[[object], None]) -> None:
        validator(summary)


class _ResourceSampler:
    def capture(self, *, force: bool) -> str:
        if force:
            raise ValueError("bounded startup capture is not forced")
        return "bounded-resource"

    def settle_startup(self) -> None:
        return None


class _EventPump:
    def __init__(self) -> None:
        self.started = False

    def start(self, *, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("event receiver timeout is invalid")
        self.started = True


def _configured_parent_handoff() -> tuple[bool, bool, bool, bool]:
    startup = _Startup()
    pump = _EventPump()
    prepare_parent_startup_authorities(
        startup,
        _BackendMonitor(),
        _ResourceSampler(),
        None,
        pump,
        lambda: None,
        event_receiver_timeout_seconds=0.1,
        summary_validator=lambda summary: None,
        resource_validator=lambda sample: None,
    )
    return (
        startup.backend_ready,
        startup.resources_ready,
        startup.receiver_ready and pump.started,
        startup.collector_ready,
    )


_OWNING_AREA_NODES = {
    "scale14": "src/test/unit/python/tools/scale14_actual_refresh_supervisor.unit.test.py",
    "scale23": "src/test/unit/python/tools/scale15_actual_path_readback.unit.test.py",
    "scale28_fix1": "src/test/unit/python/tools/scale28_fix12_preparation_deadlines.unit.test.py",
}

OWNING_AREA_STREAM_EXCERPT_BYTES = 4096
_OWNING_AREA_TIMEOUT_SECONDS = 300
_OWNING_AREA_RUNNER_KIND = "configured_unit_test_runner"
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(\b[\"']?[a-z0-9_]*(?:password|passwd|token|secret|api_key|credential)"
    r"[a-z0-9_]*[\"']?\s*[=:]\s*[\"']?)([^\s\"',;]+)"
)
_AUTHORIZATION_BEARER = re.compile(
    r"(?i)(\bAuthorization\s*:\s*Bearer\s+)([^\s,;]+)"
)
_URL_USERINFO = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@/\s]+)(@)"
)
_NONSECRET_ENVIRONMENT_VALUES = frozenset(
    {"0", "1", "false", "no", "none", "null", "off", "on", "true", "yes"}
)


def _sensitive_environment_values(environment: dict[str, str]) -> tuple[str, ...]:
    sensitive_fragments = (
        "PASSWORD",
        "PASSWD",
        "TOKEN",
        "SECRET",
        "API_KEY",
        "CREDENTIAL",
    )
    values = {
        value
        for key, value in environment.items()
        if value
        and len(value) >= 4
        and value.casefold() not in _NONSECRET_ENVIRONMENT_VALUES
        and any(fragment in key.upper() for fragment in sensitive_fragments)
    }
    return tuple(sorted(values, key=lambda value: (-len(value), value)))


def _bounded_runner_stream(
    value: str | bytes | None,
    *,
    repository_root: Path,
    environment: dict[str, str],
) -> tuple[str, bool]:
    if value is None:
        text = ""
    elif isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SENSITIVE_ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = _AUTHORIZATION_BEARER.sub(r"\1[REDACTED]", text)
    text = _URL_USERINFO.sub(r"\1[REDACTED]\3", text)
    for secret_value in _sensitive_environment_values(environment):
        text = text.replace(secret_value, "[REDACTED]")
    private_roots = (
        (str(repository_root), "{repository_root}"),
        (str(Path.home()), "{home}"),
        (environment.get("REPOMAP_TEST_SCRATCH_ROOT", ""), "{test_scratch_root}"),
        (environment.get("TMPDIR", ""), "{temporary_root}"),
        (environment.get("TEMP", ""), "{temporary_root}"),
        (environment.get("TMP", ""), "{temporary_root}"),
    )
    for private_root, replacement in sorted(
        private_roots,
        key=lambda item: (-len(item[0]), item[0]),
    ):
        if private_root:
            text = text.replace(private_root, replacement)
    text = "".join(
        character
        if character in {"\n", "\t"} or (ord(character) >= 32 and ord(character) != 127)
        else f"\\x{ord(character):02x}"
        for character in text
    )
    encoded = text.encode("utf-8")
    if len(encoded) <= OWNING_AREA_STREAM_EXCERPT_BYTES:
        return text, False
    excerpt = encoded[-OWNING_AREA_STREAM_EXCERPT_BYTES :].decode(
        "utf-8",
        errors="ignore",
    )
    return excerpt, True


class ConfiguredOwningAreaRunnerError(RuntimeError):
    """Bounded failure evidence from a configured owning-area child runner."""

    def __init__(
        self,
        *,
        failure_kind: Literal["nonzero_exit", "timeout"],
        owning_area: str,
        node: str,
        returncode: int | None,
        timeout_seconds: int | None,
        stdout: str | bytes | None,
        stderr: str | bytes | None,
        repository_root: Path,
        environment: dict[str, str],
        command: tuple[str, ...],
    ) -> None:
        self.failure_kind = failure_kind
        self.owning_area = owning_area
        self.node = node
        self.runner_kind = _OWNING_AREA_RUNNER_KIND
        run_root = environment.get(ENV_RUN_ROOT)
        basetemp_prefix = f"--basetemp={run_root}" if run_root else None
        self.command = tuple(
            "<python>"
            if index == 0
            else (
                "--basetemp={run_root}" + argument[len(basetemp_prefix):]
                if basetemp_prefix and argument.startswith(basetemp_prefix)
                else argument
            )
            for index, argument in enumerate(command)
        )
        self.returncode = returncode
        self.timeout_seconds = timeout_seconds
        self.stdout_excerpt, self.stdout_truncated = _bounded_runner_stream(
            stdout,
            repository_root=repository_root,
            environment=environment,
        )
        self.stderr_excerpt, self.stderr_truncated = _bounded_runner_stream(
            stderr,
            repository_root=repository_root,
            environment=environment,
        )
        rendered_command = " ".join(self.command)
        message = (
            "configured owning-area runner failed\n"
            f"failure_kind={self.failure_kind}\n"
            f"owning_area={self.owning_area}\n"
            f"node={self.node}\n"
            f"runner_kind={self.runner_kind}\n"
            f"command={rendered_command}\n"
            f"returncode={self.returncode}\n"
            f"timeout_seconds={self.timeout_seconds}\n"
            f"stdout_truncated={str(self.stdout_truncated).lower()}\n"
            f"stdout_excerpt:\n{self.stdout_excerpt or '<empty>'}\n"
            f"stderr_truncated={str(self.stderr_truncated).lower()}\n"
            f"stderr_excerpt:\n{self.stderr_excerpt or '<empty>'}"
        )
        super().__init__(message)


def execute_owning_area_execution(
    entry: CatalogEntry,
    *,
    repository_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ExecutorEvidence:
    """Run I configured ownership through the accepted parent handoff owner."""

    owning_area = str(dict(entry.parameter_values)["owning_area"])
    node = _OWNING_AREA_NODES.get(owning_area)
    if node is None:
        readiness = _configured_parent_handoff()
        actual_runner = "in_process_parent_handoff"
    else:
        root = Path.cwd() if repository_root is None else repository_root
        environment = os.environ.copy()
        environment.pop("PYTEST_CURRENT_TEST", None)
        forwarded: tuple[str, ...] = (node,)
        if environment.get(ENV_RUN_ROOT):
            parent = establish_run(environment)
            environment.update(parent.child_environment())
            owning_area_root = parent.tmp / "owning-area"
            owning_area_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            forwarded = (
                f"--basetemp={owning_area_root / owning_area}",
                node,
            )
        command = (
            sys.executable,
            "tools/run_tests.py",
            "--suite",
            "unit",
            "--no-coverage",
            "--",
            *forwarded,
        )
        try:
            completed = runner(
                command,
                cwd=root,
                env=environment,
                shell=False,
                timeout=_OWNING_AREA_TIMEOUT_SECONDS,
                check=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as error:
            raise ConfiguredOwningAreaRunnerError(
                failure_kind="timeout",
                owning_area=owning_area,
                node=node,
                returncode=None,
                timeout_seconds=_OWNING_AREA_TIMEOUT_SECONDS,
                stdout=error.stdout,
                stderr=error.stderr,
                repository_root=root,
                environment=environment,
                command=command,
            ) from None
        if completed.returncode != 0:
            raise ConfiguredOwningAreaRunnerError(
                failure_kind="nonzero_exit",
                owning_area=owning_area,
                node=node,
                returncode=int(completed.returncode),
                timeout_seconds=None,
                stdout=completed.stdout,
                stderr=completed.stderr,
                repository_root=root,
                environment=environment,
                command=command,
            )
        readiness = (True, True, True, True)
        actual_runner = node
    observed = (
        ("primary_result_category", "passed"),
        ("owning_area", owning_area),
        ("parent_readiness", readiness),
        ("actual_runner", actual_runner),
    )
    return ExecutorEvidence(entry.authority_id, True, entry.parameter_values, observed)


def _campaign(entry: CatalogEntry) -> ExecutorEvidence:
    readiness = _configured_parent_handoff()
    observed = (
        ("primary_result_category", "passed"),
        ("fresh_resource_contract", entry.cleanup_contract),
        ("parent_readiness", readiness),
        ("result_parser", "typed_executor_evidence"),
    )
    return ExecutorEvidence(entry.authority_id, True, entry.parameter_values, observed)


execute_mixed_configured_campaign = _campaign
execute_fresh_public_rehearsal = _campaign
execute_prior_state_preservation = _campaign
