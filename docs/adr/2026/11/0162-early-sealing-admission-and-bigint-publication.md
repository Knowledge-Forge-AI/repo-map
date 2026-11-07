# ADR 0162: Early sealing admission and BIGINT publication

## Status and authority

Accepted for both epics in `REPOMAP-CLOE-RESOURCE-GOVERNANCE1`, under the
operator's 2026-11-06 roadmap continuation after CI124 passed. Epic 2 was
initially held for the independent review's writer-conflict inventory. The
inventory and admission correction below resolve that design blocker before
its implementation; real competing-connection proof remains mandatory.

The phase selects two connected W7 engineering epics. This is partial W7
work, with no new numeric policy, dependency, schema, public surface, role
grant, complete local suite, local coverage, acquisition or image build.
Publication requires a later frozen-candidate checkpoint. Historical phase
exclusions do not permanently reserve these ordinary roadmap decisions to
the operator.

## Context

Source sealing currently scans the real inventory, materializes each entire
file and stores it, scans again, then validates the manifest limits. The
first scan already reads source bodies through discovery and stable capture;
the second repeats that work. Enforcing existing inventory policy between the
first scan and body copy avoids unnecessary artifact writes and roughly one
of five body reads, together with the whole-file allocation. It does not
bound all discovery, retry, traversal, verification or elapsed work.

The staged publisher separately passes a BIGINT repository identity to a
two-int32 advisory lock in namespace 19042. A collision-free replacement for
the unsupported high range must preserve existing low-ID interoperability,
admission behavior and publication fencing.

## Epic 1 decision

1. Reuse `ArtifactLimits` unchanged: 100,000 entries, 4 GiB logical source
   bytes, 1,024 UTF-8 path bytes and 16 MiB canonical manifest bytes. An
   internal sealing keyword may select component-wise lower limits only.
   No CLI or configuration setting is added.
2. After the first real scan, validate the complete inventory before any
   sealing body copy or store write. Share the pure inventory predicate with
   final manifest validation, including binding membership, duplicates,
   case ambiguity and portable paths. Keep final canonical-byte validation,
   real references and the second real scan.
3. Copy through descriptor-bound chunks into the existing store iterable
   interface. Pass the expected digest and exact size to its existing
   guards. Check regular-file type, single link, size, executable state,
   digest and unchanged descriptor metadata before successful exhaustion.
   The existing one-MiB chunk is an implementation buffer.
4. Resolve the configured root once. Traverse below it with owned directory
   descriptors and no-follow/nonblocking opens where supported. Reject
   symlink components, nonregular bodies and hardlinks. The fallback retains
   the incumbent path checks plus descriptor/path identity checks. Symlinked
   ancestors above the resolved root remain usable. Close descriptors even
   when a store consumes only part of the iterable.
5. Preserve sanitized refusal categories, stable accepted identities and
   shared immutable objects. Store-detected source bounds/digest drift maps
   to the incumbent source-changed refusal. Other store failures propagate;
   exact store temporary cleanup remains store-owned. Never delete shared
   valid content after a later sealing failure.

Manifest-limit applicability remains unknown on an early-refusal path that
never reaches normal-path observer hooks. `sealing_io_limit` remains absent.
ADR 0159 describes its introducing source state; this decision supersedes
its statement that inventory policy is checked only after all body copying.

## Epic 2 decision and conflict inventory

Keep the exact `(19042, repository_id)` advisory SQL for positive int32 IDs.
For `2**31..2**63-1`, lock the actual `public.repositories` row with
`FOR NO KEY UPDATE NOWAIT` before existing final-transaction guards. No hash,
truncation, modulo, advisory namespace, table or migration is introduced.
Reject invalid IDs before SQL. Missing ownership uses the existing staged
repository-identity failure; only SQLSTATE 55P03 becomes the incumbent
sanitized publication-contention error. Other driver failures, including
40001 under stronger isolation, propagate unchanged. The owner retains
commit and rollback responsibility, including after an aborted transaction.

The production inventory found these conflict surfaces:

