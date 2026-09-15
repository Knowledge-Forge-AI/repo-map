from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from repomap_kg.observations.raw import RawObservation


FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "shell" / "awk"
FAKE_SECRET_MARKERS = (
    "FAKE_AWK_TOKEN_VALUE",
    "FAKE_AWK_PASSWORD_VALUE",
    "FAKE_AWK_SYSTEM_TOKEN",
    "FAKE_AWK_PATH_TOKEN",
)
RUNTIME_PROOF_KINDS = {
    "shell.host_mutation",
    "shell.network_call",
    "shell.package_manager",
}


def observations_by_kind(
    observations: Iterable[RawObservation],
) -> dict[str, list[RawObservation]]:
    by_kind: dict[str, list[RawObservation]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return by_kind


def first_observation(
    observations: Iterable[RawObservation],
    *,
    kind: str,
    name: str | None = None,
    predicate: Callable[[RawObservation], bool] | None = None,
) -> RawObservation:
    for observation in observations:
        if observation.kind != kind:
            continue
        if name is not None and observation.name != name:
            continue
        if predicate is not None and not predicate(observation):
            continue
        return observation
    raise AssertionError(f"missing observation kind={kind!r} name={name!r}")
