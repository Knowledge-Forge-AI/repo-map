"""Static workflow contract for the exact two-step AMD projection."""

from __future__ import annotations

from collections.abc import Mapping

from ci.qualification_native_contracts import (
    D12_NATIVE_AMD64_JOB_ID, D12_NATIVE_AMD64_MAX_TIMEOUT_MINUTES,
    D12_NATIVE_AMD64_NEEDS, D12_NATIVE_AMD64_RUNNER, PINNED_PUBLIC_ACTIONS,
    script_contains_shell_loop,
)
from ci.workflow_model import Workflow

RUST_RUN_NAME = "Run Rust parser component qualification"
RUST_UPLOAD_NAME = "Upload Rust parser component evidence"
D12_UPLOAD_NAME = "Upload native D12 qualification evidence"
RUST_COMMAND = "python3 tools/ci/rust_pilot_qualification.py amd64"
RUST_ARGS = (
    '--repo-root "' + "$" + '{GITHUB_WORKSPACE}"',
    '--d12-state-dir "' + "$" + '{RUNNER_TEMP}/d12-native-amd64-evidence"',
    '--d12-sealed-json "' + "$" + '{RUNNER_TEMP}/d12-native-amd64-evidence/d12-native-amd64-sealed-evidence.json"',
    '--manifest "' + "$" + '{GITHUB_WORKSPACE}/tools/ci/rust_pilot_qualification_manifest.json"',
    '--work-dir "' + "$" + '{RUNNER_TEMP}/rust-pilot-amd64-work"',
    '--report-dir "' + "$" + '{RUNNER_TEMP}/rust-pilot-amd64-report"',
)
RUST_UPLOAD_NAME_PREFIX = ("repomap-rust-pilot-amd64-" + "$" + "{{ github.run_id }}-a" +
                            "$" + "{{ github.run_attempt }}-" + "$" + "{{ github.sha }}")
RUST_UPLOAD_PATH = "$" + "{{ runner.temp }}/rust-pilot-amd64-report"


def _always(step: Mapping[str, object]) -> bool:
    return str(step.get("if", "")) in {"always()", "$" + "{{ always() }}"}


def _validate_run(step: Mapping[str, object]) -> list[str]:
    text = str(step.get("run", ""))
    errors = []
    expected = " \\\n  ".join((RUST_COMMAND, *RUST_ARGS))
    if text.strip() != expected:
        errors.append("Rust command differs from the single frozen command")
    if set(step) != {"name", "if", "run"}:
        errors.append("Rust run fields differ from the closed projection")
    if text.count(RUST_COMMAND) != 1:
        errors.append("Rust command must occur exactly once")
    errors.extend("Rust command missing " + value for value in RUST_ARGS if value not in text)
    if script_contains_shell_loop(text):
        errors.append("Rust command must not retry or loop")
    for marker in ("docker build", "docker pull", "docker push", "setup-qemu", "setup-buildx",
                   "buildx create", "pip install", "curl ", "wget ", "arm64"):
        if marker in text:
            errors.append("Rust command contains forbidden marker " + repr(marker))
    return errors


def validate_rust_qualification_job(workflow: Workflow) -> list[str]:
    prefix = workflow.path.name + ": d12-native-amd64 "
    job = workflow.jobs.get(D12_NATIVE_AMD64_JOB_ID)
    if not isinstance(job, Mapping):
        return [prefix + "job is missing"]
    errors: list[str] = []
    if job.get("runs-on") != D12_NATIVE_AMD64_RUNNER:
        errors.append(prefix + "runner changed")
    if job.get("timeout-minutes") != D12_NATIVE_AMD64_MAX_TIMEOUT_MINUTES:
        errors.append(prefix + "timeout changed")
    if job.get("needs") != list(D12_NATIVE_AMD64_NEEDS):
        errors.append(prefix + "needs changed")
    steps = workflow.job_steps(D12_NATIVE_AMD64_JOB_ID)
    runs = [i for i, step in enumerate(steps) if step.get("name") == RUST_RUN_NAME]
    uploads = [i for i, step in enumerate(steps) if step.get("name") == RUST_UPLOAD_NAME]
    d12 = [i for i, step in enumerate(steps) if step.get("name") == D12_UPLOAD_NAME]
    if (len(runs), len(uploads), len(d12)) != (1, 1, 1):
        return errors + [prefix + "requires one D12 upload, Rust run, and Rust upload"]
    run, upload = steps[runs[0]], steps[uploads[0]]
    if not d12[0] < runs[0] < uploads[0]:
        errors.append(prefix + "requires D12 upload < Rust run < Rust upload")
    if not _always(run) or run.get("continue-on-error") not in (None, False):
        errors.append(prefix + "Rust run must be always-gated without continue-on-error")
    errors.extend(prefix + error for error in _validate_run(run))
    if not _always(upload) or upload.get("continue-on-error") not in (None, False):
        errors.append(prefix + "Rust upload must be always-gated without continue-on-error")
    if upload.get("uses") != PINNED_PUBLIC_ACTIONS["upload_artifact"]:
        errors.append(prefix + "Rust upload action is not the existing pinned action")
    config = upload.get("with")
    if set(upload) != {"name", "if", "uses", "with"}:
        errors.append(prefix + "Rust upload fields differ from the closed projection")
    if not isinstance(config, Mapping):
        return errors + [prefix + "Rust upload needs a with mapping"]
    if set(config) != {"name", "path", "if-no-files-found", "retention-days"}:
        errors.append(prefix + "Rust upload config fields changed")
    if config.get("name") != RUST_UPLOAD_NAME_PREFIX or config.get("path") != RUST_UPLOAD_PATH:
        errors.append(prefix + "Rust upload name/path changed")
    if config.get("if-no-files-found") != "error" or config.get("retention-days") != 14:
        errors.append(prefix + "Rust upload retention/error policy changed")
    if sum(str(step.get("uses", "")).startswith("actions/upload-artifact@") for step in steps) != 2:
        errors.append(prefix + "AMD job must retain exactly two uploads")
    return errors
