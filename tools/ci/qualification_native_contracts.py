"""Structured contracts for the public native D12 qualification job and system hold."""

from __future__ import annotations

from pathlib import Path
from typing import Any, overload

from ci.qualification_shell_syntax import (
    ShellWord, parse_shell_script, validate_command_option_var_expansion, validate_var_path_expansion,
)
from ci.workflow_model import Workflow, parse_yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_QUALIFICATION_WORKFLOW_NAME = "repomap-release-qualification.yml"
D12_NATIVE_AMD64_JOB_ID = "d12-native-amd64"
D12_NATIVE_AMD64_RUNNER = "ubuntu-24.04"
D12_NATIVE_AMD64_MAX_TIMEOUT_MINUTES = 90
D12_NATIVE_AMD64_RETENTION_DAYS = 14
D12_NATIVE_AMD64_NEEDS = ("source-and-export-policy",)
D12_NATIVE_AMD64_NODE_ID = (
    "src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py"
    "::test_d12_core_image_refresh_candidate_round_trip"
)
D12_NATIVE_AMD64_PREPARE_MARKER = "python3 tools/ci/d12_hosted_qualification.py prepare"
D12_NATIVE_AMD64_SEAL_MARKER = "python3 tools/ci/d12_hosted_qualification.py seal"
D12_SYSTEM_HOLD_MARKER = "python3 tools/ci/d12_hosted_qualification.py system-hold"
D12_NATIVE_AMD64_RUNNER_MARKER = "--d12-core-image-profile linux/amd64"
D12_SYSTEM_ADMISSION_HOLD_SUFFIX = "/repomap-d12-system-admission/hold.json"
D12_SYSTEM_ADMISSION_PROOF_SUFFIX = "/repomap-d12-system-admission/proof.json"
D12_SYSTEM_ADMISSION_UPLOAD_PATH = "${{ runner.temp }}/repomap-d12-system-admission"
# ADR 0102: the one exact raw Python 3.12.16 AMD config selected for the native component diagnostic.
D12_NATIVE_AMD64_RAW_PYTHON_CONFIG = "sha256:ae4e8b7c575fabea88a029b6cae757f342ca2525e07f7c22272d5105c346b35e"
D12_NATIVE_AMD64_REQUIRED_TOKENS: tuple[str, ...] = (
    "python3 tools/run_tests.py", "--sandbox", "--suite int", "--no-coverage", "--jobs 1",
    "--pg-container-port 55433", "--d12-core-image-profile linux/amd64", "--d12-core-image-preflight",
    f"--smoke-image-reference {D12_NATIVE_AMD64_RAW_PYTHON_CONFIG}",
    '--d12-core-image-source-sha256 "${D12_EXPECTED_SOURCE_SHA256}"',
    '--report-dir "${RUNNER_TEMP}/d12-native-amd64-report"', f"-- {D12_NATIVE_AMD64_NODE_ID}",
)
_NATIVE_VALUES = {"--suite": "int", "--jobs": "1", "--pg-container-port": "55433",
                  "--d12-core-image-profile": "linux/amd64"}
_NATIVE_FLAGS = ("--sandbox", "--no-coverage", "--d12-core-image-preflight")
_NATIVE_OPTIONS = frozenset({*_NATIVE_VALUES, "--d12-core-image-source-sha256", "--report-dir",
                             "--smoke-image-reference"})
