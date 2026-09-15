import pytest

from repomap_kg.coordinator.contracts import JobState
from repomap_kg.coordinator.job_control import (
    cancel_coordinator_job,
    coordinator_health,
    coordinator_job_status,
    format_coordinator_health_table,
    format_coordinator_job_table,
    format_coordinator_jobs_table,
    wait_for_coordinator_job,
    list_coordinator_jobs,
)
from repomap_kg.coordinator.job_listing import JobListCursor, encode_job_cursor
from repomap_kg.coordinator.local_mode import CoordinatorModeError
from repomap_test_support.coordinator_control_fixtures import (
    CustomPageClient,
    FakeCoordinatorClient as FakeClient,
    ItemClient,
    fixed_client_factory as _factory,
    require_dict,
    require_list,
    require_mapping,
)


def test_job_status_reads_existing_job_without_submission(tmp_path):
    client = FakeClient([{"job_id": "job-1", "graph_id": "repo-map", "state": "running"}])
    result = coordinator_job_status(
        tmp_path, "job-1", client_factory=_factory(client)
    )
    assert result["command"] == "coordinator-job-status"
    assert result["result"] == "ready"
    assert require_mapping(result["job"])["state"] == "running"
    assert client.calls == [("status", "job-1")]


def test_coordinator_health_reads_one_bounded_projection_without_mutation(tmp_path):
    client = FakeClient()
    result = coordinator_health(tmp_path, client_factory=_factory(client))
    assert result["command"] == "coordinator-health"
    assert result["result"] == "ready"
    assert require_mapping(result["health"])["health_schema_version"] == 1
    assert client.calls == [("health",)]
    table = format_coordinator_health_table(result)
    assert "service | ready" in table
    assert "storage | not_reported" in table


def test_job_wait_reaches_terminal_without_resubmission(tmp_path):
    client = FakeClient(
        [
            {"job_id": "job-1", "graph_id": "repo-map", "state": "running"},
            {"job_id": "job-1", "graph_id": "repo-map", "state": "succeeded"},
        ]
    )
    ticks = iter((0.0, 0.0, 1.0))
    result = wait_for_coordinator_job(
        tmp_path,
        "job-1",
        wait_timeout_seconds=30,
        client_factory=_factory(client),
        monotonic=lambda: next(ticks),
    )
    assert result["command"] == "coordinator-job-wait"
    assert result["result"] == "success"
    assert client.calls == [("wait", "job-1"), ("wait", "job-1")]


def test_job_wait_timeout_and_bounds_are_explicit(tmp_path):
    client = FakeClient(
        [{"job_id": "job-1", "graph_id": "repo-map", "state": "running"}]
    )
    ticks = iter((0.0, 1.0))
    with pytest.raises(CoordinatorModeError, match="coordinator_wait_timeout"):
        wait_for_coordinator_job(
            tmp_path,
            "job-1",
            wait_timeout_seconds=1,
            client_factory=_factory(client),
            monotonic=lambda: next(ticks),
        )
    with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
        wait_for_coordinator_job(tmp_path, "job-1", wait_timeout_seconds=0)


def test_job_cancel_uses_existing_authenticated_operation(tmp_path):
    client = FakeClient()
    result = cancel_coordinator_job(
        tmp_path, "job-1", client_factory=_factory(client)
    )
    assert result == {
        "command": "coordinator-job-cancel",
        "result": "accepted",
        "job": {"job_id": "job-1", "state": "cancel_requested"},
    }
    assert client.calls == [("cancel", "job-1")]


def test_job_control_rejects_mismatched_or_invalid_responses(tmp_path):
    client = FakeClient(
        [{"job_id": "other-job", "graph_id": "repo-map", "state": "running"}]
    )
    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        coordinator_job_status(
            tmp_path, "job-1", client_factory=_factory(client)
        )


