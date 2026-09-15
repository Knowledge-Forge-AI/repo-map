"""Unit tests for system scenario monotonic timer and lifecycle behaviors."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.cleanup import perform_system_cleanup
from tools.system.config import SystemTestConfig


def test_perform_system_cleanup_tracks_errors(tmp_path: Path) -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha="a" * 40,
        run_id="run-test-clean",
    )
    client = MagicMock()
    client.containers.list.side_effect = RuntimeError("docker error")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        status = perform_system_cleanup(
            compose_dir=tmp_path,
            candidate_image_id="sha256:12345",
            config=config,
            client=client,
        )
        assert status["success"] is False
        assert len(status["errors"]) > 0


def test_perform_system_cleanup_fails_closed_without_client() -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha="a" * 40,
        run_id="run-test-no-client",
    )

    status = perform_system_cleanup(
        compose_dir=None,
        candidate_image_id=None,
        config=config,
        client=None,
    )

    assert status["success"] is False
    assert status["terminal_absence_verified"] is False
    assert status["errors"] == [
        "Docker client unavailable; terminal absence not verified"
    ]


def test_perform_system_cleanup_enforces_deadline_across_sdk_calls() -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha="a" * 40,
        run_id="run-test-cleanup-deadline",
    )
    client = MagicMock()
    client.api.timeout = 60.0
    container = MagicMock()
    container.id = "container-id"
    observed_timeouts = []

    def list_containers(**_kwargs):
        observed_timeouts.append(client.api.timeout)
        return [container]

    client.containers.list.side_effect = list_containers

    with patch(
        "tools.system.cleanup.time.monotonic",
        side_effect=[0.0, 0.5, 3.0, 3.0, 3.0, 3.0, 3.0],
    ):
        status = perform_system_cleanup(
            compose_dir=None,
            candidate_image_id=None,
            config=config,
            client=client,
            timeout_seconds=2.0,
        )

    assert status["success"] is False
    assert status["terminal_absence_verified"] is False
    assert any("system cleanup deadline exhausted" in error for error in status["errors"])
    container.remove.assert_not_called()
    assert observed_timeouts == [1.5]
    assert client.api.timeout == 60.0


def test_perform_system_cleanup_restores_unset_sdk_timeout_after_interrupt() -> None:
    config = SystemTestConfig.create(
        candidate_tree_sha="a" * 40,
        run_id="run-test-cleanup-timeout-restore",
    )
    client = MagicMock()
    client.api.timeout = None
    client.containers.list.side_effect = KeyboardInterrupt

    with (
        patch("tools.system.cleanup.time.monotonic", side_effect=[0.0, 0.5]),
        pytest.raises(KeyboardInterrupt),
    ):
        perform_system_cleanup(
            compose_dir=None,
            candidate_image_id=None,
            config=config,
            client=client,
            timeout_seconds=2.0,
        )

    assert client.api.timeout is None


def test_perform_system_cleanup_restores_missing_sdk_timeout_after_interrupt() -> None:
    class ApiWithoutTimeout:
        pass

    config = SystemTestConfig.create(
        candidate_tree_sha="a" * 40,
        run_id="run-test-cleanup-missing-timeout-restore",
    )
    client = MagicMock()
    client.api = ApiWithoutTimeout()

    def interrupting_list(**_kwargs):
        assert client.api.timeout == 1.5
        raise KeyboardInterrupt

    client.containers.list.side_effect = interrupting_list

    with (
        patch("tools.system.cleanup.time.monotonic", side_effect=[0.0, 0.5]),
        pytest.raises(KeyboardInterrupt),
    ):
        perform_system_cleanup(
            compose_dir=None,
            candidate_image_id=None,
            config=config,
            client=client,
            timeout_seconds=2.0,
        )

    assert not hasattr(client.api, "timeout")
