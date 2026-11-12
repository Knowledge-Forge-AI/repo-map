"""Synthetic raw delivery over the real component-exchange boundaries (study section 19.3).

Functional mode only. The driver keeps the unchanged ``ComponentExchange``
order; this owner replaces only the external supervisor's raw delivery:

* ``admit`` writes a synthetic-functional controller admission and then its
  maintained ``encode_admission_marker`` marker into the owned nonce directory;
* ``respond`` writes the actual seven raw protocol members for the exact
  request bytes (flat worker closure, actual admission bytes) as the
  maintained response bundle, then its ready marker.

The unchanged ``await_controller_admission``/``await_response`` and parser do
all validation. Nothing is a model run, a native reservation or a model-origin
claim, and no accepted response object is fabricated here.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import tarfile

from repomap_test_support.w5_public_text_artifacts import synthetic_admission, synthetic_raw_component
from retrieval_public_text_sources import SourceClosure
from retrieval_semantic_bridge_admission import (
    CONTROLLER_ADMISSION_NAME, CONTROLLER_ADMISSION_READY_NAME, encode_admission_marker,
)
from retrieval_semantic_bridge_transport import encode_response_bundle, encode_response_tar
from retrieval_semantic_experiment_bridge import ComponentExchange

RESPONSE_NAME = "response.zip"
RESPONSE_READY_NAME = "response.ready.json"


class FunctionalDeliveryRefusal(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _tar_members(raw: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = {}
        for info in archive.getmembers():
            handle = archive.extractfile(info) if info.isreg() else None
            if handle is None:
                raise FunctionalDeliveryRefusal("functional_response_tar")
            members[info.name] = handle.read()
    if set(members) != {RESPONSE_NAME, RESPONSE_READY_NAME}:
        raise FunctionalDeliveryRefusal("functional_response_tar")
    return members


class SyntheticDelivery:
    """One concrete synthetic supplier per study; each generation is admitted and answered once."""

    def __init__(self, model_root: Path, worker: SourceClosure) -> None:
        if worker.name != "worker" or not isinstance(model_root, Path) or not model_root.is_absolute():
            raise FunctionalDeliveryRefusal("functional_delivery_configuration")
        self._model_root = model_root
        self._worker = worker
        self._admitted: dict[str, bytes] = {}
        self._answered: set[str] = set()

    def admit(self, exchange: ComponentExchange) -> str:
        """Write payload then marker for this nonce; returns the synthetic admission digest."""
        if type(exchange) is not ComponentExchange or exchange.admission_raw is not None:
            raise FunctionalDeliveryRefusal("functional_admission_state")
        if exchange.nonce in self._admitted:
            raise FunctionalDeliveryRefusal("functional_admission_repeated")
        if dict(exchange.expected_source_closure) != dict(self._worker.digests):
            raise FunctionalDeliveryRefusal("functional_worker_closure_mismatch")
        admission_raw = synthetic_admission(exchange.request_raw, self._worker.digests)
        marker = encode_admission_marker(admission_raw, nonce=exchange.nonce, attempt_id=exchange.attempt_id,
                                         request_sha256=exchange.ready.request_sha256)
        _write_exclusive(exchange.directory / CONTROLLER_ADMISSION_NAME, admission_raw)
        _write_exclusive(exchange.directory / CONTROLLER_ADMISSION_READY_NAME, marker)
        self._admitted[exchange.nonce] = admission_raw
        return "sha256:" + hashlib.sha256(admission_raw).hexdigest()

    def respond(self, exchange: ComponentExchange) -> None:
        """After the evaluator ACK: write the raw response bundle, then its ready marker."""
        admitted = self._admitted.get(exchange.nonce)
        if admitted is None or exchange.admission_raw != admitted:
            raise FunctionalDeliveryRefusal("functional_response_before_bound_admission")
        if exchange.nonce in self._answered:
            raise FunctionalDeliveryRefusal("functional_response_repeated")
        model_root = self._model_root / f"nonce-{exchange.nonce[:16]}"
        component = synthetic_raw_component(model_root, exchange.request_raw, source_files=self._worker.files,
                                            admission_raw=admitted)
        files = {"request.json": exchange.request_raw, "admission.json": admitted, **component.members}
        members = _tar_members(encode_response_tar(encode_response_bundle(files), exchange.nonce))
        _write_exclusive(exchange.directory / RESPONSE_NAME, members[RESPONSE_NAME])
        _write_exclusive(exchange.directory / RESPONSE_READY_NAME, members[RESPONSE_READY_NAME])
        self._answered.add(exchange.nonce)


__all__ = ["FunctionalDeliveryRefusal", "SyntheticDelivery"]
