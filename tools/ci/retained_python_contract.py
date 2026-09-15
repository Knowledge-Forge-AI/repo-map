# tools/ci/retained_python_contract.py
"""Canonical shared contracts and validation for retained Python ratchets."""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.file_length_policy import (
    FAILURE_LIMIT,
    WARNING_LIMIT,
)
from ci.retained_python_records import (
    BASELINE_SCHEMA,
    RecordValidationError,
    validate_baseline_records,
)

RESULT_SCHEMA = "repomap-retained-python-ratchets-result-v1"
RETAINED_CLASSES = ("cross_language_contract", "python_retained")
RETAINED_TIERS = ("T0", "T1-future", "T1-seed")
RUFF_RULES = ("F",)
EXPECTED_TOOLS = {"mypy": "2.1.0", "ruff": "0.16.2"}
EXPECTED_MYPY_CONFIG = {
    "python_version": "3.12",
    "check_untyped_defs": True,
    "no_implicit_optional": True,
    "warn_redundant_casts": True,
    "warn_unused_ignores": True,
    "warn_unreachable": True,
    "strict_equality": True,
    "show_error_codes": True,
}


class RatchetContractError(RuntimeError):
    """A tool, baseline, path, or output violated the ratchet contract."""


def validate_baseline(document: object) -> None:
    expected_tools = {
        **EXPECTED_TOOLS,
        "ruff_rules": list(RUFF_RULES),
        "ruff_target_version": "py312",
    }
    try:
        validate_baseline_records(
            document,
            schema=BASELINE_SCHEMA,
            expected_tools=expected_tools,
            retained_classes=RETAINED_CLASSES,
            retained_tiers=RETAINED_TIERS,
            warning_limit=WARNING_LIMIT,
            failure_limit=FAILURE_LIMIT,
        )
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error


__all__ = [
    "EXPECTED_MYPY_CONFIG",
    "EXPECTED_TOOLS",
    "RatchetContractError",
    "RETAINED_CLASSES",
    "RETAINED_TIERS",
    "RESULT_SCHEMA",
    "RUFF_RULES",
    "validate_baseline",
]
