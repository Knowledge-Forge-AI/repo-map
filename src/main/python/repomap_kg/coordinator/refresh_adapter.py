"""Single-attempt capability boundary for the ASYNC4 refresh pilot."""

from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Mapping, cast

from repomap_kg.coordinator._transport_validation import (
    sanitize_diagnostic_summary,
    truncate_diagnostic_bytes as _truncate_bytes,
)

from repomap_kg.coordinator._protocol_core import (
    ProtocolError,
    SyntheticWorkerResult,
    _KNOWN_ARRAY_CATEGORIES,
    _run_protocol_worker,
)
from repomap_kg.coordinator._refresh_capability import (
    RefreshCapability,
    ResolvedRefreshAuthority,
    create_refresh_capability,
    load_refresh_capability,
    remove_refresh_capability,
)
from repomap_kg.coordinator._refresh_contracts import (
    RefreshClaim,
    RefreshConfigurationError,
    RefreshGenerationChangedError,
    RefreshSourceError,
)
from repomap_kg.coordinator._refresh_generation import (
    generation_changed_terminal,
    psql_configuration_terminal,
)
from repomap_kg.coordinator._worker_environment import (
    add_windows_runtime_environment,
)


def _refresh_attempt_supervision_limits(limits: object) -> object:
    from repomap_kg.coordinator.limits import CoordinatorLimits

    att = limits.get("refresh_attempt_deadline_seconds") if isinstance(limits, Mapping) else getattr(limits, "refresh_attempt_deadline_seconds", None)
    proc = limits.get("process_deadline_seconds") if isinstance(limits, Mapping) else getattr(limits, "process_deadline_seconds", None)
    if att is None:
        raise ValueError("refresh_attempt_deadline_seconds is required for refresh worker supervision")
    if proc is not None and att <= proc:
        raise ValueError("refresh_attempt_deadline_seconds must be greater than process_deadline_seconds")
    if isinstance(limits, CoordinatorLimits):
        return replace(limits, process_deadline_seconds=att)
    if isinstance(limits, Mapping):
        return {**limits, "process_deadline_seconds": att}
    projected = copy.copy(cast(Any, limits))
    setattr(projected, "process_deadline_seconds", att)
    return projected


def run_refresh_worker(
    capability_path: Path,
    identity: Mapping[str, object],
    limits: object,
    *,
    job_context: Mapping[str, object],
    cancel_event: threading.Event | None = None,
) -> SyntheticWorkerResult:
    """Run the one allowlisted production refresh worker through v1 protocol."""

    supervision_limits = _refresh_attempt_supervision_limits(limits)
    capability = load_refresh_capability(capability_path)
    from repomap_kg.coordinator import _publication_phase

    try:
        if (
            capability.job_id != identity.get("job_id")
            or capability.attempt != identity.get("attempt")
            or capability.graph_id != job_context.get("graph_id")
            or capability.source_generation != job_context.get("source_generation")
            or capability.config_generation != job_context.get("config_generation")
        ):
            raise ProtocolError("identity_mismatch")
        repo_root = Path(__file__).resolve().parents[5]
        work_dir = (
            capability.config_path.parent
            if capability.config_path.parent.is_dir()
            else repo_root
        )
        environment = {
            "PATH": os.pathsep.join(str(path) for path in capability.executable_search_path),
            "PGUSER": capability.postgres_user,
            "PGPASSWORD": capability.postgres_password,
            "PSQLRC": os.devnull,
            "LANG": "C",
            "LC_ALL": "C",
        }
        for pg_var in ("PGHOST", "PGPORT", "PGDATABASE", "PGSSLMODE"):
            if pg_var in os.environ:
                environment[pg_var] = os.environ[pg_var]
        if (repo_root / "src/main/python").is_dir():
            environment["PYTHONPATH"] = str(repo_root / "src/main/python")
        elif "PYTHONPATH" in os.environ:
            environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
        for pvar in ("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", "_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH"):
            if pvar in os.environ:
                environment[pvar] = os.environ[pvar]
        add_windows_runtime_environment(environment)
        from repomap_kg.coordinator._refresh_execution import _is_safe_test_path
        timeout_trigger_str = os.environ.get("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER")
        timeout_probe = None
        if timeout_trigger_str:
            tp = Path(timeout_trigger_str)
            if _is_safe_test_path(tp):
                timeout_probe = lambda: tp.is_file() and not tp.is_symlink()
        _publication_phase.initialize(capability_path.parent, capability)
        result = _run_protocol_worker(
            (
                sys.executable,
                "-m",
                "repomap_kg.coordinator.refresh_worker",
                "--capability",
                str(capability_path),
                "--job-id",
                str(identity["job_id"]),
                "--attempt",
                str(identity["attempt"]),
            ),
            environment,
            work_dir,
            False,
            identity,
            supervision_limits,
            job_context=job_context,
            cancel_event=cancel_event,
            _timeout_probe=timeout_probe,
        )
        if result.waited and result.process_group_cleaned:
            state = _publication_phase.publication_state(
                capability_path.parent, capability, close_unpublished=True
            )
            cancelled = cancel_event is not None and cancel_event.is_set()
            if result.synthesized_terminal or result.process_timed_out or result.heartbeat_timed_out or cancelled:
                err = "cancelled" if cancelled else (
                    "protocol" if result.protocol_error else (
                        "worker_timeout" if result.process_timed_out or result.heartbeat_timed_out else "worker_crash"
                    )
                )
                result = replace(result, terminal={
                    **result.terminal, "publication_state": state,
                    "status": "cancelled" if cancelled else "failed", "error_category": err,
                })
            elif state == "not_started" and result.terminal.get("publication_state") == "commit_unknown":
                result = replace(result, terminal={**result.terminal, "publication_state": state})
        return result
    finally:
        remove_refresh_capability(capability_path)


