"""Host-level shared memory and IPC leak cleanup support for Postgres."""

from __future__ import annotations

import getpass
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO

from repomap_test_support.postgres_container_config import SubprocessRunner


POSTGRES_BOOTSTRAP_SHM_SIZES = frozenset({56})


@dataclass(frozen=True)
class SharedMemorySegment:
    shmid: str
    owner: str
    creator: str | None
    nattch: int | None
    size: int | None


@dataclass(frozen=True)
class IpcCleanupReport:
    removed_shmids: tuple[str, ...]
    skipped_shmids: tuple[str, ...] = ()
    unavailable: bool = False


class PostgresIpcGuard:
    def __init__(
        self,
        *,
        current_user: str | None = None,
        runner: SubprocessRunner = subprocess.run,
        stderr: TextIO | None = None,
    ):
        self.current_user = current_user or getpass.getuser()
        self.runner = runner
        self.stderr = stderr if stderr is not None else sys.stderr
        self.baseline: tuple[SharedMemorySegment, ...] | None = None

    def capture_baseline(self) -> bool:
        from repomap_test_support import postgres_harness as owner

        self.baseline = owner.capture_shared_memory_segments(self.runner)
        if self.baseline is None:
            print(
                "temporary_postgres: ipcs unavailable before initdb; "
                "refusing to start disposable Postgres because safe IPC "
                "cleanup cannot be guaranteed",
                file=self.stderr,
            )
            return False
        return True

    def cleanup(self, *, live_test_processes: bool) -> IpcCleanupReport:
        from repomap_test_support import postgres_harness as owner

        return owner.cleanup_postgres_shared_memory_leaks(
            baseline=self.baseline,
            current_user=self.current_user,
            live_test_processes=live_test_processes,
            runner=self.runner,
            stderr=self.stderr,
        )


def parse_ipcs_shared_memory(output: str) -> tuple[SharedMemorySegment, ...]:
    header: list[str] | None = None
    segments: list[SharedMemorySegment] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if "ID" in fields and "NATTCH" in fields:
            header = fields
            continue
        if fields[0] != "m" or header is None:
            continue
        values = dict(zip(header, fields, strict=False))
        shmid = values.get("ID")
        owner = values.get("OWNER")
        if shmid is None or owner is None:
            continue
        segments.append(
            SharedMemorySegment(
                shmid=shmid,
                owner=owner,
                creator=values.get("CREATOR"),
                nattch=parse_optional_int(values.get("NATTCH")),
                size=parse_optional_int(values.get("SEGSZ")),
            )
        )
    return tuple(segments)


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def capture_shared_memory_segments(
    runner: SubprocessRunner = subprocess.run,
) -> tuple[SharedMemorySegment, ...] | None:
    try:
        result = runner(
            ["ipcs", "-m", "-a"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_ipcs_shared_memory(result.stdout)


def shared_memory_cleanup_candidates(
    *,
    baseline: tuple[SharedMemorySegment, ...],
    current: tuple[SharedMemorySegment, ...],
    current_user: str,
    live_test_processes: bool = False,
) -> tuple[SharedMemorySegment, ...]:
    if live_test_processes:
        return ()
    baseline_ids = {segment.shmid for segment in baseline}
    return tuple(
        segment
        for segment in current
        if is_cleanup_candidate(segment, baseline_ids, current_user)
    )


def ambiguous_shared_memory_segments(
    *,
    baseline: tuple[SharedMemorySegment, ...],
    current: tuple[SharedMemorySegment, ...],
    current_user: str,
) -> tuple[SharedMemorySegment, ...]:
    baseline_ids = {segment.shmid for segment in baseline}
    return tuple(
        segment
        for segment in current
        if segment.shmid not in baseline_ids
        and (segment.owner == current_user or segment.creator == current_user)
        and not is_cleanup_candidate(segment, baseline_ids, current_user)
    )


def is_cleanup_candidate(
    segment: SharedMemorySegment,
    baseline_ids: set[str],
    current_user: str,
) -> bool:
    if segment.shmid in baseline_ids:
        return False
    if segment.owner != current_user:
        return False
    if segment.creator not in (None, current_user):
        return False
    if segment.nattch != 0:
        return False
    return segment.size in POSTGRES_BOOTSTRAP_SHM_SIZES


def cleanup_postgres_shared_memory_leaks(
    *,
    baseline: tuple[SharedMemorySegment, ...] | None,
    current_user: str,
    live_test_processes: bool = False,
    runner: SubprocessRunner = subprocess.run,
    stderr: TextIO | None = None,
) -> IpcCleanupReport:
    output = stderr if stderr is not None else sys.stderr
    if baseline is None:
        print(
            "temporary_postgres: baseline unavailable; skipped IPC leak cleanup",
            file=output,
        )
        return IpcCleanupReport(removed_shmids=(), unavailable=True)
    current = capture_shared_memory_segments(runner)
    if current is None:
        print(
            "temporary_postgres: ipcs unavailable; skipped IPC leak cleanup",
            file=output,
        )
        return IpcCleanupReport(removed_shmids=(), unavailable=True)
    candidates = shared_memory_cleanup_candidates(
        baseline=baseline,
        current=current,
        current_user=current_user,
    )
    ambiguous = ambiguous_shared_memory_segments(
        baseline=baseline,
        current=current,
        current_user=current_user,
    )
    if live_test_processes and (candidates or ambiguous):
        skipped = tuple(
            segment.shmid for segment in (*candidates, *ambiguous)
        )
        print(
            "temporary_postgres: skipped IPC leak cleanup because test "
            f"cluster still appears live: {', '.join(skipped)}",
            file=output,
        )
        return IpcCleanupReport(
            removed_shmids=(),
            skipped_shmids=skipped,
        )
    if ambiguous:
        skipped = tuple(segment.shmid for segment in ambiguous)
        print(
            "temporary_postgres: skipped ambiguous shared-memory segments: "
            f"{', '.join(skipped)}",
            file=output,
        )
    removed: list[str] = []
    for segment in candidates:
        try:
            result = runner(
                ["ipcrm", "-m", segment.shmid],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            print(
                "temporary_postgres: ipcrm unavailable; skipped IPC leak cleanup",
                file=output,
            )
            return IpcCleanupReport(
                removed_shmids=tuple(removed),
                skipped_shmids=tuple(
                    candidate.shmid
                    for candidate in candidates
                    if candidate.shmid not in removed
                ),
                unavailable=True,
            )
        if result.returncode == 0:
            removed.append(segment.shmid)
        else:
            print(
                "temporary_postgres: failed to remove leaked "
                f"shared-memory segment {segment.shmid}: {result.stderr.strip()}",
                file=output,
            )
    if removed:
        print(
            "temporary_postgres: removed leaked current-user Postgres "
            f"shared-memory segments: {', '.join(removed)}",
            file=output,
        )
    return IpcCleanupReport(
        removed_shmids=tuple(removed),
        skipped_shmids=tuple(segment.shmid for segment in ambiguous),
    )
