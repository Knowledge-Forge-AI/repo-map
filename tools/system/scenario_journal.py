"""Incremental scenario journaling and pre-teardown diagnostic preservation."""

from __future__ import annotations

import json
from pathlib import Path
import os
import re
import subprocess
import sys
import time
from typing import Any

from tools.system.config import DIAGNOSTIC_SCHEMA
from tools.system.report import (
    SystemStepResult,
    _snapshot_details,
    write_system_diagnostic,
)

_LOG_TAIL_LINES = 50
_DIAGNOSTIC_TIMEOUT_SECONDS = 5.0
_TOTAL_DIAGNOSTIC_RESERVE_SECONDS = 10.0
_MAX_LOG_BYTES = 4096


def _redact_log_text(text: str) -> str:
    redacted = re.sub(r'(?i)(password|token|secret|api_key)([\'":=\s]+)\S+', r'\1\2[REDACTED]', text)
    redacted = re.sub(r'(?i)(postgres|postgresql)://[^:]+:[^@]+@', r'\1://[REDACTED]:[REDACTED]@', redacted)
    redacted = re.sub(r'(?i)\bpassword\s*=\s*\S+', 'password=[REDACTED]', redacted)
    raw_bytes = redacted.encode("utf-8")
    if len(raw_bytes) > _MAX_LOG_BYTES:
        suffix = b"\n... [TRUNCATED_AT_4096_BYTES]"
        budget = max(0, _MAX_LOG_BYTES - len(suffix))
        redacted = raw_bytes[:budget].decode("utf-8", errors="ignore") + suffix.decode("utf-8")
    return redacted


def _safe_diagnostic_error(exc: Exception | str, max_bytes: int = 512) -> dict[str, str]:
    err_cls = type(exc).__name__ if isinstance(exc, Exception) else "DiagnosticError"
    msg = _redact_log_text(str(exc))
    msg_bytes = msg.encode("utf-8")
    if len(msg_bytes) > max_bytes:
        suffix = b" [TRUNCATED]"
        budget = max(0, max_bytes - len(suffix))
        msg = msg_bytes[:budget].decode("utf-8", errors="ignore") + suffix.decode("utf-8")
    return {"error_class": err_cls, "message": msg}


def _serialize_step(step: SystemStepResult) -> dict[str, Any]:
    details = _snapshot_details(step.details) if isinstance(step.details, dict) else {}
    return {
        "step_name": step.step_name,
        "status": step.status,
        "duration_seconds": round(step.duration_seconds, 3),
        "message": step.message,
        "details": details,
    }


