# Explicit recovery of one retained Server publication attempt

Accepted contract under ADR 0169 for the third W7 component of
`REPOMAP-CLOE-SERVER-PARITY1`. Implementation, scoped proof and independent
resulting-source acceptance remain separate stages.
The operator's current manual roadmap continuation owns ordinary product
selection. No dependency, image, native qualification or complete local test
authority is inferred.

## Problem and alternatives

ADR 0168 corrects false failure labels after publication. Such attempts must
remain unsettled until exact durable publication evidence is available. Server
currently has no explicit way to settle the retained record. Re-running source
capture can consume resources, and assigning failure on absent evidence is
unsafe. The status quo preserves correctness but retains objects indefinitely.

Select explicit, positive-only reconciliation of one named attempt. Defer
automatic reconciliation, scanning all records, failed-record reclamation,
deletion, receipt rewriting, publication retry and coordinator state mutation.
Existing SQLite Local reconciliation is unchanged.

## Product surface

`cloe ops retained-attempt inspect|settle --graph ID --operation-id ID
--attempt N`, with the existing home/config and optional psql selector and JSON
output conventions. Inspect is read-only: no directories, lock files, artifact
spools, database initialization or role changes. Settle is itself the explicit
single-record write action. No second confirmation ceremony is required.

Server homes only. Unknown/disabled graph and invalid identity are bounded
refusals before object or database work. The operation and attempt determine
exactly the existing SHA-256 attempt directory, without enumeration. Receipt
job and operation retain distinct nominal types, but current v1 fencing
requires equal text. Recovery rejects disagreement and preserves that
contract. No user-provided filesystem path is accepted.

Closed result fields are operation, result, reason, retention state, artifact
proof, publication proof and metadata write state. They contain categorical
values only. Paths, graph/database/repository IDs, operation/job IDs, hashes,
source bodies, exception text and credentials are not echoed. Success exit 0
means inspected accepted proof, already settled, or installed terminal mark;
held/refused/uncertain is nonzero. Documentation must distinguish inspection
from settlement and metadata settlement from new graph publication.

## Evidence chain

1. Derive the canonical Server publication root using existing configuration
   semantics. Below that root, require real owner-only directories without
   symlink traversal. Preserve and revalidate directory identities. An absent
   namespace is held and is never created by inspection.
   The resolved root itself is an owner directory without group/other write
   permission; it may retain the existing Server intermediate-directory 0755
   mode. Do not require or chmod it to 0700. Its `attempts` child and all
   selected directories below it remain 0700. A writable or foreign anchor
   refuses rather than being repaired.
2. Read one private regular, single-link, current-UID `portable-result.json`
   through a bounded no-follow read. Reuse the existing 64 KiB metadata cap.
   Reject duplicate JSON keys. Accept only the current Server record fields;
   a legacy missing manifest reference is held. Preserve exact original bytes,
   digest and file identity for compare-and-replace.
3. Open the existing artifact store without creation. Add an optional
   `create=False` constructor argument with the current default unchanged.
   Verify manifest bytes with the existing 16 MiB manifest limit. The optional
   recovery reader also limits receipt materialization to that existing
   `DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes` value: this is a new recovery
   admission rule, not an existing receipt-parser or publication limit.
   Larger receipts stay held. Stream the bundle with its existing 1 GiB bound
   and 1 MiB header
   limit, consuming EOF to verify the full digest and length without body
   materialization, staging, row ingestion or target-code execution. Compute
   the existing domain-prefixed bundle hash over all streamed bytes, including
   the trailer, and match the extraction receipt's bundle identity. Validate
   the bounded canonical header with existing semantic rules; do not claim a
   fresh whole-bundle row-conformance check or parser-family qualification.
   The accepted implementation additionally checks bounded canonical frame
   structure/order/stage representation and recomputes family stream
   checksums. It creates no spools and performs no semantic graph admission;
   these are retained-byte integrity checks under the same stream/line bounds.
4. Validate manifest, extraction receipt and header against one another and
   the selected graph, including exact manifest/vector, four generations,
   receipt attempt, bundle reference and ID, candidate, protocol and semantic
   identities. The receipt's recomputed ID and content-addressed objects bind
   all retained bytes. A serialized receipt is not independent publication
   authority or a new parser-family witness.
5. Read one historical complete graph run through the existing readback
   authority/driver path. Match configured repository identity, receipt job
   and attempt, and the operation-derived portable stage ID as well as the
   generation and portable publication fields. Compare against the full
   validated retained evidence. A superseded complete run can prove that this
   attempt published; it need not be the latest run. A different graph or
   operation, matching artifact IDs alone, absence, malformed data or transport
   failure cannot settle anything. Do not query or modify live coordinator
   control records, stages, leases, graph rows or schema.

