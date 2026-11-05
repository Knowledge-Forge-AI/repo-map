"""Audit receipts and the run report for pilot invocations (spec 13).

One ``cloe-extractor-run-receipt-v1`` per container invocation, plus one
run-level receipt for an unavailable or refused run. Receipts and reports are
sanitized audit evidence: they hold digests and categorical codes, never host
paths, target text or native diagnostics, and nothing reads them to select,
admit or replay. Their verification fact is ``unverified`` or ``refused``.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common_lore_index.extractors.contracts.bounded_io import open_directory, write_new_regular_file
from common_lore_index.extractors.contracts.receipt_codec import store_receipt
from common_lore_index.extractors.contracts.receipt_schema import (
    Attempt,
    Declaration,
    ObservedFacts,
    Receipt,
)
from common_lore_index.extractors.contracts.vocabulary import EffectVector
from common_lore_index.extractors.rust_pilot.component_lock import (
    DIALECT,
    EMPTY_SHA256,
    LOCK_SHA256,
    canonical_json,
    digest_json,
)

PRODUCER = "rust-pilot-helper"
CONSUMER_BOUNDARY = "rust-pilot-parent-v1"
INVOCATION_MODE = "container-exec-v1"
RUNTIME_IDENTITY = "cpython-3.13.12"
CAPABILITIES = ("syntax.error_tolerant", "syntax.tree")
RUN_REPORT_SCHEMA = "cloe-rust-pilot-run-report-v1"
MAX_REPORT_BYTES = 1_048_576
EFFECTS = EffectVector(target_code_evaluated="none", execution_boundary="subprocess",
                       filesystem_read_scope="selected-input", filesystem_write_scope="scratch",
                       network="none")


def declaration(profile_sha256: str | None) -> Declaration:
    return Declaration(stage="S3", language_dialect=DIALECT, runtime_identity=RUNTIME_IDENTITY,
                       capabilities=CAPABILITIES, effects=EFFECTS, provenance="python-distribution",
                       invocation_mode=INVOCATION_MODE, dependency_sha256=LOCK_SHA256,
                       profile_sha256=profile_sha256 or EMPTY_SHA256)


def _exit(status: int | None) -> int | None:
    return None if status is None else max(-255, min(255, status))


def attempt_receipt(*, run_id: str, seq: int, input_sha256: str, profile_sha256: str,
                    artifact_sha256: str | None, outcome: str, completeness: str,
                    achieved: Sequence[str], resource_events: Sequence[str],
                    exit_status: int | None, cleanup_proven: bool) -> Receipt:
    """Receipt for one executed container invocation; it can never carry success."""

    attempt = Attempt(input_sha256=input_sha256, outcome=outcome, exercised=CAPABILITIES,
                      achieved=tuple(sorted(achieved)), completeness=completeness)
    status = _exit(exit_status)
    observed = ObservedFacts(installed="installed", admitted="admitted", artifact_sha256=artifact_sha256,
                             invocation_mode=INVOCATION_MODE, attempts=(attempt,),
                             resource_events=tuple(sorted(set(resource_events))), exit_status=status,
                             cleanup="proven" if cleanup_proven else "incomplete", verification="unverified")
    state = "complete" if cleanup_proven and status is not None else "incomplete"
    return Receipt(state=state, producer=PRODUCER, consumer_boundary=CONSUMER_BOUNDARY,
                   run_id=f"{run_id}.{seq}", source_sha256=input_sha256,
                   declared=declaration(profile_sha256), observed=observed, refusal=None)


def refusal_receipt(*, run_id: str, seq: int, source_sha256: str, profile_sha256: str | None,
                    code: str, resource_events: Sequence[str] = (), cleanup: str = "not_applicable") -> Receipt:
    """Receipt for an input or run refused before any parse exec."""

    observed = ObservedFacts(installed="installed", admitted="refused", artifact_sha256=None,
                             invocation_mode=None, attempts=(),
                             resource_events=tuple(sorted(set(resource_events))), exit_status=None,
                             cleanup=cleanup, verification="refused")
    return Receipt(state="refused", producer=PRODUCER, consumer_boundary=CONSUMER_BOUNDARY,
                   run_id=f"{run_id}.{seq}", source_sha256=source_sha256,
                   declared=declaration(profile_sha256), observed=observed, refusal=code)


def unavailable_receipt(*, run_id: str, source_sha256: str) -> Receipt:
    """The single run-level ``dependency_unavailable`` receipt."""

    observed = ObservedFacts(installed="unavailable", admitted="refused", artifact_sha256=None,
                             invocation_mode=None, attempts=(), resource_events=(), exit_status=None,
                             cleanup="not_applicable", verification="refused")
    return Receipt(state="unavailable", producer=PRODUCER, consumer_boundary=CONSUMER_BOUNDARY,
                   run_id=f"{run_id}.0", source_sha256=source_sha256, declared=declaration(None),
                   observed=observed, refusal="dependency_unavailable")


def run_source_sha256(input_digests: Sequence[str]) -> str:
    """Run-level subject digest: the sorted selected input digests."""

    return digest_json({"domain": "rust-pilot-run-inputs-v1", "inputs": sorted(input_digests)})


def _runtime_report(runtime: dict[str, Any]) -> dict[str, Any]:
    """Closed projection; digests bind omitted native identities without text."""

    allowed = {
        "t": {"probe"}, "import": {"ok", "failed"},
        "executable": {"/usr/local/bin/python3.13"}, "version": {"3.13.12"},
        "cache_tag": {"cpython-313"}, "abiflags": {""},
        "soabi": {"cpython-313-aarch64-linux-gnu", "cpython-313-x86_64-linux-gnu"},
        "machine": {"aarch64", "x86_64"}, "ts_version": {"0.26.0"},
        "fs_encoding": {"utf-8"}, "preferred_encoding": {"utf-8", "UTF-8"},
        "lc_all": {"C", "C.UTF-8"},
    }
    result: dict[str, Any] = {"probe_sha256": digest_json(runtime)}
    for key, values in allowed.items():
        value = runtime.get(key)
        if type(value) is str and value in values:
            result[key] = value
    for key in ("abi_version", "language_version", "min_compatible_language_version"):
        value = runtime.get(key)
        if type(value) is int and 0 <= value <= 65535:
            result[key] = value
    flags = runtime.get("flags")
    if type(flags) is dict:
        result["flags"] = {key: flags[key] for key in ("isolated", "no_site", "dont_write_bytecode", "utf8_mode")
                           if type(flags.get(key)) is int and flags[key] in (0, 1)}
    libc = runtime.get("libc")
    if (type(libc) is list and len(libc) == 2 and libc[0] == "glibc"
            and type(libc[1]) is str and re.fullmatch(r"2\.[0-9]{1,3}", libc[1])):
        result["libc"] = list(libc)
    for key in ("kernel", "kind_ids", "field_ids"):
        if key in runtime:
            result[key + "_sha256"] = digest_json(runtime[key])
    if type(runtime.get("probe_parse_ok")) is bool:
        result["probe_parse_ok"] = runtime["probe_parse_ok"]
    return result


def run_report(*, run_id: str, platform: str, image_id: str, server: dict[str, str],
               runtime: dict[str, Any], profile_sha256: str | None, helper_closure_sha256: str,
               files: Sequence[dict[str, Any]], residue: dict[str, Any], timings: dict[str, float],
               receipt_digests: Sequence[str], run_outcome: str) -> dict[str, Any]:
    """Sanitized report: categorical per-file outcomes keyed by input digest, no paths."""

    return {
        "schema": RUN_REPORT_SCHEMA, "run_id": run_id, "run_outcome": run_outcome, "platform": platform,
        "sdk_image_id": image_id, "docker_server": dict(server), "runtime_observed": _runtime_report(runtime),
        "lock_sha256": LOCK_SHA256, "profile_sha256": profile_sha256,
        "helper_closure_sha256": helper_closure_sha256,
        "files": sorted((dict(item) for item in files), key=lambda item: (str(item.get("input_sha256")),
                                                                           int(item.get("seq", 0)))),
        "residue": dict(residue), "timings_ms": {key: round(value * 1000) for key, value in timings.items()},
        "receipt_sha256": sorted(receipt_digests), "verification": "unverified",
    }


def store_audit(audit_dir: Path | str, receipts: Sequence[Receipt], report: dict[str, Any]) -> tuple[str, ...]:
    """Store receipts and the report with bounded exclusive IO; return receipt digests."""

    dir_fd = open_directory(audit_dir)
    try:
        digests = tuple(store_receipt(dir_fd, receipt) for receipt in receipts)
        data = canonical_json({**report, "receipt_sha256": sorted(digests)})
        name = f"run-report-{hashlib.sha256(data).hexdigest()}.json"
        write_new_regular_file(dir_fd, name, data, max_bytes=MAX_REPORT_BYTES)
    finally:
        os.close(dir_fd)
    return digests