def refresh_terminal(
    capability: RefreshCapability, result: object
) -> dict[str, object]:
    """Map the existing forced-full result without reimplementing refresh semantics."""

    capability.validate()
    succeeded = getattr(result, "result", None) == "success"
    started_at = getattr(result, "started_at", None)
    finished_at = getattr(result, "finished_at", None)
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        raise ValueError("invalid refresh result")
    run_id = getattr(result, "run_id", None)
    if succeeded and (not isinstance(run_id, int) or isinstance(run_id, bool)):
        raise ValueError("invalid refresh result")
    return {
        "schema_version": 1,
        "message_type": "result" if succeeded else "error",
        "job_id": capability.job_id,
        "attempt": capability.attempt,
        "job_kind": "refresh_graph",
        "graph_id": capability.graph_id,
        "status": "succeeded" if succeeded else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "phase": "complete" if succeeded else "storage_publish",
        "files": _nonnegative_count(getattr(result, "files", None)),
        "observations": _nonnegative_count(
            getattr(result, "observations", None)
        ),
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": [
            code
            for code in (
                str(d["code"]) if isinstance(d, dict) and "code" in d else str(d)
                for d in getattr(result, "diagnostics", ())
                if isinstance(d, (dict, str))
            )
            if code in _KNOWN_ARRAY_CATEGORIES
        ][:8],
        "publication_state": getattr(
            result, "publication_state", "committed" if succeeded else "commit_unknown"
        ),
        "latest_run_identity": f"run-{run_id}" if succeeded else None,
        "source_generation": capability.source_generation,
        "config_generation": capability.config_generation,
        "extractor_generation": capability.extractor_generation,
        "canonicalizer_generation": capability.canonicalizer_generation,
        "retryable": False,
        "error_category": None if succeeded else (
            "publication_unknown"
            if getattr(result, "publication_state", "commit_unknown") == "commit_unknown"
            else getattr(result, "error_category", None) or "worker_crash"
        ),
    }


def execute_refresh(
    capability: RefreshCapability, *, before_publication: Callable[[], None] | None = None,
) -> object:
    """Delegate exactly once to the existing forced-full refresh implementation."""

    from repomap_kg.coordinator._refresh_execution import execute_refresh_attempt

    return execute_refresh_attempt(capability, before_publication=before_publication)


