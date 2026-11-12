"""Learned cells: retained decisions, blocked arms, no completion without verified metrics, old-batch status."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import repomap_test_support.w5_public_text_learned as learned
from common_lore_index.storage.semantic_candidates import CandidatePublication, EmbeddingProfile
from repomap_test_support.w5_experiment_postgres import PostgresHandle
from repomap_test_support.w5_public_text_learned import LearnedGeneration, learned_cells, old_batch_status, profiles
from repomap_test_support.w5_public_text_postgres import StudyRead
from retrieval_evaluation_execution import TaskOutcome
from retrieval_public_text_census import PublicTextCensus
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_public_text_report_cells import LEARNED_ARMS, validate_cell
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import StudyGenerationSeal
from retrieval_public_text_study_catalog import StudyCatalog
from retrieval_public_text_study_schema import StudyEmbeddingProfile, StudyNames
from retrieval_public_text_tasks import load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_provenance import VerifiedPublicationPin

REPO = Path(__file__).resolve().parents[5]
CATALOG = REPO / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json"
D = "sha256:" + "d" * 64


@pytest.fixture(scope="module")
def task() -> Any:
    return load_selected_calibration_tasks(CATALOG, registered_task_pins()).tasks[0]


def _context(task: Any, *, v1: tuple[str, str | None], ptx: tuple[str, str | None], v1_capability: str = "complete",
             imported: frozenset[str] = frozenset({ARM_V1, ARM_PTX})) -> LearnedGeneration:
    census = SimpleNamespace(tasks=[SimpleNamespace(task_id=task.task_id, v1_learned_state=v1[0],
                                                    v1_learned_reason=v1[1], public_text_state=ptx[0],
                                                    public_text_reason=ptx[1])])
    arms = {ARM_V1: SimpleNamespace(capability=v1_capability, records=(), publication_coverage="complete"),
            ARM_PTX: SimpleNamespace(capability="complete", records=(), publication_coverage="partial")}
    seal = cast(StudyGenerationSeal, SimpleNamespace(generation=task.generation, arms=arms))
    return LearnedGeneration(
        cast(PostgresHandle, None), cast(StudyCatalog, None), seal, cast(VerifiedPublicationPin, None),
        cast(CandidatePublication, None), cast(PublicGenerationInput, None), cast(PublicTextPreparation, None),
        cast(PublicTextCensus, census), cast(PrivateMarkerScope, None), imported, profiles(D))


def test_profiles_bind_the_production_v1_fields_and_the_study_v2_profile() -> None:
    values = profiles(D)
    assert type(values[ARM_V1]) is EmbeddingProfile and type(values[ARM_PTX]) is StudyEmbeddingProfile
    assert values[ARM_V1].model == values[ARM_PTX].model == "BAAI/bge-small-en-v1.5"
    assert values[ARM_PTX].representation_version == ARM_PTX


def test_non_admitted_decisions_are_retained_for_every_kind(task: Any) -> None:
    cells = learned_cells(_context(task, v1=("refused", "unsupported_semantic_query_mode"),
                                   ptx=("unavailable", None)), task, 2, lexical=cast(TaskOutcome, None))
    assert [c["arm"] for c in cells] == list(LEARNED_ARMS)
    for value in cells:
        validate_cell(value)
        assert value["metrics"] is None and value["file_grading"]["state"] == "not_run"
    assert {c["state"] for c in cells[:3]} == {"refused"} and {c["state"] for c in cells[3:]} == {"unavailable"}
    assert cells[0]["reason"] == {"source": "v1_decision", "code": "unsupported_semantic_query_mode"}
    assert cells[3]["reason"] == {"source": "public_text_decision", "code": "unavailable"}


def test_refused_or_unimported_admitted_arms_never_run_sql(task: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no SQL may run for a blocked arm")

    monkeypatch.setattr(learned, "exact_read", forbidden)
    monkeypatch.setattr(learned, "observe_ann", forbidden)
    context = _context(task, v1=("admitted", None), ptx=("admitted", None), v1_capability="refused",
                       imported=frozenset({ARM_V1}))
    cells = learned_cells(context, task, 1, lexical=cast(TaskOutcome, None))
    for value in cells:
        validate_cell(value)
    assert all(c["state"] == "refused" and c["reason"] == {"source": "study", "code": "v1_own_record_truncated"}
               for c in cells[:3])
    assert all(c["state"] == "failed" and c["reason"] == {"source": "study", "code": "study_import_refused"}
               for c in cells[3:])


def test_a_completed_cell_without_verified_metrics_is_an_invariant_failure(task: Any) -> None:
    context = _context(task, v1=("admitted", None), ptx=("admitted", None))
    outcome = learned._Outcome("completed", None, ({"row": 1},))
    with pytest.raises(RuntimeError):
        learned._cell(task, "exact_vector", ARM_V1, 1, outcome, None, context)
    plan = learned._plan([cast(StudyRead, SimpleNamespace(plan_sha256=D, plan_length=4, index_selected=False))])
    assert plan["index_selected"] is False and plan["length"] == 4


@pytest.mark.parametrize("raw,expected", [
    ('{"batch_present":true,"current":false}', "imported_non_current"),
    ('{"batch_present":false,"current":false}', "not_imported_non_current"),
])
def test_old_batch_status_is_a_no_vector_observation(monkeypatch: pytest.MonkeyPatch, raw: str, expected: str) -> None:
    seen: list[str] = []
    monkeypatch.setattr(learned, "accepted_candidate_publication_sql", lambda _publication: "accepted AS (SELECT 1)")
    def record_sql(_pg: object, sql: str) -> str:
        seen.append(sql)
        return raw

    monkeypatch.setattr(learned, "run_study_sql", record_sql)
    catalog = cast(StudyCatalog, SimpleNamespace(names=StudyNames(D)))
    status, digest = old_batch_status(
        cast(PostgresHandle, None), catalog, cast(CandidatePublication, None),
        "ptx1-g1-ptx-0123456789abcdef")
    assert status == expected and digest.startswith("sha256:")
    assert "embedding" not in seen[0] and "<=>" not in seen[0] and seen[0].startswith('SET ROLE "')


@pytest.mark.parametrize("raw", ['{"batch_present":true,"current":true}', '{"batch_present":1,"current":false}',
                                 '[]', '{"current":false}'])
def test_old_batch_status_refuses_a_current_or_malformed_readback(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setattr(learned, "accepted_candidate_publication_sql", lambda _publication: "accepted AS (SELECT 1)")
    monkeypatch.setattr(learned, "run_study_sql", lambda _pg, _sql: raw)
    with pytest.raises(ValueError):
        old_batch_status(cast(PostgresHandle, None), cast(StudyCatalog, SimpleNamespace(names=StudyNames(D))),
                         cast(CandidatePublication, None), "ptx1-g1-ptx-0123456789abcdef")
