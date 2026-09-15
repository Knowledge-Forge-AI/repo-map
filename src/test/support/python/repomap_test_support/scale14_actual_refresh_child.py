"""Test-only actual CLI child with acknowledged cancellation control."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
import sys
from threading import Event

import repomap_kg.cli as cli_facade
import repomap_kg.cli.main as _cli_main_callable
from repomap_test_support.scale14_event_control import TestEventControlChannel

product_cli = sys.modules.get(_cli_main_callable.__module__)


def main(arguments: Sequence[str] | None = None) -> int:
    """Remove test-only controls before calling the ordinary product CLI."""

    supplied = list(sys.argv[1:] if arguments is None else arguments)
    try:
        separator = supplied.index("--")
    except ValueError as error:
        raise SystemExit("test child requires -- before product arguments") from error
    control_arguments = supplied[:separator]
    product_arguments = supplied[separator + 1 :]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cancel-code", required=True)
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    parser.add_argument("--fail-after-control", action="store_true")
    parser.add_argument("--close-telemetry-after-control", action="store_true")
    parser.add_argument("--close-ack-after-control", action="store_true")
    parser.add_argument("--control-ready-fd", type=int)
    parser.add_argument("--expected-parent-pid", type=int)
    controls = parser.parse_args(control_arguments)
    if product_arguments[:2] != ["ops", "refresh-graph"]:
        raise SystemExit("test child product arguments are invalid")
    if (controls.control_ready_fd is None) != (controls.expected_parent_pid is None):
        raise SystemExit("test child control readiness is incomplete")
    if controls.control_ready_fd is not None and (
        controls.control_ready_fd < 0 or controls.expected_parent_pid <= 0
    ):
        raise SystemExit("test child control readiness is invalid")

    original_product_factory = getattr(
        product_cli, "staging_event_channel_from_inherited_fd"
    )
    original_facade_factory = getattr(
        cli_facade, "staging_event_channel_from_inherited_fd"
    )
    telemetry_fd = _option_value(product_arguments, "--backend-telemetry-fd")
    acknowledgement_fd = _option_value(
        product_arguments,
        "--backend-telemetry-ack-fd",
    )
    telemetry_closed = False
    acknowledgement_closed = False
    control_ready_fd = controls.control_ready_fd

    def announce_blocker_entered() -> None:
        nonlocal control_ready_fd
        if control_ready_fd is None:
            return
        if os.getppid() != controls.expected_parent_pid:
            raise RuntimeError("test child parent relation is invalid")
        try:
            if os.write(control_ready_fd, b"\x01") != 1:
                raise RuntimeError("test child control readiness write is incomplete")
        finally:
            os.close(control_ready_fd)
            control_ready_fd = None

    def block_at_control(wait_seconds: float) -> None:
        nonlocal acknowledgement_closed, telemetry_closed
        if controls.close_telemetry_after_control and not telemetry_closed:
            if telemetry_fd is None:
                raise RuntimeError("test-controlled telemetry descriptor is missing")
            os.close(telemetry_fd)
            telemetry_closed = True
        if controls.close_ack_after_control and not acknowledgement_closed:
            if acknowledgement_fd is None:
                raise RuntimeError("test-controlled acknowledgement is missing")
            os.close(acknowledgement_fd)
            acknowledgement_closed = True
        Event().wait(wait_seconds)
        if controls.fail_after_control:
            raise RuntimeError("test-controlled child failure")

    def controlled_factory(descriptor: int):
        return TestEventControlChannel(
            original_product_factory(descriptor),
            selected_code=controls.cancel_code,
            wait_seconds=controls.wait_seconds,
            blocker=block_at_control,
            blocker_entered=announce_blocker_entered,
        )

    setattr(
        product_cli,
        "staging_event_channel_from_inherited_fd",
        controlled_factory,
    )
    setattr(
        cli_facade,
        "staging_event_channel_from_inherited_fd",
        controlled_factory,
    )
    product_main = getattr(product_cli, "main")
    try:
        return product_main(product_arguments)
    finally:
        setattr(
            product_cli,
            "staging_event_channel_from_inherited_fd",
            original_product_factory,
        )
        setattr(
            cli_facade,
            "staging_event_channel_from_inherited_fd",
            original_facade_factory,
        )
        if control_ready_fd is not None:
            os.close(control_ready_fd)


def _option_value(arguments: Sequence[str], option: str) -> int | None:
    try:
        index = arguments.index(option)
        return int(arguments[index + 1])
    except (IndexError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
