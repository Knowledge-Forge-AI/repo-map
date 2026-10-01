"""ASYNC1 protocol session state machine and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from repomap_kg.coordinator._protocol_validation import (
    PROTOCOL_VERSION,
    ProtocolError,
    _DIRECTIONS,
    _ERROR_CATEGORIES,
    _FIELDS,
    _IDENTITY,
    _KNOWN_ARRAY_CATEGORIES,
    _PORTABLE_SNAPSHOT_CAPABILITY,
    _PORTABLE_SNAPSHOT_FIELD,
    _PROGRESS_CATEGORIES,
    _PROGRESS_PHASES,
    _PROGRESS_UNITS,
    _PROHIBITED_PROTOCOL_CONTENT,
    _PUBLICATION_STATES,
    _START_IDENTITY_FIELDS,
    _bounded_text,
    _in_vocabulary,
    _is_int,
    _parse_utc,
    _public_protocol_text,
    _valid_generation,
    _valid_graph_id,
    _valid_utc_timestamp,
    _validate_portable_snapshot_extension,
    _validate_portable_snapshot_result_extension,
    decode_jsonl,
)
from repomap_kg.coordinator.limits import DEFAULT_LIMITS

@dataclass
class ProtocolSession:
    """Validate ASYNC1 direction, negotiation, ordering, identity, and terminals."""

    identity: Mapping[str, object]

    def __post_init__(self) -> None:
        if set(self.identity) != _IDENTITY:
            raise ProtocolError("invalid_identity")
        self.identity = dict(self.identity)
        job_id = self.identity["job_id"]
        if not _bounded_text(job_id, 128) or _PROHIBITED_PROTOCOL_CONTENT.search(job_id):
            raise ProtocolError("invalid_identity")
        attempt = self.identity["attempt"]
        if not _is_int(attempt) or attempt <= 0:
            raise ProtocolError("invalid_identity")
        self.state = "awaiting_hello"
        self.negotiated_version: int | None = None
        self._portable_snapshot_capability = False
        self._portable_snapshot_requested = False
        self.terminal: dict[str, object] | None = None
        self._accepted_job_start: dict[str, object] | None = None
        self._completed = 0

    def accept_worker(self, message: Mapping[str, object] | bytes) -> dict[str, object]:
        return self._accept(message, "worker")

    def accept_coordinator(
        self, message: Mapping[str, object] | bytes
    ) -> dict[str, object]:
        return self._accept(message, "coordinator")

    def _accept(
        self, message: Mapping[str, object] | bytes, direction: str
    ) -> dict[str, object]:
        decoded = decode_jsonl(message) if isinstance(message, bytes) else message
        if not isinstance(decoded, Mapping):
            raise ProtocolError("invalid_message")
        payload = dict(decoded)
        if payload.get("schema_version") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported_version")
        message_type = payload.get("message_type")
        if message_type == "worker_exit":
            raise ProtocolError("internal_message")
        if not isinstance(message_type, str) or message_type not in _FIELDS:
            raise ProtocolError("unknown_type")
        if _DIRECTIONS[message_type] != direction:
            raise ProtocolError("wrong_direction")
        expected_fields = _FIELDS[message_type]
        if message_type == "job_start" and _PORTABLE_SNAPSHOT_FIELD in payload:
            if not self._portable_snapshot_capability:
                raise ProtocolError("negotiation_failed")
            expected_fields |= frozenset({_PORTABLE_SNAPSHOT_FIELD})
        elif message_type in {"result", "error"}:
            if _PORTABLE_SNAPSHOT_FIELD in payload:
                if not self._portable_snapshot_capability or not self._portable_snapshot_requested:
                    raise ProtocolError("negotiation_failed")
                expected_fields |= frozenset({_PORTABLE_SNAPSHOT_FIELD})
            elif self._portable_snapshot_requested:
                raise ProtocolError("negotiation_failed")
        if set(payload) != expected_fields:
            raise ProtocolError("invalid_fields")
        if message_type != "worker_hello" and any(
            payload[field] != self.identity[field] for field in _IDENTITY
        ):
            raise ProtocolError("identity_mismatch")
        self._validate_order(message_type)
        if message_type in {"result", "error"} and (
            self._accepted_job_start is None
            or any(
                payload[field] != self._accepted_job_start[field]
                for field in _START_IDENTITY_FIELDS
            )
        ):
            raise ProtocolError("identity_mismatch")
        self._validate_values(message_type, payload)
        self._advance(message_type, payload)
        return payload

    def _validate_order(self, message_type: str) -> None:
        if self.state == "terminal":
            code = "duplicate_terminal" if message_type in {"result", "error"} else "message_after_terminal"
            raise ProtocolError(code)
        allowed = {
            "awaiting_hello": {"worker_hello"},
            "awaiting_start": {"job_start"},
            "running": {"progress", "heartbeat", "cancel", "result", "error"},
            # Independent pipes can carry progress written before cancel was read.
            "cancel_requested": {"progress", "heartbeat", "cancel_ack", "result", "error"},
            "cancelling": {"progress", "heartbeat", "result", "error"},
        }
        if message_type not in allowed[self.state]:
            raise ProtocolError("out_of_order")

    def _validate_values(self, message_type: str, payload: Mapping[str, object]) -> None:
        if message_type == "worker_hello":
            versions = payload["protocol_versions"]
            if not isinstance(versions, list) or not all(_is_int(item) for item in versions):
                raise ProtocolError("invalid_value")
            if versions != [PROTOCOL_VERSION]:
                raise ProtocolError("negotiation_failed")
            if payload["capabilities"] not in (
                ["refresh_graph"],
                ["refresh_graph", _PORTABLE_SNAPSHOT_CAPABILITY],
            ):
                raise ProtocolError("negotiation_failed")
            self._portable_snapshot_capability = (
                _PORTABLE_SNAPSHOT_CAPABILITY in payload["capabilities"]
            )
            for field in ("worker_generation", "process_nonce"):
                if not _public_protocol_text(payload[field], 128):
                    raise ProtocolError("invalid_value")
        elif message_type == "job_start":
            if payload["job_kind"] != "refresh_graph":
                raise ProtocolError("invalid_value")
            if not _valid_graph_id(payload["graph_id"]):
                raise ProtocolError("invalid_value")
            if not _valid_generation(payload["source_generation"], "sg1:"):
                raise ProtocolError("invalid_value")
            if not _valid_generation(payload["config_generation"], "cg1:"):
                raise ProtocolError("invalid_value")
            if _PORTABLE_SNAPSHOT_FIELD in payload:
                _validate_portable_snapshot_extension(
                    payload[_PORTABLE_SNAPSHOT_FIELD]
                )
        elif message_type == "progress":
            completed, total = payload["completed"], payload["total"]
            if (not _is_int(completed)
                    or completed < self._completed
                    or completed > DEFAULT_LIMITS.max_counter):
                raise ProtocolError("invalid_value")
            if total is not None and (
                not _is_int(total)
                or completed > total
                or total > DEFAULT_LIMITS.max_counter
            ):
                raise ProtocolError("invalid_value")
            if (not _in_vocabulary(payload["phase"], _PROGRESS_PHASES)
                    or not _in_vocabulary(payload["unit"], _PROGRESS_UNITS)
                    or not _in_vocabulary(
                        payload["message_category"], _PROGRESS_CATEGORIES)
                    or not _valid_utc_timestamp(payload["heartbeat_at"])):
                raise ProtocolError("invalid_value")
        elif message_type == "heartbeat":
            if not _valid_utc_timestamp(payload["heartbeat_at"]):
                raise ProtocolError("invalid_value")
        elif message_type == "cancel_ack":
            if not _in_vocabulary(
                payload["status"],
                frozenset({"accepted", "deferred", "already-complete"}),
            ):
                raise ProtocolError("invalid_value")
        elif message_type in {"result", "error"}:
            self._validate_terminal(message_type, payload)

    def _validate_terminal(self, message_type: str, payload: Mapping[str, object]) -> None:
        if payload["job_kind"] != "refresh_graph":
            raise ProtocolError("invalid_value")
        if (not _valid_graph_id(payload["graph_id"])
                or not _valid_generation(payload["source_generation"], "sg1:")
                or not _valid_generation(payload["config_generation"], "cg1:")
                or not _in_vocabulary(payload["phase"], _PROGRESS_PHASES)
                or not _valid_utc_timestamp(payload["started_at"])
                or not _valid_utc_timestamp(payload["finished_at"])
                or _parse_utc(payload["started_at"]) > _parse_utc(payload["finished_at"])):
            raise ProtocolError("invalid_value")
        for field in ("extractor_generation", "canonicalizer_generation"):
            if not _public_protocol_text(payload[field], 128):
                raise ProtocolError("invalid_value")
        for field in ("files", "observations", "canonical_nodes", "canonical_edges"):
            field_val = payload[field]
            if not _is_int(field_val) or field_val < 0 or field_val > DEFAULT_LIMITS.max_counter:
                raise ProtocolError("invalid_value")
        for field in ("warnings", "diagnostics"):
            values = payload[field]
            if not isinstance(values, list) or len(values) > 32 or any(
                not _in_vocabulary(value, _KNOWN_ARRAY_CATEGORIES)
                for value in values
            ):
                raise ProtocolError("invalid_value")
        publication = payload["publication_state"]
        if (not _in_vocabulary(publication, _PUBLICATION_STATES)
                or not isinstance(payload["retryable"], bool)):
            raise ProtocolError("invalid_value")
        if _PORTABLE_SNAPSHOT_FIELD in payload:
            _validate_portable_snapshot_result_extension(
                payload[_PORTABLE_SNAPSHOT_FIELD], message_type, payload
            )
            if message_type == "result":
                if (not _in_vocabulary(
                        payload["status"], frozenset({"succeeded", "cancelled"}))
                        or payload["error_category"] is not None):
                    raise ProtocolError("invalid_value")
                if payload["status"] == "succeeded" and publication != "not_started":
                    raise ProtocolError("invalid_value")
                if (payload["status"] == "cancelled"
                        and publication not in {"not_started", "rolled_back"}):
                    raise ProtocolError("invalid_value")
            elif (payload["status"] != "failed"
                  or not _in_vocabulary(payload["error_category"], _ERROR_CATEGORIES)
                  or publication != "not_started"):
                raise ProtocolError("invalid_value")
        else:
            if message_type == "result":
                if (not _in_vocabulary(
                        payload["status"], frozenset({"succeeded", "cancelled"}))
                        or payload["error_category"] is not None):
                    raise ProtocolError("invalid_value")
                if payload["status"] == "succeeded" and publication != "committed":
                    raise ProtocolError("invalid_value")
                if (payload["status"] == "cancelled"
                        and publication not in {"not_started", "rolled_back"}):
                    raise ProtocolError("invalid_value")
            elif (payload["status"] != "failed"
                  or not _in_vocabulary(payload["error_category"], _ERROR_CATEGORIES)
                  or publication == "committed"):
                raise ProtocolError("invalid_value")
        latest_run = payload["latest_run_identity"]
        if publication == "committed":
            if not _public_protocol_text(latest_run, 128):
                raise ProtocolError("invalid_value")
        elif latest_run is not None:
            raise ProtocolError("invalid_value")

    def _advance(self, message_type: str, payload: Mapping[str, object]) -> None:
        if message_type == "worker_hello":
            self.negotiated_version = PROTOCOL_VERSION
            self.state = "awaiting_start"
        elif message_type == "job_start":
            self._accepted_job_start = {
                field: payload[field] for field in _START_IDENTITY_FIELDS
            }
            self._portable_snapshot_requested = _PORTABLE_SNAPSHOT_FIELD in payload
            self.state = "running"
        elif message_type == "progress":
            self._completed = cast(int, payload["completed"])
        elif message_type == "cancel":
            self.state = "cancel_requested"
        elif message_type == "cancel_ack":
            self.state = "cancelling"
        elif message_type in {"result", "error"}:
            self.terminal = dict(payload)
            self.state = "terminal"

