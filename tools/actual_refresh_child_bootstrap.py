"""Private child bootstrap for supervised actual refresh startup."""

from __future__ import annotations

import argparse
import os
from typing import Sequence

from actual_refresh_startup import (
    StartupChildError,
    StartupReadinessError,
    validate_actual_refresh_arguments,
    wait_for_startup_release,
)


def main(arguments: Sequence[str] | None = None) -> int:
    """Wait for parent readiness, then replace this process with the product."""

    supplied = list(arguments or ())
    try:
        separator = supplied.index("--")
    except ValueError as error:
        raise SystemExit("startup bootstrap product boundary is missing") from error
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--startup-fd", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    controls = parser.parse_args(supplied[:separator])
    try:
        product_arguments = validate_actual_refresh_arguments(
            supplied[separator + 1 :]
        )
        wait_for_startup_release(
            controls.startup_fd,
            timeout_seconds=controls.timeout_seconds,
        )
        os.execvpe(
            product_arguments[0],
            list(product_arguments),
            dict(os.environ),
        )
    except (StartupChildError, StartupReadinessError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
