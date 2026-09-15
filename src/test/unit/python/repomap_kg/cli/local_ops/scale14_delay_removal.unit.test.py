from __future__ import annotations

import inspect

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import staging_event_instrumentation as instrumentation_module


@pytest.mark.parametrize(
    "removed_flag",
    (
        "--staging-event-delay-code",
        "--staging-event-delay-seconds",
    ),
)
def test_scale14_removed_delay_flags_are_rejected(removed_flag: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "ops",
                "refresh-graph",
                "--repo-map-home",
                "/placeholder/home",
                "--graph",
                "fixture",
                removed_flag,
                "1",
            ]
        )


def test_scale14_product_instrumentation_has_no_delay_authority() -> None:
    source = inspect.getsource(instrumentation_module)

    assert "delay_code" not in source
    assert "delay_seconds" not in source
    assert "time.sleep" not in source
    assert "_DELAY_CODES" not in source
