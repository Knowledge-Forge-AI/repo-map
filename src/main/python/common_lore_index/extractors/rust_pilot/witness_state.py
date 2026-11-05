"""Live parent witness state for one open pilot run (spec 10, ADR 0155 D3).

The open run object owns the run nonce, the verified profile and expected
tree, and per file the retained input bytes, container facts, raw stdout,
resource events, absence proof and derived observations. Admission
recomputes all eight ADR 0154 ``REQUIRED_BINDINGS`` from that retained state
at the moment of the request. Nothing here is serializable or copyable;
closing or halting the run makes it inert. There is no module-level registry.

Trust limits: the in-process parent and RepoMap source are trusted, as are
same-UID host processes and Docker daemon users. A monkeypatching parent can
forge anything; no claim is made against it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import NoReturn

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.contracts.witness import REQUIRED_BINDINGS
from common_lore_index.extractors.rust_pilot.archive_verifier import ExpectedEntry, expected_tree_digest
from common_lore_index.extractors.rust_pilot.component_lock import LOCK_SHA256, digest_json, lock_document
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    DecodedParse,
    ProtocolViolation,
    decode_frames,
    invocation_nonce,
)
from common_lore_index.extractors.rust_pilot.observations import ObservationBound, build_file_observations
from common_lore_index.extractors.rust_pilot.prepared_profile import VerifiedProfile, profile_bytes
from common_lore_index.observations.raw import RawObservation

NOT_SERIALIZABLE = "witness_not_serializable"
RUN_STATES = frozenset({"open", "closed", "halted"})


class Unserializable:
    __slots__ = ()

    def __reduce__(self) -> NoReturn:
        raise ContractError(NOT_SERIALIZABLE)

    def __reduce_ex__(self, _protocol: object) -> NoReturn:
        raise ContractError(NOT_SERIALIZABLE)

    def __copy__(self) -> NoReturn:
        raise ContractError(NOT_SERIALIZABLE)

    def __deepcopy__(self, _memo: object) -> NoReturn:
        raise ContractError(NOT_SERIALIZABLE)

    def __getstate__(self) -> NoReturn:
        raise ContractError(NOT_SERIALIZABLE)


@dataclass(eq=False)
class FileRecord(Unserializable):
    """Everything the parent itself observed for one selected file."""

    path: str
    seq: int
    discovery_sha256: str
    data: bytes
    build_script_name: bool
    input_sha256: str = ""
    nonce: str | None = None
    container_id: str | None = None
    readback_digest: str | None = None
    exit_status: int | None = None
    alive_until_settlement: bool = False
    oom_killed: bool = False
    stdout: bytes = b""
    events: tuple[str, ...] = ()
    stderr_bytes: int = 0
    stderr_sha256: str | None = None
    readback_bytes: int | None = None
    installed_bytes: int | None = None
    memory_peak: int | None = None
    memory_peak_reason: str = "not_collected"
    resource_stage: str | None = None
    absence_proven: bool = False
    outcome: str = "crashed"
    completeness: str = "none"
    achieved: tuple[str, ...] = ()
    observations: tuple[RawObservation, ...] = ()
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Admission:
    """Result of one recomputation; holding it authorizes nothing later."""

    path: str
    observations: tuple[RawObservation, ...]
    refused_bindings: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return not self.refused_bindings


class RunState(Unserializable):
    """Witness state held only by the controller of one open run."""

    __slots__ = ("run_nonce", "run_id", "profile", "expected", "expected_digest", "helper_closure_sha256",
                 "records", "state", "residue_settled", "halt_code")

    def __init__(self, *, run_nonce: bytes, run_id: str, profile: VerifiedProfile,
                 expected: tuple[ExpectedEntry, ...], helper_closure_sha256: str) -> None:
        if type(run_nonce) is not bytes or len(run_nonce) != 32 or type(profile) is not VerifiedProfile:
            raise ContractError("invalid_run_state")
        self.run_nonce = run_nonce
        self.run_id = run_id
        self.profile = profile
        self.expected = expected
        self.expected_digest = expected_tree_digest(expected)
        self.helper_closure_sha256 = helper_closure_sha256
        self.records: dict[str, FileRecord] = {}
        self.state = "open"
        self.residue_settled = False
        self.halt_code: str | None = None

    def add(self, record: FileRecord) -> None:
        if self.state != "open" or type(record) is not FileRecord or record.path in self.records:
            raise ContractError("invalid_file_record")
        self.records[record.path] = record

    def halt(self, code: str) -> None:
        self.state = "halted"
        self.halt_code = code
        self.residue_settled = False

    def close(self) -> None:
        if self.state == "open":
            self.state = "closed"
        self.residue_settled = False
        self.records = {}

    @property
    def live(self) -> bool:
        return self.state == "open" and self.residue_settled

    def _profile_binding(self, record: FileRecord) -> bool:
        profile = self.profile
        return (hashlib.sha256(profile.profile_bytes).hexdigest() == profile.profile_sha256
                and profile.profile_bytes == profile_bytes(profile.cpu)
                and digest_json(lock_document()) == LOCK_SHA256
                and expected_tree_digest(self.expected) == self.expected_digest
                and record.readback_digest == self.expected_digest)

    def _decoded(self, record: FileRecord, nonce: str) -> DecodedParse | None:
        try:
            return decode_frames(record.stdout, nonce=nonce, input_length=len(record.data))
        except ProtocolViolation:
            return None

    def bindings(self, record: FileRecord) -> dict[str, bool]:
        """Recompute every required binding from retained state, now."""

        digest = hashlib.sha256(record.data).hexdigest()
        nonce = invocation_nonce(self.run_nonce, record.seq, digest) if self.state == "open" else None
        decoded = None if nonce is None else self._decoded(record, nonce)
        rebuilt: tuple[RawObservation, ...] | None = None
        if decoded is not None:
            try:
                rebuilt = build_file_observations(record.path, record.data, decoded, input_sha256=digest,
                                                  build_script_name=record.build_script_name).observations
            except ObservationBound:
                rebuilt = None
        result = {
            "admitted_profile": self._profile_binding(record),
            "selected_source_bytes": digest == record.input_sha256 == record.discovery_sha256,
            "active_run_nonce": nonce is not None and record.nonce == nonce,
            "clean_exit": record.exit_status == 0 and record.alive_until_settlement and not record.oom_killed,
            "strict_protocol": decoded is not None,
            "input_matching_ranges": rebuilt is not None and rebuilt == record.observations,
            "resource_outcome": record.events == (),
            "proven_cleanup": record.absence_proven and self.residue_settled and self.state == "open",
        }
        if tuple(result) != REQUIRED_BINDINGS:
            raise ContractError("binding_checklist_drift")
        return result

    def admit(self, path: str) -> Admission:
        """Admit one file's Rust observations only if all eight bindings hold now.

        Admission is custody, not gating: a ``parse_rejected`` or partial file
        is admitted with its recorded completeness, and the canonical claim
        mapping still refuses every non-usable scope.
        """

        record = self.records.get(path) if self.state == "open" else None
        if record is None:
            return Admission(path, (), REQUIRED_BINDINGS)
        results = self.bindings(record)
        refused = tuple(name for name in REQUIRED_BINDINGS if not results[name])
        return Admission(path, () if refused else record.observations, refused)
