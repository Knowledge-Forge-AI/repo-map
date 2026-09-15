from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable


BASH_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "shell" / "bash"
FAKE_SECRET_MARKERS = (
    "FAKE_BASH_PASSWORD",
    "FAKE_BASH_TOKEN",
    "FAKE_BASH_AWS_SECRET",
    "FAKE_BASH_NPM_TOKEN",
    "FAKE_BASH_API_KEY",
    "FAKE_BASH_HEADER_SECRET",
    "FAKE_BASH_HEREDOC_TOKEN",
    "FAKE_BASH_HEREDOC_PASSWORD",
    "FAKE_BASH_HEREDOC_API_KEY",
    "FAKE_BASH_SIDE_EFFECT_TOKEN",
    "FAKE_SECURITY_PASSWORD",
    "FAKE_DOCKER_PASSWORD",
    "FAKE_ALIAS_TOKEN",
    "FAKE_BASH_ARRAY_TOKEN",
    "FAKE_TRAP_TOKEN",
)


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
