# ADR 0076: Restart Publication Fencing

## Status

Accepted within REPOMAP-PRODUCT5-HOSTED-QUAL2-REPAIR4; amended in REPAIR5 and
REPAIR6. Independent REPAIR7 review deferred identified proof, cleanup,
reflection and health-contract defects. REPAIR8 produces their bounded
corrections; dispatcher review and container qualification remain pending.

## Date

2026-10-03

## Context

Abandonment classification and its newly written completion timestamp do not
prove that an orphan publisher has stopped. A process result made from booleans
also cannot establish reap, descendant cleanup, or current durable ownership.
The graph lease epoch supplied to a refresh capability was not persisted in the
control database, preventing exact currency validation after restart.

## Decision

Persist the existing transaction-derived graph lease epoch on both the attempt
and graph lease with an append-only control migration. Existing records receive
zero, which conveys unavailable binding and cannot authorize recovery closure
as `not_started`. Automatic quarantine or lease release without a verified graph
fence is unsafe.

Instead, a distinct store-owned `quarantine_legacy_attempt` transaction safely
restores graph schedulability:
- It locks the replacement singleton, old current reconciliation attempt, and
  exact expired matching graph lease (`lock_and_validate` with strictly opt-in
  `allow_legacy`).
- It requires both stored attempt and graph lease epochs to be exact legacy zeros,
  and the old singleton epoch to be strictly less than the replacement singleton.
- It never infers an old epoch or mints a `not_started` proof, keeping file
  uncertainty intact.
- It mints a new positive replacement graph lease epoch using `txid_current`.
- The configured fence callback accepts an optional `replacement_lease_epoch`
  only for exact legacy zeros.
- Graph storage installs the higher singleton and new lease epoch, committing
  and verifying readback before control revalidates currency, quarantines the
  attempt with `commit_unknown` and `legacy_zero_epoch`, and removes the exact
  expired lease and clears running coalescing state.
- Absence of fence callback, storage route change, lock contention, or identity
  mismatch keeps the lease pending without releasing storage.
- Terminal attempt closure occurs only after a verified graph fence.
- Startup recovery handles the zero-epoch legacy path as a special case before
  ordinary closure, preserving file uncertainty.
Preserve protocol version 1, public graph vocabulary, and the read-only MCP API.

Restart closure locks the replacement singleton, current job/attempt and exact
graph lease. It refuses a live prior lease, mismatched identity or unavailable
epoch binding. While those locks are held, it advances graph storage publication
authority to the replacement singleton and verifies committed readback. Only
then may it close the attempt's exclusive publication decision and persist
`not_started`. Failure retains reconciliation uncertainty. Requeue follows the
existing reconciliation transaction. A crash between graph fencing and control
closure leaves uncertainty and permits a subsequent idempotent fencing pass.

All control and storage fencing transactions enforce bounded PostgreSQL lock
and statement timeouts (`lock_timeout = 250ms` and `statement_timeout = 1000ms`)
before `ensure_repository` or any work. Swallowed `SET LOCAL` exceptions are
removed. Contention on durable locks rolls back cleanly and surfaces observable
expected refusals (`LockNotAvailable`, `QueryCanceled`, `StaleDurableAuthorityError`)
and unexpected sanitized diagnostics. Contention liveness remains pending the
actual row-lock integration owner; it is not established by unit timeout checks.
Unexpected error types are retained in a 32-entry coordinator diagnostic ring,
separate from the latest recovery report, until acknowledged by sequence or
evicted by later errors. A successful heartbeat does not erase them. Messages,
identities and storage routes are never retained. The ring is process-local;
`ops coordinator-health --repo-map-home <operator-selected-home> --json` exposes
the ring as `health.recovery_diagnostics`. Each item has an unexpected-error
category, a validated exception class name as its summary, and a monotonic
sequence. Readback is bounded to 32 entries and never acknowledges entries.
The maintained service acknowledgement method clears only entries through the
observed sequence; it is not a new transport operation. Expected contention
remains in aggregate refusal counts, separate from unexpected errors.

Creation also emits a warning through the structured Python logger
`repomap_kg.coordinator.startup_recovery`, including the same redacted fields.
Emission occurs outside the ring lock. Unexpected reader and reconciliation
programming failures reach this surface without raw exception messages; raised
reconciliation errors retain their original identity. The ring does not survive
restart. External log retention depends on the operator's existing stderr/log
collector; this phase supplies no persistent diagnostic database or configured
retention guarantee. The
optional recovery-mixin callback requests singleton renewal before and after
each bounded recovery item. Whether sweeps of up to 256 items preserve
heartbeat liveness remains pending the actual row-lock integration owner.

