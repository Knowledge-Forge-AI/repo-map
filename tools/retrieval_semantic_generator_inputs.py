"""Prepare accepted public metadata and calibration questions before model execution.

The calling evaluator owns the trusted store adapter. This module never treats
a caller's JSON privacy label or a previously saved receipt as current readback.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import json

from common_lore_index.graph.multi_source import graph_source_binding_id
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_generator_kernel import (
    SemanticKernelError,
    SemanticMode,
    SemanticText,
)
from retrieval_semantic_generator_kernel_validation import validated_inputs as _validate_inputs

from retrieval_semantic_provenance import (
    RepresentationValidationError,
    VerifiedPublicationPin,
    freeze_jsonable,
)
from retrieval_semantic_representation import (
    RepresentationValidationReport,
    VerifiedNodeRepresentation,
    encode_canonical_node_v1_bytes,
)

INPUT_POLICY = 'cloe-w5-public-generation-input-v1'
MAX_DOCUMENTS = 500
MAX_CALIBRATION_TASKS = 24


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RepresentationValidationError(code, 'generation input refused')


@dataclass(frozen=True)
class DocumentInput:
    record_id: str
    representation: VerifiedNodeRepresentation


@dataclass(frozen=True)
class QueryInputDecision:
    task_id: str
    task_sha256: str
    state: str
    reason: str | None
    record_id: str | None


@dataclass(frozen=True)
class PublicGenerationInput:
    """Immutable input, with scope gaps preserved independently of generation status."""

    provenance: VerifiedPublicationPin
    documents: tuple[DocumentInput, ...]
    query_decisions: tuple[QueryInputDecision, ...]
    records: tuple[SemanticText, ...]
    input_identity: str
    representation_report_identity: str
    partial_publication_coverage: bool
    excluded_representation_count: int
    truncated_representation_count: int
    _read_current: Callable[[], VerifiedPublicationPin] = field(repr=False, compare=False)
    _read_representations: Callable[[], RepresentationValidationReport] = field(repr=False, compare=False)
    _frozen_tasks: tuple[EvaluationTask, ...] = field(repr=False, compare=False)
    _tasks_identity: str = field(repr=False, compare=False)
    _content_identity: str = field(repr=False, compare=False)

    def require_current(self) -> None:
        """Re-read the pin and representation report before every downstream use.

        The callbacks are deliberately supplied by the evaluator/controller. This
        object does not pretend to make an arbitrary Python caller trustworthy; it
        does, however, detect ordinary ``dataclasses.replace`` drift by rebuilding
        the public manifest from fresh readback and frozen task values.
        """
        try:
            self.provenance.revalidate_current()
        except RepresentationValidationError:
            raise
        except Exception as exc:
            raise RepresentationValidationError('invalid_publication_readback', 'publication revalidation failed') from exc
        try:
            current = self._read_current()
        except RepresentationValidationError:
            raise
        except Exception as exc:
            raise RepresentationValidationError('invalid_publication_readback', 'publication readback failed') from exc
        _require(type(current) is VerifiedPublicationPin, 'invalid_publication_readback')
        try:
            current.revalidate_current()
        except RepresentationValidationError:
            raise
        except Exception as exc:
            raise RepresentationValidationError('invalid_publication_readback', 'publication revalidation failed') from exc
        _require(current.to_dict() == self.provenance.to_dict(), 'generation_publication_advanced')
        try:
            report = self._read_representations()
        except RepresentationValidationError:
            raise
        except Exception as exc:
            raise RepresentationValidationError('invalid_representation_readback', 'representation readback failed') from exc
        _validate_report(report)
        _require(report.provenance.to_dict() == current.to_dict(), 'generation_publication_advanced')
        report_identity = _digest(report.to_dict())
        _require(report_identity == self.representation_report_identity, 'generation_representation_advanced')
        _require(_tasks_identity(self._frozen_tasks) == self._tasks_identity, 'generation_task_snapshot_changed')
        rebuilt = _build_content(report, current, self._frozen_tasks)
        _require(rebuilt[-1] == self._content_identity, 'generation_input_changed')
        try:
            current_identity = _content_identity(self)
        except Exception as exc:
            raise RepresentationValidationError('generation_input_changed', 'public input bundle drifted') from exc
        _require(current_identity == self._content_identity, 'generation_input_changed')


def _query_decision(task: EvaluationTask, pin: VerifiedPublicationPin) -> QueryInputDecision:
    _validated_task(task)
    _require(task.split == 'calibration', 'held_out_execution_forbidden')
    _require(task.graph_id == pin.graph_id, 'graph_id_mismatch')
    _require(type(task.generation) is int and task.generation == pin.generation, 'generation_mismatch')
    task_identity = _digest(task.to_dict())
    _require(all(type(binding) is str and bool(binding.strip()) for binding in task.selected_bindings),
             'invalid_task_binding_scope')
    selected = tuple(binding if binding.startswith('bind1:') else graph_source_binding_id(task.graph_id, binding)
                     for binding in task.selected_bindings)
    _require(bool(selected) and len(set(selected)) == len(selected), 'invalid_task_binding_scope')
    for binding in selected:
        if binding in pin.denied_bindings:
            return QueryInputDecision(task.task_id, task_identity, 'refused', pin.denied_bindings[binding], None)
        if binding not in pin.admitted_public_bindings:
            return QueryInputDecision(task.task_id, task_identity, 'refused', 'unknown_source_binding', None)
    if task.comparability_stratum != 'metadata' or task.intended_match_surface == 'captured_text':
        return QueryInputDecision(task.task_id, task_identity, 'unavailable', 'metadata_representation_not_comparable', None)
    if task.requested_mode != 'ranked_discovery':
        return QueryInputDecision(task.task_id, task_identity, 'unavailable', 'unsupported_semantic_query_mode', None)
    if task.grading_rule not in {'ranked_positive', 'absent_answer'}:
        return QueryInputDecision(task.task_id, task_identity, 'unavailable', 'unsupported_semantic_task_rule', None)
    return QueryInputDecision(task.task_id, task_identity, 'admitted', None, 'query:' + task.task_id)


def prepare_public_generation_input(
    report: RepresentationValidationReport,
    tasks: Sequence[EvaluationTask],
    *,
    read_current: Callable[[], VerifiedPublicationPin],
    read_representations: Callable[[], RepresentationValidationReport],
) -> PublicGenerationInput:
    """Validate every document and task before exposing any record to a kernel.