def _build_control_diagnostic_sql() -> str:
    return (
        "SELECT json_build_object("
        "'job', (SELECT json_build_object('job_id', j.job_id, 'graph_id', j.graph_id, 'state', j.state, 'publication_state', j.publication_state, 'current_attempt', j.current_attempt, 'phase', j.phase, 'progress_completed', j.progress_completed, 'progress_total', j.progress_total, 'error_category', j.error_category, 'next_eligible_at', j.next_eligible_at, 'finished_at', j.finished_at, 'cancel_requested_at', j.cancel_requested_at) FROM jobs j WHERE j.job_id = :'job_id'), "
        "'attempts', (SELECT json_agg(json_build_object('attempt', a.attempt, 'coordinator_instance_id', a.coordinator_instance_id, 'fencing_epoch', a.fencing_epoch, 'is_current', a.is_current, 'result_category', a.result_category, 'publication_state', a.publication_state, 'started_at', a.started_at, 'heartbeat_at', a.heartbeat_at, 'finished_at', a.finished_at, 'worker_identity', a.worker_identity, 'run_identity', a.run_identity, 'diagnostic_summary', a.diagnostic_summary) ORDER BY a.attempt) FROM (SELECT * FROM job_attempts WHERE job_id = :'job_id' ORDER BY attempt LIMIT 10) a), "
        "'leases', (SELECT json_agg(json_build_object('graph_id', gl.graph_id, 'job_id', gl.job_id, 'attempt', gl.attempt, 'coordinator_instance_id', gl.coordinator_instance_id, 'fencing_epoch', gl.fencing_epoch, 'worker_identity', gl.worker_identity, 'acquired_at', gl.acquired_at, 'heartbeat_at', gl.heartbeat_at, 'expires_at', gl.expires_at) ORDER BY gl.attempt) FROM (SELECT * FROM graph_leases WHERE job_id = :'job_id' ORDER BY attempt LIMIT 10) gl), "
        "'instances', (SELECT json_agg(json_build_object('singleton_scope', ci.singleton_scope, 'instance_id', ci.instance_id, 'fencing_epoch', ci.fencing_epoch, 'status', ci.status, 'started_at', ci.started_at, 'heartbeat_at', ci.heartbeat_at, 'expires_at', ci.expires_at, 'stopped_at', ci.stopped_at)) FROM (SELECT * FROM coordinator_instances ORDER BY started_at DESC LIMIT 10) ci), "
        "'coalescing_state', (SELECT json_agg(json_build_object('graph_id', cs.graph_id, 'job_kind_family', cs.job_kind_family, 'paused', cs.paused, 'dirty', cs.dirty, 'next_reconcile_at', cs.next_reconcile_at, 'queued_job_id', cs.queued_job_id, 'running_job_id', cs.running_job_id, 'last_hint_at', cs.last_hint_at)) FROM (SELECT cs.* FROM coalescing_state cs JOIN jobs j ON cs.graph_id = j.graph_id WHERE j.job_id = :'job_id' LIMIT 10) cs), "
        "'synthetic_markers', (SELECT json_agg(json_build_object('attempt', spm.attempt, 'graph_id', spm.graph_id, 'run_identity', spm.run_identity, 'outcome', spm.outcome, 'source_generation', spm.source_generation, 'config_generation', spm.config_generation, 'extractor_generation', spm.extractor_generation, 'canonicalizer_generation', spm.canonicalizer_generation, 'published_at', spm.published_at)) FROM (SELECT * FROM synthetic_publication_markers WHERE job_id = :'job_id' ORDER BY attempt LIMIT 10) spm));"
    )


def _build_publication_diagnostic_sql() -> str:
    return (
        "SELECT json_agg(json_build_object("
        "'run_id', r.id, 'publication_job_id', r.publication_job_id, 'publication_attempt', r.publication_attempt, "
        "'source_generation', r.source_generation, 'config_generation', r.config_generation, 'extractor_generation', r.extractor_generation, 'canonicalizer_generation', r.canonicalizer_generation, "
        "'execution_route', r.execution_route, 'snapshot_manifest_id', r.snapshot_manifest_id, 'snapshot_vector_json', r.snapshot_vector_json, 'extraction_receipt_id', r.extraction_receipt_id, "
        "'publication_bundle_id', r.publication_bundle_id, 'graph_candidate_id', r.graph_candidate_id, 'resolver_identity', r.resolver_identity, 'portable_canonicalizer_identity', r.portable_canonicalizer_identity, "
        "'semantic_contract_identity', r.semantic_contract_identity, 'quality_rule_identity', r.quality_rule_identity, 'portable_protocol_version', r.portable_protocol_version, 'worker_capability_identity', r.worker_capability_identity, "
        "'portable_stage_id', r.portable_stage_id, 'portable_execution_mode', r.portable_execution_mode, 'portable_singleton_fencing_epoch', r.portable_singleton_fencing_epoch, 'portable_graph_lease_fencing_epoch', r.portable_graph_lease_fencing_epoch, "
        "'family_receipts_json', r.family_receipts_json) "
        "ORDER BY r.publication_attempt) FROM (SELECT * FROM runs WHERE publication_job_id = :'job_id' AND status = 'complete' ORDER BY publication_attempt LIMIT 10) r;"
    )


