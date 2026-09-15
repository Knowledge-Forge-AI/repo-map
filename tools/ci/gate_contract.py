"""The project-owned logical CI gate request/result contract and CLI.

``repomap-ci-gate-request-v1`` means exactly one thing: qualify exactly this
head against exactly this base for exactly this gate. Any drift in the base or
head invalidates the request, and the newer revision is never silently
qualified under an older approval.

``workflow_dispatch`` is only the bootstrap transport. The same logical request
is constructible by a JACA broker, so all binding logic lives here rather than
in workflow YAML, and every input is injected so the checks are hermetic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

# Ensure absolute import `ci.*` resolves when invoked as a script from tools/ci/
_PARENT = Path(__file__).resolve().parent
_TOOLS_ROOT = _PARENT if (_PARENT / "ci").is_dir() else _PARENT.parent
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from ci.gate_contract_bindings import (
    GATE_BASE_BRANCHES as GATE_BASE_BRANCHES,
    GATE_HEAD_BRANCHES as GATE_HEAD_BRANCHES,
    REQUEST_FIELDS as REQUEST_FIELDS,
    REQUEST_SCHEMA as REQUEST_SCHEMA,
    GateBindingError as GateBindingError,
    GateRequest as GateRequest,
    MergeCandidate as MergeCandidate,
    PullRequestState as PullRequestState,
    _require as _require,
    _require_sha as _require_sha,
    resolve_request as resolve_request,
    validate_candidate as validate_candidate,
)
from ci.gate_contract_results import (
    CONCLUSIONS as CONCLUSIONS,
    RESULT_FIELDS as RESULT_FIELDS,
    RESULT_SCHEMA as RESULT_SCHEMA,
    build_result as build_result,
    validate_result_payload as validate_result_payload,
)
from ci.gate_contract_runtime import (
    SYSTEM_BINDING_FIELDS as SYSTEM_BINDING_FIELDS,
    SYSTEM_REPORT_FIELDS as SYSTEM_REPORT_FIELDS,
    validate_successful_system_runtime as validate_successful_system_runtime,
)

_validate_successful_system_runtime = validate_successful_system_runtime


def _resolve_command(arguments: argparse.Namespace) -> int:
    payload = json.loads(Path(arguments.pull_request_json).read_text(encoding="utf-8"))
    request = resolve_request(
        gate_kind=arguments.gate_kind,
        pr_number=arguments.pr_number,
        approved_base_sha=arguments.approved_base_sha,
        approved_head_sha=arguments.approved_head_sha,
        executor_ref=arguments.executor_ref,
        executor_sha=arguments.executor_sha,
        approval_id=arguments.approval_id,
        repository=arguments.repository,
        pull_request=PullRequestState.from_api_payload(payload),
    )
    Path(arguments.request_out).write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _load_request(path: str) -> GateRequest:
    return GateRequest.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def _candidate_from_arguments(arguments: argparse.Namespace) -> MergeCandidate:
    return MergeCandidate(
        sha=arguments.candidate_sha,
        tree=arguments.candidate_tree,
        first_parent=arguments.candidate_base_parent,
        second_parent=arguments.candidate_head_parent,
    )


def _verify_command(arguments: argparse.Namespace) -> int:
    validate_candidate(
        _load_request(arguments.request_json),
        _candidate_from_arguments(arguments),
    )
    return 0


def _record_command(arguments: argparse.Namespace) -> int:
    request = _load_request(arguments.request_json)
    candidate = _candidate_from_arguments(arguments)
    system_report_path = getattr(arguments, "system_report_json", None)
    system_binding_path = getattr(arguments, "system_binding_json", None)
    result = build_result(
        request=request,
        candidate=candidate,
        conclusion=arguments.conclusion,
        system_report_path=system_report_path,
        system_binding_path=system_binding_path,
    )
    Path(arguments.result_out).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve", help="bind an approved gate request")
    resolve.add_argument("--gate-kind", required=True)
    resolve.add_argument("--pr-number", required=True, type=int)
    resolve.add_argument("--approved-base-sha", required=True)
    resolve.add_argument("--approved-head-sha", required=True)
    resolve.add_argument("--executor-ref", required=True)
    resolve.add_argument("--executor-sha", required=True)
    resolve.add_argument("--approval-id", required=True)
    resolve.add_argument("--repository", required=True)
    resolve.add_argument("--pull-request-json", required=True)
    resolve.add_argument("--request-out", required=True)
    resolve.set_defaults(handler=_resolve_command)

    def add_candidate_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--request-json", required=True)
        command.add_argument("--candidate-sha", required=True)
        command.add_argument("--candidate-tree", required=True)
        command.add_argument("--candidate-base-parent", required=True)
        command.add_argument("--candidate-head-parent", required=True)

    verify = commands.add_parser("verify", help="prove the tested candidate binding")
    add_candidate_arguments(verify)
    verify.set_defaults(handler=_verify_command)

    record = commands.add_parser("record", help="emit the gate result artifact")
    add_candidate_arguments(record)
    record.add_argument(
        "--conclusion", required=True, choices=sorted(CONCLUSIONS)
    )
    record.add_argument("--result-out", required=True)
    record.add_argument("--system-report-json", default=None)
    record.add_argument("--system-binding-json", default=None)
    record.set_defaults(handler=_record_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except GateBindingError as error:
        print(f"gate binding refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
