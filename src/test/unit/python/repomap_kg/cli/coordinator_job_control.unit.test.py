import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main


def test_job_status_cli_emits_bounded_json():
    payload = {
        "command": "coordinator-job-status",
        "result": "ready",
        "job": {"job_id": "job-1", "graph_id": "repo-map", "state": "running"},
    }
    stdout = io.StringIO()
    with patch("repomap_kg.cli.coordinator_job_status", return_value=payload) as status:
        with redirect_stdout(stdout):
            code = main([
                "ops", "coordinator-job-status", "--repo-map-home", "/placeholder/home",
                "--job-id", "job-1", "--json",
            ])
    assert code == 0
    assert json.loads(stdout.getvalue()) == payload
    status.assert_called_once_with("/placeholder/home", "job-1")


def test_job_wait_cli_returns_nonzero_for_terminal_failure():
    payload = {
        "command": "coordinator-job-wait",
        "result": "failure",
        "job": {"job_id": "job-1", "graph_id": "repo-map", "state": "failed"},
    }
    with patch("repomap_kg.cli.wait_for_coordinator_job", return_value=payload) as wait:
        code = main([
            "ops", "coordinator-job-wait", "--repo-map-home", "/placeholder/home",
            "--job-id", "job-1", "--wait-timeout-seconds", "30", "--json",
        ])
    assert code == 1
    wait.assert_called_once_with(
        "/placeholder/home", "job-1", wait_timeout_seconds=30
    )


def test_job_cancel_cli_uses_explicit_job_id():
    payload = {
        "command": "coordinator-job-cancel",
        "result": "accepted",
        "job": {"job_id": "job-1", "state": "cancel_requested"},
    }
    with patch("repomap_kg.cli.cancel_coordinator_job", return_value=payload) as cancel:
        code = main([
            "ops", "coordinator-job-cancel", "--repo-map-home", "/placeholder/home",
            "--job-id", "job-1", "--json",
        ])
    assert code == 0
    cancel.assert_called_once_with("/placeholder/home", "job-1")


def test_job_listing_cli_passes_only_bounded_filters():
    payload: dict[str, object] = {
        "command": "coordinator-jobs",
        "result": "ready",
        "jobs": [],
        "next_cursor": None,
    }
    with patch("repomap_kg.cli.list_coordinator_jobs", return_value=payload) as listing:
        code = main([
            "ops", "coordinator-jobs", "--repo-map-home", "/placeholder/home",
            "--limit", "12", "--graph-id", "repo-map", "--cursor", "opaque", "--json",
        ])
    assert code == 0
    listing.assert_called_once_with(
        "/placeholder/home", limit=12, graph_id="repo-map", cursor="opaque"
    )


def test_coordinator_health_cli_is_read_only_and_neutral():
    payload = {
        "command": "coordinator-health",
        "result": "ready",
        "health": {
            "health_schema_version": 1,
            "status": "ready",
            "service": {"status": "ready"},
            "ownership": {"status": "owned"},
            "queue": {"status": "not_reported"},
            "workers": {"status": "not_reported"},
            "publication": {"status": "not_reported"},
            "polling": {"status": "not_configured"},
            "transport": {"status": "ready"},
            "storage": {"status": "not_reported"},
        },
    }
    stdout = io.StringIO()
    with patch("repomap_kg.cli.coordinator_health", return_value=payload) as health:
        with redirect_stdout(stdout):
            code = main([
                "ops", "coordinator-health", "--repo-map-home", "/placeholder/home",
                "--json",
            ])
    assert code == 0
    assert json.loads(stdout.getvalue()) == payload
    health.assert_called_once_with("/placeholder/home")
