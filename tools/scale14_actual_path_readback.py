"""Compatibility facade for the canonical SCALE15 terminal readback."""

from __future__ import annotations

from collections.abc import Sequence

from scale15_actual_path_readback import read_scale15_terminal_state
from scale15_terminal_contracts import ExpectedRefreshAuthority, TerminalReadback


def read_scale14_actual_path_state(
    psql_args: Sequence[str],
    *,
    expected: ExpectedRefreshAuthority,
    psql_command: str = "psql",
) -> TerminalReadback:
    """Route the former SCALE14 entrypoint through receipt-bearing authority."""

    return read_scale15_terminal_state(
        psql_args,
        expected,
        psql_command=psql_command,
    )


__all__ = ["read_scale14_actual_path_state"]
