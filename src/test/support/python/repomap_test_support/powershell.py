from collections.abc import Iterable
from pathlib import Path
from typing import Any


POWERSHELL_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "powershell"


def observations_by_kind(observations: Iterable[Any]) -> dict[str, list[Any]]:
    by_kind: dict[str, list[Any]] = {}
    for observation in observations:
        by_kind.setdefault(observation.kind, []).append(observation)
    return by_kind
