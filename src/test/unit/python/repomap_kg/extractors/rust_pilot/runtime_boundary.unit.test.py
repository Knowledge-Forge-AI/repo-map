"""T1 runtime-boundary contracts for the D13 Rust pilot corrections."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Sequence
import hashlib
import sys
import threading
import time
from typing import Any, IO, cast

import pytest

from common_lore_index.extractors.rust_pilot import bounded_exec, construction, helper_protocol, observations
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.controller_audit import attempted_file
from common_lore_index.extractors.rust_pilot.containment import classify_probe
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    DockerBoundary,
    DockerRefused,
    create_arguments,
)
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    DecodedParse,
    ProtocolViolation,
    decode_frames,
)
from common_lore_index.extractors.rust_pilot.observations import (
    ObservationBound,
    build_file_observations,
)
from common_lore_index.extractors.rust_pilot.readback import confined_network
from common_lore_index.extractors.rust_pilot.witness_state import FileRecord
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import frames, item_frame

RUN = "rp1.0123456789abcdef"
IMAGE = "sha256:" + "a" * 64
CID = "c" * 64
NONCE = "b" * 64
ZERO = "0" * 64


def _result(code: int | None = 0, out: bytes = b"", *, stdout_overflow: bool = False,
            stderr_bytes: int = 0, stderr_sha256: str = ZERO, stderr_overflow: bool = False,
            timed_out: bool = False, settled: bool = True, io_failed: bool = False,
            input_complete: bool = True, callback_failed: bool = False) -> ExecResult:
    return ExecResult(
        returncode=code, stdout=out, stdout_overflow=stdout_overflow,
        stderr_bytes=stderr_bytes, stderr_sha256=stderr_sha256, stderr_overflow=stderr_overflow,
        timed_out=timed_out, settled=settled, elapsed=0.01, io_failed=io_failed,
        input_complete=input_complete, callback_failed=callback_failed,
    )


def test_clean_result_requires_all_process_and_io_evidence() -> None:
    clean = _result()
    assert clean.clean
    changes: tuple[dict[str, Any], ...] = (
        {"stdout_overflow": True}, {"stderr_overflow": True}, {"timed_out": True},
        {"settled": False}, {"io_failed": True}, {"input_complete": False},
        {"callback_failed": True}, {"returncode": 1},
    )
    for change in changes:
        assert not replace(clean, **change).clean


def test_containment_bounds_cannot_hide_failed_client_settlement() -> None:
    bounded = _result(timed_out=True)
    assert classify_probe("sleep", bounded, False) == "time_bound"
    changes: tuple[dict[str, Any], ...] = (
        {"settled": False}, {"io_failed": True},
        {"input_complete": False}, {"callback_failed": True},
    )
    for change in changes:
        assert classify_probe("sleep", replace(bounded, **change), False) == "client_cleanup_unproven"


class _ReaderStream:
    def fileno(self) -> int:
        return 23


def test_reader_hashes_all_observed_stderr_without_retaining_raw_bytes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"stderr that exceeds the retained diagnostic limit"
    chunks = [payload, b""]
    monkeypatch.setattr(bounded_exec.os, "read", lambda _fd, _size: chunks.pop(0))
    reader = bounded_exec._Reader(cast(IO[bytes], _ReaderStream()), 4, threading.Event(), keep=False)
    reader.run()
    assert reader.observed == len(payload) and reader.kept == 4 and reader.overflow
    assert reader.chunks == [] and reader.digest.hexdigest() == hashlib.sha256(payload).hexdigest()


def test_reader_failure_retains_observed_count_and_digest_but_is_not_clean(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def broken_read(_fd: int, _size: int) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            return b"prefix"
        raise OSError("synthetic reader failure")

    monkeypatch.setattr(bounded_exec.os, "read", broken_read)
    trigger = threading.Event()
    reader = bounded_exec._Reader(cast(IO[bytes], _ReaderStream()), 64, trigger, keep=False)
    reader.run()
    assert reader.failed and trigger.is_set() and reader.observed == 6
    assert reader.digest.hexdigest() == hashlib.sha256(b"prefix").hexdigest()
    assert not replace(_result(), io_failed=reader.failed).clean


def test_absolute_hard_end_and_hook_failure_still_settle_owned_process() -> None:
    callback_ends: list[float] = []

    def failing_hook(hard_end: float) -> None:
        callback_ends.append(hard_end)
        raise RuntimeError("synthetic cleanup-hook failure")

    hard_end = time.monotonic() + 0.35
    outcome = bounded_exec.run_bounded(
        [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"],
        stdout_limit=64, deadline=30, settle=15, hard_end=hard_end,
        on_deadline=failing_hook,
    )
    assert callback_ends and callback_ends[0] <= hard_end
    assert outcome.timed_out and outcome.callback_failed and outcome.settled
    assert not outcome.clean


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Runner:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[tuple[list[str], float | None, float]] = []

    def __call__(self, argv: Sequence[str], stdin: bytes, stdout_limit: int, deadline: float,
                 on_deadline: Any, *, hard_end: float | None = None) -> ExecResult:
        call = list(argv[1:])
        self.calls.append((call, hard_end, deadline))
        return self.answer(call)


def _boundary(answer: Any) -> tuple[DockerBoundary, _Runner, _Clock]:
    clock = _Clock()
    runner = _Runner(answer)
    return DockerBoundary("/usr/bin/docker", runner=runner, clock=clock, sleep=clock.sleep), runner, clock


def test_nested_client_calls_keep_one_absolute_end_and_settlement_end() -> None:
    docker, runner, clock = _boundary(lambda _call: _result())
    construction_end = 30.0
    docker.run(["start", CID], hard_end=construction_end)
    clock.now = 3.0
    docker.run(["kill", "--signal", "KILL", CID], hard_end=construction_end)
    settlement_end = docker.begin_settlement(CID)
    clock.now = 10.0
    assert docker.begin_settlement(CID) == settlement_end == 18.0
    docker.run(["rm", "-f", "-v", CID], hard_end=settlement_end)
    assert [item[1] for item in runner.calls] == [construction_end, construction_end, settlement_end]


def test_kill_exception_cannot_skip_remove_or_exact_absence_observation() -> None:
    calls: list[list[str]] = []

    def answer(call: list[str]) -> ExecResult:
        calls.append(call)
        if call[0] == "kill":
            raise DockerRefused("synthetic_kill_failure")
        return _result(0, b"")  # an empty exact-ID query proves absence

    docker, _, _ = _boundary(answer)
    assert docker.settle(CID) is True
    assert [call[0] for call in calls] == ["kill", "rm", "container"]


def test_create_journal_and_identity_require_a_clean_result() -> None:
    expected = create_arguments(run_id=RUN, seq=7, docker_arch="amd64", image_id=IMAGE)
    docker, runner, _ = _boundary(lambda _call: _result(0, (CID + "\n").encode()))
    owned: list[str] = []
    assert docker.create(run_id=RUN, seq=7, docker_arch="amd64", image_id=IMAGE, owned=owned) == CID
    assert owned == [CID] and docker.journal == [tuple(expected)]
    assert runner.calls[0][0] == expected

    failed, _, _ = _boundary(lambda _call: _result(0, (CID + "\n").encode(), io_failed=True))
    captured: list[str] = []
    with pytest.raises(DockerRefused, match="create_failed"):
        failed.create(run_id=RUN, seq=7, docker_arch="amd64", image_id=IMAGE, owned=captured)
    assert captured == [CID] and failed.journal == [tuple(expected)]


def _span(data: bytes, needle: bytes) -> list[int]:
    start = data.index(needle)
    return [start, start + len(needle)]


def _decoded(data: bytes, body: list[bytes]) -> DecodedParse:
    return decode_frames(frames(NONCE, body), nonce=NONCE, input_length=len(data))


def _nested_body(data: bytes) -> list[bytes]:
    return [
        item_frame(0, -1, 1, *_span(data, b"mod a { mod b { mod c {} } }"), n=_span(data, b"a")),
        item_frame(1, 0, 1, *_span(data, b"mod b { mod c {} }"), n=_span(data, b"b")),
        item_frame(2, 1, 1, *_span(data, b"mod c {}"), n=_span(data, b"c")),
    ]


def test_scaled_depth257_guard_refuses_before_pointer_expansion(
        monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"mod a { mod b { mod c {} } }"
    monkeypatch.setattr(helper_protocol, "MAX_SCOPE_DEPTH", 2)
    with pytest.raises(ProtocolViolation, match="scope_depth"):
        _decoded(data, _nested_body(data))

    monkeypatch.setattr(helper_protocol, "MAX_SCOPE_DEPTH", 3)
    monkeypatch.setattr(observations, "MAX_SCOPE_DEPTH", 2)
    decoded = _decoded(data, _nested_body(data))
    with pytest.raises(ObservationBound, match="parent_output_bound"):
        build_file_observations("src/lib.rs", data, decoded, input_sha256=ZERO, build_script_name=False)


def test_actual_depth257_refuses_a_small_nested_frame_stream() -> None:
    depth = 257
    data = b"mod m{" * depth + b"}" * depth
    body = [item_frame(i, i - 1, 1, 6 * i, len(data) - i, n=[6 * i + 4, 6 * i + 5])
            for i in range(depth)]
    with pytest.raises(ProtocolViolation, match="scope_depth"):
        _decoded(data, body)


def test_scaled_pointer4096_guard_refuses_without_large_input(
        monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"fn long_name() {}"
    decoded = _decoded(data, [item_frame(0, -1, 2, 0, len(data), n=_span(data, b"long_name"))])
    monkeypatch.setattr(observations, "MAX_POINTER_BYTES", 8)
    with pytest.raises(ObservationBound, match="parent_output_bound"):
        build_file_observations("src/lib.rs", data, decoded, input_sha256=ZERO, build_script_name=False)


def test_scaled_aggregate16mib_guard_refuses_retained_semantic_expansion(
        monkeypatch: pytest.MonkeyPatch) -> None:
    snippets = (b"fn a() {}", b"fn b() {}", b"fn c() {}", b"fn d() {}")
    data = b" ".join(snippets)
    body = [
        item_frame(index, -1, 2, *(_span(data, snippet)), n=_span(data, name))
        for index, (snippet, name) in enumerate(zip(snippets, (b"a", b"b", b"c", b"d")))
    ]
    decoded = _decoded(data, body)
    monkeypatch.setattr(observations, "MAX_SEMANTIC_BYTES", 1024)
    with pytest.raises(ObservationBound, match="parent_output_bound"):
        build_file_observations("src/lib.rs", data, decoded, input_sha256=ZERO, build_script_name=False)


def test_truncated_stream_does_not_assert_attribute_absence_or_complete_members() -> None:
    data = b"mod a { fn b() {} }"
    body = [item_frame(0, -1, 1, 0, len(data), n=_span(data, b"a")),
            item_frame(1, 0, 2, *_span(data, b"fn b() {}"), n=_span(data, b"b"))]
    decoded = decode_frames(frames(NONCE, body, truncated=1), nonce=NONCE, input_length=len(data))
    built = build_file_observations("src/lib.rs", data, decoded, input_sha256=ZERO, build_script_name=False)
    items = [row for row in built.observations if row.kind == "rust.item"]
    assert built.completeness == "truncated" and len(items) == 2
    assert all(row.metadata["attribute_list"] == "truncated" for row in items)
    assert all(row.metadata["conditional"] is None for row in items)
    assert items[0].metadata["member_list"] == "truncated"


def test_audit_keeps_observed_stderr_hash_and_nullable_memory_cost() -> None:
    data = b"fn f() {}\n"
    digest = hashlib.sha256(data).hexdigest()
    stderr_digest = hashlib.sha256(b"diagnostic").hexdigest()
    record = FileRecord(
        path="src/lib.rs", seq=1, discovery_sha256=digest, data=data, build_script_name=False,
        input_sha256=digest, readback_digest="c" * 64, exit_status=0, alive_until_settlement=True,
        stderr_bytes=9, stderr_sha256=stderr_digest, memory_peak=None,
        memory_peak_reason="cgroup_peak_unavailable", resource_stage="parse", absence_proven=True,
        outcome="succeeded", completeness="complete", achieved=("syntax.tree",),
        timings={"construction": 1.0, "readback": 2.0, "parse": 3.0, "settlement": 4.0},
    )
    receipt, report = attempted_file(RUN, record, "d" * 64, constructed=True)
    assert report["diagnostic"] == "diagnostic_present"
    assert report["diagnostic_sha256"] == stderr_digest
    assert report["cost"]["memory_peak_bytes"] is None
    assert report["cost"]["memory_peak_reason"] == "cgroup_peak_unavailable"
    assert receipt.run_id == f"{RUN}.1"

    probe_receipt, probe_report = attempted_file(RUN, record, "d" * 64, constructed=True, probe=True)
    assert probe_report["invocation_role"] == "probe"
    assert probe_receipt.run_id == f"{RUN}.probe.1"


_DORMANT = {"name": "tunl0", "up": False, "ipv4": False, "ipv6": False, "observable": True}
_DORMANT6 = {"name": "ip6tnl0", "up": False, "ipv4": False, "ipv6": False, "observable": True}
_LO = {"name": "lo", "up": True, "ipv4": True, "ipv6": True, "observable": True}


@pytest.mark.parametrize(("names", "facts", "allowed"), [
    (("lo",), (), True),
    (("lo", "tunl0"), (_DORMANT,), True),
    (("lo", "ip6tnl0"), (_DORMANT6,), True),
    (("lo", "tunl0", "ip6tnl0"), (_DORMANT, _DORMANT6), True),
    (("lo", "tunl0"), (), False),
    (("lo", "tunl0"), ({**_DORMANT, "up": True},), False),
    (("lo", "tunl0"), ({**_DORMANT, "ipv4": True},), False),
    (("lo", "tunl0"), ({**_DORMANT, "ipv6": True},), False),
    (("lo", "tunl0"), ({**_DORMANT, "observable": False},), False),
    (("lo", "eth0"), ({**_DORMANT, "name": "eth0"},), False),
    (("lo", "tunl0", "tunl0"), (_DORMANT,), False),
    (("lo", "tunl0"), (_DORMANT, _DORMANT), False),
    (("tunl0",), (_DORMANT,), False),
    (("lo", "tunl0"), ({**_DORMANT, "extra": 1},), False),
])
def test_confined_network_accepts_only_loopback_and_exact_dormant_facts(
        names: tuple[str, ...], facts: tuple[dict[str, Any], ...], allowed: bool) -> None:
    assert confined_network(names, (_LO, *facts)) is allowed


def test_expired_work_cutoff_never_blocks_exact_cleanup_or_final_observation() -> None:
    docker, runner, clock = _boundary(lambda _call: _result())
    docker.limit_work_deadline(10.0)
    docker.limit_work_deadline(30.0)
    clock.now = 10.0
    with pytest.raises(DockerRefused, match="internal_deadline_exceeded"):
        docker.server()
    with pytest.raises(DockerRefused, match="internal_deadline_exceeded"):
        docker.create(run_id=RUN, seq=1, docker_arch="amd64", image_id=IMAGE)
    assert not runner.calls
    assert docker.settle(CID) is True
    assert len(runner.calls) == 3 and all(row[1] == 25.0 for row in runner.calls)
    snapshot = docker.snapshot(RUN)
    assert not snapshot.images and not snapshot.volumes and not snapshot.labelled
    assert len(runner.calls) == 6


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf")])
def test_invalid_work_cutoff_never_calls_the_runner(deadline: float) -> None:
    docker, runner, _clock = _boundary(lambda _call: _result())
    with pytest.raises(DockerRefused, match="invalid_work_deadline"):
        docker.limit_work_deadline(deadline)
    assert not runner.calls


def test_cost_only_observation_remains_inside_settlement_after_work_expiry() -> None:
    from types import SimpleNamespace
    docker, runner, clock = _boundary(lambda _call: _result(0, b'{"t":"cost","memory_peak_bytes":123,"unavailable_reason":null}'))
    docker.limit_work_deadline(10.0)
    clock.now = 10.0
    end = docker.begin_settlement(CID)
    material = cast(construction.RuntimeMaterial, SimpleNamespace(
        sources=SimpleNamespace(text=lambda _name: "inert fixture probe")))
    assert construction.resource_facts(docker, CID, material, hard_end=end) == (123, None)
    assert runner.calls[-1][0][-1] == "--cost-only" and runner.calls[-1][1] == 25.0
    with pytest.raises(DockerRefused, match="internal_deadline_exceeded"):
        docker.run_guest(CID, user="10001:10001", tail=("-I",), stdin=None,
                         stdout_limit=16, deadline=5)
    with pytest.raises(DockerRefused, match="invalid_settlement_end"):
        docker.observe_cost(CID, "inert fixture probe", hard_end=26.0)