class ScenarioJournal:
    """Incremental journal for scenario execution with diagnostic capture."""

    def __init__(
        self,
        *,
        evidence_dir: Path | None = None,
        report_dir: Path | None = None,
    ) -> None:
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        self.report_dir = Path(report_dir) if report_dir is not None else None
        self._step_results: list[SystemStepResult] = []
        self._diagnostics_collected: bool = False

    def record_step(self, step: SystemStepResult) -> None:
        """Record one completed step and persist the incremental journal."""
        snapshotted = SystemStepResult(
            step_name=step.step_name,
            status=step.status,
            duration_seconds=step.duration_seconds,
            message=step.message,
            details=_snapshot_details(step.details) if isinstance(step.details, dict) else {},
        )
        self._step_results.append(snapshotted)
        self._flush_journal()

    def record_failure(
        self,
        step_name: str,
        error_message: str,
        *,
        duration_seconds: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> SystemStepResult:
        """Record an in-flight step failure into the journal."""
        failed_step = SystemStepResult(
            step_name=step_name,
            status="failed",
            duration_seconds=duration_seconds,
            message=error_message,
            details=_snapshot_details(details or {}),
        )
        self._step_results.append(failed_step)
        self._flush_journal()
        return failed_step

    def record_not_run(
        self,
        step_name: str,
        message: str = "skipped due to prior step failure",
    ) -> SystemStepResult:
        """Record an unexecuted step due to prior failure."""
        not_run_step = SystemStepResult(
            step_name=step_name,
            status="not_run",
            duration_seconds=0.0,
            message=message,
            details={},
        )
        self._step_results.append(not_run_step)
        self._flush_journal()
        return not_run_step

    def step_results(self) -> tuple[SystemStepResult, ...]:
        """Return defensive copies of all recorded step results so far."""
        return tuple(
            SystemStepResult(
                step_name=s.step_name,
                status=s.status,
                duration_seconds=s.duration_seconds,
                message=s.message,
                details=_snapshot_details(s.details),
            )
            for s in self._step_results
        )

    def _flush_journal(self) -> None:
        """Write current step journal to evidence and report directories."""
        payload = {
            "step_count": len(self._step_results),
            "steps": [_serialize_step(s) for s in self._step_results],
            "timestamp": time.time(),
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        for directory in (self.evidence_dir, self.report_dir):
            if directory is not None:
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "system-scenario-journal.json").write_text(
                        rendered, encoding="utf-8"
                    )
                except OSError as exc:
                    print(
                        f"WARNING: failed to write scenario journal: {exc}",
                        file=sys.stderr,
                    )

    def preserve_diagnostics(
        self,
        *,
        compose_dir: Path,
        env: dict[str, str] | None = None,
        error_message: str = "",
        plan: Any | None = None,
        deadline: Any | None = None,
    ) -> Path | None:
        """Capture container state and logs prior to Docker Compose teardown."""
        if self._diagnostics_collected:
            return None
        self._diagnostics_collected = True

        service_logs: dict[str, str] = {}
        compose_ps = ""
        control_state: dict[str, Any] = {}
        supplied_step_evidence: dict[str, Any] = {}
        for s in self._step_results:
            if isinstance(s.details, dict):
                for k in (
                    "job_id", "idempotency_key", "idempotency_digest", "initial_attempt", "recovered_attempt",
                    "attempt_1", "attempt_2", "initial_instance_id", "recovered_instance_id",
                    "attempt_1_instance_id", "attempt_2_instance_id", "initial_singleton_fencing_epoch",
                    "recovered_singleton_fencing_epoch", "attempt_1_singleton_fencing_epoch",
                    "attempt_2_singleton_fencing_epoch", "publication_receipt", "latest_run_id", "state",
                    "recovery_trace", "latest_observed_state", "latest_observed_attempt",
                    "latest_observed_phase", "latest_observed_completed", "observed_recovery_states",
                    "effective_wait_budget_seconds", "no_progress_boundary_seconds",
                    "replacement_ready_instance_id", "replacement_ready_singleton_fencing_epoch", "latest_status_error",
                ):
                    if k in s.details and k not in supplied_step_evidence:
                        supplied_step_evidence[k] = s.details[k]

        control_state.update(supplied_step_evidence)
        control_state["supplied_step_evidence"] = dict(supplied_step_evidence)
        control_state["observed_provenance"] = "supplied_step_evidence"

        if compose_dir.exists():
            run_env = {**os.environ, **(env or {})}
            diag_budget = _TOTAL_DIAGNOSTIC_RESERVE_SECONDS
            if deadline is not None and hasattr(deadline, "remaining_test_seconds"):
                rem_test = float(deadline.remaining_test_seconds())
                diag_budget = 0.0 if rem_test <= 0.0 else min(_TOTAL_DIAGNOSTIC_RESERVE_SECONDS, rem_test)
            diag_deadline = time.monotonic() + diag_budget

            def _probe_timeout(cap: float = _DIAGNOSTIC_TIMEOUT_SECONDS) -> float:
                remaining = diag_deadline - time.monotonic()
                return max(0.0, min(cap, remaining))

            user = getattr(plan, "user", "repomap") if plan is not None else "repomap"
            job_id = str(control_state.get("job_id", ""))
            valid_job = bool(job_id and re.fullmatch(r"[A-Za-z0-9._:-]+", job_id))

            # Probe 1: Control database authority (jobs, attempts, leases, instances, coalescing, synthetic)
            if valid_job:
                database = "repomap_control"
                if plan is not None and hasattr(plan, "database"):
                    from repomap_kg.ops.resolved_config import control_database_for
                    database = str(control_database_for(plan.database))
                if time.monotonic() < diag_deadline and _probe_timeout() > 0.0:
                    try:
                        q_res = subprocess.run(
                            ["docker", "compose", "exec", "-T", "postgres", "psql", "-XAt", "-U", user, "--dbname", database, "--set", f"job_id={job_id}", "--file", "-"],
                            input=_build_control_diagnostic_sql(),
                            cwd=compose_dir,
                            capture_output=True,
                            text=True,
                            env=run_env,
                            timeout=_probe_timeout(),
                            check=False,
                        )
                        if q_res.returncode == 0 and q_res.stdout.strip():
                            raw_ev = json.loads(q_res.stdout.strip())
                            ev = _snapshot_details(raw_ev) if isinstance(raw_ev, dict) else {}
                            if isinstance(ev, dict):
                                control_state["observed_provenance"] = "live_control_db"
                                if ev.get("job"):
                                    control_state["job_live"] = ev["job"]
                                    if "state" in ev["job"]:
                                        control_state["job_state"] = ev["job"]["state"]
                                    if "publication_state" in ev["job"]:
                                        control_state["job_publication_state"] = ev["job"]["publication_state"]
                                else:
                                    control_state["job_live"] = {"status": "unknown", "message": "job record not found"}
                                attempts = ev.get("attempts")
                                if isinstance(attempts, list):
                                    control_state["attempts_live"] = attempts
                                    for att in attempts:
                                        if isinstance(att, dict) and att.get("attempt") in (1, 2):
                                            control_state[f"attempt_{att['attempt']}_live"] = att
                                else:
                                    control_state["attempts_live"] = {"status": "unknown", "message": "no attempts found"}
                                control_state["leases_live"] = ev.get("leases") or []
                                control_state["instances_live"] = ev.get("instances") or []
                                control_state["coalescing_state_live"] = ev.get("coalescing_state") or []
                                markers = ev.get("synthetic_markers") or []
                                control_state["synthetic_markers_live"] = markers
                                control_state["synthetic_markers"] = markers
                        else:
                            control_state["live_query_error"] = _safe_diagnostic_error(q_res.stderr.strip() or f"exit code {q_res.returncode}")
                    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        control_state["live_query_error"] = _safe_diagnostic_error(exc)
                else:
                    control_state["live_query_error"] = {"error_class": "BudgetExhaustedError", "message": "diagnostic reserve deadline exhausted"}

            # Probe 2: Real graph publication reader probe on runs
            if valid_job:
                graph_db = getattr(plan, "database", "repomap_graph") if plan is not None else "repomap_graph"
                if time.monotonic() < diag_deadline and _probe_timeout() > 0.0:
                    try:
                        g_res = subprocess.run(
                            ["docker", "compose", "exec", "-T", "postgres", "psql", "-XAt", "-U", user, "--dbname", str(graph_db), "--set", f"job_id={job_id}", "--file", "-"],
                            input=_build_publication_diagnostic_sql(),
                            cwd=compose_dir,
                            capture_output=True,
                            text=True,
                            env=run_env,
                            timeout=_probe_timeout(),
                            check=False,
                        )
                        if g_res.returncode == 0:
                            raw_out = g_res.stdout.strip()
                            raw_runs = json.loads(raw_out) if raw_out and raw_out != "null" else []
                            runs_data = _snapshot_details(raw_runs) if isinstance(raw_runs, list) else []
                            target_attempt = (
                                control_state.get("latest_observed_attempt")
                                or control_state.get("attempt_2")
                                or control_state.get("attempt_1")
                            )
                            has_match = any(
                                isinstance(r, dict) and (target_attempt is None or r.get("publication_attempt") == target_attempt)
                                for r in runs_data
                            )
                            r_status, r_class = (
                                ("verified", "verified_receipt_present") if has_match
                                else ("unconfirmed", "attempt_mismatch") if runs_data
                                else ("unconfirmed", "receipt_unobserved")
                            )
                            control_state["verified_graph_receipt"] = {
                                "status": r_status,
                                "classification": r_class,
                                "runs": runs_data,
                            }
                        else:
                            control_state["verified_graph_receipt"] = {
                                "status": "unavailable",
                                "classification": "unavailable",
                                "error": _safe_diagnostic_error(g_res.stderr.strip() or f"exit code {g_res.returncode}"),
                            }
                    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        control_state["verified_graph_receipt"] = {
                            "status": "unavailable",
                            "classification": "unavailable",
                            "error": _safe_diagnostic_error(exc),
                        }
                else:
                    control_state["verified_graph_receipt"] = {
                        "status": "budget_exhausted",
                        "classification": "unavailable",
                        "reason": "diagnostic_reserve_budget_exhausted",
                    }

            # Probe 3: Docker compose ps
            if time.monotonic() < diag_deadline and _probe_timeout() > 0.0:
                try:
                    ps_res = subprocess.run(
                        ["docker", "compose", "ps", "--all", "--format", "json"],
                        cwd=compose_dir, capture_output=True, text=True, env=run_env, timeout=_probe_timeout(), check=False,
                    )
                    compose_ps = _redact_log_text(ps_res.stdout.strip()) if ps_res.returncode == 0 else json.dumps(_safe_diagnostic_error(ps_res.stderr.strip() or f"exit code {ps_res.returncode}"))
                except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError, UnicodeDecodeError) as exc:
                    compose_ps = json.dumps(_safe_diagnostic_error(exc))
            else:
                compose_ps = json.dumps({"error_class": "BudgetExhaustedError", "message": "diagnostic reserve deadline exhausted"})

            # Probe 4: Service logs
            for service in ("coordinator", "postgres", "http"):
                if time.monotonic() < diag_deadline and _probe_timeout() > 0.0:
                    try:
                        log_res = subprocess.run(
                            ["docker", "compose", "logs", "--tail", str(_LOG_TAIL_LINES), service],
                            cwd=compose_dir,
                            capture_output=True,
                            text=True,
                            env=run_env,
                            timeout=_probe_timeout(),
                            check=False,
                        )
                        raw_log = log_res.stdout.strip() or log_res.stderr.strip()
                        service_logs[service] = _redact_log_text(raw_log)
                    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError, UnicodeDecodeError) as exc:
                        service_logs[service] = json.dumps(_safe_diagnostic_error(exc))
                else:
                    service_logs[service] = json.dumps({"error_class": "BudgetExhaustedError", "message": "diagnostic reserve deadline exhausted"})

        diagnostic_payload: dict[str, Any] = {
            "schema": DIAGNOSTIC_SCHEMA,
            "error_message": _redact_log_text(error_message) if error_message else None,
            "recorded_steps": [_serialize_step(s) for s in self._step_results],
            "control_state": control_state,
            "compose_ps": compose_ps,
            "service_logs": service_logs,
            "collected_at_epoch": time.time(),
        }

        written = write_system_diagnostic(
            diagnostic_payload,
            report_dir=self.report_dir,
            evidence_dir=self.evidence_dir,
        )
        if written is None and (self.report_dir is not None or self.evidence_dir is not None):
            raise OSError("failed to write diagnostic to any destination")
        return written
