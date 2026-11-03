"""Actual disposable fixture readback for generator admission tests.

These adapters perform fresh database IO on every call. They never use the
cached PublishedCorpusState receipt as evidence of current accepted state.
"""
from __future__ import annotations

from dataclasses import dataclass

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from common_lore_index.ops.config import OpsConfig, OpsGraphConfig
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState, read_postgres_accepted_publication, read_sqlite_accepted_publication,
)
from repomap_test_support.w5_semantic_support import (
    load_postgres_accepted_nodes_and_evidence, load_sqlite_accepted_nodes_and_evidence,
)
from retrieval_semantic_provenance import (
    AcceptedStoreReadback, RepresentationValidationError, VerifiedPublicationPin, verify_publication_provenance,
    verify_publication_provenance_from_adapter,
)
from retrieval_semantic_representation import (
    RepresentationValidationReport, validate_canonical_node_representations,
)


@dataclass(frozen=True)
class GeneratorFixtureReader:
    published: PublishedCorpusState
    policy: BodyProjectionPolicy
    backend: str
    psql_command: str = 'psql'

    def _authorized_graph(self) -> tuple[OpsConfig | LocalSqliteConfig, OpsGraphConfig]:
        config = load_graph_registry_config_home(self.published.home_root)
        graph = next(graph for graph in config.graphs if graph.id == self.published.graph_id)
        if self.policy.graph_id != graph.id:
            raise RepresentationValidationError('graph_id_mismatch', 'fixture policy targets another graph')
        if graph.privacy != 'public-dev':
            raise RepresentationValidationError('graph_privacy_not_authorized', 'fixture graph is not public-dev')
        actual_bindings = {binding.binding_id: binding for binding in graph.effective_source_bindings}
        for binding_id, declared in self.policy.bindings.items():
            actual = actual_bindings.get(binding_id)
            if actual is None and binding_id not in self.policy.selected_binding_ids and declared.resolved_binding_privacy != 'public-dev':
                continue  # Explicitly denied task scope; never present in this public-only graph.
            if actual is None or actual.privacy != declared.resolved_binding_privacy:
                raise RepresentationValidationError('binding_policy_mismatch', 'fixture policy disagrees with declared binding')
        return config, graph

    def read_publication(self) -> AcceptedStoreReadback:
        config, graph = self._authorized_graph()
        binding = local_graph_binding(graph)
        if self.backend == 'sqlite':
            if not isinstance(config, LocalSqliteConfig):
                raise TypeError('expected SQLite fixture configuration')
            publication, _nodes, _evidence = load_sqlite_accepted_nodes_and_evidence(self.published)
            _reference, receipt = read_sqlite_accepted_publication(config, self.published.graph_id)
        elif self.backend == 'postgresql':
            if not isinstance(config, OpsConfig):
                raise TypeError('expected PostgreSQL fixture configuration')
            publication, _nodes, _evidence = load_postgres_accepted_nodes_and_evidence(
                self.published, psql_command=self.psql_command)
            _reference, receipt = read_postgres_accepted_publication(
                config, self.published.graph_id, psql_command=self.psql_command)
        else:
            raise ValueError('unsupported disposable generator fixture backend')
        return AcceptedStoreReadback(self.published.graph_id, str(binding.repository_identity),
                                     self.backend, publication, receipt)

    def read_pin(self) -> VerifiedPublicationPin:
        return verify_publication_provenance_from_adapter(self.read_publication, policy=self.policy)

    def read_representations(self) -> RepresentationValidationReport:
        self._authorized_graph()
        if self.backend == 'sqlite':
            publication, nodes, evidence = load_sqlite_accepted_nodes_and_evidence(self.published)
        elif self.backend == 'postgresql':
            publication, nodes, evidence = load_postgres_accepted_nodes_and_evidence(
                self.published, psql_command=self.psql_command)
        else:
            raise ValueError('unsupported disposable generator fixture backend')
        current = self.read_publication()
        pin = verify_publication_provenance(
            graph_id=current.graph_id, repository_identity=current.repository_identity,
            backend=current.backend, accepted_publication=publication, receipt=current.receipt,
            policy=self.policy, readback_adapter=self.read_publication)
        return validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
