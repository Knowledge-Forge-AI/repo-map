"""Hermetic resolver and lock-authority fixtures for generated dependency contracts."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import TypedDict

import pytest

from ci import check_generated_drift as generated_drift


LOCKS = (
    ("first.in", "first.lock"),
    ("second.in", "second.lock"),
)
LOCK_TEXT = "direct==1\ntransitive==1\n"
class PolicyInput(TypedDict):
    version: int
    default_index: str
    exclude_newer: str


POLICY: PolicyInput = {
    "version": 1,
    "default_index": "https://pypi.org/simple",
    "exclude_newer": "2026-08-26T03:43:32Z",
}
AMBIENT_RESOLVER_KEYS = (
    "UV_CACHE_DIR",
    "UV_NO_CACHE",
    "UV_UPGRADE",
    "UV_UPGRADE_PACKAGE",
    "UV_CONFIG_FILE",
    "UV_EXCLUDE_NEWER",
    "UV_FIND_LINKS",
    "UV_INDEX",
    "UV_DEFAULT_INDEX",
    "UV_EXTRA_INDEX_URL",
    "UV_INDEX_URL",
    "PIP_CONFIG_FILE",
    "PIP_EXTRA_INDEX_URL",
    "PIP_INDEX_URL",
)


class FakeUvIndex:
    def __init__(
        self,
        *,
        expose_post_cutoff_artifact: bool = False,
        remove_pre_cutoff_artifact: bool = False,
        warm_default_cache: bool = False,
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.outputs: list[Path] = []
        self.seeded: list[bool] = []
        self.expose_post_cutoff_artifact = expose_post_cutoff_artifact
        self.remove_pre_cutoff_artifact = remove_pre_cutoff_artifact
        self.warm_default_cache = warm_default_cache

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        self.commands.append(tuple(command))
        self.environments.append(dict(env))
        if Path(command[0]).name == "npm":
            return
        assert Path(command[0]).name == "uv"
        source = cwd / command[command.index("--output-file") - 1]
        output = cwd / command[command.index("--output-file") + 1]
        self.outputs.append(output)
        self.seeded.append(output.exists())
        ambient_upgrade = any(key in env for key in AMBIENT_RESOLVER_KEYS)
        cutoff_missing = "--exclude-newer" not in command
        if (
            "--upgrade" in command
            or ambient_upgrade
            or not output.exists()
            or self.remove_pre_cutoff_artifact
            or (self.warm_default_cache and "--no-cache" not in command)
            or (self.expose_post_cutoff_artifact and cutoff_missing)
        ):
            output.write_text("direct==1\ntransitive==2\n", encoding="utf-8")
        elif source.read_text(encoding="utf-8") == "direct==2\n":
            output.write_text("direct==2\ntransitive==1\n", encoding="utf-8")


def configure_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    direct_input: str = "direct==1\n",
) -> Path:
    root = tmp_path / "repository"
    ci_root = root / "tools" / "ci"
    node_root = ci_root / "pre_review_node"
    node_root.mkdir(parents=True)
    monkeypatch.setattr(generated_drift, "ROOT", root)
    monkeypatch.setattr(generated_drift, "CI_ROOT", ci_root)
    monkeypatch.setattr(generated_drift, "PYTHON_LOCKS", LOCKS)
    monkeypatch.setattr(generated_drift, "verify_uv_version", lambda _uv, _env: None)
    for source, lock in LOCKS:
        (ci_root / source).write_text("direct==1\n", encoding="utf-8")
        (ci_root / lock).write_text(LOCK_TEXT, encoding="utf-8")
    policy = {**POLICY, "authority_sha256": generated_drift.authority_digest(ci_root)}
    (ci_root / "generated_lock_policy.json").write_text(
        json.dumps(policy) + "\n", encoding="utf-8"
    )
    if direct_input != "direct==1\n":
        for source, _lock in LOCKS:
            (ci_root / source).write_text(direct_input, encoding="utf-8")
    (node_root / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (node_root / "package-lock.json").write_text(
        '{"name":"fixture","lockfileVersion":3}\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        generated_drift.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", ""),
    )
    return ci_root


def run_checker(tmp_path: Path) -> tuple[int, dict[str, bool]]:
    evidence_dir = tmp_path / "evidence"
    result = generated_drift.main(["--evidence-dir", str(evidence_dir)])
    evidence = json.loads(
        (evidence_dir / "generated-code-drift.json").read_text(encoding="utf-8")
    )
    return result, evidence
