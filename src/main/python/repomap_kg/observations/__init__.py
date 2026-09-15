"""Raw observation compatibility facade and package namespace."""

from typing import TYPE_CHECKING as _TYPE_CHECKING

from repomap_kg.observations import raw as _raw

if _TYPE_CHECKING:
    from repomap_kg.observations.raw import (
        RawObservation as RawObservation,
        read_observations_jsonl as read_observations_jsonl,
        write_observations_jsonl as write_observations_jsonl,
    )

globals().update(
    {name: getattr(_raw, name) for name in dir(_raw) if not name.startswith("__")}
)
