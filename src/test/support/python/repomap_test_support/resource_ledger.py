"""Strict private ledger for exact current-run test-resource ownership."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_test_support.resource_ledger_codec import (
    checkpoint_from_payload,
    decode_ledger_payload,
    encode_ledger_payload,
    facts_from_payload,
    identity_from_payload,
    lifecycle_from_payload,
    lifecycle_to_payload,
    record_from_payload,
    record_to_payload,
    validate_lifecycle,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json,
)
from repomap_test_support.resource_ledger_records import (
    CHECKPOINT_FIELDS,
    CHECKPOINT_INTEGER_FIELDS,
    FACTS,
    CleanupResult,
    FinalPresence,
    LEDGER_SCHEMA,
    LedgerLifecycle,
    ResourceKind,
    ResourceLedgerError,
    ResourceRecord,
    RetainedReason,
    RunIdentity,
    validate_record,
)
from repomap_test_support.resource_projection import resource_count_projection
from repomap_test_support.resource_retention import (
    TerminalOutcome,
    create_terminal_stamp,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_bool,
    nonnegative_int,
)

_FACTS = FACTS
_CHECKPOINT_INTEGER_FIELDS = CHECKPOINT_INTEGER_FIELDS
_CHECKPOINT_FIELDS = CHECKPOINT_FIELDS


class ResourceLedger:
    """Atomic v2 evidence for one exact project, phase, and run identity."""

    def __init__(
        self,
        path: Path,
        identity: RunIdentity,
        records: tuple[ResourceRecord, ...] = (),
        *,
        created_at_seconds: int,
        checkpoints: tuple[dict[str, Any], ...] = (),
        facts: dict[str, bool] | None = None,
        lifecycle: LedgerLifecycle = LedgerLifecycle(),
    ) -> None:
        self.path = Path(path)
        self.identity = identity
        self.created_at_seconds = created_at_seconds
        self._records = list(records)
        self._checkpoints = list(checkpoints)
        self._facts = dict(facts or {})
        self.lifecycle = lifecycle

    @property
    def records(self) -> tuple[ResourceRecord, ...]:
        return tuple(self._records)

    @classmethod
    def create(
        cls,
        path: Path,
        identity: RunIdentity,
        *,
        now_seconds: int | None = None,
    ) -> "ResourceLedger":
        path = Path(path)
        if path.exists() or path.is_symlink():
            raise ResourceLedgerError("resource ledger already exists")
        try:
            created = nonnegative_int(
                int(time.time()) if now_seconds is None else now_seconds,
                "ledger creation timestamp",
            )
        except HygieneValidationError as error:
            raise ResourceLedgerError(str(error)) from error
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ledger = cls(path, identity, created_at_seconds=created)
        ledger._persist()
        return ledger

    @classmethod
    def open(cls, path: Path, identity: RunIdentity) -> "ResourceLedger":
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ResourceLedgerError("resource ledger must be a plain file")
        try:
            payload = read_private_json(path)
            decoded = decode_ledger_payload(
                payload,
                identity,
                record_decoder=cls._record_from_payload,
                checkpoint_decoder=cls._checkpoint_from_payload,
                facts_decoder=cls._facts_from_payload,
                identity_decoder=cls._identity_from_payload,
                lifecycle_decoder=cls._lifecycle_from_payload,
                lifecycle_validator=cls._validate_lifecycle,
            )
        except ResourceLedgerError:
            raise
        except PrivateJsonError as error:
            raise ResourceLedgerError("resource ledger is not valid JSON") from error
        except (HygieneValidationError, TypeError, ValueError) as error:
            raise ResourceLedgerError("resource ledger fields are invalid") from error
        return cls(
            path,
            identity,
            decoded.records,
            created_at_seconds=decoded.created_at_seconds,
            checkpoints=decoded.checkpoints,
            facts=decoded.facts,
            lifecycle=decoded.lifecycle,
        )

    def register(
        self,
        kind: ResourceKind,
        identity: str,
        *,
        creation_owner: str,
        created_before_run: bool,
        creation_observed: bool,
        cleanup_required: bool,
        retained: bool = False,
        retained_reason: RetainedReason | str = RetainedReason.NOT_RETAINED,
        size_bytes: int = 0,
        inode_count: int = 0,
    ) -> ResourceRecord:
        try:
            record = ResourceRecord(
                kind=ResourceKind(kind),
                identity=bounded_string(identity, "resource identity", 4096),
                creation_owner=bounded_string(creation_owner, "creation owner"),
                created_before_run=exact_bool(created_before_run, "created_before_run"),
                creation_observed=exact_bool(creation_observed, "creation_observed"),
                cleanup_required=exact_bool(cleanup_required, "cleanup_required"),
                retained=exact_bool(retained, "retained"),
                retained_reason=RetainedReason(retained_reason),
                cleanup_result=(CleanupResult.RETAINED if retained else CleanupResult.NOT_ATTEMPTED),
                size_bytes=nonnegative_int(size_bytes, "size_bytes"),
                inode_count=nonnegative_int(inode_count, "inode_count"),
            )
            self._validate_record(record)
        except HygieneValidationError as error:
            raise ResourceLedgerError(str(error)) from error
        except ValueError as error:
            raise ResourceLedgerError(
                "retained reason is not in the closed vocabulary"
            ) from error
        existing = self._find(record.kind, record.identity)
        if existing is not None:
            if existing == record:
                return existing
            raise ResourceLedgerError("conflicting resource identity registration")
        self._records.append(record)
        self._persist()
        return record

    def get(self, kind: ResourceKind, identity: str) -> ResourceRecord:
        record = self._find(ResourceKind(kind), identity)
        if record is None:
            raise ResourceLedgerError("resource identity is not in the ledger")
        return record

    def mark_cleanup_attempted(self, kind: ResourceKind, identity: str) -> None:
        record = self.get(kind, identity)
        if record.created_before_run:
            raise ResourceLedgerError("pre-existing resource cannot be cleaned")
        if not record.cleanup_required:
            raise ResourceLedgerError("resource does not require cleanup")
        self._replace(record, cleanup_attempted=True)

    def mark_cleanup_result(self, kind: ResourceKind, identity: str, result: CleanupResult) -> None:
        record = self.get(kind, identity)
        result = CleanupResult(result)
        if not record.cleanup_attempted:
            raise ResourceLedgerError("cleanup was not attempted")
        if result not in {CleanupResult.REMOVED, CleanupResult.ALREADY_ABSENT, CleanupResult.FAILED}:
            raise ResourceLedgerError("cleanup result is not terminal")
        self._replace(record, cleanup_result=result)

    def mark_final_presence(self, kind: ResourceKind, identity: str, presence: FinalPresence) -> None:
        record = self.get(kind, identity)
        if record.cleanup_result not in {
            CleanupResult.REMOVED,
            CleanupResult.ALREADY_ABSENT,
            CleanupResult.FAILED,
            CleanupResult.RETAINED,
        }:
            raise ResourceLedgerError("terminal cleanup result is required")
        self._replace(record, final_presence=FinalPresence(presence))

    def add_checkpoint(self, label: str, values: dict[str, int | str]) -> None:
        try:
            label = bounded_string(label, "checkpoint label", 64)
            for key in _CHECKPOINT_INTEGER_FIELDS & set(values):
                nonnegative_int(values[key], key)
            if set(values) != _CHECKPOINT_FIELDS:
                raise HygieneValidationError("invalid checkpoint field set")
            category = bounded_string(
                values["largest_owned_subtree_category"],
                "largest owned subtree category",
                64,
            )
        except (HygieneValidationError, TypeError) as error:
            raise ResourceLedgerError(str(error)) from error
        checkpoint = {"label": label, **values}
        checkpoint["largest_owned_subtree_category"] = category
        self._checkpoints.append(checkpoint)
        self._persist()

    def set_fact(self, name: str, value: bool) -> None:
        if name not in _FACTS:
            raise ResourceLedgerError("unknown ledger fact")
        try:
            value = exact_bool(value, "ledger fact")
        except HygieneValidationError as error:
            raise ResourceLedgerError(str(error)) from error
        self._facts[name] = value
        self._persist()

    def stamp_terminal(
        self,
        outcome: TerminalOutcome | str,
        terminal_at_seconds: int,
        *,
        report_source_pending: bool = False,
    ) -> LedgerLifecycle:
        if self.lifecycle.terminal_at_seconds is not None:
            raise ResourceLedgerError("ledger terminal stamp already exists")
        try:
            stamp = create_terminal_stamp(
                outcome,
                terminal_at_seconds,
                report_source_pending=report_source_pending,
            )
        except RuntimeError as error:
            raise ResourceLedgerError(str(error)) from error
        self.lifecycle = LedgerLifecycle(
            stamp.retention_class,
            stamp.outcome,
            stamp.terminal_at_seconds,
        )
        self._persist()
        return self.lifecycle

    def has_report_source(self) -> bool:
        return any(
            record.retained and record.retained_reason is RetainedReason.REPORT_SOURCE
            for record in self._records
        )

    def assert_transient_cleanup(self) -> None:
        incomplete = []
        for record in self._records:
            if record.created_before_run or record.retained or not record.cleanup_required:
                continue
            if (
                not record.cleanup_attempted
                or record.cleanup_result not in {CleanupResult.REMOVED, CleanupResult.ALREADY_ABSENT}
                or record.final_presence is not FinalPresence.ABSENT
            ):
                incomplete.append(record.kind.value)
        if incomplete:
            raise ResourceLedgerError("current-run teardown is incomplete")

    def assert_current_run_teardown(self) -> None:
        self.assert_transient_cleanup()

    def host_restoration_proved(self) -> bool:
        if set(self._facts) != _FACTS:
            return False
        try:
            return all(exact_bool(self._facts[name], "mutation fact") is False for name in _FACTS)
        except HygieneValidationError as error:
            raise ResourceLedgerError(str(error)) from error

    def assert_host_restoration(self) -> None:
        self.assert_transient_cleanup()
        if set(self._facts) != _FACTS:
            raise ResourceLedgerError("host-restoration mutation facts are unobserved")
        if not self.host_restoration_proved():
            raise ResourceLedgerError("host restoration is not proved")

    def public_projection(self) -> dict[str, int | bool | str]:
        for value in self._facts.values():
            try:
                exact_bool(value, "mutation fact")
            except HygieneValidationError as error:
                raise ResourceLedgerError(str(error)) from error
        return resource_count_projection(self._records, self._facts)

    def _replace(self, record: ResourceRecord, **changes: Any) -> None:
        index = self._records.index(record)
        self._records[index] = replace(record, **changes)
        self._persist()

    def _find(self, kind: ResourceKind, identity: str) -> ResourceRecord | None:
        return next(
            (item for item in self._records if item.kind is kind and item.identity == identity),
            None,
        )

    def _persist(self) -> None:
        try:
            write_private_json(
                self.path,
                encode_ledger_payload(
                    identity=self.identity,
                    created_at_seconds=self.created_at_seconds,
                    records=self._records,
                    checkpoints=self._checkpoints,
                    facts=self._facts,
                    lifecycle=self.lifecycle,
                    record_encoder=self._record_payload,
                    lifecycle_encoder=self._lifecycle_payload,
                ),
            )
        except (OSError, PrivateJsonError) as error:
            raise ResourceLedgerError("resource ledger persistence failed") from error

    _record_payload = staticmethod(record_to_payload)

    @staticmethod
    def _record_from_payload(payload: Any) -> ResourceRecord:
        record = record_from_payload(payload, validate=False)
        ResourceLedger._validate_record(record)
        return record

    _checkpoint_from_payload = staticmethod(checkpoint_from_payload)
    _facts_from_payload = staticmethod(facts_from_payload)
    _identity_from_payload = staticmethod(identity_from_payload)
    _lifecycle_payload = staticmethod(lifecycle_to_payload)
    _lifecycle_from_payload = staticmethod(lifecycle_from_payload)
    _validate_record = staticmethod(validate_record)
    _validate_lifecycle = staticmethod(validate_lifecycle)


__all__ = [
    "CleanupResult",
    "FinalPresence",
    "LEDGER_SCHEMA",
    "LedgerLifecycle",
    "ResourceKind",
    "ResourceLedger",
    "ResourceLedgerError",
    "ResourceRecord",
    "RetainedReason",
    "RunIdentity",
]
