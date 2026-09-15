"""The project-owned logical CI gate request and candidate binding models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

REQUEST_SCHEMA = "repomap-ci-gate-request-v1"

#: Each logical gate fixes the base branch it is allowed to qualify against.
GATE_BASE_BRANCHES = {
    "staging": "staging",
    "main-system": "main",
}
GATE_HEAD_BRANCHES = {
    "main-system": "staging",
}

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_APPROVAL_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_BRANCH_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")

REQUEST_FIELDS = (
    "schema",
    "gate_kind",
    "pr_number",
    "base_branch",
    "base_sha",
    "head_branch",
    "head_sha",
    "approval_id",
    "repository",
)


class GateBindingError(RuntimeError):
    """The approved revision does not bind to current repository state."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise GateBindingError(reason)


def _require_sha(value: object, field: str) -> str:
    _require(
        isinstance(value, str) and _SHA_PATTERN.fullmatch(value),
        f"{field} must be a 40-hex commit SHA",
    )
    return str(value)


@dataclass(frozen=True, slots=True)
class PullRequestState:
    """Descriptive GitHub pull-request state used by the gate."""

    number: int
    state: str
    draft: bool
    base_ref: str
    head_ref: str
    head_repository: str

    @classmethod
    def from_api_payload(cls, payload: Mapping[str, Any]) -> PullRequestState:
        base = payload.get("base") or {}
        head = payload.get("head") or {}
        head_repository = (head.get("repo") or {}).get("full_name")
        return cls(
            number=int(payload["number"]),
            state=str(payload.get("state", "")),
            draft=bool(payload.get("draft", False)),
            base_ref=str(base.get("ref", "")),
            head_ref=str(head.get("ref", "")),
            head_repository="" if head_repository is None else str(head_repository),
        )


@dataclass(frozen=True, slots=True)
class GateRequest:
    """One approved, fully bound logical gate request."""

    gate_kind: str
    pr_number: int
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    approval_id: str
    repository: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "gate_kind": self.gate_kind,
            "pr_number": self.pr_number,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "approval_id": self.approval_id,
            "repository": self.repository,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GateRequest:
        unknown = set(payload).difference(REQUEST_FIELDS)
        _require(
            not unknown,
            f"gate request carries unknown fields: {sorted(unknown)}",
        )
        missing = set(REQUEST_FIELDS).difference(payload)
        _require(not missing, f"gate request is missing fields: {sorted(missing)}")
        _require(
            payload.get("schema") == REQUEST_SCHEMA,
            "gate request schema mismatch",
        )
        gate_kind = payload["gate_kind"]
        _require(
            isinstance(gate_kind, str) and gate_kind in GATE_BASE_BRANCHES,
            "gate request gate_kind is invalid",
        )
        pr_number = payload["pr_number"]
        _require(
            isinstance(pr_number, int)
            and not isinstance(pr_number, bool)
            and pr_number > 0,
            "gate request pr_number must be positive",
        )
        base_branch = payload["base_branch"]
        head_branch = payload["head_branch"]
        _require(
            base_branch == GATE_BASE_BRANCHES[gate_kind],
            "gate request base branch is invalid",
        )
        required_head = GATE_HEAD_BRANCHES.get(gate_kind)
        _require(
            isinstance(head_branch, str)
            and _BRANCH_PATTERN.fullmatch(head_branch)
            and (required_head is None or head_branch == required_head),
            "gate request head branch is invalid",
        )
        approval_id = payload["approval_id"]
        repository = payload["repository"]
        _require(
            isinstance(approval_id, str)
            and _APPROVAL_ID_PATTERN.fullmatch(approval_id),
            "gate request approval_id is invalid",
        )
        _require(
            isinstance(repository, str)
            and _REPOSITORY_PATTERN.fullmatch(repository),
            "gate request repository is invalid",
        )
        return cls(
            gate_kind=gate_kind,
            pr_number=pr_number,
            base_branch=base_branch,
            base_sha=_require_sha(payload["base_sha"], "base_sha"),
            head_branch=head_branch,
            head_sha=_require_sha(payload["head_sha"], "head_sha"),
            approval_id=approval_id,
            repository=repository,
        )


@dataclass(frozen=True, slots=True)
class MergeCandidate:
    """The exact merge commit the gate actually qualified."""

    sha: str
    tree: str
    first_parent: str
    second_parent: str


def resolve_request(
    *,
    gate_kind: str,
    pr_number: int,
    approved_base_sha: str,
    approved_head_sha: str,
    executor_ref: str,
    executor_sha: str,
    approval_id: str,
    repository: str,
    pull_request: PullRequestState,
) -> GateRequest:
    """Validate trusted executor and descriptive PR state, then bind the request."""
    _require(gate_kind in GATE_BASE_BRANCHES, f"unsupported gate_kind {gate_kind!r}")
    _require(
        _APPROVAL_ID_PATTERN.fullmatch(approval_id),
        "approval_id must be a short opaque correlation token",
    )
    _require(
        _REPOSITORY_PATTERN.fullmatch(repository), "repository must be owner/name"
    )
    _require(
        isinstance(pr_number, int) and pr_number > 0,
        "pr_number must be positive",
    )
    base_sha = _require_sha(approved_base_sha, "approved_base_sha")
    head_sha = _require_sha(approved_head_sha, "approved_head_sha")
    trusted_executor_sha = _require_sha(executor_sha, "executor_sha")

    required_base = GATE_BASE_BRANCHES[gate_kind]
    required_executor_ref = f"refs/heads/{required_base}"
    _require(
        executor_ref == required_executor_ref,
        f"trusted executor ref must be {required_executor_ref!r}",
    )
    _require(
        trusted_executor_sha == base_sha,
        "trusted executor SHA does not match approved base SHA",
    )

    _require(pull_request.number == pr_number, "pull request number mismatch")
    _require(pull_request.state == "open", "pull request is not open")
    _require(not pull_request.draft, "pull request is a draft")
    _require(
        pull_request.head_repository == repository,
        "head must come from this repository; forked heads are not gate-eligible",
    )
    _require(
        pull_request.base_ref == required_base,
        f"{gate_kind} gate requires base branch {required_base!r}",
    )
    required_head = GATE_HEAD_BRANCHES.get(gate_kind)
    if required_head is not None:
        _require(
            pull_request.head_ref == required_head,
            f"{gate_kind} gate requires head branch {required_head!r}",
        )
    _require(_BRANCH_PATTERN.fullmatch(pull_request.head_ref), "head branch is invalid")
    return GateRequest(
        gate_kind=gate_kind,
        pr_number=pr_number,
        base_branch=required_base,
        base_sha=base_sha,
        head_branch=pull_request.head_ref,
        head_sha=head_sha,
        approval_id=approval_id,
        repository=repository,
    )


def validate_candidate(request: GateRequest, candidate: MergeCandidate) -> None:
    """Prove the checked-out merge candidate is the approved base/head merge."""
    _require_sha(candidate.sha, "tested_candidate_sha")
    _require_sha(candidate.tree, "tested_candidate_tree")
    _require(
        _require_sha(candidate.first_parent, "candidate_base_parent") == request.base_sha,
        "merge candidate first parent is not the approved base SHA",
    )
    _require(
        _require_sha(candidate.second_parent, "candidate_head_parent") == request.head_sha,
        "merge candidate second parent is not the approved head SHA",
    )
