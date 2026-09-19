"""Shared immutable executor evidence types."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import importlib
import inspect
from pathlib import Path
import shutil
from types import CodeType

from repomap_test_support.test_cov5k_r2_fix2_catalog import ParameterTuple
from repomap_test_support.test_cov5k_r2_fix2_dynamic_targets import PYTHON_TARGETS
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_groupa_contract import (
    GroupAContractViolation,
    group_a_public_context,
    verify_group_a_contract,
    verify_parent_settlement_contract,
)


class ExecutorEvidenceError(ValueError):
    """Raised when observed enactment cannot satisfy frozen authority."""


@dataclass(frozen=True, slots=True)
class OwnerEntryEvidence:
    """Runtime proof that one exact owner was entered by one executor."""

    module_source_digest: str
    qualified_symbol: str
    code_object_identity: str
    executor_source_digest: str
    owner_entry_count: int
    scenario_seam_active: bool
    owner_source_path: str = ""
    owner_module: str = ""
    executor_source_path: str = ""
    executor_module: str = ""
    executor_qualified_symbol: str = ""
    owner_entry_during_operation: bool = False
    registered_owner_source_path: str = ""
    registered_owner_module: str = ""
    registered_owner_qualified_symbol: str = ""
    registered_owner_module_digest: str = ""
    registered_owner_code_object_identity: str = ""
    registered_executor_source_path: str = ""
    registered_executor_module: str = ""
    registered_executor_qualified_symbol: str = ""
    registered_executor_source_digest: str = ""


@dataclass(frozen=True, slots=True)
class ExecutorEvidence:
    """Unqualified rehearsal evidence produced by an enacted owner."""

    authority_id: str
    owner_entered: bool
    enacted_parameters: ParameterTuple
    observed_fields: tuple[tuple[str, object], ...]
    purpose: str = "qualification_executor_enactment_rehearsal"
    model_rehearsal_only: bool = True
    qualification_status: str = "unqualified"
    frozen_parameter_digest: str = ""
    observed_enacted_parameter_digest: str = ""
    owner_entry_evidence: OwnerEntryEvidence | None = None
    scenario_program_identity: str = ""
    observed_product_events: tuple[tuple[str, object], ...] = ()
    result_digest: str = ""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _module_name(source_path: str) -> str:
    prefixes = (
        "tools/",
        "src/main/python/",
        "src/test/support/python/",
    )
    for prefix in prefixes:
        if source_path.startswith(prefix):
            relative = source_path.removeprefix(prefix).removesuffix(".py")
            return relative.replace("/", ".")
    raise ExecutorEvidenceError("registered owner module path is unsupported")


def _resolve_symbol(module_name: str, symbol: str):
    if (module_name, symbol) not in PYTHON_TARGETS:
        raise ExecutorEvidenceError("registered symbol outside closed resolver domain")
    value = importlib.import_module(module_name)
    for part in symbol.split("."):
        value = getattr(value, part)
    return value


def _code_object_identity(code: CodeType) -> str:
    return _digest_bytes(
        b"\0".join(
            (
                str(Path(code.co_filename).resolve()).encode("utf-8"),
                code.co_qualname.encode("utf-8"),
                code.co_code,
            )
        )
    )


def _python_identity(source_path: str, symbol: str) -> tuple[str, str, str, str]:
    module_name = _module_name(source_path)
    path = _repository_root() / source_path
    source_digest = _digest_bytes(path.read_bytes())
    callable_owner = _resolve_symbol(module_name, symbol)
    code = getattr(callable_owner, "__code__", None)
    if code is None:
        raise ExecutorEvidenceError("registered callable has no Python code object")
    if _digest_bytes(path.read_bytes()) != source_digest:
        raise ExecutorEvidenceError("registered source changed during identity resolution")
    return (
        module_name,
        f"{module_name}.{symbol}",
        source_digest,
        _code_object_identity(code),
    )


def _external_identity(source_path: str) -> tuple[str, str, str, str]:
    executable = source_path.removeprefix("tool:").split(":", 1)[0]
    resolved = shutil.which(executable)
    if resolved is None:
        raise ExecutorEvidenceError("registered external executable is unavailable")
    path = Path(resolved).resolve()
    stat = path.stat()
    identity = _digest_bytes(
        f"{path.name}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}".encode("utf-8")
    )
    return "external", f"external:{path.name}", _digest_bytes(path.read_bytes()), identity


def _registered_owner_evidence(entry, owner: OwnerEntryEvidence) -> OwnerEntryEvidence:
    source_path = entry.owner.source_path
    runtime_symbol = entry.owner.registered_runtime_symbol
    if source_path.startswith("tool:"):
        module, qualified, digest, code_identity = _external_identity(source_path)
    else:
        module, qualified, digest, code_identity = _python_identity(
            source_path, runtime_symbol
        )
    executor_module, executor_qualified, _module_digest, _code_identity = _python_identity(
        entry.executor_source_path, entry.executor_symbol
    )
    executor = _resolve_symbol(executor_module, entry.executor_symbol)
    return replace(
        owner,
        registered_owner_source_path=source_path,
        registered_owner_module=module,
        registered_owner_qualified_symbol=qualified,
        registered_owner_module_digest=digest,
        registered_owner_code_object_identity=code_identity,
        registered_executor_source_path=entry.executor_source_path,
        registered_executor_module=executor_module,
        registered_executor_qualified_symbol=executor_qualified,
        registered_executor_source_digest=_digest_bytes(
            inspect.getsource(executor).encode("utf-8")
        ),
    )


def _verify_registered_owner(owner: OwnerEntryEvidence) -> None:
    if owner.owner_source_path != owner.registered_owner_source_path:
        raise ExecutorEvidenceError("runtime owner source path differs from registered owner")
    if owner.owner_module != owner.registered_owner_module:
        raise ExecutorEvidenceError("runtime owner module differs from registered owner")
    if owner.qualified_symbol != owner.registered_owner_qualified_symbol:
        raise ExecutorEvidenceError("runtime owner qualified symbol differs from registered owner")
    if owner.module_source_digest != owner.registered_owner_module_digest:
        raise ExecutorEvidenceError("runtime owner module digest differs from registered owner")
    if owner.code_object_identity != owner.registered_owner_code_object_identity:
        raise ExecutorEvidenceError("runtime owner code object differs from registered owner")
    if owner.executor_source_path != owner.registered_executor_source_path:
        raise ExecutorEvidenceError("runtime executor source path differs from registered executor")
    if owner.executor_module != owner.registered_executor_module:
        raise ExecutorEvidenceError("runtime executor module differs from registered executor")
    if owner.executor_qualified_symbol != owner.registered_executor_qualified_symbol:
        raise ExecutorEvidenceError("runtime executor qualified symbol differs from registered executor")
    if owner.executor_source_digest != owner.registered_executor_source_digest:
        raise ExecutorEvidenceError("runtime executor source digest differs from registered executor")
    if not owner.owner_entry_during_operation:
        raise ExecutorEvidenceError("registered owner was entered outside the case operation")


def _verify_owner_observations(evidence: ExecutorEvidence) -> None:
    observed = dict(evidence.observed_fields)
    events = evidence.observed_product_events
    if "observed_stage_source" in observed:
        if observed["observed_stage_source"] != "owner_event":
            raise ExecutorEvidenceError("observed stage is not sourced from an owner event")
        owner_stages = {value for name, value in events if name == "owner_stage"}
        if observed.get("observed_stage") not in owner_stages:
            raise ExecutorEvidenceError("observed stage is absent from owner events")
    if "context_program_id" in observed:
        if not observed.get("context_condition_started"):
            raise ExecutorEvidenceError("terminal context was not started")
        if not observed.get("context_condition_observed_during_owner"):
            raise ExecutorEvidenceError("terminal context was not observed during owner execution")
        program_id = observed["context_program_id"]
        if ("context_condition_started", program_id) not in events:
            raise ExecutorEvidenceError("terminal context start is absent from owner events")
        if not any(name == "context_condition_observed" for name, _value in events):
            raise ExecutorEvidenceError("terminal context observation is absent from owner events")
        if not observed.get("observed_context"):
            raise ExecutorEvidenceError("terminal observed context is absent")
        if ("context_cleanup", "completed") not in events:
            raise ExecutorEvidenceError("terminal context cleanup is unproved")


def bind_executor_evidence(
    entry,
    *,
    enacted_parameters: ParameterTuple,
    observed_fields: tuple[tuple[str, object], ...],
    owner_entry_evidence: OwnerEntryEvidence,
    scenario_program_identity: str,
    observed_product_events: tuple[tuple[str, object], ...],
) -> ExecutorEvidence:
    """Bind separate frozen and product-observed parameter authorities."""

    owner_entry_evidence = _registered_owner_evidence(entry, owner_entry_evidence)
    _verify_registered_owner(owner_entry_evidence)
    frozen_digest = canonical_digest(entry.parameter_values)
    enacted_digest = canonical_digest(enacted_parameters)
    if enacted_parameters is entry.parameter_values:
        raise ExecutorEvidenceError("enacted parameters reuse frozen tuple authority")
    if enacted_digest != frozen_digest:
        raise ExecutorEvidenceError("observed enacted parameters differ from frozen parameters")
    if owner_entry_evidence.owner_entry_count < 1:
        raise ExecutorEvidenceError("registered owner was not entered")
    if not owner_entry_evidence.scenario_seam_active:
        raise ExecutorEvidenceError("registered scenario seam was not active")
    if not scenario_program_identity or not observed_product_events:
        raise ExecutorEvidenceError("scenario identity or product events are absent")
    result_digest = canonical_digest(
        {
            "authority_id": entry.authority_id,
            "frozen_parameter_digest": frozen_digest,
            "observed_enacted_parameter_digest": enacted_digest,
            "owner": owner_entry_evidence,
            "scenario_program_identity": scenario_program_identity,
            "observed_product_events": observed_product_events,
            "observed_fields": observed_fields,
        }
    )
    return ExecutorEvidence(
        entry.authority_id,
        True,
        enacted_parameters,
        observed_fields,
        frozen_parameter_digest=frozen_digest,
        observed_enacted_parameter_digest=enacted_digest,
        owner_entry_evidence=owner_entry_evidence,
        scenario_program_identity=scenario_program_identity,
        observed_product_events=observed_product_events,
        result_digest=result_digest,
    )


def verify_executor_evidence(entry, evidence: ExecutorEvidence) -> None:
    """Recompute all independent enactment bindings for one result."""

    frozen_digest = canonical_digest(entry.parameter_values)
    enacted_digest = canonical_digest(evidence.enacted_parameters)
    if evidence.frozen_parameter_digest != frozen_digest:
        raise ExecutorEvidenceError("frozen parameter digest differs from catalog")
    if evidence.observed_enacted_parameter_digest != enacted_digest:
        raise ExecutorEvidenceError("enacted parameter digest differs from observation")
    if enacted_digest != frozen_digest:
        raise ExecutorEvidenceError("observed enacted parameters differ from frozen parameters")
    owner = evidence.owner_entry_evidence
    if owner is None or owner.owner_entry_count < 1:
        raise ExecutorEvidenceError("registered owner was not entered")
    if not owner.scenario_seam_active:
        raise ExecutorEvidenceError("registered scenario seam was not active")
    expected_owner = _registered_owner_evidence(entry, owner)
    _verify_registered_owner(expected_owner)
    if owner != expected_owner:
        raise ExecutorEvidenceError("registered owner binding differs from catalog")
    if not all(
        (
            owner.module_source_digest,
            owner.qualified_symbol,
            owner.code_object_identity,
            owner.executor_source_digest,
            evidence.scenario_program_identity,
        )
    ):
        raise ExecutorEvidenceError("owner or scenario identity is incomplete")
    if evidence.scenario_program_identity in {
        entry.authority_id,
        entry.case_id,
        entry.condition_id,
    }:
        raise ExecutorEvidenceError("scenario identity is derived from a catalog label")
    if not evidence.observed_product_events:
        raise ExecutorEvidenceError("observed product events are absent")
    _verify_owner_observations(evidence)
    contract_verifier = None
    context_label = ""
    if entry.semantic_group == "A":
        contract_verifier = verify_group_a_contract
        context_label = "group_a_context"
    elif entry.semantic_group == "PARENT_SETTLEMENT":
        contract_verifier = verify_parent_settlement_contract
        context_label = "settlement_context"
    if contract_verifier is not None:
        try:
            contract_verifier(entry, evidence)
        except GroupAContractViolation as error:
            context = group_a_public_context(evidence)
            raise ExecutorEvidenceError(
                f"{error}; {context_label}={context}"
            ) from error
    expected_result_digest = canonical_digest(
        {
            "authority_id": entry.authority_id,
            "frozen_parameter_digest": frozen_digest,
            "observed_enacted_parameter_digest": enacted_digest,
            "owner": owner,
            "scenario_program_identity": evidence.scenario_program_identity,
            "observed_product_events": evidence.observed_product_events,
            "observed_fields": evidence.observed_fields,
        }
    )
    if evidence.result_digest != expected_result_digest:
        raise ExecutorEvidenceError("result digest differs from bound evidence")
# v0.0.2 dynamic target re-attestation.
