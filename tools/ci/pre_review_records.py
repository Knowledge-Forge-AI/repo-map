"""Records, data models, and sanitization for pre-review checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = Path(__file__).resolve().parent

SENSITIVE_SCANNERS = {"betterleaks", "malskanner", "prompt-defense-audit"}
POLICY_CHECKS = {
    "actionlint",
    "betterleaks",
    "govulncheck",
    "hadolint",
    "malskanner",
    "mypy",
    "pip-audit",
    "prompt-defense-audit",
    "pyflakes",
    "ruff",
    "retained-python-ratchets",
    "scanner-suppressions",
    "semgrep",
    "zizmor",
}

MODULE_FAILURE = re.compile(r"(?:No module named|ModuleNotFoundError)")
INTERNAL_FAILURE = re.compile(
    r"(?:Traceback \(most recent call last\)|Internal error|panic:)", re.IGNORECASE
)
FINDING_RETURN_CODES = {
    "govulncheck": {3},
    "mypy": {1},
    "pyflakes": {1},
    "ruff": {1},
    "semgrep": {1},
}
SECRET_TEXT = re.compile(
    r"(?i)(token|password|secret|api[_-]?key)(\s*[:=]\s*)(\S+)"
)


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    cwd: Path = ROOT
    policy: str = "exit-zero"
    python_owned: bool = False
    python_entry: str = "interpreter"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    returncode: int | None
    elapsed_seconds: float
    detail: str
    classification: str
    interpreter: str | None


def sanitize(text: str, *private_paths: Path | str | None) -> str:
    """Redact repository paths and secrets from plain text diagnostics."""
    sanitized = text
    targets: list[tuple[str, str]] = [
        (str(ROOT.resolve()), "<repo>"),
        (str(ROOT), "<repo>"),
    ]
    for path in private_paths:
        if path is None:
            continue
        p_str = str(path)
        if p_str:
            targets.append((p_str, "<private-path>"))
        try:
            p_res = str(Path(path).resolve())
            if p_res and p_res != p_str:
                targets.append((p_res, "<private-path>"))
        except (OSError, RuntimeError):
            pass
    targets.sort(key=lambda item: len(item[0]), reverse=True)
    for target, replacement in targets:
        sanitized = sanitized.replace(target, replacement)
    return SECRET_TEXT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        sanitized,
    )


def sanitize_machine_result(value: object, *private_paths: Path | str | None) -> object:
    """Redact diagnostic strings without corrupting structured evidence, rejecting key collisions."""
    if isinstance(value, str):
        return sanitize(value, *private_paths)
    if isinstance(value, list):
        return [sanitize_machine_result(item, *private_paths) for item in value]
    if isinstance(value, (set, frozenset)):
        return type(value)(sanitize_machine_result(item, *private_paths) for item in value)
    if isinstance(value, tuple):
        return tuple(sanitize_machine_result(item, *private_paths) for item in value)
    if isinstance(value, dict):
        sanitized_dict: dict[str, object] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("machine mapping keys must be strings")
            sanitized_key = sanitize(raw_key, *private_paths)
            if sanitized_key in sanitized_dict:
                raise ValueError(
                    "mapping key collision after sanitization"
                )
            sanitized_dict[sanitized_key] = sanitize_machine_result(item, *private_paths)
        return sanitized_dict
    return value
