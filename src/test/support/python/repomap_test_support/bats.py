from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable


BATS_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "shell" / "bats"


def observations_by_kind(observations: Iterable[Any]) -> dict[str, list[Any]]:
    by_kind: dict[str, list[Any]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return by_kind


def first_observation(
    observations: Iterable[Any],
    *,
    kind: str,
    name: str | None = None,
    predicate: Callable[[Any], bool] | None = None,
) -> Any:
    for observation in observations:
        if observation.kind != kind:
            continue
        if name is not None and observation.name != name:
            continue
        if predicate is not None and not predicate(observation):
            continue
        return observation
    raise AssertionError(f"missing observation kind={kind!r} name={name!r}")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
