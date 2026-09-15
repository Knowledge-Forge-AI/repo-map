import unittest

from repomap_kg.canonicalization.shell_bash_family import _try_canonicalize_bash_observation
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.observations.raw import RawObservation

class ShellCanonicalizationBoundariesUnitTests(unittest.TestCase):
    def test_canonicalize_bash_observations(self):
        nodes: dict[str, CanonicalNode] = {}
        edges: dict[str, CanonicalEdge] = {}
        evidence: list[CanonicalEvidence] = []
        node_evidence_links: list[CanonicalNodeEvidenceLink] = []
        edge_evidence_links: list[CanonicalEdgeEvidenceLink] = []
        diagnostics: list[CanonicalizationDiagnostic] = []

        obs = RawObservation(
            kind="shell.function",
            source_id="scripts/deploy.sh#func:deploy_app:3",
            path="scripts/deploy.sh",
            start_line=3,
            end_line=8,
            name="deploy_app",
            target=None,
            confidence="extracted",
            extractor="bash_extractor",
            extractor_version="1.0.0",
            metadata={"function_name": "deploy_app", "dialect": "bash"},
        )
        res = _try_canonicalize_bash_observation(
            observation=obs,
            ordinal=1,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        self.assertTrue(res)
        self.assertTrue(len(nodes) > 0)

if __name__ == "__main__":
    unittest.main()
