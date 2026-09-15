"""Pure group-specific observation validation for the closed qualification catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from repomap_test_support.test_cov5k_r2_fix1_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix1_qualification_records import IntegrityError


def _verify_group_d(entry: CatalogEntry, observed: Mapping[str, object]) -> None:
    parameters = dict(entry.parameter_values)
    if entry.operation_kind == "runtime_driver_read":
        for field in ("driver", "mode", "failure_category", "automatic_fallback"):
            if observed[field] != parameters[field]:
                raise IntegrityError("Group D driver observation changed")
        if observed["automatic_fallback"] is not False:
            raise IntegrityError("Group D automatic fallback was enacted")
    elif entry.operation_kind == "process_rss":
        if (
            observed["process_case"] != parameters["process_case"]
            or not isinstance(observed["pid"], int)
            or observed["pid"] <= 0
            or not isinstance(observed["rss_bytes"], int)
            or observed["rss_bytes"] <= 0
        ):
            raise IntegrityError("Group D process RSS observation changed")
    elif entry.operation_kind == "container_rss":
        if (
            observed["stream"] is not False
            or observed["one_shot"] is not True
            or observed["automatic_fallback"] is not False
        ):
            raise IntegrityError("Group D container authority changed")
    elif entry.operation_kind == "terminal_read":
        if (
            observed["dimension"] != parameters["dimension"]
            or observed["read_count"] != 1
            or observed["reader_settled"] is not True
        ):
            raise IntegrityError("Group D terminal-read authority changed")


_SINGLE_ATTEMPT_PATHS = {
    "attempt_one_success",
    "retry_gate_refusal",
    "parent_settlement_cleanup_limitation_no_retry",
    "final_refused_projection",
}
_EXPECTED_FAILURES = {
    "attempt_one_success": (),
    "resource_failure_second_success": ("resource",),
    "timeout_second_success": ("timeout",),
    "two_generic_worker_failures": ("generic_worker_failure", "generic_worker_failure"),
    "generic_worker_failure_then_timeout": ("generic_worker_failure", "timeout"),
    "timeout_then_generic_worker_failure": ("timeout", "generic_worker_failure"),
    "two_timeouts": ("timeout", "timeout"),
    "retry_gate_refusal": ("retry_gate",),
    "parent_settlement_cleanup_limitation_no_retry": ("cleanup",),
    "final_refused_projection": ("projection",),
}


def _verify_group_a(entry: CatalogEntry, observed: Mapping[str, object]) -> None:
    parameters = dict(entry.parameter_values)
    path, cleanup, retry = (
        str(parameters["path"]),
        parameters["cleanup"],
        parameters["retry"],
    )
    raw_attempts, raw_resources = (
        observed.get("attempt_ids"),
        observed.get("resource_ids"),
    )
    if not isinstance(raw_attempts, Iterable):
        raise IntegrityError("attempt identity evidence is missing")
    attempts = tuple(raw_attempts)
    if not isinstance(raw_resources, Iterable):
        raise IntegrityError("resource acquisition evidence is missing")
    resources = tuple(raw_resources)
    if not attempts or len(set(attempts)) != len(attempts):
        raise IntegrityError("attempt identity evidence is missing")
    if not resources or len(set(resources)) != len(resources):
        raise IntegrityError("resource acquisition evidence is missing")
    if len(attempts) != (1 if path in _SINGLE_ATTEMPT_PATHS else 2):
        raise IntegrityError("attempt count does not match enacted path")
    expected_failures = _EXPECTED_FAILURES[path]
    raw_failures = observed.get("failure_sources")
    if (
        not isinstance(raw_failures, Iterable)
        or tuple(raw_failures) != expected_failures
    ):
        raise IntegrityError("failure-source evidence does not match path")
    if cleanup == "complete" and not (
        observed["cleanup_started"]
        and observed["cleanup_completed"]
        and observed["worker_settled"]
        and observed["descriptor_settled"]
    ):
        raise IntegrityError("claimed cleanup lacks executable evidence")
    if cleanup == "limited" and not (
        observed["cleanup_started"] and observed["cleanup_limited"]
    ):
        raise IntegrityError("cleanup limitation lacks executable evidence")
    if observed["cleanup_disposition"] != cleanup:
        raise IntegrityError("cleanup disposition does not match enacted path")
    if observed["retry_disposition"] != retry:
        raise IntegrityError("retry gate lacks executable evidence")
    if not observed["third_attempt_absent"]:
        raise IntegrityError("third attempt absence was not observed")
    forced_tail_required = "timeout" in path
    if forced_tail_required and observed["forced_tail_signal"] not in {
        "SIGTERM",
        "SIGKILL",
    }:
        raise IntegrityError("forced tail lacks executable evidence")
    if forced_tail_required:
        signal_number = 15 if observed["forced_tail_signal"] == "SIGTERM" else 9
        if (
            not isinstance(observed["forced_tail_pid"], int)
            or observed["forced_tail_pid"] <= 0
            or observed["forced_tail_returncode"] != -signal_number
        ):
            raise IntegrityError("forced tail lacks process-result evidence")
    elif (
        observed["forced_tail_pid"] is not None
        or observed["forced_tail_returncode"] is not None
    ):
        raise IntegrityError("unenacted forced tail carries process evidence")
    if observed["final_projection_category"] != entry.expected_contract_category:
        raise IntegrityError("final projection does not match observed path")
