"""Read-only, categorical distribution metadata; never installation qualification."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import metadata
import re

from common_lore_index import DISTRIBUTION_NAME as _DISTRIBUTION_NAME

_NAMES = ("common-lore-index", "repomap-kg")
_Finder = Callable[[str], Iterable[metadata.Distribution]]


@dataclass(frozen=True)
class InstallationOwnership:
    expected_distribution: str
    distributions: tuple[tuple[str, int | None], ...]
    state: str
    diagnostics: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.state == "single-owner" else 1

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "cloe-installation-ownership-v1", "metadata_only": True,
            "expected_distribution": self.expected_distribution, "state": self.state,
            "distributions": [{"name": name, "count": count} for name, count in self.distributions],
            "diagnostics": list(self.diagnostics),
        }


def inspect_installation_ownership(*, finder: _Finder | None = None) -> InstallationOwnership:
    """Inspect only the two known owners; a finder seam supports isolated metadata evidence."""
    discover: _Finder = finder if finder is not None else lambda name: metadata.distributions(name=name)
    counts: dict[str, int | None] = dict.fromkeys(_NAMES)
    try:
        for name in _NAMES:
            count = 0
            for distribution in discover(name):
                declared = distribution.metadata.get("Name")
                if not isinstance(declared, str) or re.sub(r"[-_.]+", "-", declared).lower() != name:
                    raise ValueError("distribution metadata identity unavailable")
                count += 1
                if count == 2:
                    break
            counts[name] = count
    except Exception:
        # This leaf reads external metadata/finders. Never echo their arbitrary errors or payloads.
        return InstallationOwnership(_DISTRIBUTION_NAME, tuple(counts.items()), "unverified",
                                     ("distribution_metadata_unavailable",))
    observed = [name for name, count in counts.items() if count]
    diagnostics: tuple[str, ...]
    if len(observed) > 1 or any(count == 2 for count in counts.values()):
        state, diagnostics = "conflicting", ("distribution_ownership_conflict",)
    elif not observed:
        state, diagnostics = "unverified", ("distribution_metadata_absent",)
    elif observed != [_DISTRIBUTION_NAME]:
        state, diagnostics = "owner-mismatch", ("distribution_owner_mismatch",)
    else:
        state, diagnostics = "single-owner", ()
    return InstallationOwnership(_DISTRIBUTION_NAME, tuple(counts.items()), state, diagnostics)
