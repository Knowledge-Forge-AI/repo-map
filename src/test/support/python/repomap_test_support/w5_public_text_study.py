"""The one stateful public-text study driver (study sections 12 and 19).

Both modes run this driver and the same exchange order: publish the request,
print the generation frame, emit readiness, await controller admission, admit
the genuine journal and print the ACK, await the response, then the unchanged
parser and study seal. ``functional_only`` installs the concrete synthetic
delivery; otherwise the external private supervisor answers. The driver never
reserves an allocation (native reservations stay host-only). Cleanup runs once
after ownership; a failure keeps its primary code, writes a private failure
receipt and never becomes a passing empty study.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
import time
from typing import Any, cast

from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from repomap_test_support.w5_experiment_postgres import install_candidate_schema
from repomap_test_support.w5_experiment_support import DECLARED_PROFILE_IDENTITY, experiment_source_closure
from repomap_test_support.w5_public_text_baselines import make_runner, run_incumbent_cells
from repomap_test_support.w5_public_text_evidence import (
    REPORT_NAME, emit_private_evidence, private_generation_inputs, retain_raw_members,
    write_observed_report, write_transition_pair,
)
from repomap_test_support.w5_public_text_functional import SyntheticDelivery
from repomap_test_support.w5_public_text_generation import materialize_generation, prepare_generation_inputs
from repomap_test_support.w5_public_text_journal import (
    StudyFailureReceipt, begin_component_journal, cleanup_fields, finish_component_journal,
    record_operation, write_failure_receipt,
)
from repomap_test_support.w5_public_text_learned import LearnedGeneration, learned_cells, old_batch_status, profiles
from repomap_test_support.w5_public_text_postgres import (
    cleanup_study, create_batch_index, create_study_relations, import_batch, sealed_batch,
)
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_native_gate import PREFIX, format_gate, gate_frame, stale_g1_proof
from retrieval_public_text_preflight import transition_observation
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import seal_dual_arm_result
from retrieval_public_text_sources import evaluator_closure, require_unchanged, worker_closure
from retrieval_public_text_study_schema import StudyNames, make_study_identity
from retrieval_public_text_tasks import SELECTED_TASKS, load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_experiment_artifacts import emit_attempt_artifacts
from retrieval_semantic_experiment_bridge import ComponentExchange
from retrieval_semantic_generator_output_parser import parse_verified_worker_response

CATALOG_PATH = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"


class StudyFailure(RuntimeError):
    """A closed failure at a named state; the message is the code only."""

    def __init__(self, code: str, state: str) -> None:
        super().__init__(code)
        self.code, self.state = code, state


@dataclass(frozen=True)
class StudyEnvironment:
    database: Any = field(repr=False)
    repo_root: Path
    workspace: Path
    journal_root: Path
    report_root: Path
    functional_only: bool


@dataclass(frozen=True)
class StudyOutcome:
    """Observed facts only; ``native_reservations`` is structurally zero because the driver has no allocator."""

    state: str
    failure_code: str | None
    report_identity: str | None
    failure_receipt_sha256: str | None
    observed_cells: int
    cleanup: dict[str, Any] | None
    frame_sha256: tuple[str, ...]
    record_counts: dict[str, dict[str, int]]
    transition: dict[str, Any] | None
    verification: str | None
    native_reservations: int = 0
    diagnostic_errors: tuple[str, ...] = ()


@dataclass
class _Generation:
    prepared: Any = None
    request_raw: bytes | None = None
    admission_raw: bytes | None = None
    journal: Any = None
    members: dict[str, bytes] | None = None
    response: Any = None
    seal: Any = None
    imports: list[Any] = field(default_factory=list)
    indexes: list[tuple[Any, str]] = field(default_factory=list)
    artifact: Any = None


class _Driver:
    def __init__(self, env: StudyEnvironment) -> None:
        self.env = env
        self.state = "DECLARED"
        self.failure: StudyFailure | None = None
        self.gens = {1: _Generation(), 2: _Generation()}
        self.cells: list[dict[str, Any]] = []
        self.failed_operations = 0
        self.catalog: Any = None
        self.cleanup: Any = None
        self.frames: list[str] = []
        self.marks: dict[str, float] = {}
        self.study_identity: str | None = None
        self.evaluator: Any = None
        self.cleanup_error: str | None = None
        self.diagnostic_errors: list[str] = []

    def step(self, state: str, code: str, action: Callable[[], Any]) -> Any:
        self.state = state
        try:
            return action()
        except StudyFailure:
            raise
        except Exception as error:  # every operation below is external I/O or a maintained owner
            raise StudyFailure(code, state) from error

    def declare(self) -> None:
        pins = registered_task_pins()
        self.selected = load_selected_calibration_tasks(CATALOG_PATH, pins)
        registered = tuple((t.task_id, t.generation, d) for t, d in zip(
            self.selected.tasks, (d for _t, _g, d in pins.tasks), strict=True))
        if self.selected.pins != pins or registered != SELECTED_TASKS or len(self.selected.tasks) != 24 or (
                [t.task_id for t in self.selected.for_generation(2)] != ["cal-23"]):
            raise StudyFailure("study_declaration_refused", "DECLARED")
        root = self.env.repo_root
        self.worker = worker_closure(root)
        self.evaluator = evaluator_closure(root, experiment_source_closure(root)[0])
        self.study_identity = make_study_identity(task_pins_identity=pins.identity(),
                                                  q_source_closure=self.evaluator.identity, nonce=secrets.token_hex(16))
        self.names = StudyNames(self.study_identity)
        self.scope = PrivateMarkerScope.create((str(self.env.workspace), str(self.env.journal_root)))
        self.profiles = profiles(DECLARED_PROFILE_IDENTITY)
        self.delivery = SyntheticDelivery(self.env.workspace / "synthetic-model", self.worker) \
            if self.env.functional_only else None

    def frozen(self) -> None:
        require_unchanged(self.env.repo_root, self.worker)
        require_unchanged(self.env.repo_root, self.evaluator)

    def frame(self, g: int, exchange: ComponentExchange, proof: dict[str, Any] | None) -> tuple[str, bytes]:
        dual = self.gens[g].prepared.dual
        manifest = dual.manifest()
        frame = gate_frame(
            generation=g, nonce=exchange.nonce, record_counts=manifest["partitions"],
            functional_only=self.env.functional_only, stale_proof=proof, study_identity=cast(str, self.study_identity),
            request_sha256=exchange.ready.request_sha256, input_identity=dual.input_identity,
            publication_identity=dual.publication_identity, artifact_profile_identity=DECLARED_PROFILE_IDENTITY,
            q_source_closure_identity=self.evaluator.identity, worker_source_closure_identity=self.worker.identity,
            task_pins_identity=self.selected.pins.identity(), selected_task_set_identity=self.selected.identity(),
            census_identity=manifest["census_identity"], preparation_identity=manifest["preparation_identity"])
        raw = format_gate(frame)
        print("\n" + raw.decode("ascii"), end="", flush=True)  # a frame line always starts at column 0
        digest = "sha256:" + hashlib.sha256(raw[len(PREFIX):]).hexdigest()
        self.frames.append(digest)
        return digest, raw[len(PREFIX):]

    def exchange(self, g: int, proof: dict[str, Any] | None) -> None:
        gen = self.gens[g]
        attempt = f"w5-semantic-g{g}"
        exchange = ComponentExchange.publish_request(attempt_id=attempt, request=json.loads(cast(bytes, gen.request_raw)),
                                                     expected_source_closure=dict(self.worker.digests))
        frame_sha, frame_payload = self.frame(g, exchange, proof)
        if g == 2:
            self.marks["g2_readiness"] = time.monotonic()
        exchange.emit_request_readiness()
        if self.delivery is not None:
            self.delivery.admit(exchange)
        exchange = exchange.await_controller_admission()
        gen.admission_raw = exchange.admission_raw
        gen.journal = begin_component_journal(
            self.env.journal_root, attempt_id=attempt, generation=g,
            task_ids=[t.task_id for t in self.selected.for_generation(g)], request_raw=cast(bytes, gen.request_raw),
            admission_raw=cast(bytes, gen.admission_raw), evaluator=self.evaluator, worker=self.worker,
            input_files=private_generation_inputs(gen.prepared, self.selected, frame_payload))
        record_operation(gen.journal, "generation_frame", frame_sha256=frame_sha, generation=g)
        print(exchange.admission_ack_line, flush=True)
        if self.delivery is not None:
            self.delivery.respond(exchange)
        members = exchange.await_response()
        if g == 1:
            self.marks["g1_response"] = time.monotonic()
        gen.members = {name: members[name] for name in ("declaration.json", "report.json", "source-manifest.json",
                                                        "sources.zip", "terminal.json")}
        retain_raw_members(self.env.report_root, attempt, gen.members)
        gen.response = parse_verified_worker_response(
            request_raw=cast(bytes, gen.request_raw), report_raw=members["report.json"], terminal_raw=members["terminal.json"],
            declaration_raw=members["declaration.json"], source_manifest_raw=members["source-manifest.json"],
            sources_archive_raw=members["sources.zip"], expected_controller_admission_sha256=cast(str, exchange.admission_sha256),
            expected_source_closure=dict(self.worker.digests))

    def import_generation(self, g: int, resources: Any) -> None:
        gen, pin, publication = self.gens[g], self.gens[g].prepared.pin, resources.candidate_publication()
        for arm in (ARM_V1, ARM_PTX):
            if gen.seal.arms[arm].capability == "refused":
                continue
            batch = sealed_batch(self.names, gen.seal, arm, self.profiles[arm], pin=pin,
                                 v1_input=gen.prepared.v1 if arm == ARM_V1 else None,
                                 preparation=gen.prepared.preparation if arm == ARM_PTX else None)
            import_batch(self.env.database, self.catalog, batch, publication, pin)
            gen.imports.append(batch)
            self.catalog = create_batch_index(self.env.database, self.catalog, batch.batch_id)
            gen.indexes.append((self.catalog.index_for(batch.batch_id), arm))

    def observe(self, g: int, resources: Any) -> None:
        gen = self.gens[g]
        context = LearnedGeneration(
            self.env.database, self.catalog, gen.seal, gen.prepared.pin, resources.candidate_publication(),
            gen.prepared.v1, gen.prepared.preparation, gen.prepared.census, self.scope,
            frozenset(batch.arm for batch in gen.imports), self.profiles)
        runner = make_runner(resources)
        for task in self.selected.for_generation(g):
            run = run_incumbent_cells(resources, runner, task, journal=gen.journal)
            self.cells.extend(run.cells)
            self.failed_operations += run.failed_operations
            for repetition, lexical in enumerate(run.lexical, start=1):
                learned = learned_cells(context, task, repetition, lexical)
                self.failed_operations += sum(c["state"] == "failed" for c in learned)
                self.cells.extend(learned)
                for item in learned:
                    record_operation(gen.journal, "learned_operation", task_id=task.task_id, arm=item["arm"],
                                     repetition=repetition, state=item["state"], reason=item["reason"])

    def stale_proof(self, resources: Any) -> dict[str, Any]:
        old = self.gens[1].prepared
        try:
            old.pin.revalidate_current()
        except Exception as error:  # the actual pin refusal is the observation
            refusal = getattr(error, "code", None)
        else:
            refusal = None
        if refusal != "stale_publication_receipt":
            raise StudyFailure("stale_proof_failed", "G1_STALE_PROVEN")
        status, raw_sha = old_batch_status(self.env.database, self.catalog, self.g1_publication,
                                           self.names.batch_id(1, ARM_PTX))
        proof = stale_g1_proof(old_publication_identity=old.dual.publication_identity,
                               new_publication_identity=str(digest_json(resources.postgres_reader.read_pin().to_dict())),
                               old_pin_refusal=refusal, old_batch_status=status, raw_observation_sha256=raw_sha)
        record_operation(self.gens[1].journal, "stale_g1_observation", proof_identity=proof["proof_identity"])
        return proof

    def generation(self, g: int) -> None:
        env, gen = self.env, self.gens[g]
        resources = self.step(f"G{g}_PUBLISHED", "publication_failed",
                              lambda: materialize_generation(env.workspace, env.database, g))
        proof = None if g == 1 else self.step("G1_STALE_PROVEN", "stale_proof_failed",
                                              lambda: self.stale_proof(resources))
        gen.prepared = self.step(f"G{g}_PREPARED", "preparation_refused", lambda: prepare_generation_inputs(
            resources, self.selected, scope=self.scope, study_identity=cast(str, self.study_identity),
            artifact_profile_identity=DECLARED_PROFILE_IDENTITY))
        gen.request_raw = gen.prepared.request_raw
        self.step(f"G{g}_FROZEN", "source_changed", self.frozen)
        self.step(f"G{g}_WORKER", "exchange_refused", lambda: self.exchange(g, proof))
        gen.seal = self.step(f"G{g}_SEALED", "seal_refused", lambda: seal_dual_arm_result(
            gen.prepared.dual, gen.response, refresh=gen.prepared.refresh, scope=self.scope))
        if g == 1:
            self.catalog = self.step("TABLES_CREATED", "sql_failed",
                                     lambda: create_study_relations(env.database, self.names))
            self.g1_publication = resources.candidate_publication()
        self.step(f"G{g}_IMPORTED", "sql_failed", lambda: self.import_generation(g, resources))
        self.step(f"G{g}_OBSERVED", "observation_failed", lambda: self.observe(g, resources))
        self.step(f"G{g}_OBSERVED", "source_changed", self.frozen)
        if g == 1 and self.failed_operations:
            raise StudyFailure("operation_failed", "G1_OBSERVED")

    def run(self) -> None:
        self.step("DECLARED", "study_declaration_refused", self.declare)
        self.step("CLUSTER_READY", "cluster_setup_failed", self.cluster)
        for g in (1, 2):
            self.generation(g)

    def cluster(self) -> None:
        apply_migrations(default_rdbms_root(), self.env.database.psql_args,
                         psql_command=self.env.database.psql_command)
        install_candidate_schema(self.env.database)
        self.cluster_ready = True

    def finish(self) -> None:
        """Cleanup once after ownership, then journals; each outcome is independent of the primary error."""
        if getattr(self, "cluster_ready", False):
            try:
                self.cleanup = cleanup_study(self.env.database, self.names, self.catalog)
            except Exception:  # an unreadable absence proof is a failed cleanup, kept beside the primary error
                self.cleanup_error = "cleanup_failed:readback_refused"
        if self.cleanup_error or (self.cleanup is not None and self.cleanup.status != "clean"):
            self.failure = self.failure or StudyFailure("cleanup_failed", "CLEANED")
        failed = self.failure is not None or self.failed_operations > 0
        code = None if not failed else (self.failure.code if self.failure else "operation_failed")
        for gen in self.gens.values():
            if gen.journal is None:
                continue
            try:
                recorded = gen.response is not None and gen.members is not None
                gen.artifact = finish_component_journal(
                    gen.journal, request_raw=cast(bytes, gen.request_raw), admission_raw=cast(bytes, gen.admission_raw),
                    response=gen.response if recorded else None, raw_members=gen.members if recorded else None,
                    status="failed" if failed else "completed", failure_code=code)
            except Exception:
                self.failure = self.failure or StudyFailure("journal_failed", "CLEANED")
                self.diagnostic_errors.append("journal_finish_failed")
        try:
            directories = [str(g.journal.directory) for g in self.gens.values() if g.journal is not None]
            if directories:  # raw frames only after the generations ran, never before g2 readiness
                emit_attempt_artifacts(directories)
        except Exception:
            self.failure = self.failure or StudyFailure("journal_failed", "CLEANED")
            self.diagnostic_errors.append("journal_framing_failed")


def run_public_text_study(env: StudyEnvironment) -> StudyOutcome:
    """Run the whole lifecycle once; the outcome is truthful whether or not it failed."""
    if type(env.functional_only) is not bool:
        raise TypeError("functional_only must be a bool")
    driver = _Driver(env)
    interrupted: BaseException | None = None
    try:
        driver.run()
    except StudyFailure as failure:
        driver.failure = failure
    except (KeyboardInterrupt, SystemExit) as error:
        driver.failure = StudyFailure("study_interrupted", driver.state)
        interrupted = error
    except Exception:
        driver.failure = StudyFailure("study_execution_failed", driver.state)
    finally:
        driver.state = "CLEANED"
        driver.finish()
    cleanup = None if driver.cleanup is None else driver.cleanup.to_dict()
    if driver.failure is None and (cleanup is None or cleanup["status"] != "clean"):
        driver.failure = StudyFailure("cleanup_failed", "CLEANED")
    identity = verification = None
    if driver.gens[2].seal is not None and len(driver.cells) == 864 and driver.cleanup is not None:
        try:
            driver.state = "REPORTED"
            identity, verification = write_observed_report(
                env, study_identity=cast(str, driver.study_identity), selected=driver.selected, evaluator=driver.evaluator,
                scope=driver.scope, generations=driver.gens, cells=driver.cells, cleanup=driver.cleanup)
        except Exception:  # the writer/readback failure keeps both diagnostics, never success
            driver.failure = driver.failure or StudyFailure("report_failed", "REPORTED")
            driver.diagnostic_errors.append("report_evidence_failed")
    if driver.failure is None and driver.failed_operations:
        driver.failure = StudyFailure("operation_failed", "G2_OBSERVED")
    counts = {str(g): dict(gen.prepared.dual.manifest()["partitions"]) for g, gen in driver.gens.items()
              if gen.prepared is not None}
    transition, receipt, diagnostics = None, None, driver.diagnostic_errors
    if {"g1_response", "g2_readiness"} <= set(driver.marks) and env.functional_only:
        try:
            transition = transition_observation(
                interval_seconds=driver.marks["g2_readiness"] - driver.marks["g1_response"], counts=counts,
                q_source_closure_identity=driver.evaluator.identity, task_pins_identity=driver.selected.pins.identity(),
                selected_task_set_identity=driver.selected.identity(), artifact_profile_identity=DECLARED_PROFILE_IDENTITY)
            write_transition_pair(env.report_root, transition, counts=counts,
                                  evaluator_identity=driver.evaluator.identity, selected=driver.selected)
        except Exception:
            driver.failure = driver.failure or StudyFailure("transition_failed", "REPORTED")
            diagnostics.append("transition_evidence_failed")
    if driver.failure is not None:
        try:
            receipt = write_failure_receipt(env.report_root, StudyFailureReceipt(
                env.functional_only, driver.study_identity,
                None if driver.evaluator is None else driver.evaluator.identity, registered_task_pins().identity(),
                driver.failure.state, driver.failure.code, len(driver.cells),
                tuple((g, None if gen.response is None else "sha256:" + hashlib.sha256(
                    cast(dict[str, bytes], gen.members)["report.json"]).hexdigest()) for g, gen in driver.gens.items() if gen.journal is not None),
                *cleanup_fields(cleanup, driver.cleanup_error)))
        except Exception:
            diagnostics.append("failure_receipt_write_failed")
    try:
        emit_private_evidence(env.report_root, [gen.journal.directory for gen in driver.gens.values()
                                               if gen.journal is not None], functional_only=env.functional_only)
    except Exception:
        driver.failure = driver.failure or StudyFailure("evidence_export_failed", "REPORTED")
        diagnostics.append("private_evidence_export_failed")
    outcome = StudyOutcome(driver.state if driver.failure is None else driver.failure.state,
                        None if driver.failure is None else driver.failure.code, identity, receipt, len(driver.cells),
                        cleanup, tuple(driver.frames), counts, transition, verification,
                        diagnostic_errors=tuple(diagnostics))
    if interrupted is not None:
        raise interrupted
    return outcome


__all__ = ["CATALOG_PATH", "REPORT_NAME", "StudyEnvironment", "StudyFailure", "StudyOutcome", "run_public_text_study"]
