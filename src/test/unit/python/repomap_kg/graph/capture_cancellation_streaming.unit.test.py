"""Behavioral RED uses the same real source read hook on the old capture path."""
import inspect
import threading
import pytest
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.capture_cancellation_fixtures import CAPTURE_CHUNK, capture_graph, observe_capture_io


def test_capture_stops_work_after_actual_mid_read_cancellation(tmp_path, monkeypatch):
    graph = capture_graph(tmp_path / "source", large=True)
    event = threading.Event()
    refusal = ValueError("cooperative fixture cancellation")
    consumed, written, sources = observe_capture_io(monkeypatch, event.set)

    def check():
        if event.is_set():
            raise refusal

    options = {"cancel_check": check} if "cancel_check" in inspect.signature(capture_multi_source_candidate).parameters else {}
    reached = None
    try:
        capture_multi_source_candidate(graph, elide_discovery_hash=True, **options)
    except BaseException as error:
        reached = error
    telemetry = {"consumed": sum(consumed), "written": sum(written), "source_sizes": [probe.reader.closed for probe in sources]}
    assert 0 < sum(consumed) <= CAPTURE_CHUNK, telemetry
    assert sum(written) == 0, telemetry
    assert reached is refusal
    assert sources and all(probe.reader.closed for probe in sources)


@pytest.mark.parametrize("elided", [False, True])
def test_controlled_capture_matches_default_complete_bundle(tmp_path, elided):
    graph = capture_graph(tmp_path / "source")
    plain = capture_multi_source_candidate(graph, elide_discovery_hash=elided)
    checks = []
    controlled = capture_multi_source_candidate(graph, elide_discovery_hash=elided, cancel_check=lambda: checks.append(True))
    assert controlled == plain and len(checks) > 10