def test_job_listing_validates_and_wraps_bounded_client_page(tmp_path):
    client = FakeClient()
    result = list_coordinator_jobs(
        tmp_path,
        limit=12,
        graph_id="repo-map",
        cursor=None,
        client_factory=_factory(client),
    )
    assert result["command"] == "coordinator-jobs"
    assert result["result"] == "ready"
    assert require_mapping(require_list(result["jobs"])[0])["job_id"] == "job-1"
    assert client.calls == [
        ("list", {"limit": 12, "graph_id": "repo-map", "cursor": None})
    ]


def test_job_wait_terminal_states_and_outcomes(tmp_path):
    for state, expected_res in (
        (JobState.FAILED, "failure"),
        (JobState.CANCELLED, "failure"),
        (JobState.SUPERSEDED, "failure"),
        (JobState.QUARANTINED, "failure"),
        (JobState.SUCCEEDED, "success"),
    ):
        client = FakeClient([{"job_id": "job-1", "graph_id": "repo-map", "state": state}])
        result = wait_for_coordinator_job(tmp_path, "job-1", client_factory=_factory(client))
        assert result["command"] == "coordinator-job-wait"
        assert result["result"] == expected_res
        assert require_mapping(result["job"])["state"] == state

    with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
        wait_for_coordinator_job(tmp_path, "job-1", wait_timeout_seconds=86_401)


def test_job_cancel_validation_and_refusal(tmp_path):
    client_cancelled = FakeClient(cancel_state=JobState.CANCELLED)
    res = cancel_coordinator_job(tmp_path, "job-1", client_factory=_factory(client_cancelled))
    assert res["result"] == "accepted"
    assert require_mapping(res["job"])["state"] == JobState.CANCELLED

    for bad_state in (JobState.RUNNING, JobState.SUCCEEDED, "not_a_state"):
        client_bad = FakeClient(cancel_state=bad_state)
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            cancel_coordinator_job(tmp_path, "job-1", client_factory=_factory(client_bad))


def test_coordinator_health_degraded_and_invalid_projections(tmp_path):
    base_health = {
        "health_schema_version": 1,
        "status": "degraded",
        "service": {"status": "degraded"},
        "ownership": {"status": "owned"},
        "queue": {"status": "not_reported"},
        "workers": {"status": "not_reported"},
        "publication": {"status": "not_reported"},
        "polling": {"status": "not_configured"},
        "transport": {"status": "ready"},
        "storage": {"status": "not_reported"},
    }
    client_deg = FakeClient(health=base_health)
    res = coordinator_health(tmp_path, client_factory=_factory(client_deg))
    assert res["result"] == "degraded"
    assert require_mapping(res["health"])["status"] == "degraded"

    for bad_val in (
        "not_a_dict",
        {**base_health, "health_schema_version": 2},
        {**base_health, "status": "unknown_status"},
        {**base_health, "service": {"status": "unknown_status"}},
        {**base_health, "service": "not_a_dict"},
        {k: v for k, v in base_health.items() if k != "storage"},
        {**base_health, "extra_key": 1},
        {**base_health, "root": "/prohibited"},
    ):
        client = FakeClient(health=bad_val)
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            coordinator_health(tmp_path, client_factory=_factory(client))


