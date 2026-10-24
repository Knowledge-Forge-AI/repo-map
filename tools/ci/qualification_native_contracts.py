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

D12_NATIVE_AMD64_REQUIRED_TOKENS: tuple[str, ...] = (
    "python3 tools/run_tests.py", "--sandbox", "--suite int", "--no-coverage", "--jobs 1",
    "--pg-container-port 55433", "--d12-core-image-profile linux/amd64", "--d12-core-image-preflight",
    '--d12-core-image-source-sha256 "${D12_EXPECTED_SOURCE_SHA256}"',
    '--report-dir "${RUNNER_TEMP}/d12-native-amd64-report"',
    f"-- {D12_NATIVE_AMD64_NODE_ID}",
)

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
    "      - name: Install locked dependencies\n"
    "        env:\n"
    '          PIP_ONLY_BINARY: ":all:"\n'
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
    if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
        return [dict(step) for step in parsed["steps"] if isinstance(step, dict)]
    if isinstance(parsed, list):
        return [dict(step) for step in parsed if isinstance(step, dict)]
    raise ValueError(f"{path}: invalid system-hold step fragment")


def _project_workflow_text(
    base_workflow_text: str, *, job_fragment_path: Path = DEFAULT_NATIVE_JOB_FRAGMENT_PATH,
    hold_step_fragment_path: Path = DEFAULT_SYSTEM_HOLD_STEP_FRAGMENT_PATH,
) -> str:
    text = base_workflow_text
    if "tools/ci/psycopg_bootstrap.py" not in text and _UNIT_LOCK_STEP_BEFORE in text:
        text = text.replace(_UNIT_LOCK_STEP_BEFORE, _UNIT_LOCK_STEP_AFTER, 1)
    job_lines = [ln for ln in job_fragment_path.read_text(encoding="utf-8").splitlines() if ln.strip() != "jobs:"]
    job_block = "\n".join(job_lines) + "\n"
    hold_lines = [
        ("    " + ln if ln.strip() else "")
        for ln in hold_step_fragment_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() != "steps:"
    ]
    hold_block = "\n".join(hold_lines) + "\n"
    marker_job = "  staging-integration-gate:\n"
    if marker_job not in text:
        raise ValueError("base workflow text missing staging-integration-gate job")
    with_job = text.replace(marker_job, job_block + "\n" + marker_job, 1)
    main_idx = with_job.find("  main-system-gate:\n")
    if main_idx == -1:
        raise ValueError("base workflow text missing main-system-gate job")
    head, tail = with_job[:main_idx], with_job[main_idx:]
    for step_marker in (
        "      - name: Run canonical system qualification\n",
        "      - name: Run the main system gate\n",
    ):
        if step_marker in tail:
            return head + tail.replace(step_marker, hold_block + "\n" + step_marker, 1)
    raise ValueError("main-system-gate missing insertion point for system-hold step")


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
    new_jobs: dict[str, Any] = {}
    inserted_job = False
    for name, body in base_workflow.jobs.items():
        if name == "staging-integration-gate" and not inserted_job:
            new_jobs.update(job_frag)
            inserted_job = True
        if name == "unit-tests" and isinstance(body, dict):
            u_steps = list(body.get("steps") or ())
            if not any("psycopg_bootstrap.py" in str(s.get("run", "")) for s in u_steps if isinstance(s, dict)):
                updated: list[dict[str, Any]] = []
                for step in u_steps:
                    if isinstance(step, dict) and "tools/ci/project_dependencies.lock" in str(step.get("run", "")):
                        updated.append({
                            "name": "Build the hash-locked C Psycopg prerequisite",
                            "run": "python tools/ci/psycopg_bootstrap.py --python python",
                        })
                        updated.append({**step, "env": {"PIP_ONLY_BINARY": ":all:"}})
                    else:
                        updated.append(step)
                u_steps = updated
            new_jobs[name] = {**body, "steps": u_steps}
        elif name == "main-system-gate" and isinstance(body, dict):
            steps = list(body.get("steps") or ())
            setup_idxs = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python@")]
            sys_idxs = [
                i for i, s in enumerate(steps)
                if "tools/run_tests.py" in str(s.get("run", "")) or "system" in str(s.get("name", "")).lower()
            ]
            insert_at = setup_idxs[0] + 1 if setup_idxs else (sys_idxs[0] if sys_idxs else len(steps))
            new_jobs[name] = {**body, "steps": [*steps[:insert_at], *hold_steps, *steps[insert_at:]]}
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
            raw_tok = str(word)
            if raw_tok in _CMD_PREFIX_KEYWORDS:
                continue
            stripped = raw_tok.lstrip("({")
            if stripped in _LOOP_KEYWORDS:
                return True
            if stripped in _CMD_PREFIX_KEYWORDS or ("=" in stripped and not stripped.startswith("=")):
                continue
            break
        for word in cmd:
            if isinstance(word, ShellWord):
                for part in word.parts:
                    if part.kind == "cmd_substitution" and len(part.raw) >= 3:
                        if script_contains_shell_loop(part.raw[2:-1]):
                            return True
    return False


