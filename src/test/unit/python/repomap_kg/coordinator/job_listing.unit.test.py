import pytest

from repomap_kg.coordinator.job_listing import (
    JobListCursor,
    decode_job_cursor,
    encode_job_cursor,
    validate_job_list_options,
)


def test_job_cursor_round_trips_without_private_authority():
    cursor = JobListCursor("2026-07-13T12:00:00.000000Z", "job-2")
    encoded = encode_job_cursor(cursor)
    assert decode_job_cursor(encoded) == cursor
    assert "2026" not in encoded


@pytest.mark.parametrize("value", ["", "not-base64", "e30", "a" * 513])
def test_job_cursor_rejects_malformed_or_unbounded_values(value):
    with pytest.raises(ValueError, match="job list cursor is invalid"):
        decode_job_cursor(value)


@pytest.mark.parametrize("limit", [0, 33, True])
def test_job_list_options_enforce_page_bound(limit):
    with pytest.raises(ValueError, match="job list options are invalid"):
        validate_job_list_options(limit=limit, graph_id=None, cursor=None)


def test_job_list_options_accept_exact_public_graph_filter():
    assert validate_job_list_options(
        limit=12, graph_id="repo-map", cursor=None
    ) == (12, "repo-map", None)
    with pytest.raises(ValueError, match="job list options are invalid"):
        validate_job_list_options(limit=12, graph_id="/private/root", cursor=None)
