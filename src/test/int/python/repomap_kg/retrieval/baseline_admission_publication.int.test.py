"""W5 admission against accepted SQLite and PostgreSQL publications."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.w5_experiment_journal import record_baseline
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    build_mixed_v1_projection_policy,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_evaluation_admission_w5 import (
    AdmissionState,
    AdmissionVerificationError,
    BindingDisposition,
    admit_w5_task,
)
from retrieval_evaluation_admission_w5_runner import execute_w5_callback
from retrieval_evaluation_grading import ExecutionState, GradingState
from retrieval_evaluation_native import DEFAULT_MAX_STDOUT_BYTES
from retrieval_evaluation_schema import load_task_catalog
from retrieval_evaluation_views import materialize_native_search_view
from retrieval_semantic_experiment_contracts import (
    canonical_json_bytes, digest_bytes, make_plan,
)
from retrieval_semantic_baseline_capture import (
    generation_aliases_for, make_baseline_correspondence_runner,
)
from retrieval_semantic_experiment_scope import BaselineCorrespondenceSidecar
from retrieval_semantic_grading import grade_w5_task_slot
from retrieval_evaluation_attempts import admit_attempt
from repomap_test_support.w5_experiment_results import ResultV2Run
from repomap_test_support.w5_admission_native_bytework import byte_work_accounting, byte_work_identity
from repomap_test_support.w5_experiment_vector import (
    baseline_file_metrics, baseline_file_metrics_with_correspondence,
)

PUBLIC_ALIASES = ("core", "companion", "feeds")


def _task(task_id: str):
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    return next(task for task in catalog.calibration_tasks() if task.task_id == task_id)


def _assert_private_refusal(reader: GeneratorFixtureReader, task) -> None:
    pin = reader.read_pin()
    for wrong in (replace(task, generation=task.generation + 1), replace(task, split="held_out")):
        with pytest.raises(AdmissionVerificationError, match="w5_task_publication_scope_mismatch"):
            admit_w5_task(wrong, policy=reader.policy, publication_pin=pin, observed_backend=reader.backend)
    decision = admit_w5_task(
        task,
        policy=reader.policy,
        publication_pin=pin,
        observed_backend=reader.backend,
    )
    assert decision.state is AdmissionState.REFUSED
    assert decision.refusal_code == "binding_privacy_not_authorized"
    assert decision.bindings[0].disposition is BindingDisposition.DENIED_DECLARED
    called = False

    def forbidden(_pin):
        nonlocal called
        called = True
        raise AssertionError("denied W5 callback was reached")

    outcome = execute_w5_callback(
        arm_id=f"current_graph_baseline:{reader.backend}",
        task=task,
        policy=reader.policy,
        publication_pin=pin,
        callback=forbidden,
    )
    assert outcome[0] is ExecutionState.REFUSED
    assert outcome[1].refusal_code == "binding_privacy_not_authorized"
    assert outcome[1].provenance["evaluator_precheck"] is True
    assert outcome[1].provenance["backend_policy_enforcement_observed"] is False
    assert outcome[3].observed_output_payload_bytes == 0
    assert called is False

    correct = grade_w5_task_slot(
        task,
        arm_id="vector_only",
        verified_pin=pin,
        execution_state=outcome[0],
        capability_state=outcome[1].capability_state.value,
        refusal_code=outcome[1].refusal_code,
        scope_complete=outcome[1].scope_complete,
    )
    wrong = grade_w5_task_slot(
        task,
        arm_id="vector_only",
        verified_pin=pin,
        execution_state=ExecutionState.REFUSED,
        capability_state="refused",
        refusal_code="wrong_refusal_code",
        scope_complete=False,
    )
    assert correct.safety_refusal_correct is True
    assert correct.grading_state is GradingState.NOT_APPLICABLE
    assert wrong.safety_refusal_correct is False


def test_admission_uses_actual_sqlite_and_postgres_publications(tmp_path: Path) -> None:
    task = _task("cal-21")
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    sqlite_home = write_mixed_v1_sqlite_home(
        tmp_path / "sqlite-home", working, declared_aliases=PUBLIC_ALIASES
    )
    sqlite_state = publish_and_load_sqlite_corpus(
        sqlite_home, selected_aliases=PUBLIC_ALIASES
    )
    sqlite_policy = build_mixed_v1_projection_policy(
        MIXED_V1_GRAPH_ID, selected_aliases=PUBLIC_ALIASES
    )
    sqlite_reader = GeneratorFixtureReader(sqlite_state, sqlite_policy, "sqlite")
    _assert_private_refusal(sqlite_reader, task)

    with temporary_postgres() as database:
        postgres_home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working,
            host=database.host,
            port=database.port,
            database=database.database,
            user=database.user,
            password=database.password,
            declared_aliases=PUBLIC_ALIASES,
        )
        postgres_state = publish_and_load_postgres_corpus(
            postgres_home,
            selected_aliases=PUBLIC_ALIASES,
            psql_command=database.psql_command,
        )
        postgres_policy = build_mixed_v1_projection_policy(
            MIXED_V1_GRAPH_ID, selected_aliases=PUBLIC_ALIASES
        )
        postgres_reader = GeneratorFixtureReader(
            postgres_state, postgres_policy, "postgresql", database.psql_command
        )
        _assert_private_refusal(postgres_reader, task)


def test_captured_reference_uses_each_real_pin_backend_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    task = _task("cal-01")
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    aliases = PUBLIC_ALIASES
    sqlite_home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working, declared_aliases=aliases)
    sqlite_state = publish_and_load_sqlite_corpus(sqlite_home, selected_aliases=aliases)
    sqlite_reader = GeneratorFixtureReader(sqlite_state, sqlite_state.policy, "sqlite")
    with temporary_postgres() as database:
        postgres_home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working, host=database.host, port=database.port,
            database=database.database, user=database.user, password=database.password,
            declared_aliases=aliases,
        )
        postgres_state = publish_and_load_postgres_corpus(
            postgres_home, selected_aliases=aliases, psql_command=database.psql_command,
        )
        postgres_reader = GeneratorFixtureReader(
            postgres_state, postgres_state.policy, "postgresql", database.psql_command,
        )
        for reader in (sqlite_reader, postgres_reader):
            pin = reader.read_pin()
            decision = admit_w5_task(
                task, policy=reader.policy, publication_pin=pin,
                observed_backend="captured_reference",
            )
            assert decision.state is AdmissionState.ADMITTED
            with pytest.raises(AdmissionVerificationError, match="publication_pin_not_issued"):
                admit_w5_task(
                    task, policy=reader.policy, publication_pin=replace(pin, backend="foreign"),
                    observed_backend="captured_reference",
                )


def test_admission_classifies_unknown_missing_mixed_and_forged_live_inputs(
    tmp_path: Path,
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    home = write_mixed_v1_sqlite_home(
        tmp_path / "sqlite-home", working, declared_aliases=PUBLIC_ALIASES
    )
    state = publish_and_load_sqlite_corpus(home, selected_aliases=PUBLIC_ALIASES)
    policy = build_mixed_v1_projection_policy(
        MIXED_V1_GRAPH_ID, selected_aliases=PUBLIC_ALIASES
    )
    reader = GeneratorFixtureReader(state, policy, "sqlite")
    pin = reader.read_pin()
    safe = _task("cal-01")
    unknown = replace(safe, selected_bindings=("unknown-scope",))
    unknown_decision = admit_w5_task(
        unknown, policy=policy, publication_pin=pin, observed_backend="sqlite"
    )
    assert unknown_decision.state is AdmissionState.UNAVAILABLE
    assert unknown_decision.bindings[0].disposition is BindingDisposition.UNDECLARED

    mixed = replace(safe, selected_bindings=("mailbox", "core"))
    mixed_decision = admit_w5_task(
        mixed, policy=policy, publication_pin=pin, observed_backend="sqlite"
    )
    assert mixed_decision.state is AdmissionState.REFUSED
    assert mixed_decision.bindings[0].disposition is BindingDisposition.DENIED_DECLARED
    assert mixed_decision.bindings[1].disposition is BindingDisposition.ADMITTED_PUBLIC

    foreign_binding = "bind1:" + "f" * 64
    foreign_public_pin = replace(
        pin, admitted_public_bindings=pin.admitted_public_bindings | {foreign_binding}
    )
    # Copied dataclasses cannot carry issuance, even with a real store adapter.
    for forged in (
        foreign_public_pin, replace(pin, generation=pin.generation + 1),
        replace(pin, repository_identity="repo1:foreign"),
        replace(pin, admitted_public_bindings=frozenset()),
        replace(pin, policy_digest="sha256:" + "0" * 64),
    ):
        with pytest.raises(AdmissionVerificationError, match="publication_pin_not_issued"):
            admit_w5_task(safe, policy=policy, publication_pin=forged, observed_backend="sqlite")

    # A real accepted publication may contain a binding absent from policy.
    core = binding_id_for_alias("core")
    undeclared_policy = replace(policy, bindings={k:v for k,v in policy.bindings.items() if k != core},
                                selected_binding_ids=policy.selected_binding_ids - {core}).validate()
    undeclared_pin = GeneratorFixtureReader(state, undeclared_policy, "sqlite").read_pin()
    assert core in undeclared_pin.denied_bindings
    undeclared = admit_w5_task(safe, policy=undeclared_policy, publication_pin=undeclared_pin,
                              observed_backend="sqlite")
    assert undeclared.state is AdmissionState.UNAVAILABLE and undeclared.refusal_code is None
    assert undeclared.bindings[0].disposition is BindingDisposition.UNDECLARED

    # A public policy declaration without a matching accepted source is a gap.
    subset_home = write_mixed_v1_sqlite_home(tmp_path / "subset", working, declared_aliases=("core",))
    subset = publish_and_load_sqlite_corpus(subset_home, selected_aliases=("core",))
    write_mixed_v1_sqlite_home(subset_home, working, declared_aliases=PUBLIC_ALIASES)
    missing_pin = GeneratorFixtureReader(subset, policy, "sqlite").read_pin()
    missing = admit_w5_task(replace(safe, selected_bindings=("companion",)), policy=policy,
                           publication_pin=missing_pin, observed_backend="sqlite")
    assert missing.state is AdmissionState.UNAVAILABLE and missing.refusal_code is None
    assert missing.bindings[0].disposition is BindingDisposition.DECLARED_PUBLIC_ABSENT
    with pytest.raises(AdmissionVerificationError, match="frozen_policy_digest_mismatch"):
        admit_w5_task(
            safe,
            policy=policy,
            publication_pin=pin,
            observed_backend="sqlite",
            frozen_policy_digest="sha256:" + "1" * 64,
        )


def test_blocked_native_admission_retains_one_zero_work_record_per_repetition(
    tmp_path: Path,
) -> None:
    """Real publications retain evaluator-owned blocked-native work exactly once."""
    task = _task("cal-21")
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    sqlite_home = write_mixed_v1_sqlite_home(
        tmp_path / "sqlite-home", working, declared_aliases=PUBLIC_ALIASES
    )
    sqlite_state = publish_and_load_sqlite_corpus(
        sqlite_home, selected_aliases=PUBLIC_ALIASES
    )
    sqlite_reader = GeneratorFixtureReader(sqlite_state, sqlite_state.policy, "sqlite")
    sqlite_projection = build_captured_text_projection(
        sqlite_state.projection_inputs(), sqlite_state.policy
    )
    native_view = materialize_native_search_view(
        tmp_path / "native", manifest=sqlite_state.manifest,
        bundle=sqlite_state.bundle, store=sqlite_state.store,
        policy=sqlite_state.policy,
        selected_aliases=generation_aliases_for(sqlite_state.manifest),
    )

    with temporary_postgres() as database:
        postgres_home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working,
            host=database.host, port=database.port, database=database.database,
            user=database.user, password=database.password,
            declared_aliases=PUBLIC_ALIASES,
        )
        postgres_state = publish_and_load_postgres_corpus(
            postgres_home, selected_aliases=PUBLIC_ALIASES,
            psql_command=database.psql_command,
        )
        postgres_reader = GeneratorFixtureReader(
            postgres_state, postgres_state.policy, "postgresql", database.psql_command
        )
        postgres_projection = build_captured_text_projection(
            postgres_state.projection_inputs(), postgres_state.policy
        )
        runner = make_baseline_correspondence_runner(
            BaselineCorrespondenceSidecar,
            generation_aliases_for(sqlite_state.manifest),
            native_view,
            sqlite_reader,
            postgres_reader,
            sqlite_state,
            postgres_state,
        )
        plan = make_plan(
            attempt_id="w5-semantic-g1",
            generation=1,
            tasks=(task,),
            input_identity="sha256:" + "1" * 64,
            representation_report_identity="sha256:" + "2" * 64,
            publication_identity="sha256:" + "3" * 64,
            artifact_profile_identity="sha256:" + "4" * 64,
            controller_admission_sha256="sha256:" + "5" * 64,
            source_closure={"probe.txt": digest_bytes(b"probe")},
            arms=("native_tools_baseline",),
        )
        declaration = {
            **plan.to_mapping(),
            "candidate_closure_digests": {"probe.txt": digest_bytes(b"probe")},
        }
        journal = admit_attempt(
            tmp_path / "attempts",
            declaration,
            {"probe.txt": b"probe"},
            input_files={"probe.json": b"{}"},
        )
        result_v2 = ResultV2Run(enabled=True)
        collector = result_v2.register(plan)
        assert collector is not None
        pin = sqlite_reader.read_pin()
        envelopes = []
        callback_called = False

        def forbidden(_pin):
            nonlocal callback_called
            callback_called = True
            raise AssertionError("blocked native callback was reached")

        for repetition in range(1, 4):
            callback = result_v2.baseline_callback_for_runner(
                collector,
                repetition=repetition,
                runner=runner,
                sqlite_projection=sqlite_projection,
                postgres_projection=postgres_projection,
                metrics_reader=baseline_file_metrics_with_correspondence,
                legacy_reader=baseline_file_metrics,
                pin=pin,
            )
            outcome = record_baseline(
                journal,
                task,
                "native_tools_baseline",
                repetition,
                lambda: runner.execute("native_tools_baseline", task, forbidden),
                file_metrics_callback=callback,
            )
            assert outcome[0] is ExecutionState.REFUSED
            envelopes.append(outcome[1])

        journal.finish("completed", report={})
        result_v2.finish(journal, status="completed")
        result = result_v2._results[-1].byte_work
        assert callback_called is False
        assert len(result) == 3
        assert {
            byte_work_identity(item)["repetition"] for item in result
        } == {1, 2, 3}
        for item, envelope in zip(result, envelopes, strict=True):
            accounting = byte_work_accounting(item)
            assert accounting["raw_process_stdout_bytes"] == 0
            assert accounting["direct_selected_text_bytes"] == 0
            assert accounting["native_process_stdout_cap_bytes"] == DEFAULT_MAX_STDOUT_BYTES
            assert accounting["decoded_candidate_count"] == 0
            assert accounting["returned_hit_count"] == 0
            assert accounting["serialized_envelope_bytes"] == len(
                canonical_json_bytes(envelope.to_dict())
            )
            assert accounting["observed_output_payload_bytes"] == 0
        changed = replace(sqlite_state.policy, selected_binding_ids=
                          sqlite_state.policy.selected_binding_ids - {binding_id_for_alias("core")}).validate()
        runner.sqlite_policy = changed
        runner.read_sqlite = GeneratorFixtureReader(sqlite_state, changed, "sqlite").read_pin
        frozen_outcome = runner.execute("native_tools_baseline", task, forbidden)
        assert frozen_outcome[0] is ExecutionState.FAILED
        assert frozen_outcome[1].provenance["failure_type"] == "frozen_policy_digest_mismatch"
        assert callback_called is False
