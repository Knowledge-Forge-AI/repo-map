from contextlib import contextmanager

from repomap_kg.coordinator.local_lifecycle import LocalControlAuthority


class _Store:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    @contextmanager
    def maintenance_window(self):
        self._events.append(f"enter:{self._name}")
        try:
            yield
        finally:
            self._events.append(f"exit:{self._name}")


class _Authority(LocalControlAuthority):
    def __init__(self, events: list[str]) -> None:
        self._database = "control"
        self._graph_databases = ("graph-a", "graph-b")
        self._events = events

    def control_store(self):
        return _Store("control", self._events)

    def control_store_for(self, database: str):
        return _Store(database, self._events)


def test_cross_plane_exclusive_lock_order_is_control_then_sorted_graphs() -> None:
    events: list[str] = []
    authority = _Authority(events)

    with authority.maintenance_window(
        graph_databases=("graph-b", "graph-a", "graph-a")
    ):
        events.append("owned")

    assert events == [
        "enter:control",
        "enter:graph-a",
        "enter:graph-b",
        "owned",
        "exit:graph-b",
        "exit:graph-a",
        "exit:control",
    ]
