"""Resource-view attachment seams preserve default calls and opt-in forwarding."""

from __future__ import annotations

from contextlib import contextmanager
import itertools
from types import SimpleNamespace
from typing import Any, cast

import pytest

from common_lore_index.ops import lexical_service, local_refresh, portable_refresh, refresh
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.local_refresh import LocalRefreshResult
from common_lore_index.ops.report_records import OpsRefreshGraphResult
from common_lore_index.ops.resource_view import ResourceObserver, begin
from common_lore_index.storage.authority import RefreshResult


def _observer() -> ResourceObserver:
    return ResourceObserver(
        _monotonic_ns=itertools.count(0, 100).__next__,
        _process_time_ns=itertools.count(0, 10).__next__,
    )


def _local_seams(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> tuple[Any, dict[str, Any]]:
    """Make the Local owner execute its real control flow around exact seams."""
    path = tmp_path / "graph.sqlite3"
    path.write_bytes(b"owned test placeholder")
    graph = SimpleNamespace(
        id="fixture", enabled=True, refresh_unsupported_classification=None,
        effective_source_bindings=(), repository_name="fixture",
    )
    state = SimpleNamespace(database=path)
    capture_calls: dict[str, Any] = {}

    @contextmanager
    def lock(_path: Any):
        yield

    attempt = SimpleNamespace(job_id="job-fixture", attempt=1)

    class Capture:
        def __init__(self) -> None:
            self.authority = SimpleNamespace(
                receipt=lambda: SimpleNamespace(attempt=attempt, generations=()),
            )
            self.manifest = SimpleNamespace(total_files=1, total_bytes=2)

        def annotate(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def mark_terminal(self, **_kwargs: Any) -> None:
            return None

    capture = Capture()
    validated = SimpleNamespace(
        family_spools={family: () for family in local_refresh.FAMILY_ORDER},
        family_summaries=(),
        privacy=SimpleNamespace(value="public"),
        close=lambda: None,
    )
    portable = SimpleNamespace(
        publication_bundle_id="bundle1:test",
        public_mapping=lambda: {"route": "portable-worker-v1"},
    )
    publication_result = SimpleNamespace(
        generation=1, run_id=1, previous_run_id=None,
        family_counts={family: 1 for family in local_refresh.FAMILY_ORDER},
    )

    def capture_candidate(_config: Any, _graph: Any, **kwargs: Any) -> Capture:
        capture_calls.update(kwargs)
        return capture

    monkeypatch.setattr(local_refresh, "_graph", lambda _config, _graph_id: graph)
    monkeypatch.setattr(local_refresh, "mutable_local_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(local_refresh, "local_graph_binding", lambda _graph: object())
    monkeypatch.setattr(local_refresh, "publisher_lock", lock)
    monkeypatch.setattr(local_refresh, "_reconcile", lambda *_args: None)
    monkeypatch.setattr(local_refresh, "read_accepted_generation", lambda *_args: 0)
    monkeypatch.setattr(local_refresh, "attempts_namespace", lambda _graph_id: "attempts")
    monkeypatch.setattr(local_refresh, "capture_portable_candidate", capture_candidate)
    monkeypatch.setattr(local_refresh, "validate_portable_capture", lambda *_args, **_kwargs: (object(), validated))
    monkeypatch.setattr(local_refresh, "portable_publication_binding", lambda *_args, **_kwargs: portable)
    monkeypatch.setattr(local_refresh, "LocalPublication", lambda **kwargs: SimpleNamespace(**kwargs))

    class Receipt:
        def __init__(self) -> None:
            self.attempt = attempt

        def validate(self) -> "Receipt":
            return self

    monkeypatch.setattr(local_refresh, "RunPublicationReceipt", lambda *args: Receipt())
    monkeypatch.setattr(local_refresh, "publish_generation", lambda *_args, **_kwargs: publication_result)
    monkeypatch.setattr(local_refresh, "_settle", lambda *_args, **_kwargs: None)
    return SimpleNamespace(), capture_calls


def test_local_default_keywords_stay_unchanged_and_observer_is_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    config, calls = _local_seams(monkeypatch, tmp_path)
    plain = local_refresh.refresh_local_graph(config, "fixture", limits="sentinel-limits")
    assert isinstance(plain, LocalRefreshResult)
    assert calls == {
        "authority": None,
        "limits": "sentinel-limits",
        "attempts_namespace": "attempts",
    }

    observer = _observer()
    observed = local_refresh.refresh_local_graph(
        config, "fixture", limits="sentinel-limits", resource_observer=observer
    )
    assert isinstance(observed, LocalRefreshResult)
    assert calls["resource_observer"] is observer
    assert observer.report().to_payload()["outcome"] == "published"


def test_local_replay_is_recorded_without_capture(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    config, calls = _local_seams(monkeypatch, tmp_path)
    replay = LocalRefreshResult(
        "fixture", 2, 2, 1, {"route": "portable-worker-v1"},
        {family: 1 for family in local_refresh.FAMILY_ORDER}, reconciled=True,
    )
    monkeypatch.setattr(local_refresh, "_reconcile", lambda *_args: replay)
    observer = _observer()
    result = local_refresh.refresh_local_graph(config, "fixture", resource_observer=observer)
    assert result is replay
    assert "resource_observer" not in calls
    report = observer.report().to_payload()
    assert report["outcome"] == "reconciled_replay"


def _server_result(*, result: str, publication_state: str, error_category: str | None = None) -> OpsRefreshGraphResult:
    return OpsRefreshGraphResult(
        graph_id="fixture", repository_name="fixture", privacy="public-dev", enabled=True,
        mcp_visible=False, root_path_display="[root]", root_path_expanded="[root]",
        result=cast(RefreshResult, result), database="fixture-db", publication_state=publication_state,
        error_category=error_category,
    )


@pytest.mark.parametrize(
    ("result", "publication_state", "error_category", "expected"),
    (("success", "committed", None, "committed"),
     ("failure", "not_started", "worker_crash", "failed"),
     ("failure", "commit_unknown", "publication_unknown", "commit_unknown"),
     ("failure", "rolled_back", "cancelled", "cancelled")),
)
def test_server_default_keywords_and_terminal_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    result: str,
    publication_state: str,
    error_category: str | None,
    expected: str,
) -> None:
    calls: dict[str, Any] = {}

    def refresh_call(_config: Any, _graph_id: str, **kwargs: Any) -> OpsRefreshGraphResult:
        calls.update(kwargs)
        return _server_result(
            result=result, publication_state=publication_state, error_category=error_category
        )

    monkeypatch.setattr(refresh, "_refresh_graph_call", refresh_call)
    config = cast(OpsConfig, object())
    plain = refresh.refresh_graph(config, "fixture")
    assert plain.result == result
    assert calls == {
        "psql_command": None, "publication_receipt": None, "ingestion_mode": "staged",
        "staged_authority": None, "backend_telemetry": None, "staging_measurements": None,
        "_postgres_route": None,
    }

    observer = _observer()
    observed = refresh.refresh_graph(config, "fixture", resource_observer=observer)
    assert observed.result == result
    assert calls["resource_observer"] is observer
    assert observer.report().to_payload()["outcome"] == expected


def test_lexical_default_keywords_and_observer_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    outcome: Any = SimpleNamespace(
        result="published",
        plan=SimpleNamespace(aggregate_input_bytes=12, aggregate_projected_bytes=8, documents=(), omissions=()),
    )

    monkeypatch.setattr(lexical_service, "_fresh_ops_config", lambda config: config)

    def build(_config: Any, _graph_id: str, **kwargs: Any) -> Any:
        calls.clear()
        calls.update(kwargs)
        return outcome

    monkeypatch.setattr(lexical_service, "build_and_publish_lexical_generation", build)
    config = cast(OpsConfig, object())
    plain = lexical_service.build_graph_lexical_generation(config, "fixture")
    assert plain is outcome
    assert "resource_observer" not in calls
    assert calls["private_roots"] == ()
    assert calls["selected_binding_ids"] is None
    assert calls["authorize_body"] is False
    assert calls["portable_store_root"] is None
    assert callable(calls["recheck_config_fn"])

    observer = _observer()
    observed = lexical_service.build_graph_lexical_generation(
        config, "fixture", resource_observer=observer
    )
    assert observed is outcome
    assert "resource_observer" not in calls
    assert observer.report().to_payload()["outcome"] == "published"


def test_portable_execute_forwards_observer_only_when_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    capture = SimpleNamespace(
        authority=SimpleNamespace(), manifest=SimpleNamespace(total_files=1, total_bytes=2),
        mark_terminal=lambda **_kwargs: None,
    )
    validated = SimpleNamespace(
        family_counts={"files": 1, "raw_observations": 1},
        family_summaries=(),
        to_prepared_stage_rows=lambda: (), close=lambda: None,
    )
    summary = SimpleNamespace()

    class Route:
        def apply(self, _postgres: Any) -> "Route":
            return self

        def psql_args_for_database(self, _database: str) -> tuple[str, ...]:
            return ()

    def capture_candidate(_config: Any, _graph: Any, **kwargs: Any) -> Any:
        calls["capture"] = kwargs
        return capture

    def publish(*_args: Any, **kwargs: Any) -> Any:
        calls["publish"] = kwargs
        return summary

    monkeypatch.setattr(portable_refresh, "effective_postgres_route", lambda _config: Route())
    monkeypatch.setattr(portable_refresh, "capture_portable_candidate", capture_candidate)
    monkeypatch.setattr(portable_refresh, "stage_id_for_authority", lambda _authority: "stage")
    monkeypatch.setattr(portable_refresh, "validate_portable_capture", lambda *_args, **_kwargs: (object(), validated))
    monkeypatch.setattr(portable_refresh, "portable_publication_binding", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(portable_refresh, "run_staged_portable_refresh", publish)
    config: Any = SimpleNamespace(postgres=object())
    graph: Any = SimpleNamespace(id="fixture", repository_name="fixture")

    portable_refresh.execute_portable_refresh(config, graph, "db", authority=None)
    assert "resource_observer" not in calls["capture"]

    observer = _observer()
    begin(observer, "server_refresh", "postgresql")
    portable_refresh.execute_portable_refresh(
        config, graph, "db", authority=None, resource_observer=observer
    )
    assert calls["capture"]["resource_observer"] is observer


def _lexical_query_seams(monkeypatch: pytest.MonkeyPatch, envelope: Any) -> dict[str, Any]:
    """Drive the real query owner to its immediate-envelope return."""
    calls: dict[str, Any] = {}
    graph = SimpleNamespace(id="fixture")
    monkeypatch.setattr(lexical_service, "_fresh_ops_config", lambda config: config)
    monkeypatch.setattr(lexical_service, "resolve_ops_graph", lambda _config, _graph_id: graph)

    def parameters(_config: Any, _graph: Any, **kwargs: Any) -> Any:
        calls["parameters"] = kwargs
        return SimpleNamespace(user="owner")

    monkeypatch.setattr(lexical_service, "lexical_connection_parameters", parameters)
    monkeypatch.setattr(lexical_service, "build_lexical_generation_policy", lambda _graph: object())
    monkeypatch.setattr(
        lexical_service, "resolve_lexical_query_scope",
        lambda **_kwargs: SimpleNamespace(immediate_envelope=envelope),
    )
    return calls


def test_lexical_query_wrapper_preserves_unobserved_path_and_proves_no_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope: Any = SimpleNamespace(capability_state="not_run", hits=(), omissions=(object(),))
    calls = _lexical_query_seams(monkeypatch, envelope)
    request: Any = SimpleNamespace(limit=7, validate=lambda: None)
    config = cast(OpsConfig, SimpleNamespace())
    assert lexical_service.query_graph_lexical_generation(
        config, "fixture", request, authorize_body=True,
    ) is envelope
    plain_parameters = dict(calls["parameters"])
    observer = _observer()
    assert lexical_service.query_graph_lexical_generation(
        config, "fixture", request, authorize_body=True, resource_observer=observer,
    ) is envelope
    assert calls["parameters"] == plain_parameters
    payload: dict[str, Any] = observer.report().to_payload()
    assert (payload["operation"], payload["outcome"]) == ("lexical_query", "not_run")
    assert {item["applies_this_call"] for item in payload["limits"]} == {False}
    assert next(item for item in payload["limits"] if item["name"] == "query_result_limit")["value"] == 7


def test_lexical_query_refusal_leaves_an_unfinished_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    observer = _observer()
    with pytest.raises(ValueError, match="body-authorization-required"):
        lexical_service.query_graph_lexical_generation(
            cast(OpsConfig, SimpleNamespace()), "fixture", cast(Any, SimpleNamespace(limit=1)),
            resource_observer=observer,
        )
    payload = observer.report().to_payload()
    assert (payload["outcome"], payload["instrumentation"]) == ("not_recorded", "incomplete")


def _revoke_seams(monkeypatch: pytest.MonkeyPatch, summary: Any) -> list[str]:
    events: list[str] = []
    graph = SimpleNamespace(id="fixture", repository_name="fixture")
    monkeypatch.setattr(lexical_service, "_fresh_ops_config", lambda config: config)
    monkeypatch.setattr(lexical_service, "resolve_ops_graph", lambda _config, _graph_id: graph)
    monkeypatch.setattr(lexical_service, "lexical_connection_parameters", lambda *_a, **_k: object())
    monkeypatch.setattr(lexical_service, "local_graph_binding", lambda _graph: SimpleNamespace(
        repository_identity="repo1:fixture",
    ))

    class Connection:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    @contextmanager
    def scope(_params: Any, **kwargs: Any):
        events.append(f"read_only={kwargs['read_only']}")
        yield Connection()

    def revoke(_connection: Any, **kwargs: Any) -> Any:
        events.append(f"purge={kwargs['purge_rows']} dry={kwargs['dry_run']}")
        return summary

    monkeypatch.setattr(lexical_service, "lexical_connection_scope", scope)
    monkeypatch.setattr(lexical_service, "revoke_lexical_generations", revoke)
    return events


@pytest.mark.parametrize("dry_run", (False, True))
def test_lexical_revoke_wrapper_keeps_transactions_and_reports_after_completion(
    monkeypatch: pytest.MonkeyPatch, dry_run: bool,
) -> None:
    from common_lore_index.storage.lexical_revoke import LexicalRevokeSummary

    summary = LexicalRevokeSummary(1, ("g",), 1, 2, 3, 0, "operator_revoked", not dry_run)
    events = _revoke_seams(monkeypatch, summary)
    config = cast(OpsConfig, SimpleNamespace())
    plain = lexical_service.revoke_graph_lexical_generation(
        config, "fixture", dry_run=dry_run, confirmed=not dry_run,
    )
    plain_events = list(events)
    events.clear()
    observer = _observer()
    observed = lexical_service.revoke_graph_lexical_generation(
        config, "fixture", dry_run=dry_run, confirmed=not dry_run, resource_observer=observer,
    )
    assert observed == plain and events == plain_events
    assert plain_events[-1] == ("rollback" if dry_run else "commit")
    payload = observer.report().to_payload()
    assert payload["outcome"] == ("preview" if dry_run else "revoked")
    assert payload["instrumentation"] == "complete"
