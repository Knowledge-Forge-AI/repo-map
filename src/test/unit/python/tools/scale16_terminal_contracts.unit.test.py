from __future__ import annotations

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId, PublicationGenerations
from repomap_kg.storage.publication import RunPublicationAttempt
from scale15_terminal_contracts import (
    BoundRefreshExpectation,
    ExpectedRefreshAuthority,
    PrelaunchRefreshExpectation,
)


def _prelaunch() -> ExpectedRefreshAuthority:
    return ExpectedRefreshAuthority(
        "repo1:public-fixture",
        "public-fixture",
        PublicationGenerations(
            "sg1:source",
            "cg1:config",
            "eg1:extractor",
            "kg1:canonicalizer",
        ),
        "direct",
        True,
        {
            "files": 1,
            "raw_observations": 1,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "canonical_evidence": 0,
            "canonical_node_evidence": 0,
            "canonical_edge_evidence": 0,
        },
        "0" * 64,
    ).validate()


def test_prelaunch_expectation_binds_without_mutation() -> None:
    prelaunch = _prelaunch()
    attempt = RunPublicationAttempt(JobId("direct-scale16"), AttemptNumber(1))

    bound = prelaunch.bind(attempt)

    assert isinstance(prelaunch, PrelaunchRefreshExpectation)
    assert isinstance(bound, BoundRefreshExpectation)
    assert bound.prelaunch is prelaunch
    assert bound.publication_attempt is attempt


def test_bound_expectation_rejects_invalid_attempt() -> None:
    with pytest.raises(ValueError, match="bound refresh expectation"):
        BoundRefreshExpectation(
            _prelaunch(),
            RunPublicationAttempt(JobId("bad identity"), AttemptNumber(0)),
        ).validate()
