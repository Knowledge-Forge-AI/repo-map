# Recover retained bookkeeping for one Server attempt

This command is for a Server publication that may have committed while its
final retained-record settlement failed. It checks existing evidence; it does
not refresh a graph, launch extraction, retry publication or change coordinator
state. SQLite Local continues to use its separate existing reconciliation.

Use the exact operation identity and attempt from the original operation or
its owned coordinator record. Current v1 publication fencing requires the
receipt's job identity to carry the same text as that operation. Recovery
checks both this constraint and the independent stage binding. The command does not
enumerate attempt directories or discover identities. If the selected identity
is unavailable, retain the unsettled state for operator investigation.

Inspect first, using the same configured Server home that owns the attempt:

```sh
cloe ops retained-attempt inspect --repo-map-home "$CLOE_HOME" \
  --graph demo --operation-id "$operation_id" --attempt 1 --json
```

Inspection reads one existing private record, its retained manifest, receipt
and streamed bundle, then checks exact historical PostgreSQL publication
evidence. It creates no directories, lock files or artifact spools and makes
no retained-metadata or graph writes. The application requests read-only
database work through the existing configured readback route. A caller-owned
psql wrapper or client configuration retains its existing authority.

A matching complete historical run is sufficient even if a newer run has
since become current. Matching only a job, artifact hash or graph name is not
sufficient: graph repository, selected operation's stage, attempt, generations
and retained evidence must agree. Missing, unavailable or conflicting proof
leaves the record unsettled. An oversized, legacy or unsafe record is held;
the command does not guess or repair it.

After a positive inspection, settle that same selection explicitly:

```sh
cloe ops retained-attempt settle --repo-map-home "$CLOE_HOME" \
  --graph demo --operation-id "$operation_id" --attempt 1 --json
```

Settlement repeats verification and rechecks the original record under the
Server retention lock. It retains a private backup before atomically marking
the selected record terminal-accepted with the existing 24-hour expiry. It
does not mark failure from absence, delete artifacts or update graph rows.
Already accepted metadata is idempotent; its expiry is not extended.

Closed categorical output distinguishes inspected proof, completed settlement,
held/refused work and uncertain metadata durability. Private operation, graph,
database and artifact identities, paths, bodies and exception text are not
included. Nonzero results require inspection of the category; they do not
authorize a retry of extraction or publication. Lock contention or a changed
record leaves the current record intact. A post-install sync failure preserves
the backup and reports uncertainty; a later explicit settle can recheck and
sync accepted metadata without changing its expiry.

This is cooperating-process exclusion on local POSIX storage. It does not
provide distributed locking or protection from a hostile same-UID process.
The command's successful result concerns one retained record and an already
completed publication, not current-generation freshness, image acceptance or
whole-product qualification.

The optional recovery reader materializes receipts up to 16 MiB and streams
bundles within the existing 1 GiB total and 1 MiB line bounds. Larger receipts
remain held without changing the normal publication contract. Retained backups
stay with their attempt; ordinary safe terminal pruning may remove the whole
expired owned attempt later.

See [ADR 0169](../adr/2026/11/0169-positive-server-retained-attempt-recovery.md)
and the [recovery contract](../specs/cloe-server-retained-attempt-recovery-v1.md).
