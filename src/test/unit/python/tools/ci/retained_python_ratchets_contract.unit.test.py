from __future__ import annotations

from pathlib import Path
import sys

import pytest

from ci.retained_python_contract import (
    EXPECTED_MYPY_CONFIG as CONTRACT_EXPECTED_MYPY_CONFIG,
    EXPECTED_TOOLS as CONTRACT_EXPECTED_TOOLS,
    RatchetContractError as ContractRatchetContractError,
    RETAINED_CLASSES as CONTRACT_RETAINED_CLASSES,
    RETAINED_TIERS as CONTRACT_RETAINED_TIERS,
    RESULT_SCHEMA as CONTRACT_RESULT_SCHEMA,
    RUFF_RULES as CONTRACT_RUFF_RULES,
    validate_baseline as contract_validate_baseline,
)
from ci.retained_python_ratchets import (
    EXPECTED_MYPY_CONFIG,
    EXPECTED_TOOLS,
    RatchetContractError,
    RETAINED_CLASSES,
    RETAINED_TIERS,
    RESULT_SCHEMA,
    RUFF_RULES,
    mypy_command,
    ruff_command,
    ruff_files_command,
    validate_baseline,
)
from ci.run_pre_review import checks


def test_retained_ruff_command_is_closed_read_only_and_complete() -> None:
    targets = ("src/main/python/repomap_kg/a.py", "src/main/python/repomap_kg/b.py")

    command = ruff_command(targets)

    assert command == (
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--target-version",
        "py312",
        "--select",
        "F",
        "--ignore-noqa",
        "--output-format",
        "json",
        "--no-cache",
        *targets,
    )
    assert not {"--fix", "--exit-zero", "--force-exclude"} & set(command)


def test_retained_ruff_file_attestation_is_closed_and_complete() -> None:
    targets = ("src/main/python/repomap_kg/a.py", "src/main/python/repomap_kg/b.py")

    command = ruff_files_command(targets)

    assert command == (
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--show-files",
        "--no-cache",
        *targets,
    )
    assert not {"--fix", "--exit-zero", "--force-exclude"} & set(command)


def test_t1_future_mypy_command_is_line_stable_and_cache_free() -> None:
    targets = ("src/main/python/repomap_kg/future.py",)

    command = mypy_command(targets)

    assert command[-1:] == targets
    assert "--follow-imports=silent" in command
    assert command[3:5] == ("--config-file", "pyproject.toml")
    assert "--no-error-summary" in command
    assert "--cache-dir=/dev/null" in command
    assert not {"--ignore-missing-imports", "--exclude"} & set(command)


def test_aggregate_owns_exact_read_only_ratchet_invocation(tmp_path: Path) -> None:
    ratchet = next(
        check for check in checks(tmp_path) if check.name == "retained-python-ratchets"
    )

    assert ratchet.command == (
        sys.executable,
        "tools/ci/retained_python_ratchets.py",
        "--baseline",
        "tools/ci/retained_python_ratchets.json",
        "--scope-transitions",
        "tools/ci/retained_python_scope_transitions.json",
    )
    assert ratchet.python_owned and ratchet.policy == "retained-python-ratchets"
    assert "--generate-baseline" not in ratchet.command


def test_shared_ratchet_contract_identity_and_reexports() -> None:
    assert RatchetContractError is ContractRatchetContractError
    assert validate_baseline is contract_validate_baseline
    assert EXPECTED_MYPY_CONFIG is CONTRACT_EXPECTED_MYPY_CONFIG
    assert EXPECTED_TOOLS is CONTRACT_EXPECTED_TOOLS
    assert RETAINED_CLASSES is CONTRACT_RETAINED_CLASSES
    assert RETAINED_TIERS is CONTRACT_RETAINED_TIERS
    assert RESULT_SCHEMA is CONTRACT_RESULT_SCHEMA
    assert RUFF_RULES is CONTRACT_RUFF_RULES


def test_validate_baseline_rejects_invalid_document() -> None:
    with pytest.raises(RatchetContractError, match="schema"):
        validate_baseline({"schema": "invalid"})
