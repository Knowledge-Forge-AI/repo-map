"""Exact bound-attempt terminal readback for SCALE16 supervision."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

import psycopg

from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.publication_readback import read_latest_receipt_bearing_publication
from repomap_kg.storage.run_authority import read_run_authority
from scale15_actual_path_readback import read_scale15_terminal_state
from scale15_terminal_contracts import (
    BoundRefreshExpectation,
    ExpectedRefreshAuthority,
    PublicationState,
    StageState,
    TerminalReadback,
)


@dataclass(frozen=True)
class BoundAttemptEvidence:
    """Private attempt relationships projected from terminal storage."""

    exact_stage_attempt: RunPublicationAttempt | None
    exact_stage_run_id: int | None
    newest_stage_attempt: RunPublicationAttempt | None
    latest_run_id: int | None
    latest_publication_attempt: RunPublicationAttempt | None
    latest_publication_run_id: int | None
    canonical_publication_attempt: RunPublicationAttempt | None
    canonical_publication_run_id: int | None


def classify_bound_attempt(
    base: TerminalReadback,
    bound: RunPublicationAttempt,
    evidence: BoundAttemptEvidence,
) -> TerminalReadback:
    """Require exact launch, stage, run, and receipt relationships."""

    if (
        evidence.exact_stage_attempt is None
        and evidence.newest_stage_attempt is None
        and base.stage_state is StageState.PRE_STAGE_RECONCILED
        and base.publication_state
        in {
            PublicationState.NOT_PUBLISHED,
            PublicationState.PRIOR_PUBLICATION_PRESERVED,
        }
    ):
        return base
    if evidence.exact_stage_attempt is None:
        state = (
            PublicationState.FOREIGN_PUBLICATION_DETECTED
            if evidence.newest_stage_attempt is not None
            and evidence.latest_publication_attempt
            == evidence.newest_stage_attempt
            else PublicationState.FOREIGN_STAGE_DETECTED
            if evidence.newest_stage_attempt is not None
            else PublicationState.LAUNCH_STAGE_MISSING
        )
    elif evidence.exact_stage_attempt != bound:
        state = PublicationState.LAUNCH_ATTEMPT_MISMATCH
    elif evidence.newest_stage_attempt != bound:
        state = (
            PublicationState.FOREIGN_PUBLICATION_DETECTED
            if evidence.latest_publication_attempt == evidence.newest_stage_attempt
            else PublicationState.FOREIGN_STAGE_DETECTED
        )
    elif (
        evidence.exact_stage_run_id is None
        or evidence.latest_run_id != evidence.exact_stage_run_id
    ):
        state = PublicationState.LAUNCH_ATTEMPT_MISMATCH
    elif base.publication_state is PublicationState.PUBLISHED:
        if (
            evidence.latest_publication_attempt != bound
            or evidence.canonical_publication_attempt != bound
        ):
            state = PublicationState.FOREIGN_PUBLICATION_DETECTED
        elif (
            evidence.latest_publication_run_id != evidence.exact_stage_run_id
            or evidence.canonical_publication_run_id != evidence.exact_stage_run_id
        ):
            state = PublicationState.LAUNCH_ATTEMPT_MISMATCH
        else:
            return base
    elif base.publication_state is PublicationState.NOT_PUBLISHED:
        if evidence.latest_publication_attempt != bound:
            return base
        state = PublicationState.LAUNCH_ATTEMPT_MISMATCH
    elif base.publication_state is PublicationState.PRIOR_PUBLICATION_PRESERVED:
        if evidence.latest_publication_attempt != bound:
            return base
        state = PublicationState.LAUNCH_ATTEMPT_MISMATCH
    else:
        return base
    return replace(base, publication_state=state)


def read_scale16_terminal_state(
    psql_args: Sequence[str],
    expectation: ExpectedRefreshAuthority | BoundRefreshExpectation,
    *,
    psql_command: str = "psql",
) -> TerminalReadback:
    """Read terminal state using the exact child-created attempt when bound."""

    prelaunch = expectation.prelaunch if isinstance(
        expectation, BoundRefreshExpectation
    ) else expectation
    base = read_scale15_terminal_state(
        psql_args,
        prelaunch,
        psql_command=psql_command,
        pre_binding=not isinstance(expectation, BoundRefreshExpectation),
        pre_stage=isinstance(expectation, BoundRefreshExpectation),
    )
    if not isinstance(expectation, BoundRefreshExpectation):
        if base.publication_state is PublicationState.PUBLISHED:
            return replace(
                base,
                publication_state=PublicationState.LAUNCH_AUTHORITY_MISSING,
            )
        return base

    bound = expectation.publication_attempt
    authority = read_run_authority(
        psql_args,
        prelaunch.repository_name,
        psql_command=psql_command,
    )
    canonical = read_latest_receipt_bearing_publication(
        psql_args,
        psql_command=psql_command,
    )
    latest = authority.latest_recorded_run
    publication = authority.latest_receipt_bearing_publication
    params = _psycopg_connection_params_from_psql_args(psql_args)
    exact_attempt: RunPublicationAttempt | None = None
    exact_run_id: int | None = None
    newest_attempt: RunPublicationAttempt | None = None
    with psycopg.connect(
        host=params.get("host"), port=params.get("port"),
        user=params.get("user"), dbname=params.get("dbname"),
    ) as connection:
        repository = connection.execute(
            "SELECT id FROM repositories WHERE name = %s "
            "ORDER BY id DESC LIMIT 1",
            (prelaunch.repository_name,),
        ).fetchone()
        if repository is not None:
            repository_id = int(repository[0])
            exact = connection.execute(
                "SELECT COALESCE(s.job_id, s.operation_id), s.attempt, "
                "(SELECT CASE WHEN count(*) = 1 THEN min(r.id) END "
                "FROM runs AS r WHERE r.repository_id = s.repository_id "
                "AND r.started_at = s.created_at) FROM ingestion_stages AS s "
                "WHERE s.repository_id = %s AND s.execution_mode = 'direct' "
                "AND COALESCE(s.job_id, s.operation_id) = %s "
                "AND s.attempt = %s "
                "ORDER BY s.created_at DESC, s.stage_id DESC LIMIT 1",
                (repository_id, bound.job_id, bound.attempt),
            ).fetchone()
            newest = connection.execute(
                "SELECT COALESCE(job_id, operation_id), attempt "
                "FROM ingestion_stages WHERE repository_id = %s "
                "ORDER BY created_at DESC, stage_id DESC LIMIT 1",
                (repository_id,),
            ).fetchone()
            if exact is not None:
                exact_attempt = RunPublicationAttempt(
                    JobId(str(exact[0])), AttemptNumber(int(exact[1]))
                ).validate()
                exact_run_id = None if exact[2] is None else int(exact[2])
            if newest is not None:
                newest_attempt = RunPublicationAttempt(
                    JobId(str(newest[0])), AttemptNumber(int(newest[1]))
                ).validate()
    evidence = BoundAttemptEvidence(
        exact_attempt,
        exact_run_id,
        newest_attempt,
        None if latest is None else int(latest.run_id),
        None if publication is None else publication.receipt.attempt,
        None if publication is None else int(publication.run_id),
        None if canonical is None else canonical.receipt.attempt,
        None if canonical is None else int(canonical.run_id),
    )
    return classify_bound_attempt(base, bound, evidence)


__all__ = [
    "BoundAttemptEvidence",
    "classify_bound_attempt",
    "read_scale16_terminal_state",
]