The reader must perform fresh IO through the evaluator's trusted storage
adapter. A constant receipt-returning lambda does not satisfy that boundary.
Selection contains only the already approved calibration tasks for one current
fixture generation. Inapplicable/refused tasks remain in the decision ledger.
"""
    _require(callable(read_current), 'missing_publication_reader')
    _require(callable(read_representations), 'missing_representation_reader')
    try:
        pin = read_current()
    except RepresentationValidationError:
        raise
    except Exception as exc:
        raise RepresentationValidationError('invalid_publication_readback', 'publication readback failed') from exc
    _require(type(pin) is VerifiedPublicationPin, 'invalid_publication_readback')
    try:
        pin.revalidate_current()
    except RepresentationValidationError:
        raise
    except Exception as exc:
        raise RepresentationValidationError('invalid_publication_readback', 'publication revalidation failed') from exc
    try:
        fresh_report = read_representations()
    except RepresentationValidationError:
        raise
    except Exception as exc:
        raise RepresentationValidationError('invalid_representation_readback', 'representation readback failed') from exc
    _validate_report(fresh_report)
    _require(type(report) is RepresentationValidationReport, 'unverified_representation_report')
    _require(_digest(report.to_dict()) == _digest(fresh_report.to_dict()), 'generation_representation_advanced')
    report = fresh_report
    _require(pin.to_dict() == report.provenance.to_dict(), 'generation_publication_advanced')
    try:
        frozen_tasks = tuple(_freeze_task(task) for task in tasks)
    except (KeyError, TypeError, ValueError, RepresentationValidationError) as exc:
        if isinstance(exc, RepresentationValidationError):
            raise
        raise RepresentationValidationError('invalid_generation_task', 'calibration task refused') from exc
    _require(len(frozen_tasks) <= MAX_CALIBRATION_TASKS, 'invalid_generation_task_count')
    _require(len({task.task_id for task in frozen_tasks}) == len(frozen_tasks), 'duplicate_calibration_task')
    content = _build_content(report, pin, frozen_tasks)
    documents, decisions, records, input_identity, report_identity, partial, excluded_count, truncated_count, content_identity = content
    bundle = PublicGenerationInput(
        pin, documents, decisions, records, input_identity, report_identity, partial,
        excluded_count, truncated_count, read_current, read_representations,
        frozen_tasks, _tasks_identity(frozen_tasks), content_identity,
    )
    bundle.require_current()
    return bundle


def _validated_task(task: EvaluationTask) -> EvaluationTask:
    _require(type(task) is EvaluationTask, 'invalid_generation_task')
    try:
        task.validate()
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationValidationError('invalid_generation_task', 'calibration task refused') from exc
    return task


def _freeze_task(task: EvaluationTask) -> EvaluationTask:
    validated = _validated_task(task)
    return replace(
        validated,
        permitted_query_plan=freeze_jsonable(dict(validated.permitted_query_plan)),
        selected_bindings=tuple(validated.selected_bindings),
        comparator_exposure=freeze_jsonable(dict(validated.comparator_exposure)),
        gold_targets=tuple(validated.gold_targets),
    )


def _tasks_identity(tasks: Sequence[EvaluationTask]) -> str:
    return _digest([task.to_dict() for task in tasks])


def _validate_report(report: RepresentationValidationReport) -> None:
    _require(type(report) is RepresentationValidationReport and report.status == 'ok', 'unverified_representation_report')
    _require(report.refusal_code is None, 'unverified_representation_report')
    _require(type(report.verified_entries) is tuple, 'unverified_representation_report')
    _require(type(report.excluded_entries) is tuple, 'unverified_representation_report')
    _require(type(report.partial_coverage) is bool and type(report.truncated) is bool,
             'invalid_representation_coverage')
    _require(type(report.total_eligible_count) is int and report.total_eligible_count >= len(report.verified_entries),
             'invalid_representation_coverage')
    _require(type(report.coverage_ceiling) is int and 1 <= report.coverage_ceiling <= MAX_DOCUMENTS,
             'invalid_representation_coverage')
    _require(1 <= len(report.verified_entries) <= min(MAX_DOCUMENTS, report.coverage_ceiling),
             'invalid_generation_document_count')
    expected_truncated = report.total_eligible_count > len(report.verified_entries)
    _require(report.truncated is expected_truncated, 'invalid_representation_coverage')
    _require(report.partial_coverage is (expected_truncated or bool(report.excluded_entries)),
             'invalid_representation_coverage')
    _require(type(report.provenance) is VerifiedPublicationPin, 'invalid_publication_readback')


def _build_content(
    report: RepresentationValidationReport,
    pin: VerifiedPublicationPin,
    tasks: Sequence[EvaluationTask],
) -> tuple[tuple[DocumentInput, ...], tuple[QueryInputDecision, ...], tuple[SemanticText, ...], str, str, bool, int, int, str]:
    _validate_report(report)
    _require(pin.to_dict() == report.provenance.to_dict(), 'generation_publication_advanced')
    _require(len(tasks) <= MAX_CALIBRATION_TASKS, 'invalid_generation_task_count')
    documents: list[DocumentInput] = []
    records: list[SemanticText] = []
    identities: set[tuple[str, str]] = set()
    snapshots = pin.snapshot_by_binding()
    for representation in report.verified_entries:
        pair = (representation.canonical_key, representation.source_binding_id)
        _require(pair not in identities, 'duplicate_representation_identity')
        identities.add(pair)
        _require(representation.source_binding_id in pin.admitted_public_bindings, 'binding_privacy_not_authorized')
        _require(snapshots.get(representation.source_binding_id) ==
                 (representation.binding_revision, representation.snapshot_id), 'snapshot_id_mismatch')
        encoded = encode_canonical_node_v1_bytes(representation.canonical_key, representation.kind,
                                                representation.display_name)
        _require(representation.input_digest == 'sha256:' + hashlib.sha256(encoded).hexdigest(),
                 'representation_digest_mismatch')
        _require(representation.representation_bytes_len == len(encoded), 'representation_size_mismatch')
        record_id = 'document:' + _digest(list(pair))[7:]
        documents.append(DocumentInput(record_id, representation))
        records.append(SemanticText(record_id, encoded.decode('utf-8'), SemanticMode.DOCUMENT))
    decisions: list[QueryInputDecision] = []
    task_ids: set[str] = set()
    for task in tasks:
        _validated_task(task)
        _require(task.task_id not in task_ids, 'duplicate_calibration_task')
        task_ids.add(task.task_id)
        decision = _query_decision(task, pin)
        decisions.append(decision)
        if decision.record_id is not None:
            records.append(SemanticText(decision.record_id, task.question, SemanticMode.QUERY))
    # A kernel invocation has the same total 500-record ceiling. Queries are
    # separate requests when the document batch already fills that ceiling.
    _require(len(records) <= 500, 'generation_batch_requires_explicit_partition')
    try:
        validated = _validate_inputs(tuple(records))
    except SemanticKernelError as exc:
        raise RepresentationValidationError(exc.code, 'generation input refused') from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationValidationError('invalid_generation_input', 'generation input refused') from exc
    records = list(validated[0])
    report_identity = _digest(report.to_dict())
    identity = _digest({'policy': INPUT_POLICY, 'publication': pin.to_dict(), 'representation_report': report_identity,
                        'records': [{'record_id': r.record_id, 'text_sha256': _digest(r.text), 'mode': SemanticMode(r.mode).value}
                                    for r in records],
                        'tasks': [decision.__dict__ for decision in decisions]})
    content_identity = _digest({
        'provenance': pin.to_dict(),
        'documents': [doc.representation.to_dict() for doc in documents],
        'queries': [decision.__dict__ for decision in decisions],
        'records': [{'record_id': record.record_id, 'text_sha256': _digest(record.text), 'mode': SemanticMode(record.mode).value}
                    for record in records],
        'input_identity': identity, 'representation_report_identity': report_identity,
        'partial_publication_coverage': report.partial_coverage,
        'excluded_representation_count': len(report.excluded_entries),
        'truncated_representation_count': max(0, report.total_eligible_count - len(report.verified_entries)) if report.truncated else 0,
    })
    return (
        tuple(documents), tuple(decisions), tuple(records), identity, report_identity,
        report.partial_coverage, len(report.excluded_entries),
        max(0, report.total_eligible_count - len(report.verified_entries)) if report.truncated else 0,
        content_identity,
    )


def _content_identity(bundle: PublicGenerationInput) -> str:
    return _digest({
        'provenance': bundle.provenance.to_dict(),
        'documents': [doc.representation.to_dict() for doc in bundle.documents],
        'queries': [decision.__dict__ for decision in bundle.query_decisions],
        'records': [{'record_id': record.record_id, 'text_sha256': _digest(record.text), 'mode': SemanticMode(record.mode).value}
                    for record in bundle.records],
        'input_identity': bundle.input_identity,
        'representation_report_identity': bundle.representation_report_identity,
        'partial_publication_coverage': bundle.partial_publication_coverage,
        'excluded_representation_count': bundle.excluded_representation_count,
        'truncated_representation_count': bundle.truncated_representation_count,
    })


def build_worker_request(
    inputs: PublicGenerationInput, *, attempt_id: str, artifact_profile_identity: str,
) -> dict[str, object]:
    """Build a data-only request after a final current-publication check.

    The isolated worker receives no store or socket. The calling evaluator
    archives this request and the whole source closure before launching it,
    then checks current readback again before sealing its response.
    """
    from retrieval_semantic_generator_worker import REQUEST_SCHEMA, parse_worker_request

    inputs.require_current()
    request: dict[str, object] = {
        'schema': REQUEST_SCHEMA, 'attempt_id': attempt_id,
        'input_identity': inputs.input_identity,
        'representation_report_identity': inputs.representation_report_identity,
        'publication_identity': _digest(inputs.provenance.to_dict()),
        'artifact_profile_identity': artifact_profile_identity,
        'records': [{'record_id': item.record_id, 'text': item.text,
                     'mode': SemanticMode(item.mode).value} for item in inputs.records],
    }
    parse_worker_request(json.dumps(request, sort_keys=True, allow_nan=False).encode('utf-8'))
    return request
