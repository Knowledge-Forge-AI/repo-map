# ADR 0169: Positive-only recovery of one retained Server attempt

* **Status:** Accepted by the parent under the operator's current manual
  roadmap continuation, before implementation. Scoped proof and independent
  resulting-source review remain pending.
* **Date:** 2026-11-07
* **Phase:** `REPOMAP-CLOE-SERVER-PARITY1`, third selected W7 component.
* **Contract:** [Server retained-attempt recovery](../../../specs/cloe-server-retained-attempt-recovery-v1.md).
* **Related:** [ADR 0168](0168-bounded-server-context-and-refresh-outcomes.md).

## Context

ADR 0168 prevents refresh cleanup failures from asserting that a possibly
committed publication rolled back. Its retained Server attempt must remain in
`publication-reconciliation` until exact durable evidence resolves it. The
current Server implementation has no explicit metadata-settlement operation;
SQLite Local has separate, existing graph-lock-backed reconciliation.

Blindly rerunning capture wastes work and can create a new attempt. Marking
an absent or uncertain publication failed would assert a fact without proof.
Leaving every such record indefinitely is safe but unnecessarily retains its
sealed objects after successful publication is provable.

## Decision

Add `cloe ops retained-attempt inspect|settle` for exactly one configured
Server graph, explicit operation ID and positive attempt number. This is an
ordinary roadmap implementation selection, not a new dependency, runtime
image, database schema, role or complete-test selection.

Inspect performs no filesystem writes, lock-file creation, object spooling,
database/role initialization or graph publication. Settle is an explicit
single-record metadata action. It cannot launch extraction, retry publication,
write coordinator state, scan all attempts, delete artifacts, or settle failure
from absent evidence. SQLite Local refuses this Server-only command and keeps
its existing behavior.

The operation and attempt select the existing hashed Server attempt directory.
Receipt job and operation are distinct nominal identities whose text must
agree under the current v1 stage-owner and publication-handoff contracts.
Preserve that constraint and reject disagreement. Validate the
retained manifest, receipt, full bundle content digest, bounded canonical
header/trailer and their cross-identities. Verify the exact graph repository,
operation-derived portable stage ID, receipt job/attempt, generations and
portable evidence against one complete PostgreSQL run. A superseded complete
run can prove that this attempt published. It need not be the current run.
Malformed, absent, unavailable or conflicting proof leaves metadata unchanged.

Use existing current-UID, private-mode, no-follow, regular single-link checks
and the existing 64 KiB retained-record cap. Opening an artifact store for
inspection must not create its directories. Manifest materialization retains
its 16 MiB limit. The optional recovery reader also bounds receipt bytes by
`DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes` (currently 16 MiB), before reading.
This new consumer admission rule does not alter receipt generation or the
general 4 GiB artifact/publication limit. Oversized receipts remain held.
Bundles reuse the 1 GiB streaming and 1 MiB line limits. No new row staging,
parser-family admission or target-code execution occurs.

The parent also accepts bounded structural frame checks while streaming:
canonical framing, order, stage representation and recomputed family stream
checksums bind the retained trailer to the existing database family receipts.
This retains the same total/line limits and bounded memory. It does not run
the ingestion validator, create row spools, reclassify semantic claims or admit
a new parser-family witness. It is additional retained-byte integrity proof.

The resolved publication root is the authority anchor. On first creation, the
owning capture path must create it deterministically as owner-only `0700`,
before shared attempts or the retained-record lock are created; this remains
true under an ambient umask such as `002`. An existing anchor is admitted only
when current-UID-owned and without group/other write permission; the existing
`0755` anchor admission is preserved. An existing group-writable root is
explicitly refused and held for separate operator repair. Inspection never
chmods an unsafe legacy namespace, and this change performs no permission
migration. Directories below the anchor, including `attempts`, the selected
attempt and artifact-store directories, remain owner-only.

Only `publication-reconciliation` to `terminal-accepted` is writable. Reuse
the existing 24-hour retention period. A matching terminal-accepted record is
idempotent without extending expiry. Terminal-failed records are held rather
than rewritten. Closed categorical output exposes no private identities,
paths, source bodies, credentials, hashes or raw exception messages.

## Concurrency and durability

