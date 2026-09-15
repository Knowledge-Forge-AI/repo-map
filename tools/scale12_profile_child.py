"""Repository-owned current-source publication child for SCALE12 profiling."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
from typing import Callable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (
    _REPO_ROOT / "src" / "main" / "python",
    _REPO_ROOT / "src" / "test" / "support" / "python",
    _REPO_ROOT / "tools",
):
    _candidate_str = str(_candidate)
    if _candidate_str not in sys.path:
        sys.path.insert(0, _candidate_str)

from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
)
from scale11_profile_contracts import ProfileResult
from scale11_profile_normalized_ingestion import profile_publication
from scale11_profile_workloads import PROFILES, build_workload
from scale12_event_transport import Scale12EventChannel
from scale12_profile_delay import ProfilingOperationDelay


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-fd", type=int, required=True)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--work-items", type=int, required=True)
    parser.add_argument("--repetition", type=int, required=True)
    parser.add_argument("--psql-arg", action="append", default=[])
    parser.add_argument("--uninstrumented", action="store_true")
    parser.add_argument("--delay-operation")
    parser.add_argument("--delay-seconds", type=float)
    arguments = parser.parse_args(argv)
    if (arguments.delay_operation is None) != (arguments.delay_seconds is None):
        parser.error("delay operation and duration must be supplied together")
    if arguments.event_fd < 0 or arguments.repetition < 1:
        parser.error("event descriptor and repetition must be positive")
    return arguments


def _summary(result: ProfileResult) -> dict[str, object]:
    return {
        "schema_version": 1,
        "workload_profile": result.profile,
        "work_items": result.work_items,
        "repetition": result.repetition,
        "elapsed_seconds": result.elapsed_seconds,
        "receipt_complete": result.receipt_complete,
        "cleanup_complete": result.cleanup_complete,
        "structural_digest": result.structural_digest,
        "family_row_counts": {
            family.family: family.row_count for family in result.families
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one publication and emit only acknowledged structural events."""

    arguments = _arguments(argv)
    connection = socket.socket(fileno=arguments.event_fd)
    channel = Scale12EventChannel(connection)
    try:
        channel.send("ready", {})

        def send_operation(event: StagingOperationEvent) -> None:
            channel.send("operation", event.to_payload())

        operation_sink: Callable[[StagingOperationEvent], None] | None = (
            None if arguments.uninstrumented else send_operation
        )
        if arguments.delay_operation is not None:
            operation_sink = ProfilingOperationDelay(
                operation_sink,
                operation_code=arguments.delay_operation,
                delay_seconds=arguments.delay_seconds,
                profile_mode=True,
            )
        workload = build_workload(arguments.profile, arguments.work_items)
        result = profile_publication(
            tuple(arguments.psql_arg),
            workload,
            repetition=arguments.repetition,
            instrumented=not arguments.uninstrumented,
            operation_sink=operation_sink,
        )
        channel.send(
            "terminal",
            {
                "terminal_category": "completed",
                "profile_summary": _summary(result),
            },
        )
        return 0
    except KeyboardInterrupt:
        channel.send(
            "terminal",
            {"terminal_category": "cancelled", "profile_summary": None},
        )
        return 130
    except Exception:
        try:
            channel.send(
                "terminal",
                {"terminal_category": "failed", "profile_summary": None},
            )
        except Exception:
            pass
        return 1
    finally:
        channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
