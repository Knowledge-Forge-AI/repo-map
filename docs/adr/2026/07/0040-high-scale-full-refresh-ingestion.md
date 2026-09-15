# SCALE0 High-Scale Full-Refresh Ingestion Architecture Decision

## Title

SCALE0 High-Scale Full-Refresh Ingestion Architecture

## Status

Accepted on 2026-07-14.

This ADR opens the language-neutral `SCALE` epic. It selects an architecture
for high-scale forced-full refresh, but it does not implement the selected
storage redesign. No production source, schema, migration, dependency, graph,
or private-repository artifact is changed by SCALE0.

SCALE1 adds the accepted staging and legacy-family clarification below. The
SCALE0 evidence and decision remain historical and unchanged.

## Context

RepoMap has completed the bounded ASYNC architecture and the Go epic through
GO23. ASYNC is closed. The Go epic is closed and is not reopened by this ADR;
GO24 remains a possible later recommendation only after the SCALE epic exits.

The remaining release-blocking problem is storage throughput for a complete
forced-full refresh at Argo CD scale. Extraction and canonicalization can
finish, while the current storage transaction remains active for more than two
hours, consumes approximately one PostgreSQL core, publishes nothing, and
rolls back to an empty graph when cancelled.

SCALE is language-neutral. The same storage architecture must serve Python and
any later supported language extractor without creating a Go-specific loader,
second publication protocol, or alternate lifecycle authority.

Governing predecessor records are:

- `docs/status/2026/07/12/00468-go22-full-refresh-memory-correction.md`;
- `docs/status/2026/07/12/00469-go23-go-epic-closure.md`;
- `docs/adr/2026/07/0039-synchronous-and-asynchronous-architecture.md`;
- `docs/specs/durable-job-and-coordinator-contract.md`;
- `docs/status/2026/07/14/00535-async-close-durable-coordinator-architecture.md`;
- `docs/contrib/refactor-roadmap.md`; and
- the current storage migrations, row adapters, streaming path, publication
  readback, lifecycle, baseline, and drift implementations.

## GO22 evidence

GO22 corrected the client-memory failure without changing final table shape,
canonical identities, graph vocabulary, publication semantics, or the
one-transaction boundary. It retained lazy row adaptation, deterministic
strict-UTF-8 SQL chunks, bounded backpressure into `psql`, one `BEGIN`, and one
`COMMIT`.

The correction made smaller dogfood practical. The RepoMap runner completed two
refreshes in approximately 13 seconds each with approximately 229 MiB maximum
process RSS. The recipes workload completed in approximately 86 and 100
seconds with approximately 445 MiB maximum process RSS. Both retained
deterministic counts and baseline/drift parity.

The correction did not make the Argo CD storage path practical. The accepted
GO22 record reports that the corrected path completed extraction and
canonicalization, remained active for more than two hours in storage, kept
PostgreSQL near one full core, did not publish, and rolled back to an empty
graph after cancellation. The worker's observed RSS reached approximately
11.9 GiB before later sampling fell, while PostgreSQL remained approximately
155 MiB in the reported observation. No complete publication, repeat, stored
baseline, preflight baseline, or drift proof was obtained.

The diagnosis was not an extractor defect:

```text
millions of individual deterministic upserts inside one PostgreSQL transaction
are operationally impractical at Argo CD scale
```

GO22 explicitly deferred set-based loading, `COPY`, staging, run-membership,
and transaction/storage redesign to a new language-neutral architecture.

## ASYNC constraints and opportunities

SCALE uses the closed ASYNC contracts as existing authority boundaries:

- one semantic coordinator and one semantic worker implementation;
- durable jobs and attempts with at-least-once delivery;
- one mutating graph lease and singleton fencing;
- source, configuration, extractor, and canonicalizer generations;
- complete publication-generation receipts;
- commit-unknown reconciliation;
- explicit cancellation and forced descendant cleanup;
- polling-first desired-state reconciliation;
- automatic refresh coalescing with manual intent independence;
- bounded worker protocol and path-free public diagnostics;
- explicit direct and coordinator execution with no silent fallback;
- read-only MCP; and
- CLI-owned graph and control-database lifecycle.

The worker, queue, stage transfer, `COPY` completion, and stage validation are
not publication proof. Only the accepted final publication transaction and its
matching complete receipt establish freshness. SCALE adds no second
publication authority and does not change the accepted ASYNC fencing or
reconciliation contracts.

## Problem statement

The current path performs a deterministic SQL statement for each row-shaped
storage operation. Conflict checks, index maintenance, joins, and result
handling are repeated at row granularity. GO22 reduced client-side memory but
did not reduce the PostgreSQL executor and statement-count cost. At Argo CD
scale, the current transaction has an unacceptable duration and cancellation
rollback interval.

The required outcome is a practical authoritative forced-full refresh with:

- bounded client and PostgreSQL resource use;
- deterministic output equivalent to the current storage contracts;
- one all-or-nothing final publication;
- restart, cancellation, stale-worker, and commit-unknown recovery;
- no private source disclosure or target-code execution; and
- one implementation shared by direct and coordinator modes.

## Goals

SCALE selects and incrementally implements a storage architecture that:

1. loads normalized storage rows without statement growth proportional to row
   count;
2. preserves raw ordinals, payload hashes, stable keys, canonical keys,
   graph-key versions, evidence identity, conflict behavior, and deterministic
   ordering;
3. validates duplicates, missing references, and conflict conditions before
   final publication;
4. preserves an all-or-nothing final graph mutation and complete publication
   receipt;
5. makes staging ownership, cleanup, restart recovery, and fencing explicit;
6. keeps the final graph schema and public read semantics unchanged unless a
   separately accepted compatibility decision is required;
7. keeps `psql` as a supported comparison and fallback boundary;
8. provides direct and coordinator execution through one ingestion
   implementation; and
9. proves the result through a protected Argo CD dogfood campaign.

## Non-goals

SCALE does not silently expand into:

- incremental per-file graph mutation or unchanged-file caching;
- watcher implementation or event-driven graph mutation;
- remote workers or multi-coordinator scaling;
- cloud, SQLite, or Desktop architecture;
- Go-specific extraction or storage redesign;
- canonical identity or graph-vocabulary redesign;
- MCP mutation;
- automatic graph deletion;
- partial graph publication; or
- a new runtime dependency, connector, ORM, Arrow/Parquet format, native
  extension, or Rust/Go loader.

The current final-table retention semantics are not redefined in SCALE0. The
current model updates stable identities and retains run-scoped history; it does
not provide a general source-removal delete phase. Source-removal retirement
would require an explicit read-path and compatibility decision, not an
unreviewed performance optimization.

## Current ingestion model

The current forced-full path is:

```text
discover observations
→ canonicalize
→ adapt file, relationship, raw, and canonical rows
→ generate deterministic SQL chunks
→ stream chunks through psql with bounded backpressure
→ commit one final transaction
```

The inspected execution path is `refresh_graph()` through the storage loaders
and `_load_stream` chunk builders. The prefix starts a transaction, upserts the
repository, creates a run, and captures identifiers with `\\gset`. The legacy
path emits file and relationship statements. The raw path emits a conflict-hash
check plus an upsert per observation. Canonical nodes, edges, evidence, and
links are emitted as row-shaped operations. Completion, commit, and summary
readback finish the stream.

The current final write families are:

| Family | Current contract | SCALE0 finding |
| --- | --- | --- |
| `repositories` and `runs` | repository identity, run state, generations, publication receipt | final schema and receipt columns are retained |
| `files` | repository/path identity and `last_seen_run_id` | stable-key update semantics are retained |
| legacy `nodes`, `evidence`, `edges` | repository-scoped stable identities and joins | no source-removal delete phase is currently present |
| `raw_observations` | run/ordinal identity and payload hash | run-scoped history is retained |
| `canonical_nodes`, `canonical_edges` | repository, graph-key version, and canonical identity | canonical keys and uniqueness remain unchanged |
| canonical evidence and links | run-scoped evidence and stable-key links | set-based joins must preserve link semantics |

The current legacy readback is repository-wide. Canonical readback exposes
`last_seen_run_id` but does not use it as a general current-run filter. This is
why SCALE0 selects a staging and merge architecture while deferring any change
to stale-row retirement semantics.

## Measured bottleneck model

For `F` file rows, `R` relationship rows, `O` raw observations, `N` canonical
nodes, `E` canonical edges, `V` canonical evidence rows, `L_n` node-evidence
links, and `L_e` edge-evidence links, the current generated SQL statement
model is:

```text
6 + 3F + 4R + 2O + N + E + V + L_n + L_e
```

The fixed six are repository/run setup, completion, commit, and summary
operations. The two `\\gset` commands are psql metacommands and are not counted
as SQL statements. The model is a source-derived characterization, not a
performance claim about an Argo CD run.

SCALE0 ran a disposable public-safe PostgreSQL probe with 20,010 input rows,
20,000 unique node keys, deterministic duplicate replacements, existing final
rows, evidence links, one injected merge failure, and cancellation. The
storage-family counts and modeled current-path statement count were:

| Family | Synthetic rows |
| --- | ---: |
| repository/run setup | 1 |
| legacy files | 20,000 |
| relationship node/edge rows | 20,010 |
| raw observations | 20,010 |
| canonical nodes | 20,000 |
| canonical edges | 20,010 |
| evidence | 20,010 |
| node-evidence links | 20,000 |
| edge-evidence links | 20,010 |
| completion and summary | 2 |
| modeled current SQL statements | 280,096 |

The probe comparison was:

| Variant | Logical SQL statements | UTF-8/text-equivalent payload | Elapsed | Client CPU | PostgreSQL peak CPU sample | PostgreSQL peak RSS | WAL delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| row-wise upsert | 60,032 | 8,624,370 bytes | 1.32 s | 0.74 s | 42.6% | 22.5 MiB | 15,612,376 bytes |
| multi-row `INSERT` batches | 125 | 2,054,569 bytes | 0.34 s | 0.16 s | 34.6% | 24.8 MiB | 15,612,376 bytes |
| prepared/pipelined row-wise | 60,032 | wire payload not isolated | 0.37 s | 0.37 s | 46.8% | 22.5 MiB | 15,612,352 bytes |
| `COPY` plus set-based merge | 7 | 1,249,580 bytes | 0.25 s | 0.04 s | 37.5% | 31.3 MiB | 20,609,232 bytes |

The probe process maximum RSS stayed between 49.1 and 50.8 MiB across the
variants. PostgreSQL reported no temporary-file delta in this workload. The
injected merge failure left the final row count unchanged. Cancellation of a
disposable sleeping backend was observed in 0.05 seconds. These figures are
synthetic controls and are not Argo CD evidence. They demonstrate that
round-trip reduction helps, while `COPY` plus set-based merge changes statement
growth from row-shaped to family-shaped work.

A separate disposable rollback probe inserted 20,000 generated rows, injected
a merge failure, and measured explicit transaction rollback at 0.0001 seconds;
the final row count was zero. This is a local control measurement, not a
large-transaction rollback guarantee.

