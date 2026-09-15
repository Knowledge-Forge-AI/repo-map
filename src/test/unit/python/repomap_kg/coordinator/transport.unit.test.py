from typing import Any, cast

import pytest

from repomap_kg.coordinator.transport import LocalRequestDispatcher, TransportError


def dispatcher():
    return LocalRequestDispatcher(
        "synthetic-auth-token",
        {
            "health": lambda _payload: {"status": "ready"},
            "submit": lambda payload: {"job_id": cast(dict[str, Any], payload["request"])["request_id"]},
            "status": lambda payload: {"job_id": payload["job_id"]},
            "wait": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
            "cancel": lambda payload: {"job_id": payload["job_id"], "accepted": True},
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=1,
    )


def request(operation="health", payload=None, **updates):
    value = {
        "schema_version": 1,
        "auth_token": "synthetic-auth-token",
        "operation": operation,
        "payload": {} if payload is None else payload,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    "value,category",
    [
        (request(schema_version=2), "incompatible_version"),
        (request(auth_token="wrong"), "unauthorized"),
        (request(extra=True), "invalid_request"),
        (request(operation="drop"), "unsupported_operation"),
        (request(payload={"root": "/private/source"}), "invalid_request"),
        (request("health", {"extra": True}), "invalid_request"),
        (request("status", {"job_id": "job-1", "extra": True}), "invalid_request"),
        (request("wait", {"job_id": ["job-1"]}), "invalid_request"),
        (request("submit", {"request": "not-an-object"}), "invalid_request"),
        (request("list", {"limit": 33}), "invalid_request"),
        (request("list", {"limit": True}), "invalid_request"),
        (request("list", {"limit": False}), "invalid_request"),
        (request("list", {"limit": "20"}), "invalid_request"),
        (request("list", {"limit": 20, "graph_id": 123}), "invalid_request"),
        (request("list", {"limit": 20, "cursor": 123}), "invalid_request"),
        (request("list", {"limit": 20, "cursor": "invalid_cursor"}), "invalid_request"),
        (request("list", {"limit": 20, "state": "running"}), "invalid_request"),
    ],
)
def test_transport_rejects_incompatible_unauthorized_or_authority_requests(
    value, category
):
    with pytest.raises(TransportError, match=category):
        dispatcher().dispatch(value)


@pytest.mark.parametrize(
    "operation", ["health", "submit", "status", "wait", "cancel", "list"]
)
def test_transport_exposes_only_the_six_bounded_operations(operation):
    payload: dict[str, object] = {}
    if operation == "submit":
        payload = {"request": {"request_id": "request-1"}}
    elif operation == "list":
        payload = {"limit": 20}
    elif operation != "health":
        payload = {"job_id": "job-1"}
    response = dispatcher().dispatch(request(operation, payload))
    assert response["schema_version"] == 1
    assert response["ok"] is True
    assert set(response) == {"schema_version", "ok", "result"}


def test_transport_saturation_is_bounded_and_path_free():
    target = dispatcher()
    target._in_flight = 1
    with pytest.raises(TransportError, match="saturated") as error:
        target.dispatch(request())
    assert "/" not in str(error.value)


def test_transport_rejects_private_or_unbounded_handler_results():
    handlers = dispatcher()._handlers
    handlers["health"] = lambda _payload: {"detail": "/private/result"}
    target = LocalRequestDispatcher(
        "synthetic-auth-token", handlers, max_in_flight=1
    )
    with pytest.raises(TransportError, match="invalid_response"):
        target.dispatch(request())


@pytest.mark.parametrize(
    "private_value",
    [
        "password=secret",
        "DROP DATABASE example",
        "command --unsafe",
        "raw payload detail",
        "token=secret",
    ],
)
def test_transport_rejects_private_response_strings(private_value):
    handlers = dispatcher()._handlers
    handlers["health"] = lambda _payload: {"detail": private_value}
    target = LocalRequestDispatcher(
        "synthetic-auth-token", handlers, max_in_flight=1
    )
    with pytest.raises(TransportError, match="invalid_response"):
        target.dispatch(request())


def test_transport_list_accepts_valid_options_and_cursor():
    from repomap_kg.coordinator.job_listing import JobListCursor, encode_job_cursor

    cursor = encode_job_cursor(
        JobListCursor("2026-09-08T12:00:00.000000Z", "job-1")
    )
    response = dispatcher().dispatch(
        request("list", {"limit": 10, "graph_id": "graph-1", "cursor": cursor})
    )
    assert response["ok"] is True
    assert response["result"] == {"jobs": [], "next_cursor": None}
