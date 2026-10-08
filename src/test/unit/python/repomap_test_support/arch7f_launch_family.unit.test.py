"""Unit test contract owner for ARCH7F launch family registration and semantics."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

_TOOLS_DIR = Path(__file__).resolve().parents[5] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pytest

from runner_coverage_execution import (
    ALL_LAUNCH_FAMILIES,
    MEASURED_FAMILIES,
    UNMEASURED_FAMILIES,
    popen_observed_process,
    prepare_child_coverage_environment,
)

INVENTED_ARCH7F_FAMILIES = (
    "arch7f_pip_private",
    "arch7f_pip_public",
    "arch7f_probe_private",
    "arch7f_probe_public",
)


def test_arch7f_canonical_families_registered() -> None:
    """Canonical ARCH7F pip and probe families must be registered unmeasured families."""
    assert "arch7f_pip" in UNMEASURED_FAMILIES
    assert "arch7f_pip" in ALL_LAUNCH_FAMILIES
    assert "arch7f_pip" not in MEASURED_FAMILIES

    assert "arch7f_probe" in UNMEASURED_FAMILIES
    assert "arch7f_probe" in ALL_LAUNCH_FAMILIES
    assert "arch7f_probe" not in MEASURED_FAMILIES


@pytest.mark.parametrize("invented_family", INVENTED_ARCH7F_FAMILIES)
def test_arch7f_unknown_families_fail_closed_in_env_prep(invented_family: str) -> None:
    """Environment preparation must fail closed on unknown launch families."""
    with pytest.raises(ValueError, match=f"unknown coverage launch family: {invented_family}"):
        prepare_child_coverage_environment(os.environ, family=invented_family)


@pytest.mark.parametrize("invented_family", INVENTED_ARCH7F_FAMILIES)
def test_arch7f_unknown_families_fail_closed_in_popen(invented_family: str) -> None:
    """Process execution seam must fail closed on unknown launch families."""
    with pytest.raises(ValueError, match=f"unknown coverage launch family: {invented_family}"):
        popen_observed_process([sys.executable, "-c", "pass"], family=invented_family)


def test_arch7f_pip_unmeasured_semantics_scrubs_coverage() -> None:
    """arch7f_pip unmeasured family must scrub all coverage env vars and bootstrap."""
    base_env = {
        "COVERAGE_PROCESS_START": "/opt/repo/.coveragerc",
        "COVERAGE_PROCESS_CONFIG": "/opt/repo/.coveragerc",
        "COVERAGE_FILE": "/tmp/.coverage.shard",
        "COVERAGE_CHILD_MANIFEST_DIR": "/tmp/manifests",
        "COVERAGE_SESSION_INVOCATION_ID": "inv-12345",
        "PYTHONPATH": "/usr/local/lib/python3.13/site-packages",
        "CUSTOM_VAR": "preserved",
    }
    result = prepare_child_coverage_environment(base_env, family="arch7f_pip")

    assert not any(k.startswith("COVERAGE_") for k in result)
    assert result["CUSTOM_VAR"] == "preserved"
    assert result.get("PYTHONPATH") == "/usr/local/lib/python3.13/site-packages"


def test_arch7f_probe_unmeasured_semantics_scrubs_coverage() -> None:
    """arch7f_probe unmeasured family must scrub coverage and preserve target extra_env."""
    base_env = {
        "COVERAGE_PROCESS_START": "/opt/repo/.coveragerc",
        "COVERAGE_FILE": "/tmp/.coverage.shard",
        "PYTHONPATH": "/user/code",
    }
    target_install = "/tmp/scratch/installed_private"
    result = prepare_child_coverage_environment(
        base_env,
        family="arch7f_probe",
        extra_env={"PYTHONPATH": target_install},
    )

    assert not any(k.startswith("COVERAGE_") for k in result)
    assert target_install in result.get("PYTHONPATH", "")


@pytest.mark.parametrize("family", ["arch7f_pip", "arch7f_probe"])
def test_arch7f_families_reject_reserved_coverage_keys_in_extra_env(family: str) -> None:
    """extra_env smuggling of runner-reserved coverage keys must fail closed."""
    with pytest.raises(ValueError, match="runner-reserved coverage key"):
        prepare_child_coverage_environment(
            {},
            family=family,
            extra_env={"COVERAGE_PROCESS_START": "/bad/path"},
        )


def test_arch7f_unmeasured_popen_defaults_namespace_relation() -> None:
    """Unmeasured arch7f_pip allows omitted pid_namespace_relation while measured forbids it."""
    # Measured family fails closed when pid_namespace_relation is omitted:
    with pytest.raises(ValueError, match="requires explicit pid_namespace_relation"):
        popen_observed_process([sys.executable, "-c", "pass"], family="cli_module")

    # Unmeasured family arch7f_pip defaults to "unknown" without error:
    mock_proc = MagicMock(spec=subprocess.Popen)
    with patch("subprocess.Popen", return_value=mock_proc):
        proc = popen_observed_process(
            [sys.executable, "-c", "pass"],
            family="arch7f_pip",
        )
        assert proc is mock_proc

