"""One actual public-text fixture generation and its PostgreSQL-only inputs (study sections 12 and 19.1).

Topology is the retained optional experiment's, unchanged: one shared working
root and SQLite home (declared core/companion/feeds, selected ``PUBLIC_ALIASES``),
a per-generation PostgreSQL home on the SAME disposable database and graph,
the maintained captured-text projections, the native search view and the
maintained lexical generation. Generation 2 is published only after every
generation-1 observation. Learned inputs are prepared against PostgreSQL only.
Returned objects hold private text in memory; nothing here serializes them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy, write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState, publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_experiment_support import PUBLIC_ALIASES, candidate_publication, make_public_reader
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from repomap_test_support.w5_public_text_readback import load_postgres_span_rows
from repomap_test_support.w5_semantic_store_support import (
    load_postgres_accepted_nodes_and_evidence, make_postgres_readback_adapter,
)
from retrieval_evaluation_execution import ArmContext
from retrieval_evaluation_views import materialize_native_search_view
from retrieval_public_text_census import PublicTextCensus, build_public_text_census
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_descriptors import PublicTextPreparation, prepare_public_text_generation
from retrieval_public_text_request import DualArmInput, build_dual_arm_input, encode_dual_arm_request
from retrieval_public_text_tasks import SelectedTaskSet
from retrieval_semantic_baseline_capture import generation_aliases_for
from retrieval_semantic_generator_inputs import PublicGenerationInput, prepare_public_generation_input
from retrieval_semantic_provenance import VerifiedPublicationPin

DECLARED_ALIASES = ("core", "companion", "feeds")
LEXICAL_ALIASES = ("core", "companion")


class GenerationRefusal(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, repr=False)
class GenerationResources:
    """Live disposable backends and fresh readers for one published generation."""

    generation: int
    sqlite_state: PublishedCorpusState
    postgres_state: PublishedCorpusState
    sqlite_reader: GeneratorFixtureReader
    postgres_reader: GeneratorFixtureReader
    context: ArmContext
    psql_command: str

    def __repr__(self) -> str:
        return f"GenerationResources(generation={self.generation})"

    @property
    def generation_aliases(self) -> tuple[str, ...]:
        return generation_aliases_for(self.sqlite_state.manifest)

    def candidate_publication(self) -> Any:
        return candidate_publication(self.postgres_reader)

    def read_v1_evidence(self) -> tuple[Any, ...]:
        return load_postgres_accepted_nodes_and_evidence(self.postgres_state, psql_command=self.psql_command)[2]

    def read_span_rows(self) -> tuple[Any, ...]:
        return load_postgres_span_rows(self.postgres_state, psql_command=self.psql_command)


def materialize_generation(workspace: Path, database: Any, generation: int) -> GenerationResources:
    """Publish one actual mixed-v1 generation to SQLite and the shared PostgreSQL database."""
    if type(generation) is not int or generation not in (1, 2):
        raise GenerationRefusal("generation_invalid")
    if not isinstance(workspace, Path) or not workspace.is_absolute() or workspace.is_symlink():
        raise GenerationRefusal("generation_workspace_invalid")
    working = materialize_mixed_v1_working_copy(workspace / "working-shared", generation=generation)
    sqlite_home = write_mixed_v1_sqlite_home(workspace / "sqlite-shared", working, declared_aliases=DECLARED_ALIASES)
    sqlite_state = publish_and_load_sqlite_corpus(sqlite_home, selected_aliases=PUBLIC_ALIASES)
    postgres_home = write_mixed_v1_postgres_home(
        workspace / f"postgres-g{generation}", working, host=database.host, port=database.port,
        database=database.database, user=database.user, password=database.password,
        declared_aliases=DECLARED_ALIASES)
    psql = database.psql_command
    postgres_state = publish_and_load_postgres_corpus(postgres_home, selected_aliases=PUBLIC_ALIASES, psql_command=psql)
    sqlite_projection = build_captured_text_projection(sqlite_state.projection_inputs(), sqlite_state.policy)
    postgres_projection = build_captured_text_projection(postgres_state.projection_inputs(), postgres_state.policy)
    native_view = materialize_native_search_view(
        workspace / f"native-g{generation}", manifest=sqlite_state.manifest, bundle=sqlite_state.bundle,
        store=sqlite_state.store, policy=sqlite_state.policy,
        selected_aliases=generation_aliases_for(sqlite_state.manifest))
    config = load_graph_registry_config_home(postgres_home)
    if not isinstance(config, OpsConfig):
        raise GenerationRefusal("generation_postgres_config")
    lexical = build_graph_lexical_generation(
        config, MIXED_V1_GRAPH_ID, selected_binding_ids=tuple(binding_id_for_alias(a) for a in LEXICAL_ALIASES),
        authorize_body=True)
    if lexical.result != "published":
        raise GenerationRefusal("generation_lexical_publication_refused")
    context = ArmContext(native_view, sqlite_state.home_root, sqlite_projection, postgres_state.home_root,
                         postgres_projection, psql)
    return GenerationResources(
        generation, sqlite_state, postgres_state,
        GeneratorFixtureReader(sqlite_state, sqlite_state.policy, "sqlite", psql),
        make_public_reader(postgres_state, psql_command=psql), context, psql)


@dataclass(frozen=True, repr=False)
class PreparedGeneration:
    """Actual PostgreSQL-bound inputs for one generation and the request bytes built from them."""

    pin: VerifiedPublicationPin
    preparation: PublicTextPreparation
    census: PublicTextCensus
    v1: PublicGenerationInput
    dual: DualArmInput
    request_raw: bytes = field(repr=False)
    refresh: Callable[[], DualArmInput] = field(repr=False)

    def __repr__(self) -> str:
        return f"PreparedGeneration(generation={self.dual.generation})"


def _build(resources: GenerationResources, selected: SelectedTaskSet, scope: PrivateMarkerScope, *,
           study_identity: str, artifact_profile_identity: str) -> tuple[Any, ...]:
    reader = resources.postgres_reader
    state = resources.postgres_state
    pin = reader.read_pin()
    adapter = make_postgres_readback_adapter(state, psql_command=resources.psql_command,
                                             projection_inputs=state.projection_inputs())
    preparation = prepare_public_text_generation(
        publication_pin=pin, readback_adapter=adapter, policy=reader.policy, scope=scope,
        read_representations=reader.read_representations, read_v1_evidence=resources.read_v1_evidence,
        read_span_rows=resources.read_span_rows)
    tasks = selected.for_generation(resources.generation)
    census = build_public_text_census(
        tasks, retained_task_digests=selected.retained_digests(resources.generation), policy=reader.policy,
        publication_pin=pin, observed_backend="postgresql", frozen_policy_digest=pin.policy_digest,
        preparation=preparation)
    v1 = prepare_public_generation_input(reader.read_representations(), tasks, read_current=reader.read_pin,
                                         read_representations=reader.read_representations)
    dual = build_dual_arm_input(
        generation=resources.generation, attempt_id=f"w5-semantic-g{resources.generation}",
        study_identity=study_identity, v1_input=v1, preparation=preparation, census=census, tasks=selected,
        publication_pin=pin, artifact_profile_identity=artifact_profile_identity)
    return pin, preparation, census, v1, dual


def prepare_generation_inputs(resources: GenerationResources, selected: SelectedTaskSet, *,
                              scope: PrivateMarkerScope, study_identity: str,
                              artifact_profile_identity: str) -> PreparedGeneration:
    """Selected tasks, census, preparation, v1 input and the dual request, all against PostgreSQL."""
    if resources.postgres_reader.backend != "postgresql":
        raise GenerationRefusal("generation_learned_backend")
    values = dict(study_identity=study_identity, artifact_profile_identity=artifact_profile_identity)
    pin, preparation, census, v1, dual = _build(resources, selected, scope, **values)

    def refresh() -> DualArmInput:
        return _build(resources, selected, scope, **values)[4]

    return PreparedGeneration(pin, preparation, census, v1, dual, encode_dual_arm_request(dual), refresh)


__all__ = [
    "DECLARED_ALIASES", "GenerationRefusal", "GenerationResources", "PreparedGeneration", "materialize_generation",
    "prepare_generation_inputs",
]
