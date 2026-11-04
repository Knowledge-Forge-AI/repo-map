"""Small, dependency-neutral contracts for W5 admission decisions."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy


W5_ADMISSION_SCHEMA = "cloe-w5-admission-v1"


class AdmissionVerificationError(ValueError):
    """A live pin or policy could not be verified before candidate access."""

    def __init__(self, code: str) -> None:
        safe = (
            code
            if isinstance(code, str) and code and all(ord(c) >= 32 for c in code)
            else "w5_admission_verification_failed"
        )
        self.code = safe
        super().__init__(safe)


class BindingDisposition(StrEnum):
    ADMITTED_PUBLIC = "admitted_public"
    DENIED_OBSERVED = "denied_observed"
    DENIED_DECLARED = "denied_declared"
    UNDECLARED = "undeclared"
    DECLARED_PUBLIC_ABSENT = "declared_public_absent"
    FOREIGN_PUBLIC = "foreign_publication"


class AdmissionState(StrEnum):
    ADMITTED = "admitted"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


@runtime_checkable
class PublicationPin(Protocol):
    @property
    def graph_id(self) -> str: ...

    @property
    def backend(self) -> str: ...

    @property
    def run_id(self) -> int: ...

    @property
    def generation(self) -> int: ...

    @property
    def policy_digest(self) -> str: ...

    @property
    def admitted_public_bindings(self) -> Collection[str]: ...

    @property
    def denied_bindings(self) -> Mapping[str, str]: ...

    def revalidate_current(self) -> PublicationPin: ...


@dataclass(frozen=True)
class BindingAdmission:
    binding_id: str
    disposition: BindingDisposition
    reason_code: str | None = None

    def validate(self) -> BindingAdmission:
        if type(self.binding_id) is not str or not self.binding_id:
            raise AdmissionVerificationError("invalid_binding_identity")
        if not isinstance(self.disposition, BindingDisposition):
            raise AdmissionVerificationError("invalid_binding_disposition")
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
            or any(ord(c) < 32 for c in self.reason_code)
        ):
            raise AdmissionVerificationError("invalid_binding_reason")
        return self

    def to_dict(self) -> dict[str, str | None]:
        self.validate()
        return {"binding_id": self.binding_id, "disposition": self.disposition.value, "reason_code": self.reason_code}


@dataclass(frozen=True)
class W5AdmissionDecision:
    task_id: str
    graph_id: str
    requested_mode: str
    observed_backend: str
    selected_binding_ids: tuple[str, ...]
    bindings: tuple[BindingAdmission, ...]
    state: AdmissionState
    reason_category: str | None
    refusal_code: str | None
    policy_digest: str
    policy_enforcement_layer: str | None
    backend_policy_enforcement_observed: bool = False
    publication_identity: Mapping[str, Any] | None = None

    @property
    def execution_allowed(self) -> bool:
        return self.state is AdmissionState.ADMITTED

    @property
    def omitted_binding_ids(self) -> tuple[str, ...]:
        return tuple(
            item.binding_id for item in self.bindings
            if item.disposition is not BindingDisposition.ADMITTED_PUBLIC
        )

    def validate(self) -> W5AdmissionDecision:
        if any(type(value) is not str or not value for value in (
            self.task_id, self.graph_id, self.requested_mode, self.observed_backend, self.policy_digest,
        )):
            raise AdmissionVerificationError("invalid_admission_identity")
        if len(self.selected_binding_ids) != len(set(self.selected_binding_ids)):
            raise AdmissionVerificationError("duplicate_selected_binding")
        if tuple(item.binding_id for item in self.bindings) != self.selected_binding_ids:
            raise AdmissionVerificationError("admission_selection_mismatch")
        for item in self.bindings:
            item.validate()
        if self.backend_policy_enforcement_observed is not False:
            raise AdmissionVerificationError("backend_policy_enforcement_must_be_false")
        denied = any(
            item.disposition in {
                BindingDisposition.DENIED_OBSERVED,
                BindingDisposition.DENIED_DECLARED,
            }
            for item in self.bindings
        )
        unknown = any(
            item.disposition in {
                BindingDisposition.UNDECLARED,
                BindingDisposition.DECLARED_PUBLIC_ABSENT,
                BindingDisposition.FOREIGN_PUBLIC,
            }
            for item in self.bindings
        )
        if denied and self.state is not AdmissionState.REFUSED:
            raise AdmissionVerificationError("denial_must_refuse_whole_scope")
        if not denied and unknown and self.state is not AdmissionState.UNAVAILABLE:
            raise AdmissionVerificationError("unknown_scope_must_fail_closed")
        if not denied and not unknown and self.state is not AdmissionState.ADMITTED:
            raise AdmissionVerificationError("admitted_scope_state_mismatch")
        if self.state is AdmissionState.REFUSED and not self.refusal_code:
            raise AdmissionVerificationError("refusal_code_required")
        if self.state is not AdmissionState.REFUSED and self.refusal_code is not None:
            raise AdmissionVerificationError("unexpected_refusal_code")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": W5_ADMISSION_SCHEMA, "task_id": self.task_id, "graph_id": self.graph_id,
            "requested_mode": self.requested_mode, "observed_backend": self.observed_backend,
            "selected_binding_ids": list(self.selected_binding_ids),
            "bindings": [item.to_dict() for item in self.bindings], "state": self.state.value,
            "execution_allowed": self.execution_allowed, "reason_category": self.reason_category,
            "refusal_code": self.refusal_code, "policy_digest": self.policy_digest,
            "policy_enforcement_layer": self.policy_enforcement_layer,
            "backend_policy_enforcement_observed": False,
            "publication_identity": dict(self.publication_identity or {}),
        }


@dataclass(frozen=True)
class W5AdmissionRuntime:
    """Actual per-backend policy/pin inputs used by the generic arm adapter."""

    policy_by_backend: Mapping[str, BodyProjectionPolicy]
    pin_by_backend: Mapping[str, PublicationPin]
    frozen_policy_digest: str | None = None
    _policy_digests: Mapping[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.validate()
        object.__setattr__(self, "_policy_digests", MappingProxyType({
            backend: str(policy.policy_digest()) for backend, policy in self.policy_by_backend.items()
        }))

    def validate(self) -> W5AdmissionRuntime:
        if not self.policy_by_backend or set(self.policy_by_backend) != set(self.pin_by_backend):
            raise AdmissionVerificationError("w5_admission_backend_inputs_incomplete")
        for backend, policy in self.policy_by_backend.items():
            if backend not in {"sqlite", "postgresql"} or not isinstance(policy, BodyProjectionPolicy):
                raise AdmissionVerificationError("w5_admission_policy_input_invalid")
            policy.validate()
            pin = self.pin_by_backend[backend]
            if not all(hasattr(pin, name) for name in (
                "graph_id", "backend", "run_id", "generation", "policy_digest",
                "admitted_public_bindings", "denied_bindings",
            )) or not callable(getattr(pin, "revalidate_current", None)):
                raise AdmissionVerificationError("w5_admission_pin_input_invalid")
        if self.frozen_policy_digest is not None and (
            type(self.frozen_policy_digest) is not str or not self.frozen_policy_digest
        ):
            raise AdmissionVerificationError("w5_admission_frozen_policy_digest_invalid")
        return self

    def admit(self, arm_id: str, task: Any, *, observed_backend: str) -> W5AdmissionDecision:
        self.validate()
        target_backend = target_backend_for_arm(arm_id)
        pin = self.pin_by_backend[target_backend]
        if getattr(pin, "backend", None) != target_backend:
            raise AdmissionVerificationError("w5_admission_pin_backend_mismatch")
        frozen_digest = self._policy_digests[target_backend]
        if self.frozen_policy_digest is not None and self.frozen_policy_digest != frozen_digest:
            raise AdmissionVerificationError("frozen_policy_digest_mismatch")
        from retrieval_evaluation_admission_w5 import admit_w5_task
        return admit_w5_task(
            task, policy=self.policy_by_backend[target_backend],
            publication_pin=pin, observed_backend=observed_backend,
            frozen_policy_digest=frozen_digest,
        )


def target_backend_for_arm(arm_id: str) -> str:
    if arm_id == "native_tools_baseline" or arm_id.endswith(":sqlite"):
        return "sqlite"
    if arm_id.endswith(":postgresql"):
        return "postgresql"
    raise AdmissionVerificationError("unsupported_w5_admission_arm")


__all__ = [
    "AdmissionState", "AdmissionVerificationError", "BindingAdmission", "BindingDisposition",
    "PublicationPin", "W5AdmissionDecision", "W5AdmissionRuntime", "W5_ADMISSION_SCHEMA",
    "target_backend_for_arm",
]