Only the real process supervisor, after reap and descendant cleanup of an
unforgeable per-launch registration created inside the maintained real capability
worker path, registers an opaque result identity. The registration binds the
exact capability identity and expected command line; alternate workers, arbitrary
identities, and injected process doubles are rejected. Reaped registrations and
issued `WorkerFencingProof` instances are strictly single-use; any reuse or stale
proof verification fails under current durable locks. REPAIR6 persists a SHA-256
registration digest on the locked current attempt before child spawn. The digest
binds the real supervisor nonce and exact job, attempt, instance, singleton and
graph lease epochs; the secret token is never stored. Closure carries that digest,
validates it under the same currency locks, and retains a durable consumed flag
while holding those locks through the file decision. A consumed attempt cannot
register another launch. Abandonment and attempt turnover clear the registration.
Result tracking uses weak references and monotonic registration keys, independent
of reusable object addresses. Database execution of this lifecycle remains pending.

The storage publication transaction is designed to enforce the durable fence.
Orphan atomic rollback and replacement publication remain pending until the
sealed-capability worker publication integration owner executes green. The
owner must seal attempt A before turnover, drive the maintained worker execution
through actual storage prepare/finalize, inspect durable graph and publication
rows after refusal, and prove replacement attempt B can publish. A handcrafted
StageOwner transaction does not establish this property.

The REPAIR8 executable owner drives `refresh_worker.main`, its real protocol
start, heartbeat wrapper, refresh execution and final storage transaction.
It retains the real `before_publication` check. Separate cases assert refusal
after A's claim and validated staging, before any final storage transaction when
replacement authority creates truthful closure, and a deterministic turnover
immediately after the maintained check passes. The latter
continues through the unchanged final transaction, asserts durable fence refusal
and empty publication relations, and then exercises replacement storage authority
through a real store-issued claim for a distinct configured graph. Published B
jobs and attempts reach committed terminal control state and release their lease.
It does not claim automatic control retry scheduling
after `transaction_started` uncertainty: that attempt remains reconciliation
required. These are authored assertions; Docker denial prevents executable
PostgreSQL proof in the current producer. Independent source review remains pending.

SQLite qualification helpers keep original read, timeout and protocol failures
primary while requesting orderly termination and bounded reap for ordinary
children. One managed emergency escalation path verifies process/group absence
and requires authentic coverage settlement; it never fabricates a receipt after
killing. Explicit abrupt children retain their settlement/kill path. This is a
maintained-source enforced ownership contract. Python reflection can bypass
runtime guards; the static owner rejects explicit `object.__setattr__` and
`object.__getattribute__` counterexamples, tracked aliases, and existing direct
kill/signal bypass forms. It does not claim Python internals are unreachable.

The alternatives are completion timestamps, caller assertions, or filesystem
decisions alone; all permit an orphan publisher or stale proof to outlive their
authority. A durable graph fence enforces refusal in the publication transaction
itself. A new coordinator service or protocol handshake is unnecessary.

## Compatibility and Verification

### REPAIR8 health schema correction

The original maintained v1 CLI validator requires exactly the eight health
sections plus `health_schema_version` and `status`. It rejects unknown top-level
fields; neither the transport's public-result validation nor the health
compatibility tests grant an optional-field extension mechanism. Adding
`recovery_diagnostics` therefore changes the health schema shape and requires
**health schema version 2**. This is distinct from the unchanged transport and
worker protocol version 1.

The service emits v2 with a required diagnostics array, including `[]` when
empty. The current CLI accepts the original exact v1 shape and the exact v2
shape, treating absent v1 diagnostics as empty when formatting.
V1 with the new field, v2 without it, unknown fields, unsupported versions and
non-integer versions are refused. Older v1-only CLI validators refuse v2;
forward compatibility or version negotiation is not claimed. Existing
diagnostic bounds, redaction and explicit acknowledgement semantics remain.
The durable-job spec and serialization/client unit and integration owners
record this correction before implementation.

Existing control databases require the ordinary backup-first migration workflow;
this phase does not migrate operator databases. Rollback must first stop all
coordinators and publishers and restore a verified backup. Reverting the repair
does not safely revoke a graph fence already installed.

Unit owners cover fabrication, alternate-worker rejection, proof reuse rejection,
stale currency, lease identity and closure failure. Container integration owners
cover hard abandonment, active lease refusal, replacement fencing, old-owner
publication rollback in actual publication transactions, lock contention timeouts
preserving singleton liveness, and zero-epoch legacy quarantine restoring
schedulability. The assembled system scenario observes reconciliation history
and rejects the old storage owner via the publication transaction path.
Qualification remains incomplete until those container owners execute.
