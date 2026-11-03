"""Stable schemas, bounds and authority records for the semantic worker."""

from __future__ import annotations

from dataclasses import dataclass
import re

REQUEST_SCHEMA = "cloe-w5-native-generation-request-v1"
RESPONSE_SCHEMA = "cloe-w5-native-generation-response-v1"
CONTROLLER_ADMISSION_SCHEMA = "cloe-w5-native-generation-admission-v1"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_ADMISSION_BYTES = 512 * 1024
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
ATTEMPT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")

# This is an authority list, not a discovery glob. The controller hashes the
# same set before admitting a run, including every imported worker owner.
WORKER_SOURCE_FILES = (
    "retrieval_evaluation_attempts.py",
    "retrieval_semantic_generator_artifacts.py",
    "retrieval_semantic_generator_inputs.py",
    "retrieval_semantic_generator_kernel.py",
    "retrieval_semantic_generator_kernel_contracts.py",
    "retrieval_semantic_generator_kernel_runtime_factory.py",
    "retrieval_semantic_generator_kernel_runtime_types.py",
    "retrieval_semantic_generator_kernel_runtime_validation.py",
    "retrieval_semantic_generator_kernel_validation.py",
    "retrieval_semantic_generator_output.py",
    "retrieval_semantic_generator_output_parser.py",
    "retrieval_semantic_generator_output_receipt.py",
    "retrieval_semantic_generator_pins.json",
    "retrieval_semantic_generator_runtime.py",
    "retrieval_semantic_generator_worker.py",
    "retrieval_semantic_generator_worker_contracts.py",
    "retrieval_semantic_generator_worker_protocol.py",
)


class WorkerRequestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PhaseControllerAdmission:
    phase: str
    admission_sha256: str
    operator_authority_sha256: str
    gate_references: tuple[tuple[str, str], ...]
    request_sha256: str
    input_identity: str
    representation_report_identity: str
    publication_identity: str
    artifact_profile_identity: str
    candidate_closure_digests: tuple[tuple[str, str], ...]
    scope: str


__all__ = [
    "ATTEMPT_ID_PATTERN",
    "CONTROLLER_ADMISSION_SCHEMA",
    "MAX_ADMISSION_BYTES",
    "MAX_REQUEST_BYTES",
    "PhaseControllerAdmission",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "SHA256_PATTERN",
    "WORKER_SOURCE_FILES",
    "WorkerRequestError",
]
