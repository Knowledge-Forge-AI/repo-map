# ADR 0061: Production Publisher Bundle Consumption And Route Selection

## Status

Accepted for the STR-PUB5 local implementation. Deployment, branch publication,
and promotion remain pending hosted qualification and PYLEN-SCALE14-FIX1.

## Date

2026-09-02

## Context

ADRs 0059 and 0060 define the portable manifest, extraction receipt, publication
bundle, validator, and database-independent worker. They intentionally did not
select that route for production refresh. Direct and coordinator forced-full
refresh now need one route into the existing staged PostgreSQL publisher without
granting database or publication authority to the worker or creating a dual writer.

## Decision

Supported direct and coordinator forced-full refresh use `portable-worker-v1`.
The parent resolves graph and attempt authority, derives an owner-private artifact
root from control configuration, seals all selected source bytes, and launches the
existing supervised worker with no source-checkout root or database credential under
standard process limits (60s process deadline, 10s heartbeat). There is no automatic
fallback after portable execution starts.

The worker emits untrusted `receipt1:` and `bundle1:` objects containing all seven
publication families under `stage-unassigned-v1`. The sole staged publisher verifies
object version, canonical bytes, length, digest, schema, bounds, ordering, complete
family inventory, semantic identities, snapshot vector, privacy, provenance,
terminal state, capability, claim, lease, generation, and candidate authority before
staging. Only the publisher derives the physical PostgreSQL stage identity and
projects the placeholder while using the existing COPY, validation, merge, receipt,
fencing, rollback, cleanup, and `commit_unknown` reconciliation path.

An additive Liquibase migration adds an all-null or all-present portable binding to
the final `runs` receipt. Historical receipts remain valid legacy state (readback
filters require only core receipt fields and treat portable columns as optional). The
binding records the manifest, extraction receipt, bundle, candidate, snapshot vector,
engine and protocol identities, execution mode, fences, family receipts, and the
physical stage as private execution evidence. No duplicate portable authority is added
to `ingestion_stages`; existing stage ownership already supplies transient execution
authority.

Owner-private filesystem artifacts are attempt-owned. Unresolved publication state
uses non-expiring `publication-reconciliation` retention, while deterministic
publication failures (e.g. storage/validation errors before commit) and authoritatively
accepted runs receive bounded 24-hour terminal retention and may be removed only by
exact owner/device/inode, regular-file, link-count, mode, and no-follow checks. Public
readback exposes only route/protocol and semantic IDs, source-binding count, and family
counts; it excludes locators, source roots, snapshot contents, physical stage IDs, and
credentials.

## Atomicity And Recovery

The final graph transaction revalidates stage ownership, generation, singleton and
graph-lease fences, writes all seven families and the complete receipt together, and
leaves the prior accepted graph visible on validation, load, merge, constraint,
cancellation, or receipt failure. A worker exit or bundle presence is never commit
evidence. An uncertain commit retains exact portable evidence and is accepted only
when authoritative graph readback matches every portable receipt field; absence or
mismatch classifies as absent/conflicting without inventing success or authorizing a
second candidate.

## Rollout And Rollback

There is no live dual writer or shadow accepted-table write. Offline fixture parity
may continue. Pipeline qualification precedes merge and deployment. Rollback uses
operator deployment of a previously qualified release, or an explicitly selected
compatible route before a new attempt begins; semantics never switch mid-attempt.
In-flight portable attempts settle or reconcile under their recorded protocol, and
legacy receipts remain readable.

## Consequences

PostgreSQL remains canonical graph authority and the existing staged publisher is
the only graph mutator. The worker remains database-, registry-, lifecycle-, and
publication-independent. This decision grants no cloud deployment, federation,
multi-tenancy, billing, remote acquisition, or Go control-plane authority.