D12_NATIVE_AMD64_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "--d12-core-image-budget-ledger", "--d12-core-image-profile linux/arm64",
    "--suite all", "--suite unit", "--suite staging", "--suite system", "--suite smoke",
    "--report ", "setup-qemu-action", "setup-buildx-action", "buildx create", "ubuntu-24.04-arm",
)
PINNED_PUBLIC_ACTIONS: dict[str, str] = {
    "checkout": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "setup_python": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "upload_artifact": "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
DEFAULT_NATIVE_JOB_FRAGMENT_PATH = REPO_ROOT / "tools/ci/d12_native_amd64_job.yml"
DEFAULT_SYSTEM_HOLD_STEP_FRAGMENT_PATH = REPO_ROOT / "tools/ci/d12_system_hold_step.yml"
_LOOP_KEYWORDS = frozenset({"for", "while", "until", "do", "done"})
_CMD_PREFIX_KEYWORDS = frozenset({"!", "{", "(", "then", "else", "elif", "time"})
_UNIT_LOCK_STEP_BEFORE = (
    "      - name: Install locked dependencies\n"
    "        run: python -m pip install --require-hashes --no-deps --requirement tools/ci/project_dependencies.lock\n"
)
_UNIT_LOCK_STEP_AFTER = (
    "      - name: Build the hash-locked C Psycopg prerequisite\n"
    "        run: python tools/ci/psycopg_bootstrap.py --python python\n\n"
    "      - name: Install locked dependencies\n        env:\n          PIP_ONLY_BINARY: \":all:\"\n"
    "        run: python -m pip install --require-hashes --no-deps --requirement tools/ci/project_dependencies.lock\n"
)

def load_native_amd64_job_fragment(path: Path = DEFAULT_NATIVE_JOB_FRAGMENT_PATH) -> dict[str, Any]:
    parsed = parse_yaml(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict):
        return dict(parsed["jobs"])
    if isinstance(parsed, dict) and D12_NATIVE_AMD64_JOB_ID in parsed:
        return dict(parsed)
    raise ValueError(f"{path}: invalid d12-native-amd64 job fragment")

def load_system_hold_step_fragment(path: Path = DEFAULT_SYSTEM_HOLD_STEP_FRAGMENT_PATH) -> list[dict[str, Any]]:
    parsed = parse_yaml(path.read_text(encoding="utf-8"))
    raw = parsed.get("steps") if isinstance(parsed, dict) else parsed
    if isinstance(raw, list):
        return [dict(step) for step in raw if isinstance(step, dict)]
    raise ValueError(f"{path}: invalid system-hold step fragment")

def _project_main_system_tail(tail: str, hold_block: str) -> str:
    updated = tail.replace("    runs-on: ubuntu-latest\n", f"    runs-on: {D12_NATIVE_AMD64_RUNNER}\n", 1)
    if "--d12-system-proof-json" not in updated:
        proof_arg = '            --d12-system-proof-json "${RUNNER_TEMP}/repomap-d12-system-admission/proof.json" \\\n'
        updated = updated.replace(
            '            --repository "${GITHUB_REPOSITORY}" \\\n            --report \\\n',
            '            --repository "${GITHUB_REPOSITORY}" \\\n' + proof_arg + '            --report \\\n', 1,
        )
    if D12_SYSTEM_ADMISSION_UPLOAD_PATH not in updated:
        up_lines = f"          path: |\n            ci-system-report\n            {D12_SYSTEM_ADMISSION_UPLOAD_PATH}\n"
        updated = updated.replace("          path: ci-system-report\n", up_lines, 1)
    for step_marker in (
        "      - name: Record free disk before the system suite\n",
        "      - name: Run canonical system qualification\n", "      - name: Run the main system gate\n",
    ):
        if step_marker in updated:
            return updated.replace(step_marker, hold_block + "\n" + step_marker, 1)
    raise ValueError("main-system-gate missing insertion point for system-hold step")

def _project_workflow_text(
    base_workflow_text: str, *, job_fragment_path: Path = DEFAULT_NATIVE_JOB_FRAGMENT_PATH,
    hold_step_fragment_path: Path = DEFAULT_SYSTEM_HOLD_STEP_FRAGMENT_PATH,
) -> str:
    text = base_workflow_text
    if "tools/ci/psycopg_bootstrap.py" not in text and _UNIT_LOCK_STEP_BEFORE in text:
        text = text.replace(_UNIT_LOCK_STEP_BEFORE, _UNIT_LOCK_STEP_AFTER, 1)
    job_lines = [ln for ln in job_fragment_path.read_text(encoding="utf-8").splitlines() if ln.strip() != "jobs:"]
    hold_lines = [
        ("    " + ln if ln.strip() else "")
        for ln in hold_step_fragment_path.read_text(encoding="utf-8").splitlines() if ln.strip() != "steps:"
    ]
    marker_job = "  staging-integration-gate:\n"
    if marker_job not in text:
        raise ValueError("base workflow text missing staging-integration-gate job")
    with_job = text.replace(marker_job, "\n".join(job_lines) + "\n\n" + marker_job, 1)
    main_idx = with_job.find("  main-system-gate:\n")
    if main_idx == -1:
        raise ValueError("base workflow text missing main-system-gate job")
    return with_job[:main_idx] + _project_main_system_tail(with_job[main_idx:], "\n".join(hold_lines) + "\n")

def _project_main_system_job_dict(body: dict[str, Any], hold_steps: list[dict[str, Any]]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for s in (x for x in (body.get("steps") or ()) if isinstance(x, dict)):
        s_copy, run_txt = dict(s), str(s.get("run", ""))
        if "tools/run_tests.py" in run_txt and "--suite system" in run_txt and "--d12-system-proof-json" not in run_txt:
            s_copy["run"] = (
                run_txt.rstrip()
                + ' \\\n  --d12-system-proof-json "${RUNNER_TEMP}/repomap-d12-system-admission/proof.json"\n'
            )
        if str(s_copy.get("uses", "")).startswith("actions/upload-artifact@"):
            w = dict(s_copy.get("with") or {})
            if w.get("path") == "ci-system-report":
                s_copy["with"] = {**w, "path": f"ci-system-report\n{D12_SYSTEM_ADMISSION_UPLOAD_PATH}"}
        steps.append(s_copy)
    setup_idxs = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python@")]
    sys_idxs = [
        i for i, s in enumerate(steps)
        if "tools/run_tests.py" in str(s.get("run", "")) or "system" in str(s.get("name", "")).lower()
    ]
    insert_at = setup_idxs[0] + 1 if setup_idxs else (sys_idxs[0] if sys_idxs else len(steps))
    return {**body, "runs-on": D12_NATIVE_AMD64_RUNNER, "steps": [*steps[:insert_at], *hold_steps, *steps[insert_at:]]}

@overload
def project_public_qualification_workflow(
    base_workflow: str, *, job_fragment_path: Path = ..., hold_step_fragment_path: Path = ...,
) -> str: ...
@overload
def project_public_qualification_workflow(
    base_workflow: Workflow, *, job_fragment_path: Path = ..., hold_step_fragment_path: Path = ...,
) -> Workflow: ...
def project_public_qualification_workflow(
    base_workflow: str | Workflow, *, job_fragment_path: Path = DEFAULT_NATIVE_JOB_FRAGMENT_PATH,
    hold_step_fragment_path: Path = DEFAULT_SYSTEM_HOLD_STEP_FRAGMENT_PATH,
) -> str | Workflow:
    if isinstance(base_workflow, str):
        return _project_workflow_text(
            base_workflow, job_fragment_path=job_fragment_path, hold_step_fragment_path=hold_step_fragment_path
        )
    job_frag = load_native_amd64_job_fragment(job_fragment_path)
    hold_steps = load_system_hold_step_fragment(hold_step_fragment_path)
    new_jobs, inserted_job = {}, False
    for name, body in base_workflow.jobs.items():
        if name == "staging-integration-gate" and not inserted_job:
            new_jobs.update(job_frag)
            inserted_job = True
        if name == "unit-tests" and isinstance(body, dict):
            u_steps = list(body.get("steps") or ())
            if not any("psycopg_bootstrap.py" in str(s.get("run", "")) for s in u_steps if isinstance(s, dict)):
                bootstrap = {
                    "name": "Build the hash-locked C Psycopg prerequisite",
                    "run": "python tools/ci/psycopg_bootstrap.py --python python",
                }
                u_steps = [
                    item
                    for s in u_steps
                    for item in (
                        (bootstrap, {**s, "env": {"PIP_ONLY_BINARY": ":all:"}})
                        if isinstance(s, dict) and "tools/ci/project_dependencies.lock" in str(s.get("run", ""))
                        else (s,)
                    )
                ]
            new_jobs[name] = {**body, "steps": u_steps}
        elif name == "main-system-gate" and isinstance(body, dict):
            new_jobs[name] = _project_main_system_job_dict(body, hold_steps)
        else:
            new_jobs[name] = body
    if not inserted_job:
        new_jobs.update(job_frag)
    return Workflow(path=base_workflow.path, document={**base_workflow.document, "jobs": new_jobs})

def _opt_vals(args: list[str], flag: str) -> list[str | None]:
    vals: list[str | None] = []
    for idx, tok in enumerate(args):
        if tok == flag:
            nxt = args[idx + 1] if idx + 1 < len(args) else None
            vals.append(nxt if nxt and not nxt.startswith("--") else None)
        elif tok.startswith(flag + "="):
            vals.append(tok[len(flag) + 1 :] or None)
    return vals

def script_contains_shell_loop(script: str) -> bool:
    for cmd in parse_shell_script(script):
        for word in cmd:
            if not (isinstance(word, ShellWord) and word.parts and all(p.kind == "literal" for p in word.parts)):
                break
            raw_tok, stripped = str(word), str(word).lstrip("({")
            if raw_tok in _CMD_PREFIX_KEYWORDS:
                continue
            if stripped in _LOOP_KEYWORDS:
                return True
            if stripped in _CMD_PREFIX_KEYWORDS or ("=" in stripped and not stripped.startswith("=")):
                continue
            break
        for word in cmd:
            if isinstance(word, ShellWord) and any(
                p.kind == "cmd_substitution" and len(p.raw) >= 3 and script_contains_shell_loop(p.raw[2:-1])
                for p in word.parts
            ):
                return True
    return False

def validate_d12_native_amd64_runner_command(
    command: str, *, workflow_name: str = PUBLIC_QUALIFICATION_WORKFLOW_NAME,
) -> list[str]:
    prefix = f"{workflow_name}: d12-native-amd64 "
    violations = [prefix + f"contains forbidden marker {m!r}" for m in D12_NATIVE_AMD64_FORBIDDEN_MARKERS
                  if m in command]
    try:
        parsed, has_loop = parse_shell_script(command), script_contains_shell_loop(command)
    except ValueError:
        return violations + [prefix + "shell parse error: command cannot be parsed"]
    violations += [prefix + "must not wrap runner in a retry loop"] if has_loop else []
    runners = [cmd[2:] for cmd in parsed if len(cmd) >= 2 and cmd[0] in {"python", "python3"}
               and cmd[1] in {"tools/run_tests.py", "./tools/run_tests.py"}]
    if len(runners) != 1:
        return violations + [prefix + f"must invoke python3 tools/run_tests.py once; found {len(runners)}"]
    if "--" not in (args := runners[0]):
        return violations + [prefix + "runner must separate node selector after --"]
    pre_args, post_args = args[:args.index("--")], args[args.index("--") + 1 :]
    if [str(x) for x in post_args] != [D12_NATIVE_AMD64_NODE_ID]:
        violations.append(prefix + f"must select exact node {D12_NATIVE_AMD64_NODE_ID}")
    violations.extend(prefix + f"runner rejects unknown or abbreviated option {tok!r}"
                      for tok in _unexpected_native_tokens(pre_args))
    violations.extend(prefix + f"runner missing {flag} {expected}"
                      for flag, expected in _NATIVE_VALUES.items() if _opt_vals(pre_args, flag) != [expected])
    violations.extend(prefix + f"runner missing {flag}" for flag in _NATIVE_FLAGS if pre_args.count(flag) != 1
                      or any(str(tok).startswith(flag + "=") for tok in pre_args))
    pins = [i for i, tok in enumerate(pre_args) if str(tok).split("=", 1)[0] == "--smoke-image-reference"]
    if len(pins) != 1 or [str(t) for t in pre_args[pins[0]:pins[0] + 2]] != [  # ADR 0102 B2: one exact raw config
            "--smoke-image-reference", D12_NATIVE_AMD64_RAW_PYTHON_CONFIG]:
        violations.append(prefix + f"runner must pass exactly one literal --smoke-image-reference "
                          f"{D12_NATIVE_AMD64_RAW_PYTHON_CONFIG}")
    if any(str(tok) == "--report" or str(tok).startswith("--report=") for tok in pre_args):
        violations.append(prefix + "runner must not pass --report with --no-coverage")
    if not validate_command_option_var_expansion(pre_args, "--d12-core-image-source-sha256",
                                                 "D12_EXPECTED_SOURCE_SHA256"):
        violations.append(prefix + "runner must expand D12_EXPECTED_SOURCE_SHA256")
    rep_dirs = _opt_vals(pre_args, "--report-dir")
    if len(rep_dirs) != 1 or rep_dirs[0] is None or not validate_var_path_expansion(
            rep_dirs[0], "RUNNER_TEMP", "/d12-native-amd64-report"):
        violations.append(prefix + "runner must set --report-dir in RUNNER_TEMP")
    return violations

def _unexpected_native_tokens(pre_args: list[str]) -> list[str]:
    """B2: each pre-separator word is an exact full allowlisted option or the one value that option consumes."""
    found: list[str] = []
    idx = 0
    while idx < len(pre_args):
        tok = str(pre_args[idx])
        joined = tok in _NATIVE_FLAGS or ("=" in tok and tok.split("=", 1)[0] in _NATIVE_OPTIONS)
        found += [] if joined or tok in _NATIVE_OPTIONS else [tok]
        idx += 1 if joined or tok not in _NATIVE_OPTIONS else 2
    return found

def validate_d12_native_amd64_job(workflow: Workflow) -> list[str]:
    prefix = f"{workflow.path.name}: "
    violations = [
        prefix + f"ARM64 job {name!r} is out of scope in first slice"
        for name in workflow.jobs if "arm64" in name.lower()
    ]
    if D12_NATIVE_AMD64_JOB_ID not in workflow.jobs:
        return violations + [prefix + f"missing required job {D12_NATIVE_AMD64_JOB_ID}"]
    job = workflow.jobs[D12_NATIVE_AMD64_JOB_ID]
    if not isinstance(job, dict):
        return violations + [prefix + "d12-native-amd64 job must be a mapping"]
    if job.get("runs-on") != D12_NATIVE_AMD64_RUNNER:
        violations.append(prefix + f"d12-native-amd64 runs-on must be {D12_NATIVE_AMD64_RUNNER}")
    if job.get("timeout-minutes") != D12_NATIVE_AMD64_MAX_TIMEOUT_MINUTES:
        violations.append(prefix + f"d12-native-amd64 timeout-minutes must be {D12_NATIVE_AMD64_MAX_TIMEOUT_MINUTES}")
    if job.get("needs") != list(D12_NATIVE_AMD64_NEEDS):
        violations.append(prefix + "d12-native-amd64 needs must be [source-and-export-policy]")
    if "strategy" in job:
        violations.append(prefix + "d12-native-amd64 must not use matrix strategy")
    steps, allowed_actions = workflow.job_steps(D12_NATIVE_AMD64_JOB_ID), set(PINNED_PUBLIC_ACTIONS.values())
    for step in steps:
        if step.get("uses") is not None and str(step.get("uses")) not in allowed_actions:
            violations.append(prefix + f"d12-native-amd64 uses unapproved or unpinned action {step.get('uses')!r}")
    bind_idxs = [i for i, s in enumerate(steps) if s.get("id") == "bind" and "CANDIDATE_SHA=" in str(s.get("run", ""))
                 and "CANDIDATE_TREE=" in str(s.get("run", ""))]
    prep_idxs = [i for i, s in enumerate(steps) if D12_NATIVE_AMD64_PREPARE_MARKER in str(s.get("run", ""))]
    run_idxs = [i for i, s in enumerate(steps) if "tools/run_tests.py" in str(s.get("run", ""))]
    seal_idxs = [i for i, s in enumerate(steps) if D12_NATIVE_AMD64_SEAL_MARKER in str(s.get("run", ""))]
    up_idxs = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if (len(bind_idxs), len(prep_idxs), len(run_idxs), len(seal_idxs), len(up_idxs)) != (1, 1, 1, 1, 1):
        return violations + [prefix + "d12-native-amd64 requires exact bind, prepare, runner, seal, and upload steps"]
    if not (bind_idxs[0] < prep_idxs[0] < run_idxs[0] < seal_idxs[0] < up_idxs[0]):
        violations.append(prefix + "d12-native-amd64 steps must order bind < prepare < runner < seal < upload")
    for label, step in (("prepare", steps[prep_idxs[0]]), ("runner", steps[run_idxs[0]])):
        if "if" in step:
            violations.append(prefix + f"d12-native-amd64 {label} step must not set if")
        if step.get("continue-on-error") not in (None, False):
            violations.append(prefix + f"d12-native-amd64 {label} step must not set continue-on-error")
    run_cmd = str(steps[run_idxs[0]].get("run", ""))
    violations.extend(validate_d12_native_amd64_runner_command(run_cmd, workflow_name=workflow.path.name))
    if str(steps[seal_idxs[0]].get("if", "")) not in {"always()", "${{ always() }}"}:
        violations.append(prefix + "d12-native-amd64 seal step must run with if: always()")
    up_step, up_with = steps[up_idxs[0]], steps[up_idxs[0]].get("with")
    if str(up_step.get("if", "")) not in {"always()", "${{ always() }}"}:
        violations.append(prefix + "d12-native-amd64 upload step must run with if: always()")
    if not isinstance(up_with, dict) or up_with.get("retention-days") != D12_NATIVE_AMD64_RETENTION_DAYS:
        violations.append(prefix + f"d12-native-amd64 upload retention-days must be {D12_NATIVE_AMD64_RETENTION_DAYS}")
    return violations

def _validate_hold_step_command(hold_run: str, prefix: str) -> list[str]:
    try:
        cmds = parse_shell_script(hold_run)
    except ValueError:
        return [prefix + "d12-system-hold shell command cannot be parsed"]
    hold_cmds = [
        cmd[3:] for cmd in cmds
        if len(cmd) >= 3 and cmd[0] in {"python", "python3"}
        and cmd[1] == "tools/ci/d12_hosted_qualification.py" and cmd[2] == "system-hold"
    ]
    if len(hold_cmds) != 1:
        return [prefix + "d12-system-hold must invoke d12_hosted_qualification.py system-hold once"]
    args, violations = hold_cmds[0], []
    for flag, suffix in (
        ("--output-json", D12_SYSTEM_ADMISSION_HOLD_SUFFIX), ("--proof-json", D12_SYSTEM_ADMISSION_PROOF_SUFFIX),
    ):
        vals = _opt_vals(args, flag)
        if len(vals) != 1 or vals[0] is None or not validate_var_path_expansion(vals[0], "RUNNER_TEMP", suffix):
            violations.append(prefix + f"d12-system-hold missing valid {flag} in RUNNER_TEMP")
    return violations

def validate_d12_system_hold_step(workflow: Workflow, *, job_id: str = "main-system-gate") -> list[str]:
    prefix = f"{workflow.path.name}: {job_id} "
    if job_id not in workflow.jobs:
        return [prefix + "job is missing"]
    job, steps, violations = workflow.jobs[job_id], workflow.job_steps(job_id), []
    if isinstance(job, dict) and job.get("runs-on") != D12_NATIVE_AMD64_RUNNER:
        violations.append(prefix + f"runs-on must be {D12_NATIVE_AMD64_RUNNER}")
    hold_idxs = [i for i, s in enumerate(steps) if D12_SYSTEM_HOLD_MARKER in str(s.get("run", ""))]
    if len(hold_idxs) != 1:
        return violations + [prefix + f"requires exactly one d12-system-hold step; found {len(hold_idxs)}"]
    hold_idx = hold_idxs[0]
    if "if" in steps[hold_idx]:
        violations.append(prefix + "d12-system-hold step must not set if")
    if steps[hold_idx].get("continue-on-error") not in (None, False):
        violations.append(prefix + "d12-system-hold step must not set continue-on-error")
    violations.extend(_validate_hold_step_command(str(steps[hold_idx].get("run", "")), prefix))
    verify_idxs = [
        i for i, s in enumerate(steps)
        if s.get("id") == "bind" or "gate-request.json" in str(s.get("run", ""))
        or "trusted_gate_contract.py" in str(s.get("run", ""))
    ]
    setup_idxs = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python@")]
    sys_idxs = [
        i for i, s in enumerate(steps)
        if "--suite system" in str(s.get("run", "")) or "--suite \\\n            system" in str(s.get("run", ""))
    ]
    if not (verify_idxs and setup_idxs and sys_idxs and verify_idxs[0] < setup_idxs[0] < hold_idx < sys_idxs[0]):
        return violations + [prefix + "d12-system-hold step must appear after setup-python and before system runner"]
    for idx in [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/upload-artifact@")]:
        up_with = steps[idx].get("with")
        raw_path = str(up_with.get("path", "")) if isinstance(up_with, dict) else ""
        if "ci-system-report" not in raw_path or D12_SYSTEM_ADMISSION_UPLOAD_PATH not in raw_path:
            violations.append(prefix + "upload-artifact path must include ci-system-report and d12-system-admission")
    return violations

def validate_maintained_fragments(repo_root: Path = REPO_ROOT) -> list[str]:
    job_frag = load_native_amd64_job_fragment(repo_root / "tools/ci/d12_native_amd64_job.yml")
    hold_steps = load_system_hold_step_fragment(repo_root / "tools/ci/d12_system_hold_step.yml")
    sys_cmd = (
        "python3 tools/run_tests.py --suite system "
        '--d12-system-proof-json "${RUNNER_TEMP}/repomap-d12-system-admission/proof.json"'
    )
    up_path = f"ci-system-report\n{D12_SYSTEM_ADMISSION_UPLOAD_PATH}"
    main_steps: list[dict[str, Any]] = [
        {"id": "bind", "run": "echo gate-request.json"}, {"uses": PINNED_PUBLIC_ACTIONS["setup_python"]},
        *hold_steps, {"run": sys_cmd}, {"uses": PINNED_PUBLIC_ACTIONS["upload_artifact"], "with": {"path": up_path}},
    ]
    wf = Workflow(
        Path(PUBLIC_QUALIFICATION_WORKFLOW_NAME),
        {"jobs": {**job_frag, "main-system-gate": {"runs-on": D12_NATIVE_AMD64_RUNNER, "steps": main_steps}}},
    )
    return [*validate_d12_native_amd64_job(wf), *validate_d12_system_hold_step(wf)]