One stable private nonblocking `.server-retention.lock` file in the Server
publication root coordinates all Server retained-record mutations. It lives
outside `attempts` and the selected attempt directory. Never unlink that lock.
Hold it for metadata read/modify/write and removal only, not artifact hashing,
worker execution or PostgreSQL proof. Acquisition is nonblocking: a busy lock
yields a refusal without introducing a bounded-wait policy. The current Server
path shape is distinguished from SQLite Local's graph-scoped
namespace; Local locking and directory-chain durability remain unchanged.
Keeping the lock outside `attempts` also preserves Local's existing inventory
of legacy shared attempt directories; it introduces no non-directory entry
that would be classified unsafe there.

Participants include initial retained-record creation, terminal marking,
annotation, terminal pruning **and** capture-error whole-attempt removal in
`capture_portable_candidate`. A busy cleanup lock preserves the attempt and
reports cleanup uncertainty; it cannot authorize unguarded deletion.

After proof, reacquire the lock and compare the original record's bytes,
digest, inode and namespace identities. Refuse a concurrent replacement.
Retain a verified owner-private backup of the exact old metadata before
installing the terminal record. Fsync backup and directory, then use an
exclusive temporary file, file fsync, atomic same-directory replacement and
directory fsync. Preserve backup after settlement. Existing terminal pruning
may later remove the whole expired owned attempt.

A pre-install failure leaves the old record intact. Post-install sync failure
reports uncertain metadata durability and never rolls back graph publication.
A settle retry may sync an already accepted record and its directory without
extending expiry; inspect never syncs. Preserve primary BaseException identity
across secondary cleanup failures, and close all owned descriptors.

This is cooperating-process exclusion on local POSIX storage. It does not
promise protection from hostile same-UID actors, uncooperating writers,
distributed filesystem anomalies, or power-loss durability above the synced
attempt directory. A successful action settles retained bookkeeping; it does
not publish, admit a new image, or prove a current graph generation.

## Alternatives

* Keep all uncertain records forever: correct but leaves provably completed
  attempts without a usable settlement path.
* Automatically reconcile during refresh: mixes recovery writes with capture
  and complicates retry authority; deferred.
* Use the existing job/attempt readback alone: it lacks a repository predicate
  and does not independently bind the selected operation's stage; rejected.
* Mark absent proof failed, rerun a worker, or delete the attempt: unsafe
  inference or unnecessary new work; rejected.
* Lock only atomic replacement: permits stale read/modify/write and does not
  coordinate pruning or capture-error deletion; rejected.

## Acceptance and rollback

Exact scoped unit and containerized integration owners must prove the accepted
positive path, historical publication, foreign graph/operation and conflicting
proof refusal, real private-file custody, no-create inspection, lock
contention, compare-and-replace, backup/install/sync faults, idempotence,
descriptor cleanup and unchanged Local behavior. The staged-ingestion custody
unit owner, context-work-bounds unit owner, PostgreSQL-context integration
owner, Server-refresh-custody integration owner and retained-attempt-recovery
integration owner are the required entry owners. These are required proof
owners, not pass claims; the rollback-failure, default-witness, publication-
root-permission, namespace-lock-contention and positive-settlement gaps remain
unproved until their scoped selectors run. The connected positive path uses a
real portable worker and disposable PostgreSQL publication; settlement must
not launch a second worker. CLI output must remain categorical.

The permission proof includes an ambient umask `002`: a first-owned
publication root is `0700` before any shared attempt or lock, an existing
`0755` anchor is admitted, and an existing group-writable root is refused and
held without chmod or migration. No result or hosted qualification is claimed
by this contract.

The parent owns proof and final integration. An independent APGR source review
must challenge graph-bound authority, custody and concurrent replacement.
No pass, coverage result, whole W7 closure or hosted qualification is preclaimed.
No complete local suites, coverage, SDK/application build, native parser/model
qualification, public-main change or automatic successor campaign is granted.

Rollback removes the command and its helpers in a forward source change.
Existing terminal records and backups remain valid. No schema/data migration,
history rewrite or quality-debt increase is required; quality admissions remain
append-only. ADR 0168's automatic-reconciliation exclusion still applies to
refresh itself; this ADR separately authorizes the explicit operator command.
