"""Live pilot controller: one run, fresh exact containers, settled residue (spec 7-10).

The controller verifies the prepared profile before any Docker command,
refuses wrong platforms before any container, constructs and checks one
run-level probe container, then parses each selected file in its own fresh
container, never retrying. Every container is settled with proven exact-ID
absence before the next one; unproven absence halts the run and refuses all
of its Rust claims. ``process`` completes the run-wide residue attribution
before it returns, and ``admit``/``verify_live`` recompute from live state.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from common_lore_index.extractors.contracts.receipt_schema import Receipt
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.contracts.witness import REQUIRED_BINDINGS
from common_lore_index.extractors.rust_pilot import construction, controller_audit, receipts
from common_lore_index.extractors.rust_pilot.controller_audit import RunSummary as RunSummary
from common_lore_index.extractors.rust_pilot.component_lock import (
    CPU_BY_DOCKER_ARCH,
    DOCKER_ARCH_BY_CPU,
)
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    DockerBoundary,
    ResidueSnapshot,
)
from common_lore_index.extractors.rust_pilot.guest_sources import helper_closure_sha256, load_guest_sources
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    ProtocolViolation,
    decode_frames,
    invocation_nonce,
)
from common_lore_index.extractors.rust_pilot.observations import ObservationBound, build_file_observations
from common_lore_index.extractors.rust_pilot.prepared_profile import ProfileUnavailable, load_profile
from common_lore_index.extractors.rust_pilot.probe_material import (
    PROBE_PATH,
    PROBE_SOURCE_SHA256,
    probe_matches_gold,
    probe_source,
)
from common_lore_index.extractors.rust_pilot.selection import SelectionRecord, select_inputs
from common_lore_index.extractors.rust_pilot.witness_state import Admission, FileRecord, RunState, Unserializable
from common_lore_index.graph.discovery_records import FileInfo

PLATFORMS = {"linux/arm64": "aarch64", "linux/amd64": "x86_64"}


def run_identity(run_nonce: bytes) -> str:
    """``rp1.`` plus the first 16 hex digits of SHA-256 of the run nonce."""

    return "rp1." + hashlib.sha256(run_nonce).hexdigest()[:16]


def _new_boundary(docker_cli: str) -> DockerBoundary:
    """Private test seam; the public pilot never accepts a command-result callback."""

    return DockerBoundary(docker_cli)


class RustPilotController(Unserializable):
    """Owns the run nonce, Docker boundary, live witness state and audit trail."""

    __slots__ = ("_boundary", "_image_id", "_profile_dir", "_cpu", "_audit_dir", "_clock", "_nonce",
                 "_run_id", "_state", "_owned", "_receipts", "_report_files", "_processed", "_closed",
                 "_start_snapshot", "_residue", "_runtime", "_server", "_timings")

    def __init__(self, *, docker_cli: str, sdk_image_id: str, profile_dir: Path | str, platform: str,
                 audit_dir: Path | str | None = None) -> None:
        if platform not in PLATFORMS:
            raise ContractError("unsupported_platform")
        self._boundary = _new_boundary(docker_cli)
        self._image_id = sdk_image_id
        self._profile_dir = profile_dir
        self._cpu = PLATFORMS[platform]
        self._audit_dir = audit_dir
        self._clock = time.monotonic
        self._nonce = secrets.token_bytes(32)
        self._run_id = run_identity(self._nonce)
        self._state: RunState | None = None
        self._owned: list[str] = []
        self._receipts: list[Receipt] = []
        self._report_files: list[dict[str, Any]] = []
        self._processed = False
        self._closed = False
        self._start_snapshot: ResidueSnapshot | None = None
        self._residue: dict[str, Any] = {}
        self._runtime: dict[str, Any] = {}
        self._server: dict[str, str] = {}
        self._timings: dict[str, float] = {}

    def __enter__(self) -> RustPilotController:
        return self

    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        try:
            self.close()
        except ContractError as cleanup:
            if value is None:
                raise
            value.add_note("rust_pilot_cleanup_incomplete")
            if value.__cause__ is None:
                raise value.with_traceback(traceback) from cleanup
            raise value.with_traceback(traceback)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def helper_closure_sha256(self) -> str:
        """Read-only generation identity, never authority to admit a graph claim."""

        if self._state is None or not self._state.live or self._closed:
            raise ContractError("witness_unavailable")
        return self._state.helper_closure_sha256

    def close(self) -> None:
        """Make the run inert; settle any owned container not yet proven absent."""

        if self._closed:
            return
        self._closed = True
        cleanup_ok = all([self._settle(cid) for cid in list(self._owned)])
        if self._state is not None and self._state.halt_code == "cleanup_incomplete":
            cleanup_ok = False
        if self._state is not None:
            if not cleanup_ok:
                self._state.halt("cleanup_incomplete")
            self._state.close()
        if not cleanup_ok:
            raise ContractError("cleanup_incomplete")

    # -- run-level refusals -------------------------------------------------------------------

    def _finish(self, outcome: str, refusal: str | None, selections: Sequence[SelectionRecord]) -> RunSummary:
        profile_sha = None if self._state is None else self._state.profile.profile_sha256
        report = receipts.run_report(
            run_id=self._run_id, platform=self._cpu, image_id=self._image_id, server=self._server,
            runtime=self._runtime, profile_sha256=profile_sha,
            helper_closure_sha256="" if self._state is None else self._state.helper_closure_sha256,
            files=self._report_files, residue=self._residue, timings=self._timings,
            receipt_digests=(), run_outcome=outcome)
        if self._audit_dir is not None:
            receipts.store_audit(self._audit_dir, self._receipts, report)
        observed = {} if self._state is None else {p: r.outcome for p, r in self._state.records.items()}
        return RunSummary(self._run_id, outcome, refusal, tuple(
            (item.path, observed.get(item.path, "not_executed" if item.outcome == "selected" else item.outcome))
            for item in selections))

    def _unavailable(self, selections: Sequence[SelectionRecord]) -> RunSummary:
        digests = [item.input_sha256 or item.discovery_sha256 for item in selections]
        self._receipts.append(receipts.unavailable_receipt(
            run_id=self._run_id, source_sha256=receipts.run_source_sha256(digests)))
        return self._finish("dependency_unavailable", "dependency_unavailable", selections)

    def _refuse_run(self, code: str, selections: Sequence[SelectionRecord], cleanup: str) -> RunSummary:
        digests = [item.input_sha256 or item.discovery_sha256 for item in selections]
        profile_sha = None if self._state is None else self._state.profile.profile_sha256
        self._receipts.append(receipts.refusal_receipt(
            run_id=self._run_id, seq=0, source_sha256=receipts.run_source_sha256(digests),
            profile_sha256=profile_sha, code=code, cleanup=cleanup))
        return self._finish("inadmissible" if cleanup != "incomplete" else "cleanup_incomplete", code, selections)

    # -- process ------------------------------------------------------------------------------

    def process(self, root: Path | str, file_infos: Sequence[FileInfo]) -> RunSummary:
        """Select, construct, parse, settle and attribute residue; once per run."""

        if self._processed or self._closed:
            raise ContractError("run_not_processable")
        self._processed = True
        try:
            selections = select_inputs(root, file_infos)
        except (ContractError, OSError):
            return self._refuse_run("inadmissible_effects", (), "not_applicable")
        try:
            profile = load_profile(self._profile_dir)
        except ProfileUnavailable:
            return self._unavailable(selections)
        if profile.cpu != self._cpu:
            return self._unavailable(selections)
        try:
            server = self._boundary.server()
        except ContractError:
            return self._refuse_run("inadmissible_effects", selections, "not_applicable")
        self._server = {"os": server.os, "arch": server.arch}
        if server.os != "linux" or CPU_BY_DOCKER_ARCH.get(server.arch) != profile.cpu:
            return self._unavailable(selections)
        docker_arch = DOCKER_ARCH_BY_CPU[profile.cpu]
        try:
            self._boundary.check_image(self._image_id, docker_arch)
            sources = load_guest_sources()
            material = construction.build_material(profile, sources, construction.load_notices())
            self._start_snapshot = self._boundary.snapshot(self._run_id)
        except (ContractError, OSError):
            return self._refuse_run("inadmissible_effects", selections, "not_applicable")
        self._state = RunState(run_nonce=self._nonce, run_id=self._run_id, profile=profile,
                               expected=material.expected,
                               helper_closure_sha256=helper_closure_sha256(sources, PROBE_SOURCE_SHA256))
        probe_ok, settled = self._probe(material, docker_arch)
        if not settled:
            self._state.halt("cleanup_incomplete")
            return self._refuse_run("witness_unavailable", selections, "incomplete")
        if not probe_ok:
            return self._refuse_run("inadmissible_effects", selections, "proven")
        for seq, selection in enumerate(selections, start=1):
            try:
                self._boundary.require_work_deadline()
            except ContractError as error:
                self._attribute_residue()
                self._state.halt(self._state.halt_code or error.code)
                raise
            if selection.outcome != "selected" or selection.data is None:
                self._refuse_selection(seq, selection)
                continue
            if not self._attempt(seq, selection, material, docker_arch):
                self._state.halt("cleanup_incomplete")
                return self._refuse_run("witness_unavailable", selections, "incomplete")
        self._attribute_residue()
        return self._finish("processed" if self._state.residue_settled else "cleanup_incomplete", None,
                            selections)

    def _settle(self, container_id: str) -> bool:
        started = self._clock()
        try:
            proven = self._boundary.settle(container_id)
        except Exception:
            # An ordinary boundary failure supplies no absence proof.
            proven = False
        if proven:
            self._owned.remove(container_id)
        self._timings["settlement"] = self._timings.get("settlement", 0.0) + self._clock() - started
        return proven

    def _probe(self, material: construction.RuntimeMaterial, docker_arch: str) -> tuple[bool, bool]:
        selection = SelectionRecord(PROBE_PATH, "selected", PROBE_SOURCE_SHA256, probe_source(), False)
        settled = self._attempt(0, selection, material, docker_arch, probe=True)
        return self._runtime.get("probe_parse_ok") is True, settled

    def _refuse_selection(self, seq: int, selection: SelectionRecord) -> None:
        receipt, report = controller_audit.refused_selection(
            self._run_id, seq, selection, None if self._state is None else self._state.profile.profile_sha256)
        self._receipts.append(receipt)
        self._report_files.append(report)

    def _attempt(self, seq: int, selection: SelectionRecord, material: construction.RuntimeMaterial,
                 docker_arch: str, *, probe: bool = False) -> bool:
        """Parse one selected file in its own container; return False on unproven absence."""

        assert self._state is not None and selection.data is not None
        data = selection.data
        record = FileRecord(selection.path, seq, selection.discovery_sha256, data, selection.build_script_name)
        record.input_sha256 = selection.input_sha256 or ""
        nonce = invocation_nonce(self._nonce, seq, record.input_sha256)
        record.nonce = nonce
        if not probe:
            self._state.add(record)
        owned_before = len(self._owned)
        journal_before = len(self._boundary.journal)
        constructed = False
        attempt_refused = False
        deadline_expired = False
        settlement_started: float | None = None
        try:
            built = construction.construct(self._boundary, run_id=self._run_id, seq=seq, docker_arch=docker_arch,
                                           image_id=self._image_id, material=material, owned=self._owned,
                                           clock=self._clock)
            record.container_id, record.readback_digest = built.container_id, built.readback_digest
            record.readback_bytes, record.installed_bytes = built.readback_bytes, built.installed_bytes
            record.timings.update(construction=built.elapsed, readback=built.readback_elapsed)
            constructed = True
            if probe:
                self._runtime = construction.run_runtime_probe(self._boundary, built.container_id, material, self._cpu)
            started = self._clock()
            result = construction.parse_exec(self._boundary, built.container_id, data, nonce)
            record.timings["parse"] = self._clock() - started
            record.stdout, record.exit_status, record.stderr_bytes = result.stdout, result.returncode, result.stderr_bytes
            record.stderr_sha256 = result.stderr_sha256
            record.events = tuple(sorted(set(result.events)))
            record.resource_stage = "S4" if record.events else None
            settlement_started = self._clock()
            end = self._boundary.begin_settlement(built.container_id)
            record.memory_peak, reason = construction.resource_facts(
                self._boundary, built.container_id, material, hard_end=end)
            record.memory_peak_reason = reason or "available"
            try:
                running, record.oom_killed = construction.container_state(
                    self._boundary, built.container_id, hard_end=end)
            except ContractError:
                running = False
            record.alive_until_settlement = running and result.clean
            if record.oom_killed:
                record.events = tuple(sorted({*record.events, "memory_bound"}))
        except ContractError as error:
            deadline_expired = error.code == "internal_deadline_exceeded"
            attempt_refused = True
            record.outcome = "inadmissible"
        started = self._clock() if settlement_started is None else settlement_started
        created = any(args[:1] == ("create",) for args in self._boundary.journal[journal_before:])
        newly_owned = list(self._owned[owned_before:])
        absent = all([self._settle(cid) for cid in newly_owned])
        if created and not newly_owned:
            absent = False  # A sent create with no returned ID has no absence proof.
        record.timings["settlement"] = self._clock() - started
        record.absence_proven = absent and len(self._owned) == owned_before
        if constructed and not attempt_refused:
            self._classify(record)
        if probe:
            self._runtime["probe_parse_ok"] = (constructed and record.absence_proven
                and record.outcome == "succeeded" and probe_matches_gold(record.observations))
        self._record_attempt(record, constructed, probe=probe)
        if deadline_expired:
            self._attribute_residue()
            self._state.halt(self._state.halt_code or "internal_deadline_exceeded")
            raise ContractError("internal_deadline_exceeded")
        return record.absence_proven

    def _classify(self, record: FileRecord) -> None:
        if record.events:
            record.outcome = "resource_bound_exceeded"
            return
        if record.exit_status != 0 or not record.alive_until_settlement or record.nonce is None:
            record.outcome = "crashed"
            return
        try:
            decoded = decode_frames(record.stdout, nonce=record.nonce, input_length=len(record.data))
        except ProtocolViolation:
            record.outcome = "crashed"
            return
        try:
            built = build_file_observations(record.path, record.data, decoded, input_sha256=record.input_sha256,
                                            build_script_name=record.build_script_name)
        except ObservationBound:
            record.events, record.resource_stage = ("output_bound",), "S4"
            record.outcome = "resource_bound_exceeded"
            return
        record.outcome, record.completeness, record.achieved = built.outcome, built.completeness, built.achieved
        record.observations = built.observations

    def _record_attempt(self, record: FileRecord, constructed: bool, *, probe: bool = False) -> None:
        assert self._state is not None
        receipt, report = controller_audit.attempted_file(
            self._run_id, record, self._state.profile.profile_sha256, constructed=constructed, probe=probe)
        self._receipts.append(receipt)
        self._report_files.append(report)

    def _attribute_residue(self) -> None:
        """Finish component attribution before any admissible result is returned."""

        assert self._state is not None
        self._residue, settled = controller_audit.observe_residue(
            self._boundary, self._run_id, self._start_snapshot, self._owned)
        self._state.residue_settled = settled
        if not settled:
            self._state.halt("cleanup_incomplete")

    # -- live admission -----------------------------------------------------------------------

    def verify_live(self) -> bool:
        """Recompute the pre-publication condition, including exact owned-container absence."""

        state = getattr(self, "_state", None)
        if state is None or getattr(self, "_closed", True) or not state.live or self._owned:
            return False
        try:
            if state.helper_closure_sha256 != helper_closure_sha256(load_guest_sources(), PROBE_SOURCE_SHA256):
                return False
            if self._boundary.snapshot(self._run_id).labelled:
                return False
            return all(self._boundary.absent(record.container_id) is True
                       for record in state.records.values() if record.container_id is not None)
        except (ContractError, OSError):
            return False

    def admit(self, path: str) -> Admission:
        """Recompute all eight bindings for one path from this run's live state."""

        if not self.verify_live():
            return Admission(path, (), REQUIRED_BINDINGS)
        assert self._state is not None
        return self._state.admit(path)

    def selected_paths(self) -> tuple[str, ...]:
        return () if self._state is None or self._closed else tuple(self._state.records)

    def audit_snapshot(self) -> dict[str, Any]:
        """Return a deep, inert copy for qualification reports, never graph authority."""

        return controller_audit.audit_snapshot(self._run_id, self._report_files, self._receipts,
                                               self._residue, self._boundary)