def validate_d12_native_amd64_runner_command(
    command: str, *, workflow_name: str = PUBLIC_QUALIFICATION_WORKFLOW_NAME,
) -> list[str]:
    prefix = f"{workflow_name}: "
    violations: list[str] = []
    for marker in D12_NATIVE_AMD64_FORBIDDEN_MARKERS:
        if marker in command:
            violations.append(prefix + f"d12-native-amd64 contains forbidden marker {marker!r}")
    try:
        parsed = parse_shell_script(command)
        has_loop = script_contains_shell_loop(command)
    except ValueError:
        return violations + [prefix + "d12-native-amd64 shell parse error: command cannot be parsed"]
    if has_loop:
        violations.append(prefix + "d12-native-amd64 must not wrap runner in a retry loop")
    runners = [
        cmd[2:] for cmd in parsed
        if len(cmd) >= 2 and cmd[0] in {"python", "python3"}
        and cmd[1] in {"tools/run_tests.py", "./tools/run_tests.py"}
    ]
    if len(runners) != 1:
        return violations + [
            prefix + f"d12-native-amd64 must invoke python3 tools/run_tests.py once; found {len(runners)}"
        ]
    args = runners[0]
    if "--" not in args:
        return violations + [prefix + "d12-native-amd64 runner must separate node selector after --"]
    sep = args.index("--")
    pre_args, post_args = args[:sep], args[sep + 1 :]
    if [str(x) for x in post_args] != [D12_NATIVE_AMD64_NODE_ID]:
        violations.append(prefix + f"d12-native-amd64 must select exact node {D12_NATIVE_AMD64_NODE_ID}")
    for flag, expected in {
        "--suite": "int", "--jobs": "1", "--pg-container-port": "55433", "--d12-core-image-profile": "linux/amd64",
    }.items():
        if _opt_vals(pre_args, flag) != [expected]:
            violations.append(prefix + f"d12-native-amd64 runner missing {flag} {expected}")
    for flag in ("--sandbox", "--no-coverage", "--d12-core-image-preflight"):
        if pre_args.count(flag) != 1:
            violations.append(prefix + f"d12-native-amd64 runner missing {flag}")
    if not validate_command_option_var_expansion(
        pre_args, "--d12-core-image-source-sha256", "D12_EXPECTED_SOURCE_SHA256"
    ):
        violations.append(
            prefix + "d12-native-amd64 runner must expand D12_EXPECTED_SOURCE_SHA256 for --d12-core-image-source-sha256"
        )
    rep_dirs = _opt_vals(pre_args, "--report-dir")
    if len(rep_dirs) != 1 or rep_dirs[0] is None or not validate_var_path_expansion(
        rep_dirs[0], "RUNNER_TEMP", "/d12-native-amd64-report"
    ):
        violations.append(
            prefix + "d12-native-amd64 runner must set --report-dir to ${RUNNER_TEMP}/d12-native-amd64-report"
        )
    return violations


