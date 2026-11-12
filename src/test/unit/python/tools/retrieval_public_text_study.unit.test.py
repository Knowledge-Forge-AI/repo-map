"""Driver transitions: injected failure at each state, cleanup once after ownership, truthful receipt, no retry.

External backends are replaced at the driver's module boundary only; the real
declaration (registered pins, catalog, closures, study identity) runs. The
complete successful path is the pgvector functional lifecycle owner.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import repomap_test_support.w5_public_text_study as study
from repomap_test_support.w5_public_text_journal import FAILURE_NAME
from repomap_test_support.w5_public_text_postgres import CleanupResult
from retrieval_public_text_request import ARM_PTX, ARM_V1

REPO = Path(__file__).resolve().parents[5]
COUNTS = {"v1.document": 3, "ptx.document": 2, "v1.query": 1, "ptx.query": 1}


class _Recorder:
    def __init__(self) -> None:
        self.calls: dict[str, list[Any]] = {}

    def record(self, name: str, result: Any = None, error: Exception | None = None):
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.setdefault(name, []).append((args, kwargs))
            if error is not None:
                raise error
            return result
        return call

    def count(self, name: str) -> int:
        return len(self.calls.get(name, []))


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    recorder = _Recorder()
    root = tmp_path.resolve()
    clean = CleanupResult("clean", None, ({"kind": "batch", "absent": True}, {"kind": "entry", "absent": True}))
    for name, value in (("apply_migrations", None), ("install_candidate_schema", None),
                        ("cleanup_study", clean), ("emit_attempt_artifacts", None), ("emit_private_evidence", None)):
        monkeypatch.setattr(study, name, recorder.record(name, value))
    prepared = SimpleNamespace(request_raw=b"{}", pin="pin", v1="v1", preparation="preparation", refresh=lambda: None,
                               dual=SimpleNamespace(manifest=lambda: {"partitions": dict(COUNTS)}))
    monkeypatch.setattr(study, "materialize_generation", recorder.record("materialize_generation", SimpleNamespace()))
    monkeypatch.setattr(study, "prepare_generation_inputs", recorder.record("prepare_generation_inputs", prepared))
    monkeypatch.setattr(study, "require_unchanged", recorder.record("require_unchanged"))
    env = study.StudyEnvironment(database=SimpleNamespace(psql_args=[], psql_command="psql"), repo_root=REPO,
                                 workspace=root / "workspace", journal_root=root / "journals",
                                 report_root=root / "report", functional_only=True)
    return SimpleNamespace(recorder=recorder, env=env, monkeypatch=monkeypatch, root=root)


def _receipt(env: Any) -> dict[str, Any]:
    return json.loads((env.report_root / FAILURE_NAME).read_bytes())


def _assert_failed(outcome: Any, env: Any, state: str, code: str) -> dict[str, Any]:
    assert (outcome.state, outcome.failure_code) == (state, code)
    assert outcome.report_identity is None and outcome.verification is None and outcome.native_reservations == 0
    assert not (env.report_root / study.REPORT_NAME).exists()
    receipt = _receipt(env)
    assert (receipt["stop_state"], receipt["failure_code"], receipt["functional_only"]) == (state, code, True)
    assert (receipt["planned_cells"], receipt["observed_cells"], receipt["unknown_cells"]) == (864, 0, 864)
    assert outcome.failure_receipt_sha256 is not None and outcome.transition is None
    return receipt


def test_declaration_refusal_precedes_any_cluster_or_cleanup(harness) -> None:
    harness.monkeypatch.setattr(study, "load_selected_calibration_tasks",
                                harness.recorder.record("load", error=ValueError("bad pins")))
    outcome = study.run_public_text_study(harness.env)
    receipt = _assert_failed(outcome, harness.env, "DECLARED", "study_declaration_refused")
    assert receipt["study_identity"] is None and receipt["cleanup"] == {"status": "not_run",
                                                                        "reason": "cleanup_not_reached"}
    assert harness.recorder.count("apply_migrations") == harness.recorder.count("cleanup_study") == 0


def test_cluster_failure_has_no_owned_objects_to_clean(harness) -> None:
    harness.monkeypatch.setattr(study, "apply_migrations", harness.recorder.record("migrate", error=OSError("x")))
    outcome = study.run_public_text_study(harness.env)
    receipt = _assert_failed(outcome, harness.env, "CLUSTER_READY", "cluster_setup_failed")
    assert receipt["study_identity"] is not None and receipt["components"] == []
    assert harness.recorder.count("cleanup_study") == 0


@pytest.mark.parametrize("target,state,code", [
    ("materialize_generation", "G1_PUBLISHED", "publication_failed"),
    ("prepare_generation_inputs", "G1_PREPARED", "preparation_refused"),
    ("require_unchanged", "G1_FROZEN", "source_changed"),
])
def test_each_pre_worker_transition_fails_closed_and_cleans_once(harness, target: str, state: str, code: str) -> None:
    harness.monkeypatch.setattr(study, target, harness.recorder.record(target, error=RuntimeError("private detail")))
    outcome = study.run_public_text_study(harness.env)
    receipt = _assert_failed(outcome, harness.env, state, code)
    assert harness.recorder.count("cleanup_study") == 1
    assert harness.recorder.calls["cleanup_study"][0][0][2] is None
    assert harness.recorder.count(target) == 1 and harness.recorder.count("materialize_generation") <= 1
    assert "private detail" not in json.dumps(receipt) and receipt["cleanup"]["status"] == "clean"


def test_exchange_refusal_writes_no_journal_and_no_component(harness) -> None:
    harness.monkeypatch.setattr(study.ComponentExchange, "publish_request",
                                harness.recorder.record("publish", error=RuntimeError("bridge")))
    outcome = study.run_public_text_study(harness.env)
    receipt = _assert_failed(outcome, harness.env, "G1_WORKER", "exchange_refused")
    assert receipt["components"] == [] and not (harness.env.journal_root / "w5-semantic-g1").exists()
    assert harness.recorder.count("emit_attempt_artifacts") == 0 and outcome.frame_sha256 == ()


def _sealed(harness) -> None:
    def exchange(self: Any, generation: int, proof: Any) -> None:
        self.gens[generation].response = object()

    harness.monkeypatch.setattr(study._Driver, "exchange", exchange)
    seal = SimpleNamespace(arms={ARM_V1: SimpleNamespace(capability="complete"),
                                 ARM_PTX: SimpleNamespace(capability="complete")})
    harness.monkeypatch.setattr(study, "seal_dual_arm_result", harness.recorder.record("seal", seal))


def test_seal_refusal_stops_before_any_table(harness) -> None:
    _sealed(harness)
    harness.monkeypatch.setattr(study, "seal_dual_arm_result", harness.recorder.record("seal", error=ValueError()))
    harness.monkeypatch.setattr(study, "create_study_relations", harness.recorder.record("create"))
    _assert_failed(study.run_public_text_study(harness.env), harness.env, "G1_SEALED", "seal_refused")
    assert harness.recorder.count("create") == 0 and harness.recorder.calls["cleanup_study"][0][0][2] is None


def test_table_creation_failure_cleans_without_an_unknown_catalog(harness) -> None:
    _sealed(harness)
    harness.monkeypatch.setattr(study, "create_study_relations", harness.recorder.record("create", error=OSError()))
    _assert_failed(study.run_public_text_study(harness.env), harness.env, "TABLES_CREATED", "sql_failed")
    assert harness.recorder.count("cleanup_study") == 1 and harness.recorder.calls["cleanup_study"][0][0][2] is None


def test_import_failure_after_creation_cleans_the_recorded_catalog_exactly_once(harness) -> None:
    _sealed(harness)
    catalog = SimpleNamespace(names="names")
    harness.monkeypatch.setattr(study, "create_study_relations", harness.recorder.record("create", catalog))
    resources = SimpleNamespace(candidate_publication=lambda: "publication")
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("materialize", resources))
    harness.monkeypatch.setattr(study, "sealed_batch", harness.recorder.record("batch", error=ValueError("entry")))
    outcome = study.run_public_text_study(harness.env)
    _assert_failed(outcome, harness.env, "G1_IMPORTED", "sql_failed")
    assert harness.recorder.count("cleanup_study") == 1 and harness.recorder.calls["cleanup_study"][0][0][2] is catalog
    assert harness.recorder.count("materialize") == 1 and outcome.record_counts == {"1": COUNTS}


def test_a_dirty_cleanup_is_reported_beside_the_primary_failure(harness) -> None:
    dirty = CleanupResult("failed", "cleanup_failed:object_present", ({"kind": "batch", "absent": False},
                                                                       {"kind": "entry", "absent": True}))
    harness.monkeypatch.setattr(study, "cleanup_study", harness.recorder.record("cleanup_study", dirty))
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("m", error=OSError()))
    receipt = _assert_failed(study.run_public_text_study(harness.env), harness.env, "G1_PUBLISHED",
                             "publication_failed")
    assert receipt["cleanup"] == {"status": "failed", "reason": "cleanup_failed:object_present"}


def test_an_unreadable_cleanup_is_failed_not_clean(harness) -> None:
    harness.monkeypatch.setattr(study, "cleanup_study", harness.recorder.record("cleanup_study", error=OSError()))
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("m", error=OSError()))
    receipt = _assert_failed(study.run_public_text_study(harness.env), harness.env, "G1_PUBLISHED",
                             "publication_failed")
    assert receipt["cleanup"] == {"status": "failed", "reason": "cleanup_failed:readback_refused"}


def test_functional_flag_must_be_a_real_bool(harness) -> None:
    env = study.StudyEnvironment(**{**harness.env.__dict__, "functional_only": 1})
    with pytest.raises(TypeError):
        study.run_public_text_study(env)


def test_generation_one_failed_operation_keeps_second_generation_unstarted(harness) -> None:
    _sealed(harness)
    resources = SimpleNamespace(candidate_publication=lambda: "publication")
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("materialize", resources))
    harness.monkeypatch.setattr(study, "create_study_relations", harness.recorder.record("create", object()))
    harness.monkeypatch.setattr(study._Driver, "import_generation", lambda *args: None)

    def observed(self: Any, generation: int, actual: Any) -> None:
        assert generation == 1 and actual is resources
        self.cells.extend({} for _ in range(828))
        self.failed_operations = 1

    harness.monkeypatch.setattr(study._Driver, "observe", observed)
    outcome = study.run_public_text_study(harness.env)
    assert (outcome.state, outcome.failure_code, outcome.observed_cells) == ("G1_OBSERVED", "operation_failed", 828)
    assert harness.recorder.count("materialize") == 1 and harness.recorder.count("cleanup_study") == 1
    assert set(outcome.record_counts) == {"1"} and outcome.frame_sha256 == ()
    assert _receipt(harness.env)["unknown_cells"] == 36


@pytest.mark.parametrize("error", [RuntimeError("private unexpected failure"), KeyboardInterrupt(), SystemExit(2)])
def test_unexpected_failure_or_interrupt_still_cleans_once(harness, error: BaseException) -> None:
    def run(self: Any) -> None:
        self.declare()
        self.cluster_ready = True
        self.state = "G1_PUBLISHED"
        raise error

    harness.monkeypatch.setattr(study._Driver, "run", run)
    if isinstance(error, Exception):
        outcome = study.run_public_text_study(harness.env)
        _assert_failed(outcome, harness.env, "G1_PUBLISHED", "study_execution_failed")
    else:
        with pytest.raises(type(error)) as raised:
            study.run_public_text_study(harness.env)
        assert raised.value is error
        assert _receipt(harness.env)["failure_code"] == "study_interrupted"
        assert harness.recorder.count("emit_private_evidence") == 1
    assert harness.recorder.count("cleanup_study") == 1


def test_failure_receipt_error_keeps_primary_failure_and_independent_diagnostic(harness) -> None:
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("m", error=OSError()))
    harness.monkeypatch.setattr(study, "write_failure_receipt", harness.recorder.record("receipt", error=OSError()))
    outcome = study.run_public_text_study(harness.env)
    assert (outcome.state, outcome.failure_code) == ("G1_PUBLISHED", "publication_failed")
    assert outcome.failure_receipt_sha256 is None and outcome.diagnostic_errors == ("failure_receipt_write_failed",)
    assert harness.recorder.count("cleanup_study") == 1


def test_export_failure_cannot_replace_a_primary_failure(harness) -> None:
    harness.monkeypatch.setattr(study, "materialize_generation", harness.recorder.record("m", error=OSError()))
    harness.monkeypatch.setattr(study, "emit_private_evidence", harness.recorder.record("export", error=OSError()))
    outcome = study.run_public_text_study(harness.env)
    assert (outcome.state, outcome.failure_code) == ("G1_PUBLISHED", "publication_failed")
    assert outcome.failure_receipt_sha256 is not None
    assert outcome.diagnostic_errors == ("private_evidence_export_failed",)


def test_later_report_failure_is_a_whole_study_failure_after_clean_execution(harness) -> None:
    def observed(self: Any) -> None:
        self.declare()
        self.cluster_ready = True
        self.cells.extend({} for _ in range(864))
        self.gens[2].seal = object()

    harness.monkeypatch.setattr(study._Driver, "run", observed)
    harness.monkeypatch.setattr(study, "write_observed_report", harness.recorder.record("report", error=OSError()))
    outcome = study.run_public_text_study(harness.env)
    assert (outcome.state, outcome.failure_code, outcome.observed_cells) == ("REPORTED", "report_failed", 864)
    assert outcome.cleanup is not None and outcome.cleanup["status"] == "clean"
    assert harness.recorder.count("cleanup_study") == 1
    assert _receipt(harness.env)["unknown_cells"] == 0 and outcome.report_identity is None


def test_journal_and_framing_errors_remain_beside_the_primary_failure(harness) -> None:
    def broken(self):
        self.declare()
        self.cluster_ready = True
        self.gens[1].journal = SimpleNamespace(directory=harness.root / "actual-journal")
        raise study.StudyFailure("operation_failed", "G1_OBSERVED")

    harness.monkeypatch.setattr(study._Driver, "run", broken)
    harness.monkeypatch.setattr(study, "finish_component_journal", harness.recorder.record("finish", error=OSError()))
    harness.monkeypatch.setattr(study, "emit_attempt_artifacts", harness.recorder.record("frame", error=OSError()))
    outcome = study.run_public_text_study(harness.env)
    assert outcome.failure_code == "operation_failed" and outcome.state == "G1_OBSERVED"
    assert outcome.diagnostic_errors == ("journal_finish_failed", "journal_framing_failed")
    assert _receipt(harness.env)["failure_code"] == "operation_failed"
    assert harness.recorder.count("cleanup_study") == 1


def test_report_failure_remains_beside_an_existing_primary_failure(harness) -> None:
    def broken(self):
        self.declare()
        self.cluster_ready = True
        self.cells.extend({} for _ in range(864))
        self.gens[2].seal = object()
        raise study.StudyFailure("operation_failed", "G1_OBSERVED")

    harness.monkeypatch.setattr(study._Driver, "run", broken)
    harness.monkeypatch.setattr(study, "write_observed_report", harness.recorder.record("report", error=OSError()))
    outcome = study.run_public_text_study(harness.env)
    assert outcome.failure_code == "operation_failed" and outcome.state == "G1_OBSERVED"
    assert outcome.diagnostic_errors == ("report_evidence_failed",)
    assert _receipt(harness.env)["failure_code"] == "operation_failed"
    assert outcome.cleanup is not None and outcome.cleanup["status"] == "clean"