def test_job_listing_cursor_and_structure_validation_refusal(tmp_path):
    bad_pages: tuple[object, ...] = (
        "not_a_map",
        {"jobs": []},
        {"jobs": [], "next_cursor": None, "extra": 1},
        {"jobs": "not_a_list", "next_cursor": None},
        {"jobs": [{"job_id": f"j-{i}", "graph_id": "g", "state": "running", "submitted_at": "2026-07-13T12:00:00.000000Z"} for i in range(5)], "next_cursor": None},
        {"jobs": [], "next_cursor": "cursor_without_jobs"},
        {"jobs": [{"job_id": "j-1", "graph_id": "g", "state": "running", "submitted_at": "2026-07-13T12:00:00.000000Z"}], "next_cursor": 12345},
        {"jobs": [{"job_id": "j-1", "graph_id": "g", "state": "running", "submitted_at": "2026-07-13T12:00:00.000000Z"}], "next_cursor": "invalid_cursor_token"},
    )
    for bad_page in bad_pages:
        factory = _factory(CustomPageClient(bad_page))
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            list_coordinator_jobs(tmp_path, limit=2, client_factory=factory)

    last_job = {"job_id": "job-1", "graph_id": "repo-map", "state": "succeeded", "submitted_at": "2026-07-13T12:00:00.000000Z"}
    valid_cursor = encode_job_cursor(JobListCursor(last_job["submitted_at"], last_job["job_id"]))
    valid_page = {"jobs": [last_job], "next_cursor": valid_cursor}
    res = list_coordinator_jobs(
        tmp_path, limit=2, client_factory=_factory(CustomPageClient(valid_page))
    )
    assert res["next_cursor"] == valid_cursor

    mismatched_cursor = encode_job_cursor(
        JobListCursor(last_job["submitted_at"], "different-job")
    )
    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        list_coordinator_jobs(
            tmp_path,
            limit=2,
            client_factory=_factory(CustomPageClient(
                {"jobs": [last_job], "next_cursor": mismatched_cursor}
            )),
        )


def test_job_listing_item_validation_refusal(tmp_path):
    bad_items: tuple[object, ...] = (
        "not_a_dict",
        {"job_id": "j-1"},
        {"job_id": "j-1", "graph_id": "g", "state": "invalid_state", "submitted_at": "2026-07-13T12:00:00.000000Z"},
        {"job_id": "j-1", "graph_id": "other-graph", "state": "running", "submitted_at": "2026-07-13T12:00:00.000000Z"},
        {"job_id": "j-1", "graph_id": "g", "state": "running", "submitted_at": "invalid_date"},
    )
    for bad_item in bad_items:
        factory = _factory(ItemClient(bad_item))
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            list_coordinator_jobs(tmp_path, graph_id="g", client_factory=factory)


def test_format_coordinator_tables(tmp_path):
    jobs_payload = {
        "command": "coordinator-jobs",
        "result": "ready",
        "jobs": [{
            "job_id": "j-1",
            "graph_id": "g-1",
            "state": "running",
            "submitted_at": "2026-07-13T12:00:00.000000Z",
        }],
        "next_cursor": "cursor-token-1",
    }
    table = format_coordinator_jobs_table(jobs_payload)
    assert "j-1 | g-1 | running | 2026-07-13T12:00:00.000000Z" in table
    assert "next_cursor | cursor-token-1" in table

    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        format_coordinator_jobs_table({"jobs": "not_a_list"})

    job_payload = {
        "command": "coordinator-job-status",
        "result": "ready",
        "job": {
            "job_id": "job-1",
            "graph_id": "g-1",
            "state": "running",
            "attempt_count": 2,
            "phase": "indexing",
            "completed": 10,
            "total": 20,
            "error_category": "none",
        },
    }
    job_table = format_coordinator_job_table(job_payload)
    assert "result | ready" in job_table
    assert "job_id | job-1" in job_table
    assert "attempt_count | 2" in job_table
    assert "completed | 10" in job_table

    for bad_payload in (
        {},
        {"job": "not_a_map", "result": "ready"},
        {"job": {"job_id": ""}, "result": "ready"},
        {"job": {"job_id": "j-1"}, "result": ""},
    ):
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            format_coordinator_job_table(bad_payload)


def test_job_control_rejects_untyped_jobs_and_health_sections(tmp_path):
    bad_values: tuple[object, ...] = (
        [],
        {"job_id": "job-1", "state": 1},
        {"job_id": "job-1", "state": "unknown"},
    )
    for value in bad_values:
        client = FakeClient([value])
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            coordinator_job_status(tmp_path, "job-1", client_factory=_factory(client))

    health = require_dict(FakeClient().health_payload)
    health["storage"] = {"status": 1}
    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        coordinator_health(tmp_path, client_factory=_factory(FakeClient(health=health)))
