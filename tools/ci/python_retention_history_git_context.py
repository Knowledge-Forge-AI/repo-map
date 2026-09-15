"""Resolve GitHub event and target identities for retention history checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ci.python_retention_history_git import (
    GitRunner,
    HistoryContext,
    HistoryValidationError,
    _required_sha,
    _resolve_commit,
    _run_git,
)


def event_context() -> HistoryContext:
    """Read optional pull-request lineage facts without contacting a host."""
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    payload: Mapping[str, Any] = {}
    if event_path:
        try:
            loaded = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HistoryValidationError(
                "unsupported history: GitHub event payload is invalid"
            ) from error
        if not isinstance(loaded, dict):
            raise HistoryValidationError(
                "unsupported history: GitHub event payload is invalid"
            )
        payload = loaded
    pull_request = payload.get("pull_request")
    if "pull_request" in payload and not isinstance(pull_request, Mapping):
        raise HistoryValidationError(
            "unsupported history: GitHub pull-request event is malformed"
        )
    pull_request_data = pull_request if isinstance(pull_request, Mapping) else {}
    base = pull_request_data.get("base")
    if "base" in pull_request_data and not isinstance(base, Mapping):
        raise HistoryValidationError(
            "unsupported history: GitHub target event is malformed"
        )
    base_data = base if isinstance(base, Mapping) else {}
    target_ref = base_data.get("ref")
    target_commit = base_data.get("sha")
    if target_ref is not None and not isinstance(target_ref, str):
        raise HistoryValidationError(
            "unsupported history: GitHub target ref is malformed"
        )
    if target_commit is not None and not isinstance(target_commit, str):
        raise HistoryValidationError(
            "unsupported history: GitHub target commit is malformed"
        )
    target_ref_value = target_ref if isinstance(target_ref, str) and target_ref else None
    target_commit_value = target_commit if isinstance(target_commit, str) and target_commit else None
    ref = os.environ.get("GITHUB_REF", "")
    is_pull_request = bool(pull_request_data) or ref.endswith("/merge")
    if not is_pull_request and not os.environ.get("GITHUB_BASE_REF"):
        return HistoryContext(github_candidate_sha=os.environ.get("GITHUB_SHA"))
    return HistoryContext(
        target_ref=target_ref_value or os.environ.get("GITHUB_BASE_REF") or None,
        target_commit=target_commit_value,
        pull_request_merge=is_pull_request,
        github_candidate_sha=os.environ.get("GITHUB_SHA"),
    )


def target_commit(
    repo_root: Path, context: HistoryContext, runner: GitRunner
) -> str | None:
    """Resolve an explicitly supplied target identity from local Git objects."""
    if context.target_commit is not None:
        return _resolve_commit(repo_root, context.target_commit, runner, "target commit")
    if context.target_ref is None:
        return None
    candidates = (
        f"refs/remotes/origin/{context.target_ref}",
        f"refs/heads/{context.target_ref}",
        context.target_ref,
    )
    for reference in candidates:
        completed = _run_git(
            repo_root,
            ["rev-parse", "--verify", f"{reference}^{{commit}}"],
            runner,
        )
        if completed.returncode == 0:
            return _required_sha(completed, "target commit")
    raise HistoryValidationError(
        "unsupported history: target branch identity is unavailable"
    )


__all__ = ["event_context", "target_commit"]