| Owner | Repository-row activity | Treatment |
| --- | --- | --- |
| `_staged_ingestion_stages._ensure_repository` | Metadata upsert by root or stable identity | Add same-transaction NOWAIT admission check for an existing high-ID row before upsert. |
| `sql_load.repository_run_prefix_sql` using `repository_identity.repository_upsert_sql` | Legacy loader metadata upsert | Add the equivalent preceding SQL guard, preserving upsert and psql result binding. |
| `repository_identity` reconciliation | Maintenance table lock, repository update/delete and authority remapping | Remains maintenance-owned. Row conflicts refuse; table waits retain incumbent behavior. |
| Staging, graph and lexical population | Child inserts with repository foreign keys | KEY SHARE remains compatible with the new final-publication lock. |
| Lexical lifecycle/revoke and staging cleanup | Separate advisory and child-row locks | Keep their existing protocols. |
| `_configured_fencing` | Admission, then authority lock with its own bounded timeouts | Reuse the corrected admission owner; preserve timeout values and lock order. |

Admission checks match the same existing root or stable identity as the
upsert, restricted to IDs above int32. They neither suppress metadata
updates nor claim exclusion from a missing row. A publisher already holding
the high row therefore causes admission to refuse before its upsert waits.
The SQL loader guard emits no result row and sanitizes its contention error.
Low-ID upserts and final advisory SQL remain unchanged.

This is not a universal nonblocking admission promise. Missing-row insertion
races, stronger locks needed by a metadata/key update, and incompatible table
locks retain PostgreSQL's existing wait behavior. NOWAIT applies to row locks;
no new lock or statement timeout is set. Ordinary staged connections retain
their configured/default isolation and timeouts. A high-ID row held by an
unrelated update/share locker can produce the same conservative busy category
as a publisher; that refusal is an accepted internal tradeoff. SQLSTATE 55P03
from an existing lock timeout has the same sanitized category.

The actual standard graph refresh role already has the needed UPDATE
privilege. The graph control role is not the publisher and has no graph
CONNECT grant. Do not change grants for custom principals; insufficient
privilege fails closed. Test the generated standard role SQL.

An authority-row mutex is rejected because direct publications explicitly
skip authority upsert/check and may have no such row. Splitting direct and
coordinator mutex owners would break cross-mode exclusion. A single-bigint
advisory key shares the lexical hashed keyspace; hashing/truncating adds
collisions. Reserving a large negative two-int key range is a larger protocol
change. The existing repository row is the smallest common deterministic
identity, with the admission correction above.

The compatibility reasoning follows PostgreSQL's
[row and table lock matrix](https://www.postgresql.org/docs/16/explicit-locking.html)
and [SELECT locking rules](https://www.postgresql.org/docs/16/sql-select.html).
It is this project's design inference, not a PostgreSQL recommendation.

## Alternatives

Keeping final-only limits retains avoidable work. A new aggregate I/O or
deadline policy requires separate design and is deferred. Polling scanner
limits are not ordinary capture policy. Removing the second scan weakens
custody. Deleting all objects on refusal violates shared-object ownership.
No new dependency or parser is needed for descriptor streaming.

## Verification and ownership

Use exact canonical unit and containerized integration selectors with
`--no-coverage`, real filesystem/store boundaries and real PostgreSQL
publication for Epic 2. Preserve adjacent Local/Server/replay, low-ID locking,
fencing, reconciliation and sanitized errors. Replace obsolete `read_bytes`
and path-stat fault injections with faults at the actual descriptor boundary.
Prove default-policy path refusal, lower limits, exact boundaries, mutation,
partial consumption, cleanup and unchanged accepted identities.

Implementation spans seven production modules, including two new helpers,
and seven new focused test owners. Keep each new owner clean and within the
400-line profile; extract
siblings rather than expand the nearly-full staged publisher. Append exact
ownership-digest and retained-set lineage without changing debt ceilings.
Do not manufacture code to meet the operator's 10k–100k publication aim.
Complete both epics before considering one batched public campaign.

The parent owns design acceptance and resulting-source disposition. The
independent APGR design checkpoint found one Epic 2 blocker and twelve
advisories; all relevant Epic 1 advisories are adopted above. Its source was
read through registered immutable excerpts; that is not kernel file-open
proof or implementation qualification. No whole-W7, installed, production,
scientific or 87/82 coverage-margin acceptance follows from this decision.

## Verification-plan observation

The subsequent canonical grant test recorded one dependency-only runtime
logical materialization inside the existing sandbox. The introducing plan's
broad zero-image-build/acquisition wording did not predict that helper path.
Application and SDK builds remain zero; package acquisition completeness is
unestablished. The [phase exit](../../../../tools/ci/cloe-resource-governance1-exit.md)
retains the deviation and required review disposition. No dependency or runner
policy changes, raw/native qualification or additional hosted start follow.
