"""Attempt-bound file evidence refuses unsafe retirement without durable closure."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any, cast

import pytest
from repomap_kg.coordinator import _publication_phase as phase
from repomap_test_support.startup_recovery_scenarios import _harness, _req


@pytest.mark.parametrize("corruption", [
    "initial-not-object", "initial-mode", "initial-identity",
    "decision-not-object", "decision-state", "decision-symlink",
])
def test_unsafe_evidence_cannot_authorize_closure_or_partial_retirement(corruption):
    with _harness() as (store, directory, _connect):
        epoch = store.acquire_singleton("evidence-owner", timedelta(seconds=30))
        submitted = store.submit(_req("evidence-graph", "evidence-unsafe"))
        claim = store.claim_next("evidence-owner", epoch, timedelta(seconds=30))
        assert claim is not None and claim.job_id == submitted.job_id
        phase.initialize(directory, claim)
        phase.before_publication(directory, claim)
        initial, = directory.glob("publication-*.initial.json")
        decision, = directory.glob("publication-*.decision.json")
        foreign = directory / "foreign.json"
        foreign.write_text("fixture-owned-elsewhere")
        if corruption == "initial-not-object":
            initial.write_text("[]")
        elif corruption == "initial-mode":
            initial.chmod(0o644)
        elif corruption == "initial-identity":
            payload = json.loads(initial.read_text())
            payload["job_id"] = "different-job"
            initial.write_text(json.dumps(payload))
        elif corruption == "decision-not-object":
            decision.write_text("[]")
        elif corruption == "decision-state":
            payload = json.loads(decision.read_text())
            payload["publication_state"] = "committed"
            decision.write_text(json.dumps(payload))
        else:
            decision.unlink()
            decision.symlink_to(foreign)
        before = initial.read_bytes(), decision.read_bytes()
        assert phase.publication_state(directory, claim) == "commit_unknown"
        with pytest.raises(TypeError, match="Authoritative WorkerFencingProof"):
            phase.close_unpublished(directory, claim, proof=cast(Any, True))
        with pytest.raises(ValueError):
            phase.retire_evidence(directory, claim)
        assert initial.exists() and decision.exists()
        assert (initial.read_bytes(), decision.read_bytes()) == before
        assert foreign.read_text() == "fixture-owned-elsewhere"
        assert store.status(submitted.job_id).state == "claimed"
        assert store.status(submitted.job_id).publication_state != "committed"
        assert store.stop_singleton("evidence-owner", epoch)


def test_mismatched_initial_evidence_prevents_publication_start():
    with _harness() as (store, directory, _connect):
        epoch = store.acquire_singleton("evidence-owner", timedelta(seconds=30))
        store.submit(_req("evidence-graph", "evidence-mismatch"))
        claim = store.claim_next("evidence-owner", epoch, timedelta(seconds=30))
        assert claim is not None
        phase.initialize(directory, claim)
        initial, = directory.glob("publication-*.initial.json")
        payload = json.loads(initial.read_text())
        payload["config_generation"] = "cg1:different"
        initial.write_text(json.dumps(payload))
        before = initial.read_bytes()
        with pytest.raises(ValueError, match="publication evidence identity mismatch"):
            phase.before_publication(directory, claim)
        assert not tuple(directory.glob("publication-*.decision.json"))
        assert initial.read_bytes() == before
        assert phase.publication_state(directory, claim) == "commit_unknown"
        assert store.status(claim.job_id).state == "claimed"
        assert store.stop_singleton("evidence-owner", epoch)


def test_failed_initial_evidence_write_never_becomes_nonpublication_proof(monkeypatch):
    with _harness() as (store, directory, _connect):
        epoch = store.acquire_singleton("evidence-owner", timedelta(seconds=30))
        store.submit(_req("evidence-graph", "evidence-write-failure"))
        claim = store.claim_next("evidence-owner", epoch, timedelta(seconds=30))
        assert claim is not None
        with monkeypatch.context() as fault:
            fault.setattr(os, "write", lambda _fd, _data: 0)
            with pytest.raises(OSError, match="publication evidence write failed"):
                phase.initialize(directory, claim)
        initial, = directory.glob("publication-*.initial.json")
        assert initial.read_bytes() == b""
        assert phase.publication_state(directory, claim) == "commit_unknown"
        with pytest.raises(ValueError, match="invalid publication evidence"):
            phase.retire_evidence(directory, claim)
        assert initial.exists()
        assert not tuple(directory.glob("publication-*.decision.json"))
        assert store.status(claim.job_id).state == "claimed"
        assert store.stop_singleton("evidence-owner", epoch)
