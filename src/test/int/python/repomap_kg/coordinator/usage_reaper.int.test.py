"""Real owned-worker attribution through the private portable launch chain.

Each case runs the closed ``repomap_test_support.usage_worker`` module with
``collect_usage=True``. CPU and peak RSS come only from the parent's single
``wait4`` of the launched child; nothing here is self-reported by the worker.
These are Linux container proofs; no native Windows or Darwin claim is made.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from repomap_test_support.usage_worker import BURN_SECONDS, RSS_BYTES, run_usage_worker

LINUX = sys.platform.startswith("linux")
BURN_FLOOR_NS = int(BURN_SECONDS * 0.8 * 10**9)


def _live_members(pgid: int) -> list[int]:
    """Live (non-zombie) processes whose process group is ``pgid`` (Linux /proc)."""
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if fields[0] != "Z" and int(fields[2]) == pgid:
            members.append(int(entry.name))
    return members


def _alive(pid: int) -> bool:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return False
    return fields[0] != "Z"


@pytest.fixture(autouse=True)
def _linux_proc() -> None:
    assert Path("/proc/self/stat").exists(), "these proofs observe Linux /proc"


def test_nominal_worker_reports_plausible_usage_and_a_popen_compatible_status(tmp_path: Path) -> None:
    result = run_usage_worker(tmp_path, "nominal")
    usage = result.resource_usage
    assert result.returncode == 0 and result.terminal.get("status") == "succeeded"
    assert usage is not None and usage.reason is None
    assert usage.total_cpu_ns == usage.user_cpu_ns + usage.system_cpu_ns > 0
    assert usage.peak_rss_bytes is not None and usage.peak_rss_bytes > 1024 * 1024
    if LINUX:
        assert (usage.cpu_basis, usage.rss_basis) == (
            "wait4_self_and_waited_descendants", "wait4_max_single_process_rss",
        )
    assert result.process_group_cleaned


def test_cpu_burn_lower_bound_is_attributed_to_the_worker(tmp_path: Path) -> None:
    usage = run_usage_worker(tmp_path, "burn").resource_usage
    assert usage is not None and usage.total_cpu_ns >= BURN_FLOOR_NS


def test_a_resident_allocation_raises_peak_rss_above_its_size(tmp_path: Path) -> None:
    usage = run_usage_worker(tmp_path, "rss").resource_usage
    assert usage is not None and usage.peak_rss_bytes >= RSS_BYTES


def test_a_waited_grandchild_is_included_on_linux(tmp_path: Path) -> None:
    assert LINUX, "the integration sandbox is Linux; waited-descendant inclusion is its wait4 contract"
    witness = tmp_path / "cpu.witness"
    usage = run_usage_worker(tmp_path, "grandchild-waited", probe_path=witness).resource_usage
    own_ns, waited_ns = (int(value) for value in witness.read_text(encoding="ascii").split())
    assert waited_ns >= BURN_FLOOR_NS, "the waited grandchild really burned CPU"
    assert usage is not None and usage.cpu_basis == "wait4_self_and_waited_descendants"
    # Without the grandchild, wait4 would report only the worker's own CPU, which
    # was own_ns at the worker's last instant; the parent's total must carry both.
    assert usage.total_cpu_ns >= own_ns + waited_ns


def test_a_grandchild_left_in_the_group_is_flagged_then_cleaned(tmp_path: Path) -> None:
    probe = tmp_path / "grandchild.pid"
    result = run_usage_worker(tmp_path, "grandchild-remaining", probe_path=probe)
    usage = result.resource_usage
    assert usage is not None and usage.group_members_after_reap == 1
    assert not _alive(int(probe.read_text())), "group cleanup killed the remaining member"


def test_sigkill_still_yields_rusage_and_a_negative_return_code(tmp_path: Path) -> None:
    result = run_usage_worker(tmp_path, "sigkill")
    assert result.returncode == -9
    assert result.terminal.get("message_type") == "worker_exit"
    usage = result.resource_usage
    assert usage is not None and usage.total_cpu_ns is not None and usage.peak_rss_bytes is not None


class _InterruptingEvent:
    """A cancel event whose third check raises ``KeyboardInterrupt`` in the parent."""

    def __init__(self) -> None:
        self.calls = 0
        self.raised = KeyboardInterrupt()

    def is_set(self) -> bool:
        self.calls += 1
        if self.calls >= 3:
            raise self.raised
        return False


def test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original(tmp_path: Path) -> None:
    probe = tmp_path / "worker.pid"
    event = _InterruptingEvent()
    with pytest.raises(KeyboardInterrupt) as raised:
        run_usage_worker(tmp_path, "block", probe_path=probe, cancel_event=event)
    assert raised.value is event.raised
    pgid = int(probe.read_text())
    assert _live_members(pgid) == [], "no member of the worker group survived"
    assert not (tmp_path / "workspace").exists() or not any((tmp_path / "workspace").iterdir())