def build_refresh_worker_runner(
    resolve: Callable[[str], ResolvedRefreshAuthority],
    capability_directory: Path,
    limits: object,
) -> Callable[[RefreshClaim, threading.Event], Mapping[str, object]]:
    """Build the explicit pilot runner used by the existing coordinator core."""

    _refresh_attempt_supervision_limits(limits)
    raw_leaf = limits.get("process_deadline_seconds") if isinstance(limits, Mapping) else getattr(limits, "process_deadline_seconds", None)
    if not isinstance(raw_leaf, int) or isinstance(raw_leaf, bool) or not (0 < raw_leaf <= 3600):
        raise ValueError("process_deadline_seconds must be a positive integer <= 3600")
    leaf_deadline = raw_leaf

    def run(
        claim: RefreshClaim, cancel_event: threading.Event
    ) -> Mapping[str, object]:
        try:
            authority = resolve(claim.graph_id)
        except RefreshSourceError as error:
            terminal = dict(generation_changed_terminal(claim))
            terminal["error_category"] = error.category
            terminal["_error_category"] = error.category
            return terminal
        claim_generations = (
            claim.source_generation, claim.config_generation,
            claim.extractor_generation, claim.canonicalizer_generation,
        )
        authority_generations = (
            authority.source_generation, authority.config_generation,
            authority.extractor_generation, authority.canonicalizer_generation,
        )
        if authority.graph_id != claim.graph_id:
            raise ValueError("invalid refresh capability")
        if authority_generations != claim_generations:
            return generation_changed_terminal(claim)
        capability = RefreshCapability(
            schema_version=1, job_id=claim.job_id, attempt=claim.attempt,
            graph_id=claim.graph_id, config_path=authority.config_path,
            psql_path=authority.psql_path, postgres_user=authority.postgres_user,
            postgres_host=authority.postgres_host, postgres_port=authority.postgres_port,
            postgres_route_kind=authority.postgres_route_kind,
            postgres_password=authority.postgres_password,
            executable_search_path=authority.executable_search_path,
            source_generation=claim.source_generation,
            config_generation=claim.config_generation,
            extractor_generation=claim.extractor_generation, canonicalizer_generation=claim.canonicalizer_generation,
            coordinator_instance_id=claim.instance_id,
            singleton_fencing_epoch=claim.fencing_epoch, graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
            process_deadline_seconds=leaf_deadline,
        )
        try:
            path = create_refresh_capability(capability_directory, capability)
        except RefreshConfigurationError:
            return psql_configuration_terminal(claim)
        result = run_refresh_worker(
            path,
            {"job_id": claim.job_id, "attempt": claim.attempt},
            limits,
            job_context={
                "graph_id": claim.graph_id,
                "source_generation": claim.source_generation,
                "config_generation": claim.config_generation,
            },
            cancel_event=cancel_event,
        )
        if result.protocol_error is not None:
            category = "protocol"
        elif result.process_timed_out or result.heartbeat_timed_out:
            category = "worker_timeout"
        elif not result.synthesized_terminal:
            category = str(
                result.terminal.get("error_category") or "publication_unknown"
            )
        else:
            category = "worker_crash"
        return {
            **result.terminal,
            "_termination_proved": result.waited and result.process_group_cleaned,
            "_error_category": category,
            "_diagnostic_summary": _extract_diagnostic_summary(result),
        }

    return run


_GENERIC_FAILURE_DIAGNOSTICS = frozenset({"refresh-failed"})


def _extract_diagnostic_summary(result: object) -> str | None:
    stderr = getattr(result, "stderr", None)
    refresh_failure_line: str | None = None
    if isinstance(stderr, str) and stderr:
        for line in stderr.splitlines():
            stripped = line.strip()
            if stripped.startswith("refresh-failure:"):
                refresh_failure_line = stripped
                break

    terminal = getattr(result, "terminal", None)
    if isinstance(terminal, dict):
        term_diags = terminal.get("diagnostics")
        if isinstance(term_diags, list) and term_diags:
            codes = [str(d) for d in term_diags if isinstance(d, (str, int))]
            if codes:
                is_generic = all(c in _GENERIC_FAILURE_DIAGNOSTICS for c in codes)
                if not (is_generic and refresh_failure_line is not None):
                    return sanitize_diagnostic_summary(";".join(codes[:8]))

    if isinstance(stderr, str) and stderr.strip():
        truncated = getattr(result, "stderr_truncated", False)
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        target_line = refresh_failure_line or (lines[0] if lines else "")
        if target_line:
            redacted = sanitize_diagnostic_summary(target_line)
            if redacted is not None and truncated and len(redacted.encode("utf-8")) >= 253:
                return _truncate_bytes(redacted, 253) + "..."
            return redacted

    for attribute in ("protocol_error", "cleanup_error"):
        diagnostic = getattr(result, attribute, None)
        if isinstance(diagnostic, str) and diagnostic:
            return sanitize_diagnostic_summary(diagnostic)

    if getattr(result, "process_timed_out", False):
        return "worker_timed_out"
    if getattr(result, "heartbeat_timed_out", False):
        return "heartbeat_timed_out"
    if getattr(result, "hello_timed_out", False):
        return "hello_timed_out"
    returncode = getattr(result, "returncode", None)
    if isinstance(returncode, int):
        return f"worker_exit:{returncode}"
    return "worker_exit:abrupt_termination"


def _nonnegative_count(value: object) -> int:
    if value is None:
        return 0
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > 2**63 - 1
    ):
        raise ValueError("invalid refresh result")
    return value


__all__ = [
    "RefreshCapability", "RefreshConfigurationError", "RefreshGenerationChangedError", "RefreshSourceError",
    "ResolvedRefreshAuthority", "build_refresh_worker_runner", "create_refresh_capability", "execute_refresh",
    "load_refresh_capability", "remove_refresh_capability", "run_refresh_worker", "refresh_terminal",
]