def validate_d12_native_amd64_job(workflow: Workflow) -> list[str]:
    prefix = f"{workflow.path.name}: "
    violations: list[str] = [
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
    steps = workflow.job_steps(D12_NATIVE_AMD64_JOB_ID)
    allowed_actions = set(PINNED_PUBLIC_ACTIONS.values())
    for step in steps:
        uses = step.get("uses")
        if uses is not None and str(uses) not in allowed_actions:
            violations.append(prefix + f"d12-native-amd64 uses unapproved or unpinned action {uses!r}")
    bind_idxs = [
        i for i, s in enumerate(steps)
        if s.get("id") == "bind" and "CANDIDATE_SHA=" in str(s.get("run", ""))
        and "CANDIDATE_TREE=" in str(s.get("run", ""))
    ]
    prep_idxs = [i for i, s in enumerate(steps) if D12_NATIVE_AMD64_PREPARE_MARKER in str(s.get("run", ""))]
    run_idxs = [i for i, s in enumerate(steps) if "tools/run_tests.py" in str(s.get("run", ""))]
    seal_idxs = [i for i, s in enumerate(steps) if D12_NATIVE_AMD64_SEAL_MARKER in str(s.get("run", ""))]
    up_idxs = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(bind_idxs) != 1 or len(prep_idxs) != 1 or len(run_idxs) != 1 or len(seal_idxs) != 1 or len(up_idxs) != 1:
        return violations + [prefix + "d12-native-amd64 requires exact bind, prepare, runner, seal, and upload steps"]
    if not (bind_idxs[0] < prep_idxs[0] < run_idxs[0] < seal_idxs[0] < up_idxs[0]):
        violations.append(prefix + "d12-native-amd64 steps must order bind < prepare < runner < seal < upload")
    for label, step in (("prepare", steps[prep_idxs[0]]), ("runner", steps[run_idxs[0]])):
        if "if" in step:
            violations.append(prefix + f"d12-native-amd64 {label} step must not set if")
        if step.get("continue-on-error") not in (None, False):
            violations.append(prefix + f"d12-native-amd64 {label} step must not set continue-on-error")
    violations.extend(
        validate_d12_native_amd64_runner_command(
            str(steps[run_idxs[0]].get("run", "")), workflow_name=workflow.path.name
        )
    )
    if str(steps[seal_idxs[0]].get("if", "")) not in {"always()", "${{ always() }}"}:
        violations.append(prefix + "d12-native-amd64 seal step must run with if: always()")
    up_step = steps[up_idxs[0]]
    if str(up_step.get("if", "")) not in {"always()", "${{ always() }}"}:
        violations.append(prefix + "d12-native-amd64 upload step must run with if: always()")
    up_with = up_step.get("with")
    if not isinstance(up_with, dict) or up_with.get("retention-days") != D12_NATIVE_AMD64_RETENTION_DAYS:
        violations.append(prefix + f"d12-native-amd64 upload retention-days must be {D12_NATIVE_AMD64_RETENTION_DAYS}")
    return violations


def validate_d12_system_hold_step(workflow: Workflow, *, job_id: str = "main-system-gate") -> list[str]:
    prefix = f"{workflow.path.name}: {job_id} "
    if job_id not in workflow.jobs:
        return [prefix + "job is missing"]
    steps = workflow.job_steps(job_id)
    hold_idxs = [i for i, s in enumerate(steps) if D12_SYSTEM_HOLD_MARKER in str(s.get("run", ""))]
    if len(hold_idxs) != 1:
        return [prefix + f"requires exactly one d12-system-hold step; found {len(hold_idxs)}"]
    hold_idx = hold_idxs[0]
    if "if" in steps[hold_idx]:
        return [prefix + "d12-system-hold step must not set if"]
    if steps[hold_idx].get("continue-on-error") not in (None, False):
        return [prefix + "d12-system-hold step must not set continue-on-error"]
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
    if not verify_idxs or not setup_idxs or not sys_idxs or not (
        verify_idxs[0] < setup_idxs[0] < hold_idx < sys_idxs[0]
    ):
        return [
            prefix
            + "d12-system-hold step must appear after candidate verification and setup-python and before system runner"
        ]
    return []


def validate_maintained_fragments(repo_root: Path = REPO_ROOT) -> list[str]:
    job_frag = load_native_amd64_job_fragment(repo_root / "tools/ci/d12_native_amd64_job.yml")
    hold_steps = load_system_hold_step_fragment(repo_root / "tools/ci/d12_system_hold_step.yml")
    wf = Workflow(
        Path(PUBLIC_QUALIFICATION_WORKFLOW_NAME),
        {
            "jobs": {
                **job_frag,
                "main-system-gate": {
                    "steps": [
                        {"id": "bind", "run": "echo gate-request.json"},
                        {"uses": PINNED_PUBLIC_ACTIONS["setup_python"]},
                        *hold_steps,
                        {"run": "python3 tools/run_tests.py --suite system"},
                    ]
                },
            }
        },
    )
    return [*validate_d12_native_amd64_job(wf), *validate_d12_system_hold_step(wf)]