The PostgreSQL documentation supports the relevant distinction: `COPY FROM
STDIN` transfers data through the client connection, `ON CONFLICT DO UPDATE`
provides an atomic insert/update outcome but rejects duplicate proposals that
would affect one target row more than once, and pipeline mode reduces waiting
for many small operations but does not itself turn row-wise work into set-based
loading. See [COPY](https://www.postgresql.org/docs/current/sql-copy.html),
[INSERT](https://www.postgresql.org/docs/current/sql-insert.html), and
[libpq pipeline mode](https://www.postgresql.org/docs/current/libpq-pipeline-mode.html).

## Candidate architectures

### Candidate A: attempt-scoped staging, `COPY`, and set-based merge

Candidate A is selected.

```text
extract and canonicalize
→ create or resume an attempt-owned staging header
→ stream normalized rows through COPY into regular staging tables
→ commit staging as prepared data, not publication
→ validate counts, duplicates, hashes, and references with set-based queries
→ revalidate lease, fencing, generations, and staging ownership
→ merge final tables with bounded set-based statements
→ write completion and the complete publication receipt
→ commit the authoritative final publication transaction
```

The selected staging form is durable, regular, WAL-logged tables keyed by a
staging header containing graph, job, attempt, fencing, generation, row-count,
payload/checksum, state, and expiry metadata. There is one logical staging
scope per graph/job/attempt. A connection is only a transport session; it is
not the ownership boundary. The header and row tables remain recoverable after
the COPY connection closes.

The first staging schema should use one table per normalized storage family or
one equivalently auditable family partition, with an attempt key and stable
identity/ordinal columns. It should use only the indexes needed for ownership,
deterministic ordering, duplicate detection, and set-based joins. It should
not add foreign keys from staging to final tables; validation performs those
checks before the publication transaction.

The final merge preserves the current final-table schemas and uniqueness
constraints. It uses `INSERT ... SELECT`, `UPDATE ... FROM`, `DELETE` only if a
separately accepted retention contract permits it, and joins on existing
stable/canonical keys. It must not use stage row order as a canonical identity.

The dependency order is explicit: repository/run metadata, files, legacy
nodes and evidence, legacy edges, raw observations, canonical nodes, canonical
edges, canonical evidence, and finally canonical node/edge links. Relationship
edges join staged source and target identities; canonical evidence joins raw
run/ordinal rows; links join stable canonical identities. Missing references,
duplicate identities, and conflicting payloads fail validation before a final
merge statement can publish them.

Regular staging is selected over temporary or unlogged tables:

- temporary tables are connection-scoped and disappear when a transfer session
  closes, which prevents committed staging recovery across worker restart;
- unlogged tables reduce WAL but are truncated after an unclean shutdown and
  are not crash-safe or standby-replicated; and
- regular tables support explicit ownership, reconciliation, bounded cleanup,
  and restart recovery at the cost of measured WAL and disk usage.

PostgreSQL documents the crash-safety tradeoff for [unlogged
tables](https://www.postgresql.org/docs/current/sql-createtable.html) and the
session scope of [temporary tables](https://www.postgresql.org/docs/current/sql-createtable.html#SQL-CREATETABLE-TEMPORARY).

### Candidate B: direct final-table `COPY` with run membership

Candidate B is rejected for SCALE0. It would require run identity on every
final row family, new or changed uniqueness, current-run read predicates,
retention and old-run cleanup, greater storage amplification, and compatibility
work for every final query. It would change public read semantics before the
current retention contract is specified. Existing run and publication receipt
columns are not sufficient to turn all legacy rows into atomically selected
current-run rows.

Run membership remains a future option only if an explicit compatibility phase
proves that current final-table semantics cannot support the required
retirement behavior. It is not added merely to make loading easier.

### Candidate C: shadow tables or replacement partitions

Candidate C is rejected for the initial implementation. Swapping a complete set
of shadow tables or partitions would require graph-scoped isolation for every
foreign-key-connected table, lock and ownership analysis, schema/partition
management, old-copy retention, and read compatibility. Many local graphs and
the current migration model make this a larger authority and migration change
than staging-only tables. It remains a later architecture option if set-based
merge cost remains release-blocking after SCALE7.

### Candidate D: optimized row-wise ingestion

Multi-row insert, prepared statements, and pipeline mode are useful controls
and may remain useful for small graphs or fallback operation. The disposable
probe reduced 60,032 row-wise statements to 125 multi-row statements, but the
operation remained row-shaped and still maintained final indexes and conflict
logic per proposed row. Pipeline mode reduced elapsed time in the local probe
but retained 60,032 statements and higher sampled server CPU than the
multi-row control. These techniques are not sufficient as the primary Argo CD
architecture.

### Candidate E: incremental storage

Candidate E is not selected. Incremental mutation would change the correctness,
retention, watcher, cancellation, and publication problem. The SCALE objective
is an authoritative forced-full refresh. Incremental storage remains a separate
future architecture unless evidence shows it is inseparable from a correct
full-refresh implementation.

## Connector comparison

| Connector or technique | Strength | SCALE0 decision |
| --- | --- | --- |
| existing streamed `psql` SQL | mature current transaction and fallback path; exact current SQL oracle | retain for compatibility, migration/lifecycle, comparison, and emergency fallback |
| `psql \\copy` / `COPY FROM STDIN` | can transfer bulk rows through stdin | technically viable, but typed row framing, resumable attempt ownership, and staged receipt handling are less direct in the current stream seam |
| existing Psycopg 3 `Cursor.copy()` | existing dependency, parameter/type boundary, explicit COPY lifecycle, block streaming, cancellation through the connection | selected as the future high-scale bulk transport boundary; implement only in a later phase |
| Psycopg binary `COPY` | likely lower text parsing/escaping overhead; block writes avoid per-row dumpers | performance candidate for SCALE2; binary format is not claimed as production-ready until parity and type-dumper tests pass |
| multi-row SQL | fewer round trips and statements | control/fallback, not the primary architecture |
| prepared/pipelined execution | reduces round-trip waiting for many small operations | control/fallback; it does not replace set-based loading and pipeline mode cannot carry COPY in libpq pipeline mode |
| server-side function/procedure | can centralize operations | not selected; it would hide transaction, diagnostics, deployment, and rollback boundaries without removing the need for staging or set-based relations |
| asyncpg, pgx, Rust, Arrow, Parquet, native extensions | possible specialized transports | not evaluated as implementation choices; no new connector or dependency is authorized |

The existing project dependency metadata already includes
`psycopg[binary]>=3.2,<4`; SCALE0 adds no dependency. The high-scale phase must
keep `psql` as a fallback and comparison oracle until a later parity gate proves
the new transport. Psycopg's [COPY documentation](https://www.psycopg.org/psycopg3/docs/basic/copy.html)
supports block writes and binary mode, while warning that binary loading has
strict type-dumper requirements. SCALE2 owns the text/CSV versus binary wire
format decision within this accepted connector boundary.

## Schema comparison

SCALE0 inventories final tables as follows:

| Final table family | Final schema in SCALE0 | Staging counterpart | Final index/uniqueness change | Read-path change |
| --- | --- | --- | --- | --- |
| `repositories` | unchanged | header metadata only | none | none |
| `runs` | unchanged, including generation and publication receipt columns | run values are validated from staging header | none | none |
| `files` | unchanged | file rows | none beyond staging indexes | none |
| legacy `nodes` | unchanged | relationship/file-node rows | existing stable identity retained | none |
| legacy `evidence` | unchanged | relationship/file-evidence rows | existing identity retained | none |
| legacy `edges` | unchanged | relationship edge rows | existing identity retained | none |
| `raw_observations` | unchanged | raw rows with source ordinal/hash | existing `(run_id, ordinal)` retained | none |
| `canonical_nodes` | unchanged | canonical node rows | existing canonical-key uniqueness retained | none |
| `canonical_edges` | unchanged | canonical edge rows | existing composite identity retained | none |
| canonical evidence | unchanged | canonical evidence rows | existing run/key uniqueness retained | none |
| canonical node/edge links | unchanged | link rows | existing link keys retained | none |

The later staging migration will add staging-only header, row tables, ownership
indexes, and cleanup metadata. It will not add final run membership, change
canonical identities, change graph-key version, change public query predicates,
or add new publication metadata. A migration is therefore required for the
staging schema, but no final-table schema migration is selected by SCALE0.

Run-membership is not required by the selected architecture. Attempt membership
and completeness live in staging; existing final run and receipt fields carry
publication identity. Any future final run-membership design must first prove
that the current repository-wide read semantics can change compatibly.

## Transaction comparison

### One transaction including COPY and merge

This option keeps staging and final changes under one database transaction. It
has a simple rollback story and no durable intermediate data, but it retains a
long transaction, keeps staging and final locks/resources open, increases WAL
and vacuum pressure, makes restart progress opaque, and makes cancellation
rollback proportional to the entire transfer plus merge.

It is a valid disposable control and may be useful for small graphs. It is not
the selected high-scale lifecycle.

### Staging committed separately, final merge atomic

This option is selected. The staging transaction commits only the attempt-owned
stage and its complete counts/checksum. It never updates final graph rows or
claims freshness. The final merge transaction is separate and authoritative:

1. it revalidates job/attempt, graph lease, singleton fencing, all four
   generations, staging ownership, completeness, and expected counts;
2. it creates or updates the final run and performs all set-based final-table
   work;
3. it writes the complete publication-generation receipt and run completion;
4. it records the summary needed for readback; and
5. it commits once.

If the final transaction fails or is cancelled, PostgreSQL rolls back all final
graph mutations. The committed stage remains non-public and is reconciled or
cleaned. If the client cannot determine whether the final commit succeeded,
publication is `commit_unknown` until receipt reconciliation resolves it.

The selected design accepts durable abandoned-stage cleanup as the price for a
shorter and more observable transfer boundary. No cleanup action may delete or
modify final graph rows.

## Publication and fencing model

The authority sequence is:

1. The existing coordinator claims a job, creates an attempt, acquires the
   graph lease, and obtains the singleton fencing epoch. Direct mode obtains
   its explicit local operation authority through the same semantic interface.
2. The worker creates a stage header containing graph, job, attempt, fencing,
   source/configuration/extractor/canonicalizer generations, expected families,
   and expiry. The header is `loading`.
3. Psycopg COPY transfers rows into stage tables. Counts and deterministic
   checksums are recorded. The stage transaction commits and the header becomes
   `prepared`. This is not publication.
4. Set-based validation checks duplicate/conflicting keys, raw hash
   invariants, canonical endpoint existence, evidence references, link
   references, family counts, and generation consistency. Validation success is
   not publication.
5. The final transaction rechecks the stage header and all publication
   authority values immediately before merge and again at the final publication
   fence. A stale owner, lease, fencing epoch, generation, or attempt cannot
   publish.
6. Final-table merge, completion, receipt, and summary occur in the one final
   transaction. Only a committed matching receipt establishes freshness.
7. The worker emits a bounded result. The coordinator reconciles the durable
   receipt and publication state; it never infers freshness from worker exit,
   queue state, stage state, or COPY completion.

Direct and coordinator modes call the same ingestion and merge implementation.
Direct mode supplies an explicit local operation authority; coordinator mode
supplies the durable job/attempt and fencing authority. The implementation may
use a small authority adapter, but it may not fork SQL semantics or silently
fall back from one mode to another.

The final merge cannot rely on an unbounded coordinator-side read from another
connection. The authority adapter must make the fencing token part of the
database-local atomic final write or otherwise provide an equivalent monotonic
fence that the final transaction verifies. If control and graph storage are
separate databases and that atomic fence cannot be proved, SCALE5 must stop;
best-effort cross-database checks are not an accepted publication design.

## Failure and recovery model

| Failure point | Required result |
| --- | --- |
| before stage creation | no final change; attempt is failed or cancelled under existing ASYNC state rules |
| during COPY | transfer connection is cancelled or closed; its uncommitted batch rolls back; incomplete stage is marked for cleanup |
| after prepared stage, before merge | final graph is unchanged; stage is retained for safe retry only while attempt/generation authority remains valid |
| validation failure | no final change; bounded category is recorded; stage is quarantined or cleaned after reconciliation |
| final merge statement failure | final transaction rolls back completely; no committed receipt; stage remains non-public until cleanup |
| lease or fencing loss | final publication fails closed; stale worker cannot commit an accepted receipt |
| process crash before final commit | stage and attempt are reconciled on restart; final graph is unchanged unless a matching receipt proves commit |
| commit result unknown | state becomes `commit_unknown`; coordinator waits for old owner/backend quiescence and reads the authoritative receipt before retry or terminal cancellation |
| committed receipt found | attempt becomes succeeded; stage cleanup is safe after receipt and graph readback checks |
| no receipt and rollback/absence proven | attempt can be retried or cancelled according to existing job policy; stage is reused only if ownership and generations remain valid |
| conflicting receipt or generation | attempt is quarantined; it is never silently retried |

Idempotency is based on durable job/attempt identity, stage ownership, existing
final unique identities, and the complete publication receipt. A repeated
final merge for the same valid attempt must produce the same logical graph and
receipt, not duplicate stable rows. Duplicate proposals that could produce
order-dependent results must be rejected or resolved by an explicit stable
ordinal rule before `ON CONFLICT` merge.

### Staging cleanup and abandoned attempts

Stage headers have bounded lifecycle states such as `loading`, `prepared`,
`merging`, `published`, `abandoned`, `failed`, and `cleanup_pending`. Cleanup
first reconciles publication evidence, then deletes only rows belonging to the
stage header. It uses bounded batches, an expiry/grace period, and the existing
lease/fencing rules. Startup recovery scans expired headers and attempts. A
stage with unknown final publication is retained until receipt reconciliation;
an incomplete or invalid stage is not reused by a new authority.

Regular staging is therefore graph-scoped and attempt-scoped, not
connection-scoped. Its row count and byte count are observable without exposing
source paths or row contents.

## Cancellation

Cancellation during extraction or row adaptation follows the existing worker
protocol. Cancellation during COPY closes or cancels the COPY connection and
waits for the stage transaction to resolve. Cancellation during set-based
validation or final merge cancels the database operation, waits for rollback,
and verifies that no final receipt was committed. Forceful worker and
descendant cleanup remains the ASYNC responsibility.

Cancellation at the final commit boundary is not treated as a successful
cancel. It becomes `commit_unknown` until the authoritative receipt proves
commit or rollback. A cancelled stage is not publication proof and cannot
overwrite a newer accepted generation.

## Privacy and source protection

SCALE0 uses only committed source, schema, test, and public-safe synthetic
evidence. The disposable probe used generated identifiers and values, a
disposable local PostgreSQL cluster, and no target repository.

The protected Argo CD clone may be inspected read-only during the later
dogfood campaign. RepoMap must not execute its tests, builds, generators,
hooks, binaries, scripts, dependency installation, package initialization, or
network operations. No target source, path, graph content, database identity,
credential, backup, raw observation, SQL value, process dump, or private
baseline may be committed or reported.

Public diagnostics remain bounded and path-free. Staging metadata exposes only
categories, counts, sizes, state, and safe identifiers already permitted by
the ASYNC worker protocol.

## Performance and resource bounds

SCALE0 proposes the following provisional acceptance bounds. SCALE7 may
calibrate them with representative disposable workloads, but the calibrated
values must remain public in the status record before Argo CD acceptance.

| Measure | Provisional bound |
| --- | --- |
| authoritative Argo CD refresh | complete and published within 30 minutes end-to-end; storage transfer/merge within 20 minutes |
| RepoMap process RSS | no more than 12 GiB absolute and no more than 2 GiB above the pre-storage canonicalization watermark |
| PostgreSQL working memory | no uncontrolled growth; measured backend/worker working RSS remains below 4 GiB for the graph operation and stays within preflight disk/memory budget |
| staging, WAL, and temporary disk | total operation remains within preflight free-space budget and no more than 3x normalized staged input bytes; temporary-file growth is reported |
| write statement scaling | one COPY per staged family plus bounded validation/merge statements; provisional total no more than 128 SQL statements excluding bounded COPY chunks, never proportional to row count |
| cancellation | terminal cancellation or `commit_unknown` classification within 60 seconds of worker cancellation request, followed by receipt reconciliation |
| rollback | injected merge failure and cancellation leave final counts, structural digests, and receipt unchanged; rollback settles within 5 minutes |
| repeatability | unchanged forced-full refresh produces exact structural/count parity and no baseline or drift change |
| cleanup | zero orphan stage headers/rows after the authorized cleanup window and zero stale publication |

The absolute memory bounds are campaign gates, not proof that the synthetic
probe predicts Argo CD. Each later phase must report elapsed time, client CPU,
maximum RSS, PostgreSQL CPU behavior, PostgreSQL memory, WAL growth,
temporary-file behavior, transaction duration, cancellation latency, and
rollback latency by storage family.

## Migration and compatibility

SCALE0 changes no production source or schema. SCALE1 may add staging-only
tables and indexes through a reversible migration after this ADR is approved.
The migration must not alter final table columns, final uniqueness,
canonical-key identity, graph-key version, public read predicates, publication
receipt columns, or control-database authority.

The current psql loader remains available as an explicit fallback and parity
oracle. A future high-scale path must be selected explicitly through the
accepted execution mode and must fail explicitly if its connector or staging
schema is unavailable. There is no silent fallback that could hide a partial or
uncertain publication.

Migration rollback is backup-first and bounded. Staging-only objects may be
removed only after no active attempt references them and after publication
reconciliation. Final graph data is never removed as part of staging cleanup.

## Rollout plan

The illustrative phase ladder is refined by evidence, but each phase remains a
bounded commit:

1. `SCALE1` — staging and attempt-ownership schema contract;
2. `SCALE2` — COPY transport and strict row encoding;
3. `SCALE3` — set-based legacy and raw merge;
4. `SCALE4` — set-based canonical graph merge;
5. `SCALE5` — publication fencing, receipts, reconciliation, and cleanup;
6. `SCALE6` — failure injection, cancellation, and rollback;
7. `SCALE7` — performance and resource calibration;
8. `SCALE8` — intermediate repository dogfood;
9. `SCALE9` — protected Argo CD dogfood; and
10. `SCALE-CLOSE` — final acceptance and exactly one GO24 recommendation.

SCALE1 is the next phase because the probe and schema inventory show that
attempt ownership, staging state, and final-schema compatibility are the first
implementation contracts to pin. No phase may skip deterministic parity or
publication failure proofs to reach Argo CD sooner.

### SCALE9 opening clarification — protected Argo CD dogfood

SCALE9 is the protected campaign phase and begins only after the pushed,
independently approved SCALE8 production path. The campaign must safely identify
the configured local Argo CD clone and isolated RepoMap graph, run bounded
preflight, verify backup-first lifecycle readiness, execute a staged
forced-full refresh, and accept it only after the final graph transaction and
complete publication receipt commit. Staging, COPY, validation, merge
completion, queue completion, and worker exit remain insufficient freshness
proof.

The campaign must repeat the unchanged refresh through an explicitly isolated
backup-first graph or database lifecycle and compare exact deterministic
structural projections, family counts, canonical identities, relationship and
evidence-link identities, receipt generations, publication state, graph
baselines, preflight baselines, and immediate drift. It must also prove
cancellation, rollback, cleanup, stale-fence rejection, and commit-unknown
reconciliation on an isolated or disposable attempt.

The target clone may be inspected read-only for registration, source-worktree
cleanliness, and static extraction inputs. RepoMap must not execute target tests,
builds, generators, hooks, binaries, scripts, package managers, dependency
installation, or network operations. Private paths, source text, graph data,
database identities, credentials, raw SQL, and process dumps remain outside
committed records. Any destructive cleanup requires explicit authorization and
a verified backup; retaining the graph is the default disposition.

SCALE9 must establish concrete public-safe duration, client-memory,
PostgreSQL-resource, WAL, temporary-file, cancellation, rollback, cleanup, and
statement-category thresholds from protected observations before final
acceptance. The Go epic remains closed during SCALE9. GO24 is considered only
by SCALE-CLOSE under the accepted recommendation rule.

## Dogfood ladder

The evidence ladder is:

1. generated public-safe unit and SQL-shape fixtures;
2. disposable PostgreSQL storage-family probes with duplicate, conflict,
   missing-reference, failure, cancellation, and rollback cases;
3. RepoMap runner dogfood with the current graph lifecycle;
4. recipes and other representative public-safe repositories;
5. a read-only source inventory and preflight of the protected Argo CD clone;
6. an isolated, backup-first Argo CD graph registration and forced-full
   refresh; and
7. repeated unchanged refresh, parity, receipt, rollback, baseline, and drift
   campaign evidence.

Direct and coordinator modes are tested at each applicable level through the
same ingestion implementation. No target-repository code is executed.

## Argo CD acceptance campaign

The SCALE epic cannot close until a protected local Argo CD campaign proves all
of the following without disclosing the clone's identity or contents:

1. preflight passes with bounded source and resource checks;
2. the graph is explicitly registered or an isolated dogfood configuration is
   used;
3. graph/database lifecycle is backup-first;
4. forced-full refresh reaches a committed final publication;
5. the complete publication receipt matches job/attempt, lease/fencing, and
   all four source/configuration/extractor/canonicalizer generations;
6. graph status and bounded family summaries are available;
7. an unchanged forced-full refresh repeats successfully;
8. structural and count parity is exact, ignoring only documented volatile
   run/attempt identifiers;
9. publication integrity is checked after each run;
10. a stored graph baseline and a preflight baseline are written;
11. an immediate drift check reports no graph or source drift;
12. disposable or isolated cancellation and injected-failure attempts prove
    rollback and no partial publication;
13. stage cleanup reports no orphan or stale staging rows;
14. the source worktree remains clean and untouched; and
15. cleanup or retention of the dogfood graph is an explicit authorized
    decision.

Direct extraction or staging completion alone is not success. A refresh without
an accepted committed publication is a failed campaign.

## GO24 recommendation rule

SCALE0 does not create GO24 and issues no final GO24 recommendation. At
`SCALE-CLOSE`, exactly one of the following statements must be issued:

```text
Recommend reopening the Go epic with GO24.
```

or:

```text
Do not recommend reopening the Go epic with GO24.
```

A positive recommendation requires all of these conditions:

- authoritative Argo CD storage-backed dogfood succeeds;
- repeated deterministic graph parity succeeds;
- memory and duration are acceptable against the calibrated public bounds;
- no Go-specific storage workaround is required;
- no extraction or canonicalization defect blocks parity; and
- a bounded, valuable set of remaining Go-specific work is identified.

Storage speed alone is not sufficient. If Argo CD succeeds and no material
Go-specific work remains, the final recommendation must leave the Go epic
closed.

## Rejected alternatives

SCALE0 rejects or defers:

- direct final-table COPY without staging and validation;
- run-membership on all final rows before a read-semantics decision;
- shadow-table or replacement-partition publication for the first redesign;
- row-wise batching, prepared statements, or pipeline mode as the primary
  high-scale solution;
- incremental graph mutation;
- a second coordinator or publication authority;
- a new PostgreSQL connector or language-specific loader;
- unlogged or temporary staging as the recovery contract; and
- target-repository execution or premature private Argo CD access.

## Risks

| Risk | Mitigation |
| --- | --- |
| set-based merge remains CPU- or index-bound | measure each family, inspect query plans in disposable data, and retain a bounded phase boundary before Argo CD |
| regular staging amplifies WAL and disk use | preflight free-space checks, family byte counts, cleanup leases, and SCALE7 calibration |
| duplicate stage rows produce nondeterministic `ON CONFLICT` behavior | deterministic ordinal policy plus pre-merge duplicate/conflict validation |
| abandoned stages leak sensitive intermediate data | durable owner/expiry state, receipt-first cleanup, bounded retention, and no raw values in diagnostics |
| stale workers publish after restart | generation, lease, singleton fencing, attempt ownership, and final transaction revalidation |
| commit result is unknown | preserve `commit_unknown` and reconcile only from the authoritative complete receipt |
| COPY transport diverges from psql semantics | byte/row parity tests, malformed Unicode tests, injected failures, psql fallback, and explicit connector rollout |
| source-removal retirement is underspecified | preserve current semantics in SCALE0 and stop before any incompatible final/read-path change |
| performance claims overfit the disposable probe | use the probe only as decision evidence and require intermediate plus Argo CD campaign measurements |
| a Go-specific path is introduced | keep the contract language-neutral and reject any loader requiring Go-only storage behavior |

## Decision

Select Candidate A: durable regular attempt-scoped staging, existing Psycopg 3
COPY as the future bulk transport boundary, set-based validation and merge,
and a separate final transaction that revalidates all ASYNC publication
authority and commits the complete receipt with the graph mutation.

The final graph schema, canonical identities, public read semantics, ASYNC
coordinator/worker authority, `psql` fallback, and direct/coordinator boundary
remain unchanged in SCALE0. Staging completion, worker exit, queue state, and
COPY completion are never publication proof. The final accepted transaction and
receipt are the only freshness authority.

Issue: approved.

## Consequences

Positive consequences:

- statement count becomes bounded by storage families and transfer chunks rather
  than rows;
- PostgreSQL can plan validation, joins, conflict resolution, and merge as
  set-based work;
- committed staging makes restart and cancellation observable without exposing
  intermediate data through final read paths;
- final publication remains all-or-nothing and compatible with ASYNC
  reconciliation; and
- direct and coordinator modes share one storage implementation.

Costs and consequences:

- a staging-only schema migration and cleanup lifecycle are required;
- WAL and disk usage must be measured rather than assumed away;
- the final merge can still be a large transaction and requires query-plan and
  rollback evidence;
- connector parity and binary/text COPY encoding need dedicated phases; and
- stale source-object retirement remains an explicit compatibility decision,
  not an incidental property of the loader.

## SCALE1 accepted clarification — staging ownership, schema, and legacy-family decision

SCALE1 is accepted as an additive contract phase. It does not implement
production COPY, a final set-based merge, staging-backed publication, legacy API
removal, an automatic cleanup daemon, Argo CD access, or a new dependency.

### Legacy-family inventory and outcome

The normal configured forced-full path derives all legacy, raw, and canonical
families from one `RawObservation` sequence. The current writer boundary is
`repomap_kg.ops.refresh.refresh_graph()` through
`repomap_kg.storage.main.load_file_observations()`,
`repomap_kg.storage.legacy_rows`, `repomap_kg.storage.canonical_rows`,
`repomap_kg.storage.sql_load`, and `_load_stream`. The current read and operator
surfaces were inspected in `storage.legacy`, `storage.sql_readback`,
`storage.sql_summaries`, `cli.storage_parser`, the legacy readback command
dispatchers, `server.mcp`, `server.ops`, baseline operations, drift checks, and
the storage connector-parity and legacy-readback tests.

| Family | Current product surface | Canonical replacement gap | SCALE1 outcome |
| --- | --- | --- | --- |
| `files` | Final file identity and joins for legacy nodes/evidence; legacy nodes, neighborhood, file-neighborhood, edge, host-mutator, and summary readback; baseline and drift counts | Canonical file nodes and evidence support graph-file views but do not replace the final `files` table or its legacy join semantics | **retain in SCALE high-scale ingestion** |
| legacy nodes | `FileRow` and `RelationshipRow` writers; legacy node, neighborhood, file-neighborhood, and host-mutator reads; explicit CLI `--legacy` modes and connector parity | `canonical_nodes` aggregates by canonical identity and does not preserve every observation-derived stable-key/readback contract | **retain through a compatibility adapter and schedule bounded decommissioning** |
| legacy evidence | File and relationship evidence writers; evidence joins in legacy neighborhoods, edges, host-mutator views, summaries, baselines, and drift | `canonical_evidence` is run/observation keyed and has different identity and link semantics | **retain through a compatibility adapter and schedule bounded decommissioning** |
| legacy edges | Relationship edge writer; legacy edge, neighborhood, and host-mutator reads; explicit CLI `--legacy` modes and connector parity | `canonical_edges` deduplicates and aggregates identities and cannot be treated as an exact replacement for legacy stable keys and evidence joins | **retain through a compatibility adapter and schedule bounded decommissioning** |

The compatibility-adapter outcome means that the SCALE staging rows feed the
existing final family with the current public semantics. It does not authorize
removal of a final table. A separate bounded decommissioning phase must produce
executable parity evidence, preserve or explicitly version CLI, connector,
summary, baseline, drift, and neighborhood behavior, and stop for user input if
public semantics or baseline meaning would change. No family is selected for
pre-ingestion retirement in SCALE1.

A public-safe canonicalization fixture provides the following family shape for
contract tests: 124 raw observations, 4 files, 217 distinct legacy node keys,
120 distinct legacy evidence keys, 116 legacy edges, 99 canonical nodes, 110
canonical edges, 124 canonical evidence rows, 236 canonical node-evidence
links, and 116 canonical edge-evidence links. These are fixture counts, not
Argo CD measurements.

The safe statement-cost inventory remains the SCALE0 symbolic model:

```text
6 + 3F + 4R + 2O + N + E + V + L_n + L_e = 280,096
```

Here `F` is the file-derived input count, `R` the relationship count, `O` the
raw-observation count, `N` and `E` the canonical node and edge counts, `V` the
canonical evidence count, and `L_n`/`L_e` the canonical node-evidence and
edge-evidence link counts. The current row adapters do not expose independent
statement terms for legacy nodes and legacy evidence: those writes are inside
the file-derived and relationship-derived groups. Therefore the public-safe
Argo contribution estimate is linear growth in these source-derived units, not
a private Argo row count; the formula must be remeasured by family in SCALE2–7.

The inventory also checked read-only MCP and operator exposure. The existing
MCP summaries report `files`, `legacy_nodes`, `legacy_edges`, and
`legacy_evidence`, while canonical node/edge, source-summary, project-summary,
search, neighborhood, and edge-explanation tools remain read-only. Baseline,
preflight-baseline, drift, graph-summary, CLI, and connector-parity consumers
therefore remain compatibility obligations for the three projected legacy
families and for `files`.

### Stage ownership and states

`ingestion_stages` is durable, regular, WAL-logged, repository-scoped, and
attempt-scoped by `stage_id`. It records the graph-local repository identity,
operation identity, coordinator or direct mode, coordinator instance when
applicable, job and attempt, singleton and graph-lease fencing values, all four
source/configuration/extractor/canonicalizer generations, timestamps and
expiry, the complete family manifest, expected and observed counts, per-family
checksums, normalized byte counts, validation and merge status, publication
reconciliation state, and cleanup eligibility. It persists no source root,
source text, credential, endpoint token, arbitrary command, raw diagnostic, or
connection string.

The accepted state machine is:

```text
loading → prepared | failed | cancelled | abandoned | quarantined
prepared → validating | cancelled | abandoned | quarantined
validating → validated | failed | cancelled | abandoned | quarantined
validated → merging | cancelled | abandoned | quarantined
merging → commit_unknown | failed | quarantined
commit_unknown → published | failed | cancelled | quarantined
published → cleanup_pending
failed | cancelled | abandoned → cleanup_pending
cleanup_pending → cleaned | quarantined
```

`cleaned` and `quarantined` are terminal. Replaying the current state with the
same complete owner tuple is idempotent. Cancellation after the final mutation
transaction begins is classified as `commit_unknown`; it is not converted to a
known cancellation by worker exit. `published` means that the associated final
publication transaction and receipt have been accepted; the stage itself is
never a freshness authority.

Every stage row carries `stage_id` and a deterministic family ordinal. Family
identity duplicates are admitted for set-based validation, while exact source
ordinals are unique within a stage. Validation must reject conflicting
duplicate proposals or choose one deterministic source-ordinal proposal before
the final merge; the final merge must not send order-dependent proposals to
`ON CONFLICT`. Staging tables have only ownership, ordinal, stable-identity,
endpoint, evidence, canonical-key, and expiry/cleanup indexes. They have no
cross-family foreign keys; referential conditions are validated set-wise.

The retained staging families are `stage_files`, `stage_legacy_nodes`,
`stage_legacy_evidence`, `stage_legacy_edges`, `stage_raw_observations`,
`stage_canonical_nodes`, `stage_canonical_edges`,
`stage_canonical_evidence`, `stage_canonical_node_evidence`, and
`stage_canonical_edge_evidence`. Their values mirror only the fields needed for
validation and the existing final merge. Existing final schemas, canonical
identities, graph-key versions, public read predicates, and baseline meaning
remain unchanged.

Per-family completeness evidence consists of row count, normalized byte count,
stable-key digest, payload digest, and the family manifest. The contract uses
explicit type tags for null, boolean, integer, float, string, list, and object
values, sorts by stable identity and payload, and hashes canonical UTF-8
records. It is independent of COPY chunk boundaries and input enumeration
order, and only aggregate counts and digests are public-safe.

### Control and graph authority

The ASYNC control database continues to own durable jobs, attempts, singleton
fencing, graph leases, coalescing state, and publication reconciliation. The
graph database continues to own repositories, runs, final graph rows, and
publication receipts. The local lifecycle currently derives a distinct control
database from the graph database, so an unproved best-effort cross-database
fencing read is not accepted.

SCALE1 therefore adds `graph_publication_authority`, a minimal graph-local,
monotonic projection for coordinator-owned accepted publication handoffs. It
records the accepted singleton and graph-lease fencing values, job/attempt,
coordinator instance, generations, last stage identity, and optional run
identity. It is not a second coordinator, does not claim a stage is published,
and does not replace the control database. SCALE5 must define and test the
transactional handoff, row lock/CAS, stale-attempt rejection, and
commit-unknown reconciliation that make this projection authoritative inside
the final graph transaction.

Direct mode creates an explicit operation/attempt stage with `execution_mode`
`direct`, no fabricated coordinator job or instance, and the existing direct
mutation authority. Coordinator mode carries the exact job, attempt, instance,
singleton fencing, graph-lease fencing, and generation tuple. Both modes use
the same future stage, validation, merge, receipt, and cleanup implementation;
there is no silent connector or mode fallback.

### Migration, cleanup, and rollback

Migration `src/main/resources/rdbms/2026/07/14-001-scale1-create_staging_contract.sql`
is additive to the final graph schema. It leaves final tables and public reads
unchanged, adds no run membership or trigger publication, and has no
cross-database authority assumption. The reverse procedure is backup-first:
lock and inspect `ingestion_stages`, reconcile receipts first, require no live
attempt, and refuse to proceed if any stage is unresolved, commit-unknown,
conflicting, or quarantined. Only cleaned stage rows may be dropped, followed
by the stage tables and graph-local projection in dependency order. The
migration includes the same refusal guard in its Liquibase rollback block.

Cleanup is retryable and stage-owned. It first reconciles publication, verifies
that no live attempt can resume the stage, deletes rows by `stage_id` in bounded
batches, preserves final graph rows, and reports bounded counts/categories.
Incomplete, failed, cancelled, abandoned, and published stages become cleanup
candidates only after their provisional expiry/grace policy; commit-unknown and
quarantined stages remain blocked until explicit reconciliation. SCALE7
calibrates retention and resource limits.

### SCALE1 boundary and next phase

SCALE1 implements only the pure state/owner/checksum contract, the additive
staging and authority schema, and disposable schema/rollback tests. Existing
Psycopg 3, `psql`, package metadata, and connector selection remain unchanged.
The next bounded phase is `SCALE2`, which must define strict row encoding and
COPY transfer against this contract before any set-based final merge is added.

## SCALE2 accepted clarification — COPY encoding and transfer

SCALE2 is accepted as a bounded transport phase. It uses the existing
synchronous Psycopg 3 `Cursor.copy()` and `Copy.write_row()` protocol against a
closed repository-owned catalog for the ten retained staging families. It does
not implement set-based validation, final-table merge, publication, cleanup
automation, legacy API removal, or Argo CD access.

The transport builds `COPY stage_table (fixed columns) FROM STDIN` with
`psycopg.sql.Identifier`, validates exact row columns and stage ownership,
preserves integer/boolean distinctions, and wraps JSONB values with the
existing Psycopg JSON adapter. It uses text-mode row COPY because the staging
families have different compatible schemas and JSONB values; binary COPY is a
later measured option, not an implicit optimization. The caller owns the
connection transaction. COPY success returns a bounded row count only; it does
not advance stage state, write a receipt, update graph authority, or establish
freshness. COPY failure leaves transaction recovery and commit-unknown
classification to the caller.

The SCALE2 unit and disposable PostgreSQL tests preserve delimiters, newlines,
backslashes, quotes, Unicode, JSONB, booleans, duplicate ordinal failure, and
explicit rollback without changing final graph rows. No dependency or
connector fallback was added. The next phase is `SCALE3` for set-based
validation and retained legacy/raw merge design.

## SCALE3 accepted clarification — retained legacy and raw set-based merge

SCALE3 implements the first set-based final-table mutation boundary for the
retained `files`, legacy node, legacy evidence, legacy edge, and raw observation
families. It does not implement canonical merge, graph replacement, publication
receipts, graph-authority updates, cleanup, legacy API removal, or protected
Argo CD access.

The final identity mapping is unchanged: files use `(repository_id, path)`;
legacy nodes, evidence, and edges use their existing repository-scoped stable
keys; raw observations use `(run_id, ordinal)`. The SQL proposals preserve the
current row-wise update columns, file joins, evidence links, source ordinals,
payload hashes, and metadata. The legacy families remain compatibility
projections required by current readback, CLI, MCP, summary, baseline, drift,
neighborhood, entrypoint, host-mutator, and connector-parity surfaces. Their
decommissioning remains a separate bounded migration.

The caller-owned builder returns eight statements: complete stage-owner and
run-ownership validation, duplicate/hash guards, and one set-based merge for
each retained family plus edge-reference validation. Exact duplicate proposals
are reduced by lowest deterministic family/source ordinal. Conflicting payloads,
incompatible existing raw hashes, missing edge nodes, missing edge evidence,
and raw ordinals outside the final integer range fail before publication. The
builder contains no `BEGIN` or `COMMIT`; an injected disposable failure proves
that the caller can roll back all final mutations.

`MergeContext` carries the full SCALE1 `StageOwner` tuple. The stage guard
compares graph, operation, job/attempt, mode, fencing snapshot, and generation
values with the durable graph-local stage header while permitting the
validated-to-merging transition. This is ownership validation,
not publication authority. SCALE5 must revalidate the current ASYNC control
lease, singleton fence, graph-local monotonic authority projection, generations,
stage completeness, and receipt handoff inside the final publication
transaction. No cross-database best-effort fence is introduced.

The disposable PostgreSQL proof uses the actual SCALE1 migration and SCALE2
Psycopg COPY boundary. It proves final-identity upserts, repeated idempotent
merge, duplicate refusal, missing-reference refusal, caller rollback, and no
canonical mutation. Eight statements per synthetic merge are evidence of the
new protocol shape only; SCALE7 remains responsible for measured duration,
memory, WAL, temporary-file, cancellation, and Argo CD resource bounds.

The next bounded phase is `SCALE4`, canonical set-based merge. It must retain
the same stage-owner, validation, transaction, final-schema, and no-publication
boundaries.

## Review triggers

Stop and request a new decision if evidence shows that SCALE requires:

- a new runtime dependency or connector;
- incompatible final-table schema or public read semantics;
- a second publication authority;
- partial publication;
- incremental storage rather than high-scale full refresh;
- changed ASYNC fencing, receipt, or commit-unknown contracts;
- target-code execution or disclosure of protected source;
- an unbacked destructive graph/database action; or
- resource bounds that cannot be met without shadow publication or a new
  retention model.

The next phase is `SCALE4` and is limited to canonical set-based validation
and merge. It must not publish a graph or access the protected Argo CD clone.

## SCALE4 accepted clarification — canonical set-based merge

SCALE4 accepts the canonical set-based mutation boundary for the five canonical
families retained by SCALE1: canonical nodes, canonical evidence, canonical
edges, canonical node-evidence links, and canonical edge-evidence links. It
preserves the existing final schemas, graph-key versions, canonical identities,
conflict-update columns, foreign keys, public canonical readback, connector
parity, baseline meaning, and drift meaning. The retained legacy node,
evidence, and edge compatibility projections remain in the high-scale path;
SCALE4 does not remove or bypass them.

The implementation returns eleven caller-owned SQL statements. It reuses the
SCALE3 `MergeContext` and complete stage-owner guard, rejects conflicting
typed proposals, reduces exact duplicates by lowest `family_ordinal`, checks
run-owned raw observation references, merges canonical nodes and evidence,
validates and merges edges, then validates and merges both link families.
Dependent edge and link statements resolve their final foreign keys only after
their predecessors have been merged in the same transaction. The canonical
merge preserves current row-wise behavior for `first_seen_run_id`,
`last_seen_run_id`, evidence raw-observation resolution, and link idempotency.

The builder contains no transaction control and does not update staging state,
publication authority, ASYNC leases, generations, receipts, old graph rows,
cleanup eligibility, or graph freshness. Merge completion, staging completion,
COPY completion, validation, queue completion, and worker exit remain distinct
from publication. SCALE5 must perform current ASYNC lease/singleton/generation
revalidation, graph-local authority handoff, complete receipt publication, and
commit-unknown reconciliation in the authoritative final transaction. No
cross-database best-effort fence is introduced by SCALE4.

Disposable public-safe PostgreSQL tests prove canonical identity preservation,
successful readback for nodes/evidence/edges/links, repeat idempotency,
conflict refusal, raw-reference resolution, and caller rollback. This is a
query-shape and correctness result, not Argo CD throughput or resource proof.
No dependency, final-schema migration, public read change, legacy API removal,
connector fallback, protected Argo CD access, or GO24 work is part of SCALE4.

## SCALE5 accepted clarification — publication fencing and reconciliation

SCALE5 defines the graph-database side of the final publication handoff. The
caller first obtains the accepted ASYNC control-database job, attempt, singleton,
graph-lease, and generation claim through the existing authority adapter. The
graph transaction does not read the separate control database and does not
assume cross-database atomicity. It locks and validates the exact stage owner,
run identity, completeness manifest, and graph-local authority projection
before any final-table merge is allowed.

The caller-owned sequence is:

1. lock the complete stage owner and running or already matching run receipt;
2. lock the graph-local authority row and reject a higher singleton or
   graph-lease fence;
3. transition `validated` to `merging`;
4. execute the SCALE3 and SCALE4 set-based final-table statements in the same
   caller transaction;
5. update the running `runs` row to `complete` with the complete publication
   receipt, or accept an already complete exact receipt;
6. update the monotonic `graph_publication_authority` projection and the stage
   to `published` in that same transaction; and
7. commit once.

The receipt-bearing final transaction is publication proof. Stage validation,
COPY completion, merge completion, queue completion, worker exit, and authority
projection updates without the accepted receipt are not publication proof. The
known-commit path directly permits the explicit stage transition
`merging` → `published`; `commit_unknown` remains the recovery state when the
client cannot determine whether the final transaction committed. The stage
state machine is not a graph freshness state machine.

The graph-local authority row is a monotonic fencing projection, not a second
coordinator. Its row is locked unconditionally inside the graph transaction;
the transaction rejects any higher singleton or graph-lease fence and then
updates the projection only with the accepted handoff. Equal-fence sequencing
remains an ASYNC responsibility: the authority adapter must revalidate the
current control claim immediately before the graph transaction, and old
attempts must be quiesced before a new attempt is allowed to reconcile or
publish. A best-effort control-database read inside the graph transaction is
not part of the design.

Direct mode carries an explicit local operation/attempt and uses the same
stage, merge, receipt, and reconciliation SQL. It does not create a control
database job, coordinator instance, or fabricated coordinator fencing claim.
For compatibility with the existing receipt schema, the direct operation
identity occupies the historical receipt attempt identity slot; this is not a
coordinator job and direct serialization remains the responsibility of the
explicit direct-mode authority adapter. Coordinator mode carries the durable
job, attempt, coordinator instance, singleton fence, graph-lease fence, and
generation tuple.

Commit-unknown reconciliation is receipt-first and fail-closed. A missing
authoritative graph marker is classified as absent but is actionable only after
the old backend is terminated or rolled back and absence is proved. A matching
complete receipt makes the stage published and committed. A proved-absent
receipt makes it failed or cancelled with rolled-back merge status. A
conflicting receipt quarantines the stage with unknown merge status. An
insufficient marker leaves the stage blocked for further reconciliation. All
dispositions revalidate stage ownership, are idempotent, and refuse a silent
no-op caused by an owner mismatch.

SCALE5 adds no migration, dependency, connector, final-table column, canonical
identity, public read semantic, CLI/MCP operation, cleanup daemon, or target
repository access. It adds the publication-fencing SQL seam and focused
disposable PostgreSQL evidence for atomic receipt/authority/stage publication,
stale-fence rejection, rollback, idempotent replay, matching receipt
reconciliation, and proved-absence reconciliation. The next phase is `SCALE6`,
limited to cancellation, rollback, cleanup, and failure-injection behavior
around the full set-based merge and this publication contract.

## SCALE6 accepted clarification — cancellation, rollback, cleanup, and failure injection

SCALE6 closes the failure and cleanup boundary around the ten retained staging
families. Cleanup is a caller-owned SQL contract, not a worker or coordinator
publication action. A cleanup request carries the complete `StageOwner`, an
explicit no-live-attempt proof, a validated stage identity, and a bounded batch
size. The builder contains no `BEGIN` or `COMMIT`; the caller owns receipt
reconciliation, transaction control, retry, and bounded diagnostics.

Cleanup locks the exact stage owner and requires an expired stage in a
terminal or `cleanup_pending` state, reconciled publication state, and
eligible cleanup state. It deletes only rows with that `stage_id` from the ten
stage families in bounded batches. An incomplete batch remains
`cleanup_pending`; an empty result transitions the stage to `cleaned`.
`commit_unknown` and quarantined stages remain blocked. Receipt reconciliation
therefore precedes cleanup, and cleanup never touches final graph tables.
The deletion boundary uses the shared stage ownership key and PostgreSQL
`ctid` only for bounded batch selection; it does not reproduce final-table
indexes or infer ownership from enumeration order.

The disposable failure proof starts a valid publication handoff, runs the
final merge guard and set-based legacy/raw mutation, and injects a failure
before the complete publication receipt. Caller rollback removes the final
mutation and leaves the stage recoverable in `merging`; no receipt,
graph-authority update, or published stage is accepted. After the old attempt
is terminated or rolled back and graph absence is explicitly proved, the
accepted SCALE5 reconciliation marks the stage cancelled. Only then can
stage-owned cleanup proceed. An injected cleanup failure rolls back the
cleanup state and deletions, and a retry completes without changing final
graph rows.

Focused unit and disposable PostgreSQL evidence passes `23` tests for request
validation, exact ownership, bounded retry, stage-only deletion, cleanup
blocking, transaction rollback, proved-absence cancellation, and
commit-unknown safety. SCALE6 adds no migration, dependency, connector,
final-schema change, public-read change, canonical-identity change, legacy API
removal, cleanup daemon, or protected-repository access. The next phase is
`SCALE7`, public-safe performance and resource-bound calibration.

## SCALE7 accepted clarification — performance and resource calibration

SCALE7 calibrates the accepted durable staging, existing Psycopg 3 COPY, and
SCALE3/SCALE4 set-based merge shape on generated public-safe workloads. It
does not wire the path into production refresh, access the protected Argo CD
clone, alter final schemas or public reads, add a dependency, or publish a
graph.

The disposable probe generates one file and one Python-import observation per
size unit, derives all ten retained family row sets through the existing
canonical and legacy adapters, and measures two fresh disposable PostgreSQL
databases:

```text
current: streamed deterministic per-row SQL through the existing psql loader
staged: ten Psycopg COPY transfers followed by eight legacy/raw and eleven
        canonical set-based merge executions in one caller-owned transaction
```

Both paths produce the same family row-count vector. The probe records
normalized observation JSONL bytes, wire and internal SQL-text statement
counts, encoded bytes, operation/transaction duration, client CPU and peak
RSS, and available PostgreSQL transaction, tuple, WAL, temporary-file,
temporary-byte, and block-I/O statistics. Reports contain only synthetic
aggregate values and fixed field names; no local path, database value,
connection argument, raw SQL, source text, credential, or process dump is
retained.

At generated sizes 4, 16, and 64, the current wire statement counts were 85,
325, and 1,285, respectively; the staged data-plane wire count remained 29.
The post-fix size-64 operation took `0.174062–0.174979` seconds current and
`0.073556–0.075520` seconds staged across two repeats. Client peak RSS stayed
within approximately 58–59 MiB current and 59–59 MiB staged in those repeats.
Temporary files and bytes were zero in every probe. Durable staging increased
WAL in this small probe, as expected, and that amplification remains a resource
to measure during protected dogfood rather than an omitted cost.

The staged timing and wire count cover the COPY plus set-based merge data
plane. Durable stage-header, repository, and run setup is prepared before that
timed operation; the current streamed count includes its fixed repository/run
prefix and completion summary. SCALE8 must measure the complete orchestration
path before protected dogfood acceptance.

The staged wire shape is a data-plane protocol bound, not a performance
guarantee: it
removes the current per-row client statement growth, while PostgreSQL work,
index maintenance, WAL, locks, and transaction duration still grow with the
data. The probe therefore does not claim Argo CD completion time, server-wide
PostgreSQL memory safety, graph parity, receipt integrity, baseline parity, or
drift safety. SCALE3/SCALE4 tests retain duplicate, conflict, existing-row,
identity-collision, evidence-link, missing-reference, and rollback evidence;
SCALE6 retains cancellation, commit-unknown, receipt-first cleanup, and
failure-injection evidence. The size sweep itself is intentionally a stable
growth workload.

SCALE7 establishes provisional synthetic bounds of 29 staged wire statements,
less than 5 seconds and 128 MiB client peak RSS for generated size 64, and no
uncontrolled temporary-file growth. Protected dogfood must replace these
calibration bounds with measured duration, client/server resources, WAL,
cancellation, rollback, cleanup, publication, parity, baseline, and drift
thresholds before SCALE-CLOSE. Independent performance, PostgreSQL, privacy,
compatibility, recovery, and operations review is `approved` with that
protected-measurement requirement.

The next bounded phase is `SCALE8`, production orchestration of the accepted
staging/COPY/set-based merge/publication path through the existing direct and
coordinator adapters, followed by intermediate public-safe repository
dogfood. It must preserve one authoritative publication transaction and must
not access the protected Argo CD clone.

## SCALE8 accepted clarification — production staged ingestion

SCALE8 wires the accepted architecture through the direct CLI, enabled-graph
orchestration, and coordinator forced-full refresh adapters. The shared
implementation builds all ten retained family row sets, commits a durable
attempt-scoped stage header, transfers rows through the existing Psycopg 3
COPY boundary, validates counts and checksums, executes the SCALE3/SCALE4
set-based merge, and writes the complete receipt-bearing final transaction.
The stage state transitions and cleanup eligibility remain distinct from graph
publication. Only the final graph transaction and complete receipt establish
freshness.

The production adapter carries the accepted ASYNC job, attempt, coordinator
instance, singleton fencing epoch, graph lease fencing value, and four
generation values into the stage owner. Direct mode carries an explicit local
operation/attempt and uses local advisory mutation serialization; it does not
fabricate a durable coordinator job. No second coordinator, publication
authority, cross-database best-effort fence, connector fallback, dependency,
final-table change, run-membership column, canonical identity change, or
public-read change is introduced. The programmatic `refresh_graph()` default
remains an explicit row-wise compatibility mode; production CLI and
coordinator call sites select staged mode explicitly.

Pre-publication failures record rollback as failed and make only stage-owned
cleanup eligible. A matching commit-unknown marker is reconciled through a
fresh connection. Absent or insufficient evidence remains blocked, and a
conflicting marker is quarantined. Replaying an exact operation/attempt returns
only for a complete matching receipt; active, unresolved, or terminal
non-published stages cannot be overwritten.

The public-safe intermediate direct orchestration run discovered `19` fixture
files and `189` observations, completed in an approximately `0.166` second
band, and remained within an approximately `15 MiB` client RSS delta. Its
isolated final-family counts were files `19`, legacy nodes `196`, legacy
evidence `109`, legacy edges `90`, raw observations `189`, canonical nodes
`94`, canonical edges `77`, canonical evidence `97`, canonical node-evidence
links `173`, and canonical edge-evidence links `77`. The focused staging unit
and disposable PostgreSQL tests pass `14` tests, including exact
row-wise/staged parity, authority fencing, matching commit-unknown
reconciliation, and published-attempt replay. The complete repository gate
passes `3132` tests with `7` skipped, `92.8%` aggregate line coverage, `85.0%`
aggregate branch coverage, and the container smoke suite. These values are
public-safe fixture evidence, not protected Argo CD performance or parity
proof.

An unchanged second run in the same graph database retains the existing
run-scoped raw-observation and canonical-evidence history, so same-database
aggregate counts are not an exact repeat oracle. SCALE8 records this boundary
explicitly. SCALE9 must use the authorized backup-first isolated graph or
database lifecycle for deterministic repeat parity unless a later decision
changes run-retirement semantics. The next bounded phase is `SCALE9`, the
protected Argo CD campaign; no private clone was accessed in SCALE8.

## SCALE9A accepted clarification — bounded protected refresh preparation

The first protected attempts measured a preparation boundary that was not
visible in the synthetic calibration. A protected aggregate run contained
`1,385,624` raw observations. The tuple-retaining path reached approximately
`10.6 GB` client RSS. Discovery plus canonicalization reached approximately
`4.2 GB`, and family-row spilling reduced the completed preparation peak to
approximately `5.0 GB`. A representative approximately `38 MB` HTML
document produced approximately `220,000` observations and approximately
`896 MiB` parser RSS in the existing structural parser.

SCALE9A therefore accepts private mode-600, re-iterable observation and
family-row spools, streaming order-independent typed family checksums, and
explicit close paths for all prepared rows. These are preparation resources;
they do not assert publication and do not alter final schemas, public reads,
canonical identities, graph-key versions, ASYNC authority, receipts, or
connector dependencies. Every retained legacy and canonical family remains in
the staging manifest.

For oversized HTML documents, the extractor retains the stable document
identity and emits a bounded structural-extraction diagnostic rather than
retaining an unbounded parser tree or inventing partial structure. This is an
explicit deterministic unsupported-input policy, not a claim that the omitted
element observations are present. Protected unchanged-repeat parity and the
final GO24 rule must include this policy; a semantic gap that prevents parity
blocks closure.

The protected retry reached final canonical validation but did not publish.
The JSONB-distinct proposal guard exceeded eleven minutes and accumulated
approximately `7.4 GB` of temporary files. SCALE9B is selected to replace that
validation shape with an exact typed comparison and to preserve the established
row-wise compatibility behavior for retained legacy projections.

## SCALE9B accepted clarification — exact validation and legacy compatibility

The protected stage contained `1,381,770` canonical-evidence rows. The prior
`COUNT(DISTINCT jsonb_build_array(...))` proposal guard exceeded eleven
minutes and accumulated approximately `7.4 GB` of temporary files. An exact
typed PostgreSQL composite-row comparison over the same stage completed in
approximately `1.2` seconds. A digest-based comparison was measured but
rejected because a collision would weaken the conflict contract.

SCALE9B selects `COUNT(DISTINCT (typed columns...))` for proposal validation.
The fixed PostgreSQL column types preserve null-aware distinctness without
constructing a per-row JSONB value. Canonical proposal conflicts remain
fail-closed, as do missing-reference and raw-payload guards.

The same stage exposed one relationship-derived legacy-node stable-key
collision with differing metadata. The existing row-wise loader applies the
relationship sequence in order, so the set-based retained legacy projections
now select the descending family ordinal as the compatibility winner. This
behavior applies to files, legacy nodes, legacy evidence, and legacy edges;
the families remain current product requirements and are not decommissioned.
No final schema, public read, canonical identity, publication authority,
dependency, or connector change is introduced. The next phase is `SCALE9C`,
the protected authoritative retry.

## SCALE9C accepted clarification — reference-guard resource bound

The first retry after SCALE9B completed COPY and stage validation but the
canonical edge-reference guard remained active for approximately four
minutes and raised the isolated PostgreSQL temporary-file counter to
approximately `11.7 GB`. The attempt was cancelled before the receipt-bearing
commit. The query plan used parallel hash joins carrying wide staged edge
rows despite the canonical-node identity index.

SCALE9C replaces that single guard with correlated `NOT EXISTS` identity
lookups keyed by repository, graph-key version, and canonical key. It retains
the exact fail-closed missing-source or missing-target result and changes no
schema, index, dependency, connector, canonical identity, public read,
authority, or receipt contract. Other reference guards remain unchanged until
protected evidence selects a separate bounded optimization. The next phase is
`SCALE9D`, the protected authoritative retry.

## SCALE9D accepted clarification — node-evidence reference-guard resource bound

The protected retry completed the SCALE9C edge-reference guard and reached the
canonical node-evidence reference guard. The campaign ran for approximately
`36.5` minutes, with an approximately `29.6` minute final transaction and an
approximately `12.9` minute node-evidence guard. Its active temporary-file
footprint stabilized at approximately `1.05 GB`, and the client returned to
approximately `0.23 GiB` RSS after preparation. Cancellation occurred before
the receipt-bearing commit; final graph tables remained empty.

The node-evidence guard now uses correlated `NOT EXISTS` lookups for the
canonical node and canonical evidence identities. The exact fail-closed
missing-reference condition remains unchanged. No schema, index, dependency,
connector, canonical identity, public read, authority, or receipt contract
changes.

The foreground direct-mode interrupt did not by itself quiesce the PostgreSQL
backend. An isolated bounded backend cancellation was required before the
existing receipt-first pre-publication failure transition reconciled the three
validated direct stages. This is an open direct-cancellation acceptance
boundary, not publication evidence. A backup-first isolated reset then
reinitialized the source schema. The next phase is `SCALE9E`, which must verify
cancellation quiescence before retrying authoritative publication.

## SCALE9E accepted clarification — direct cancellation quiescence boundary

SCALE9E adds a private signal boundary around the shared Psycopg connection
used by `run_staged_full_refresh()`. Once the connection is open, direct and
coordinator execution temporarily install `SIGINT` and `SIGTERM` handlers on
the main thread. Each handler requests PostgreSQL cancellation through
`cancel_safe(timeout=1.0)` and falls back to the existing `cancel()` API if
needed. The handlers do not raise; the existing database error path performs
rollback, receipt-first failure transition, commit-unknown reconciliation, or
cleanup as appropriate.

The previous process handlers are restored before connection close, including
the commit-unknown path, and by final operation cleanup. No signal handler is
installed around preparation before a database connection exists. This seam
does not make COPY, stage validation, worker exit, or queue completion into
publication; only the accepted final transaction and complete receipt do so.

The focused cancellation unit coverage passes `2` tests. The complete
repository gate passes `3,141` tests with `7` skips, `92.7%` aggregate line
coverage, and `85.0%` aggregate branch coverage; container smoke, compileall,
file-length, dependency, and diff checks pass. This is implementation evidence
only. The next selected phase is `SCALE9F`, actual backend-quiescence proof and
the next protected authoritative retry. No publication, repeat parity,
baseline, drift, or GO24 recommendation is claimed by SCALE9E.

## SCALE9F accepted clarification — direct cancellation and cleanup proof

The protected direct CLI was interrupted only after database work began. The
signal boundary quiesced PostgreSQL without an external backend-cancellation
command. The stage had completed validation but reconciled as a pre-publication
rollback; final graph rows and complete publication receipts remained absent.
This confirms that staging and validation are not publication.

The isolated failed stage contained `4,550,368` owned rows. After receipt
reconciliation, exact ownership, and no-live-attempt checks, an isolated
harness advanced its expiry without changing the production grace policy. The
existing owner-scoped bounded cleanup completed in `338` transactions over
`319.812` seconds and left the stage `cleaned`, all stage rows absent, and
final rows unchanged. Cleanup remains receipt-first and cannot delete a
commit-unknown stage before reconciliation.

This clarification changes no schema, final table, public read, canonical
identity, authority, receipt, connector, dependency, or retention policy. The
next phase is `SCALE9G`, protected authoritative publication; repeat parity,
baseline, drift, performance acceptance, and GO24 remain open.
## SCALE9H accepted clarification — canonical node-evidence guard query-plan bound

The first authoritative attempt after SCALE9F reached the canonical
node-evidence reference boundary after durable COPY and staging validation, but
was cancelled through the accepted direct path after more than twenty minutes.
The backend quiesced, the merge rolled back, final graph rows remained absent,
and no complete receipt was accepted. This is safe diagnostic evidence, not
publication. The retained protected record has no raw backend statement or
plan, so committed source ordering identifies canonical merge-builder slot `7`,
direct final-transaction ordinal `19`.

SCALE9H changes only this reference guard. It replaces one combined pair of
correlated missing-reference predicates with separate narrow canonical-node and
canonical-evidence full-identity checks. Each check projects graph-key version
and its one applicable key, keeps exact repository and current-run fences, and
raises the existing missing-reference error. A non-strict stage-presence test
keeps the full-join shape under stale final-transaction statistics while
non-null, non-empty key contracts preserve exact missing-reference semantics.

Public-safe PostgreSQL fixtures expose the former constrained-memory repeated
probe fallback and demonstrate a merge full join for nodes and spill-capable
hash full join for evidence without a nested-loop fallback. Existing staging
and target identity indexes serve the selected plans, so SCALE9H adds no index.
Targeted staging analysis is measured but not selected; final-table analysis
inside a transaction is rejected because rollback can leave misleading planner
statistics. COPY, WAL, index size, temporary-resource, cancellation, rollback,
and privacy measurements remain bounded fixture evidence only.

The unchanged complete repository gate subsequently passed `3,148` tests with
`7` skips, `92.7%` aggregate line coverage, `85.0%` aggregate branch coverage,
and the container smoke suite. Independent review is `approved`. This accepted
clarification does not authorize publication, repeat parity, baseline, drift,
performance acceptance, or GO24. The next separate phase is SCALE9I, one
authoritative protected direct retry after SCALE9H is committed, pushed, and
reported.

## SCALE9J clarification — exact direct backend attribution

SCALE9I established that aggregate backend counts cannot safely distinguish an
owned direct client, an attributable PostgreSQL parallel worker, an observer,
or unrelated activity. SCALE9J therefore selects an opt-in, query-blind local
connection-ownership contract for one direct staged refresh.

Each source-controlled direct staged connection emits only a bounded local
lifecycle event with schema version, attempt-local sequence and generation,
closed role, backend PID, event category, and monotonic time. An exact-identity
admission uses a synchronous local ownership callback while that direct
connection remains live, or an acknowledged pair of private FIFOs. In the
paired transport, the source blocks after its ready frame until the one
registered autocommit observer combines the reported PID with the current
backend start time from its fixed activity projection and returns the matching
acknowledgement. A one-way pipe remains audit transport and cannot grant
ownership by itself. Each telemetry instance begins with a cryptographically
random positive local sequence, so a buffered acknowledgement from an earlier
instance cannot match a new ready event. The classifier recognizes only exact
direct clients, parallel workers led by an active exact direct client, exact
observer identities, internal PostgreSQL processes, ambient clients, and
unknown work. Ambient and unknown remain fail-closed.

The observer has one caller-owned autocommit connection at most, binds
acknowledgements and snapshots to that exact connection, and executes only its
fixed activity projection. The public projection contains categories and
counts, never backend identifiers, telemetry values, source values, SQL,
parameters, paths, credentials, or receipt data. Paired inherited FIFO
adapters are available only to direct CLI refresh; coordinator mode rejects
either side and the ordinary path remains uninstrumented. A terminal channel
failure is a bounded operation failure unless an active direct interruption
remains primary.

Disposable PostgreSQL controls prove actual parallel-worker attribution,
reconnect safety, cancellation rollback, receipt absence, and parity between
instrumented and uninstrumented staged publication. This clarification changes
no schema, final table, merge SQL, public read, authority, receipt, dependency,
or protected graph state. It does not authorize publication, repeat parity,
baseline, drift, performance acceptance, or GO24. The next separate phase is
SCALE9K after the required direct-main publication and fresh-cluster preflight.

## SCALE9K0 clarification — local runtime image dependency packaging

Before SCALE9K protected static preflight, the RepoMap-owned local server image
failed during its coordinator import path because it copied source and
resources without installing the project and its already-declared runtime
dependencies. SCALE9K0 preserves one dependency authority by copying the
existing package metadata and README before the source/resource tree, then
installing the project with `python -m pip install --no-cache-dir .`. The
runtime source-root predicate requires those metadata files with the existing
entrypoint and resources, refusing an incomplete explicit Docker build context
before Compose can render it.

The correction adds no dependency declaration, lockfile, schema, migration,
final-table behavior, canonical identity, public read, authority, receipt,
connector, or protected graph state. The checkout module entrypoint is the
current-source lifecycle evidence; an unrelated installed executable is not
accepted as a substitute. Focused regression coverage, the complete repository
gate, and owned runtime health verification establish only image-packaging
correctness. They do not authorize protected preflight, refresh, publication,
repeat parity, baseline, drift, performance acceptance, or GO24. The next
separate phase remains SCALE9K after SCALE9K0 is committed, pushed, reported,
parity-verified, and independently reviewed.

## SCALE9K clarification — fresh-cluster bounded canonical merge stop

SCALE9K established one fresh exact-scope RepoMap-owned runtime through the
existing lifecycle and retained one private manual registration. Static-only
preflight, zero-state readback, source cleanliness, fixed aggregate counters,
and an exact ownership baseline preceded the sole direct staged attempt. The
local observer used an acknowledged private FIFO pair and classified only one
registered direct client, its exact observer identity, and PostgreSQL internal
activity; no ambient or unknown client was admitted.

The attempt completed final-transaction boundaries 1 through 19 and reached
boundary 20, canonical_node_evidence_merge. That boundary exceeded the
accepted 90-second statement limit, so the supervisor sent one direct signal.
No PostgreSQL termination or cancellation SQL, manual rollback, container
intervention, or retry was used. Terminal aggregate temporary-byte and WAL
upper bounds also exceeded their accepted limits. Direct-client RSS remained
below its cap; PostgreSQL process-group RSS was unavailable and was not
inferred.

Receipt and stored-graph readback established a failed terminal run, no
complete receipt, zero stored graph families, post-exit backend quiescence,
and source cleanliness. This is accepted pre-publication diagnostic evidence,
not publication, parity, baseline, drift, calibrated performance, or GO24
evidence. It changes no schema, merge SQL, canonical identity, authority,
receipt, lifecycle, privacy, or public-read contract.

The next separate phase is SCALE9L. It must use disposable evidence and a
test-first source correction for the bounded canonical node-evidence merge
boundary before any later protected retry. The unchanged-repeat phase is
deferred to a later number.

## SCALE9L clarification — canonical node-evidence merge bound

SCALE9L accepts a narrow correction for the canonical-node-evidence merge
boundary isolated by SCALE9K. The selected shape materializes staged logical
link identities before canonical node and evidence joins, rather than choosing
a representative after those joins through ordered source-key deduplication.
It groups only graph-key version, canonical key, evidence key, and link kind.

The staged path refreshes statistics for that one staged family after COPY and
before the prepared-state transition. Public synthetic disposable PostgreSQL
evidence confirms the grouping shape without the prior ordered deduplication
path and confirms preservation of existing and insertion of distinct valid
links. The target conflict boundary remains in place.

This clarification changes no schema, migration, COPY transport, retained
legacy/raw merge, canonical identity, authority, final-transaction order,
receipt, cancellation, public-read, CLI, MCP write, dependency, or protected
graph contract. A test-fixture-only availability-probe mock keeps two dry-run
mapping checks independent of unrelated local listeners; explicit port-conflict
coverage continues to exercise the real preflight.

Independent review required a controlled orchestration regression that proves
the statistics refresh runs once after COPY and before preparation and
validation. The regression fails when the refresh is absent. The follow-up
complete repository gate passed with 3,240 tests and 7 skips; static checks
also pass. No protected operation occurred in SCALE9L, and this clarification
is not protected publication, parity, baseline, drift, performance,
SCALE-CLOSE, or GO24 evidence. The next separate phase is SCALE9M, one fresh
bounded protected authoritative retry. A successful retry must be followed by
the deferred unchanged-repeat parity phase; a new bounded query-category
failure requires the next numbered source-correction phase first.

A fresh independent review approved the published follow-up, including the
orchestration regression, scope, privacy boundary, and remote-parity closeout.

## SCALE9M clarification — complete-attempt elapsed boundary

SCALE9M repeated the fresh-runtime, static-only preflight, zero-state,
source-cleanliness, and exact direct-ownership gates after SCALE9L. The one
direct staged attempt reached the accepted complete-attempt elapsed limit. The
supervisor delivered one direct signal, reconciled the owned set to quiescence,
and left the protected source clean. It used no PostgreSQL cancellation or
termination, manual rollback SQL, external process or container intervention,
or retry.

The stop did not identify a final-transaction statement category. Exact
ownership telemetry stayed healthy, aggregate temporary and WAL upper bounds
and direct-client RSS remained within their accepted limits, and host-visible
PostgreSQL process-group RSS was unavailable rather than inferred. Bounded
RepoMap readback found a failed terminal run, no complete receipt, and zero
exposed graph families.

This clarification changes no schema, migration, COPY transport, merge SQL,
canonical identity, authority, receipt, cancellation contract, lifecycle,
public read, CLI, MCP write surface, dependency, or protected-source policy.
It is not authoritative publication, repeat parity, baseline, drift,
calibrated-performance acceptance, SCALE-CLOSE, or GO24 evidence. SCALE9N is
the next separate phase: it must isolate the total-attempt throughput boundary
with public-safe synthetic evidence before a later protected retry. The
unchanged-repeat phase remains deferred.

Independent review approved the published clarification with no actionable
findings across lifecycle, ownership, cancellation, publication, privacy, and
successor boundaries.

## SCALE9N clarification — pre-attempt storage-readback availability

SCALE9N accepted a private coarse timing-attribution seam for a later direct
attempt, but the exact-scope eligibility gate failed closed before the seam was
installed or any protected child began. The protected source was clean and the
owned local runtime reported its services running. Required bounded refresh
status, graph-summary, and graph-baseline readbacks did not re-establish
readable storage state; a supported alternate readback path did not establish
it either.

This is an availability boundary, not evidence that stored graph content,
receipt state, or a prior run changed. No reset, rebuild, cleanup, direct
attempt, signal, database cancellation, manual rollback, source change,
schema change, or public contract change occurred. A running service remains
insufficient evidence for a protected retry when exact storage reconciliation
is unavailable.

The next separate phase is SCALE9O. It must diagnose this lifecycle-readback
availability boundary using public-safe synthetic evidence and RepoMap-owned
lifecycle commands before proposing a narrow correction. It does not authorize
protected retry, publication, repeat parity, baseline, drift, calibrated
performance, SCALE-CLOSE, or GO24 advice. The unchanged-repeat phase remains
deferred.

Independent review approved the published clarification with no actionable
findings across no-attempt, lifecycle, privacy, and successor boundaries.

## SCALE9O clarification — lifecycle-readback topology boundary

SCALE9O ran one private closed-category diagnostic after protected-source and
owned-service checks passed. It classified the primary operational readback as
a connection failure, found that the existing fallback classifier did not
accept the category, and found the owned-container plan unavailable. A
supported alternate readback also failed.

This is not evidence of stored graph content, receipt, run, rollback, or
source state. No protected child, signal, database cancellation, manual
rollback, external process or container action, backup, reset, cleanup,
rebuild, source change, schema change, or public contract change occurred.

The next separate phase is SCALE9P, a bounded RepoMap-owned
lifecycle-readback topology correction. It must reproduce the closed category
with public-safe synthetic evidence before any lifecycle mutation or protected
retry. It does not authorize publication, repeat parity, baseline, drift,
calibrated performance, SCALE-CLOSE, or GO24 advice. The unchanged-repeat phase
remains deferred.

Independent review approved the published clarification with no actionable
findings across closed-category, no-mutation, privacy, chronology, and
successor boundaries.

## SCALE9P clarification — lifecycle-readback topology classification

SCALE9P accepts a narrow private classifier that emits one closed
configuration-or-runtime topology category without retaining diagnostics or
opening a graph readback connection. Public synthetic unavailable-plan and
disposable PostgreSQL readback evidence pass before that classifier is used.

The classifier returned `non_container_topology`. This result does not prove a
live configuration value, graph content, receipt, run, rollback, or
protected-source state. Its decision table prohibits a configuration edit and
does not authorize a lifecycle start, so no protected child, target-code
execution, retry, signal, container action, database action, backup, reset,
cleanup, rebuild, or publication occurred.

This clarification changes no source, schema, migration, dependency, public
CLI/MCP contract, or lifecycle behavior. It is not publication, unchanged-repeat
parity, baseline, drift, calibrated performance, SCALE-CLOSE, or GO24 evidence.
The next separate phase is SCALE9Q, a bounded configuration-contract
readback-topology correction using public synthetic evidence and static
contract analysis. Independent review approved the published clarification with
no actionable findings.

## SCALE9Q clarification — loopback container-readback contract

SCALE9Q adds an explicit loopback allowance only to operational JSON-readback
container-plan resolution. A configuration with a config home and disabled
direct host-port mapping remains eligible for the existing owned-container
readback fallback across supported loopback host spellings. The shared
refresh-ingestion fallback retains its existing host restriction. The host
attempt, fallback classifier, runtime plan, ownership check, execution
arguments, diagnostics, and public interfaces are unchanged. Public regression
coverage preserves the direct-host opt-out.

The public loopback regression failed against the prior predicate. Independent
review identified a shared-helper scope gap and incomplete loopback-matrix
coverage; the published correction resolves both. The complete repository gate,
compile check, file-length profile validation with warnings only, and diff
checks passed. No private
configuration, live runtime inspection, graph query, live SQL, target-code
execution, protected child, retry, signal, lifecycle action, operational
publication, unchanged-repeat parity, baseline, drift, or performance operation
occurred.

This clarification changes no schema, migration, dependency, storage semantic,
graph vocabulary, or public CLI/MCP contract. It is not SCALE-CLOSE or GO24
evidence. The next separate phase is SCALE9R, a bounded private no-query
topology reclassification before any later operational readback or protected
retry. Fresh independent review of this corrected closeout approved the
published result with no actionable findings.

## SCALE9R clarification — JSON-readback topology reclassification

SCALE9R retains SCALE9Q's readback-only loopback allowance and the shared
refresh-ingestion restriction. Public loopback and disposable integration
evidence passed before one private fail-closed classifier was used. The
classifier was syntax-validated, executed once, and returned the closed
category `non_container_topology` through a fixed, schema-checked result.

The category establishes no configuration value, graph, receipt, run,
rollback, or protected-source state. No configuration edit, graph query, SQL
execution, private database-client invocation, target-code execution,
protected child, retry, signal, lifecycle operation, publication, parity,
baseline, drift, or performance operation occurred.

This clarification changes no source, schema, migration, dependency, storage
semantic, receipt behavior, graph vocabulary, or public CLI/MCP contract. It
is not SCALE-CLOSE or GO24 evidence. The next separate phase is SCALE9S, a
bounded direct-host or topology-contract phase. It must not treat the category
as authorization for a configuration edit, operational readback, lifecycle
action, or protected retry. Fresh independent review approved the closed
category, no-action boundary, privacy, verification claims, and successor with
no actionable findings.

## SCALE9S clarification — direct-host topology contract boundary

SCALE9S records the public source-only AST proof and the existing public
synthetic three-case matrix as passed. The closed category is
`non_container_topology_contract`; it preserves the predecessor category's
ambiguity without disclosing a private condition.

No target execution and no private runtime, graph, configuration, or lifecycle
action occurred; permitted public Git publication and checking were separate.
This clarification records no private values, paths, identities, credentials,
diagnostics, telemetry, or source-derived data.

SCALE9S is closed. The public topology-contract evidence is approved. The
result preserves ambiguity where private runtime state cannot be inferred from
public evidence.

No readiness determination is made from public evidence alone.

No private runtime, graph, configuration, storage, lifecycle, or protected
operation occurred as part of the public closeout.

No successor SCALE phase is opened. Further private-runtime diagnosis or
protected work requires explicit user direction and a new bounded plan.

Fresh independent review approved the public closeout with no actionable
findings and introduced no new operational evidence.

## SCALE10 clarification — Argo CD staging throughput boundary

SCALE10 established a fresh private runtime, coherent zero-state readback,
static preflight, protected-source cleanliness, exact owned-client categories,
and public supervisor-transparency evidence before one direct staged
forced-full attempt. The attempt reached the 90-minute limit while the
staging/COPY/validation partition remained active. One direct signal quiesced
the child.

Current-source reconciliation found a failed run, no complete receipt, no
active or commit-unknown stage, and zero retained-family rows. Post-signal
aggregate counters exceeded the temporary and WAL ceilings after the private
supervisor had already selected the elapsed-time stop; its priority-ordered
evaluation did not revise the resource verdict. SCALE10 therefore records
`staging_copy_validation_throughput` and a private acceptance-instrumentation
defect, but does not claim resource acceptance or a product source defect.

No repeat, parity, accepted baseline, drift, SCALE closure, or final GO24
recommendation follows. SCALE11 is not opened without public-safe reproduction
that isolates COPY, staged checksums, validation, statistics, or another
product boundary. A later protected attempt requires a new bounded plan.