## Metadata transition and concurrency

Only `publication-reconciliation` to `terminal-accepted` is permitted. Reuse
the existing 24-hour terminal retention period. Never write terminal-failed.
An already terminal-accepted record with matching exact proof is idempotent;
do not extend its expiry. Settle may re-sync its record and attempt directory
to resolve a prior installed-but-sync-failed outcome. Inspect never does so.
Terminal-failed or malformed terminal metadata is
held, without rewriting historical state.

Use one stable owner-private nonblocking `.server-retention.lock` in the Server
publication root, outside both `attempts` and the selected attempt directory.
This avoids introducing a file into Local's existing legacy shared-attempt
inventory. Do not unlink the lock
file: waiters and pruners must refer to the same inode. A single namespace lock
avoids per-attempt lock-file garbage and deletion/recreation races. Hold it
only around metadata read/modify/write or prune, not while hashing artifacts,
running a worker, or reading PostgreSQL. Busy is a bounded hold/refusal, with no
new numeric timeout. Server initial-record creation, terminal marking,
annotation and terminal pruning cooperate. SQLite Local's existing graph-lock
and durability rules remain unchanged.

After artifact and database proof, reacquire the namespace lock and revalidate
the original record bytes/digest, inode and directory chain. Any change is
held; never replace a newer record. Before mutation, exclusively retain the
exact old record as an owner-private backup in the attempt directory. Flush
backup bytes and directory. Install the new canonical JSON through an
exclusive temporary file, file fsync, same-directory atomic replace and
directory fsync. Do not delete the original backup. Normal terminal retention
pruning can remove the whole owned expired attempt later.

Failure before replacement leaves the old record unchanged. Failure after
replacement yields uncertain metadata durability, preserves backup, and never
rolls back or rewrites publication. A retry can inspect exact proof and the
current state. Primary BaseException identity must survive secondary close and
cleanup faults; failures with no primary remain observable. Close every FD.

This is cooperating-process exclusion on local POSIX storage. It does not
claim protection from a hostile same-UID actor, uncooperating programs, remote
filesystem locking anomalies or power-loss guarantees above the synced
attempt directory. No current graph publication is created or accepted by
this bookkeeping action.

## Proof and rollback

Required focused unit tests cover closed parsing and privacy; no-create
inspection; graph/operation/attempt mismatch; missing/corrupt objects; bounded
stream/hash/header reads; foreign/symlink/hardlink/mode/inode changes; busy lock;
compare-and-replace races; backup/fsync/install failure stages; expiry
idempotence; exact FD cleanup; and all cooperating writer/pruner paths.

Required containerized integration uses a real portable worker and temporary
PostgreSQL migrations. Publish an attempt, inject a post-return settlement
fault, inspect and settle exact retained proof with no second worker, verify
historical proof after a newer publication, and refuse graph/operation or
database mismatches without changing records or graph state. Use existing
fixture and harness patterns. Keep pure validator matrices in unit tests.
Test CLI parsing and categorical output; run Local retention nonregressions.
All scoped runs use the canonical runner and `--no-coverage`.

Final source review must independently falsify custody, graph-bound authority,
historical proof and concurrent replacement. No pass or full W7 closure is
preclaimed. Rollback removes the explicit command/readback helper and
retention-lock participation through a forward source change. Existing
terminal records and backups remain valid; no schema migration or history
rewrite is needed. Quality admissions remain append-only.

## Source binding and parent disposition

Readback joins public.runs.repository_id to public.repositories.id and binds
repository_identity plus portable_stage_id, receipt job/attempt, complete
status and all evidence-derived publication fields. Parse the full existing
RunPublicationReceipt shape and validate remaining mode/fence fields. Compare
family receipts to the bounded bundle trailer. The configured graph identity
and stage hash bind graph and operation alongside the current v1 required
textual operation/job equality. StageOwner and PublicationHandoff enforce that
equality in the current publisher; no new unequal-identity authority is added.
Reuse execute_ops_json_readback and its existing resolved authority; no runtime
initialization is permitted. Canonical Server attempts/portable-publication
layout distinguishes Local retention paths. All four retention mutators plus
capture-error whole-attempt deletion must participate in the Server lock.

The parent accepts this selection before implementation under the current
manual roadmap continuation. The read-only source review identified the
capture-error deletion participant and receipt-memory limit correction; both
are incorporated. This is not source verification or hosted qualification.
