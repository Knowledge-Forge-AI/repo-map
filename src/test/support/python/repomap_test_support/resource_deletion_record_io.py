"""Store methods for immutable deletion-record persistence."""

from __future__ import annotations

import hashlib

from repomap_test_support.resource_deletion_record_persistence import (
    _write_checked,
    read_private_json,
)
from repomap_test_support.resource_deletion_record_types import DeletionRecordError
from repomap_test_support.resource_deletion_record_types import (
    _DeletionRecordStoreProtocol,
)
from repomap_test_support.resource_deletion_record_validation import (
    _validate_barrier,
    _validate_completion,
    _validate_intent,
    _validate_restoration,
    _validate_tombstone,
)
from repomap_test_support.resource_index_records import safe_run_id
from repomap_test_support.resource_ledger_io import PrivateJsonError
from repomap_test_support.resource_validation import HygieneValidationError

class _DeletionRecordStoreIoMixin(_DeletionRecordStoreProtocol):
    def _write(self, kind: str, payload: dict[str, object]):
        run_id = str(payload["run_id"])
        record_id = str(payload["quarantine_record_id"])
        root, validator = _record_owner(self, kind)
        path = root / f"{self._key(run_id, record_id)}.json"
        return _write_checked(
            path, payload, lambda item: validator(item, self.project)
        )

    def _read_optional(
        self, kind: str, run_id: str, quarantine_record_id: str
    ) -> dict[str, object] | None:
        root, validator = _record_owner(self, kind)
        path = root / f"{self._key(run_id, quarantine_record_id)}.json"
        if not path.exists() and not path.is_symlink():
            return None
        try:
            return validator(read_private_json(path), self.project)
        except (OSError, PrivateJsonError, HygieneValidationError) as error:
            raise DeletionRecordError("deletion record is invalid") from error

    @staticmethod
    def _key(run_id: str, quarantine_record_id: str) -> str:
        digest = hashlib.sha256(quarantine_record_id.encode()).hexdigest()
        return f"{safe_run_id(run_id)}--{digest}"


def _record_owner(store, kind: str):
    owners = {
        "intent": (store.intent_root, _validate_intent),
        "barrier": (store.barrier_root, _validate_barrier),
        "completion": (store.completion_root, _validate_completion),
        "tombstone": (store.tombstone_root, _validate_tombstone),
        "restoration": (store.restoration_root, _validate_restoration),
    }
    try:
        return owners[kind]
    except KeyError as error:
        raise DeletionRecordError("deletion record kind is unsupported") from error


__all__ = ["_DeletionRecordStoreIoMixin", "_record_owner"]
