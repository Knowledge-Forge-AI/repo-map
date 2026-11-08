# ADR 0168: Bounded Server context parity and truthful refresh outcomes

* **Status:** Parent-accepted for Epics 1 and 2 after independent design
  review and resulting-state corrections. Epic 3 remains held pending a safe
  inheritance-preserving contract; it grants no implementation authority.
* **Date:** 2026-11-07
* **Phase:** `REPOMAP-CLOE-SERVER-PARITY1`. This is a partial W7 selection
  under the current manual roadmap continuation.
* **Contract:** [cloe-server-parity-v1.md](../../../specs/cloe-server-parity-v1.md)
  is the detailed executable specification. This ADR and its explicit parent
  dispositions govern scope and acceptance.
* **Amends forward:** the active W4 PostgreSQL refusal in
  [cloe-intent-context-v1.md](../../../specs/cloe-intent-context-v1.md) (OD2/F6).
  ADR 0133 and the W4 outcomes stay immutable history.

## Context

CI128 run 42414664976 attempt 1 qualified staging
`5ce48979661a13cd017bca48fea7f61ac6ec23b8` (`EXECUTED_PASS`, all nine jobs).
The operator's continuation authorizes ordinary W7 selections. The parent
selected three connected epics. The original scope named two. The third-epic
grant is the parent's amendment, and the post-commit grant sets the
report-uncertainty priority. Current source (`5ce4897`) has the following
facts:

1. **PostgreSQL refuses depth-1 context expansion.**
   - `build_compact_context` in `retrieval/context_assembly.py` returns
     `unavailable/backend_unsupported` for PostgreSQL `graph_investigation`.
     The only exception is an explicit `fallback_to`.
   - `execute_scans_and_pack` in `retrieval/context_packet_builder.py`
     (lines 315–319) records `expansion_backend_unsupported` for
     `expand_depth=1`.
   - `PostgresContextReadAdapter.expand_seeds_depth1` returns
     `backend_unsupported`.
   - SQLite's `expand_seeds_depth1` performs a greedy fold. For each seed it
     reads one window of at most `edge_limit+1` rows in each direction. It
     dedupes by edge key, caps relations at 256, and caps neighbors at 128.
     Each seed's `node_limit` charges only neighbors that are newly admitted
     globally.
   - SQLite then reads direct locations for exactly the admitted neighbors in
     one statement, using `EVIDENCE_SCAN_LIMIT=10000`+1.
   - SQLite's edge key is `identity_metadata_hash` alone, a hash of the edge's
     identity metadata only. Canonicalizers commonly emit empty identity
     metadata, so many distinct relations share one key, and SQLite silently
     skips all but the first. W4's own relation identity is the 4-tuple
     (source, kind, target, hash).
   - Repeating the SQLite pattern on PostgreSQL would need 1+8+5+1 statements,
     which exceeds the 12-statement cap.
2. **Refresh outcomes can be untruthful.**
   - `_refresh_graph_call` labels every converted `KeyboardInterrupt` as
     `rolled_back`.
   - `_refresh_graph_impl` labels every non-unknown publisher failure as
     `not_started`.
   - `staged_ingestion` can propagate a raw `KeyboardInterrupt` from inside the
     commit-reconciliation window.
   - In the final-transaction handler, rollback failure can otherwise leave
     cleanup ordering ambiguous; the accepted custody rule must not issue a
     later metadata commit after rollback fails, and must preserve the primary
     exception.
   - `execute_portable_refresh` calls `mark_terminal(accepted=False)` when
     `mark_terminal(accepted=True)` fails after the publisher has returned. A
     committed run can therefore be retained as `terminal-failed`.
   - `finish_server` ranks `cancelled` ahead of `commit_unknown`.
3. **The PostgreSQL deadline is checked only between statements.**
   `WorkLedger` owns a deadline of at most 10,000 ms. PostgreSQL context
   statements run with no server-side bound derived from that deadline.

## Decision

Accept Epics 1 and 2 in one milestone. The timeout proposal below is retained
as a held alternative, not accepted behavior. All existing numeric ceilings,
public CLI/MCP/wire/schema fields, roles, dependencies and DDL stay unchanged
under this ADR.

1. **PostgreSQL depth-1 parity, built in.**
   - `PostgresContextReadAdapter` sets a private capability attribute,
     `supports_depth1_expansion = True`.
   - Assembly and the packet builder use one predicate. For ports that lack the
     attribute, it defaults to `backend != "postgresql"`. This keeps explicit
     `backend_unsupported` and fallback behavior for unsupported ports.
   - The new `storage/postgres_context_expansion_sql.py` builds **one**
     self-contained statement. The statement pins repository identity and the
     context accepted identity. It then:
     - reads two windows per seed, one per direction, each limited to
       `edge_limit+1` rows, with kind-filtered `LATERAL` reads;
     - ranks rows exactly as SQLite does and keeps `edge_limit` per seed;
     - replays the SQLite greedy fold as a bounded `WITH RECURSIVE` walk of at
       most 320 steps, deduplicating on the relation identity chosen under
       RD-2;
     - fetches direct evidence only for the admitted neighbors, using SQLite's
       selected-run rule and global order, with `10000`+1 rows.
   - Locations reuse the existing `_direct_location` formatter with the
     accepted vector.
   - The adapter returns the existing consumer shape.
   - Stale identity becomes a stale packet.
   - Consistency stays `per_statement_identity_checked`.
2. **Truthful refresh outcomes.**
   - A per-call `PublicationPhaseWitness` is created by `_refresh_graph_call`
     and threaded down as an optional private argument. The public
     `execute_portable_refresh` creates an internal witness when its optional
     argument is omitted and always forwards it. The publisher advances it at
     real program-order boundaries: final transaction entered, rollback
     returned, commit attempted, reconciliation entered, committed, and
     publisher returned. A lower-level helper explicitly invoked without a
     witness cannot infer precommit failure.
   - A pure classifier maps the phase and the exception to the existing
     `not_started`, `rolled_back` or `commit_unknown`. It never asserts a
     rollback without the witness.
   - A failure after the publisher returns is reported as `commit_unknown`.
     It never causes `terminal-failed`. Replaying an existing `published` or
     `commit_unknown` stage also counts as possibly committed.
   - An interrupt that storage converted to `StorageCommitUnknownError` keeps
     the `cancelled` category through its direct `__cause__`.
   - Primary exception identity survives secondary cleanup faults.
   - The final-transaction handler runs rollback first. If rollback fails, it
     does not call `mark_failed_before_publication()` or `commit()`; the phase
     remains unsettled and is classified conservatively as `commit_unknown`.
   - `finish_server` ranks `commit_unknown` ahead of `cancelled`.
   - Coordinator code is unchanged. Its existing receipt reconciliation resolves
     the uncertainty.
3. **Held proposal: request-budget server statement timeout.**
   - The unaccepted proposal would have built-in PostgreSQL context reads pass
     `statement_timeout_ms = floor(remaining WorkLedger budget)` through the
     existing readback protocol.
   - The value is applied as a connection **startup option**: the Psycopg
     `options` parameter, or `PGOPTIONS` in the private psql child environment.
   - The merge keeps any stricter observable inherited client-layer value. It
     refuses ambiguous inheritance.
   - A budget below 1 ms is refused before IO.
   - `deadline_exceeded` is reported only when the ledger itself proves expiry
     and the failure came from the built-in executor call, not a parser.
   - Custom executors stay unsupervised. On the psql path, a user's psqlrc or
     a psql-named wrapper is caller-owned client configuration and can
     override or drop the budget. This is disclosed, not supervised.

## Reserved decision RD-1

This decision blocks only the Epic 3 rollout.

**The conflict:**

- PostgreSQL applies startup options with source `PGC_S_CLIENT`. That source
  outranks `ALTER ROLE`, `ALTER DATABASE` and configuration-file values.
- A server-side default that is stricter than the request budget would
  therefore be replaced for these context sessions.
- Detecting such a default needs an extra statement, and the grant forbids
  extra statements.
- This conflicts with "never replace a stricter inherited timeout."

**Original design recommendation, rejected by the parent:** accept and disclose
the limitation. The original reasons were:

- These server-side values are session defaults, not enforced ceilings. Any
  session of the read role can already `SET` them.
- The request budget never exceeds 10,000 ms.

**Alternative:** descope Epic 3.

**Disposition:** Epic 3 remains held. No startup-option timeout code,
additional statement or implementation authority is granted by this ADR. Any
future safe replacement requires a separate parent disposition.

Epics 1 and 2 do not depend on RD-1.

## Reserved decision RD-2

The parent resolved this decision before Epic 1 source work: select (a).
Only the fold's deduplication key and an SQLite correction depend on it.

**The conflict:** exact parity with SQLite would copy its hash-only
deduplication, which drops relations silently on production-shaped data. The
W4 fixture's synthetic unique hashes hide this.

**Recommendation (a):** deduplicate on the 4-tuple (source, kind, target,
hash) in both backends. This corrects Local output toward W4's stated relation
identity, with updated SQLite non-regression tests.

**Alternative (b):** keep SQLite unchanged, replicate hash-only deduplication
in PostgreSQL, and record the limitation for both backends.

## Consequences

**Positive:**

- PostgreSQL `graph_investigation` and `ranked_discovery --expand-depth 1`
  produce the same admitted items, neighbors, relations, omissions and
  provenance as SQLite.
- Expansion costs exactly one statement and one logical unit. The 12-statement
  and 16-unit caps still govern, and exhaustion stays the existing `partial`.
- Interrupt and fault reporting no longer fabricates a rollback or a
  non-publication.
- Committed work is reconciled rather than retried.

**Negative:**

- The expansion statement still scans every incident edge of a seed in the
  filtered kinds, and every evidence link of admitted neighbors. Row limits
  bound only the returned windows.
- Physical work, memory, locks and whole-request latency are not bounded.
- More cases become `commit_unknown`. One example is an interrupt that arrives
  during the final rollback. These outcomes rely on the existing receipt
  reconciliation.
- More retained attempts stay unsettled, without a terminal mark. Nothing in
  current source settles or prunes them, so their sealed objects remain until
  an operator removes them. A new reconciliation write is out of scope.
- The retained namespace lock is nonblocking. Namespace-wide contention may
  leave a published refresh unsettled as `commit_unknown` or fail capture while
  preserving the attempt; no new bounded-wait policy is introduced.
- No request-derived server statement timeout is introduced. The existing
  between-statement deadline checks remain; physical statement latency is
  still outside that cooperative bound.
- Under RD-2 (a), SQLite Local expansion output changes: it admits relations
  it used to drop.
- Packet serialization differs by backend (`consistency_mode`, `backend`,
  ledger fields). Parity therefore holds on admitted content, not on every
  byte-budget boundary.

**Size:** the independent design forecast for its original three proposals
was about 3.5k–4.4k meaningful LOC, detailed in specification §7. It is a
forecast, not a completed delta or an authority limit on a later manual
roadmap selection. Substantial related work may be separately designed and
accepted; line-count padding is refused.

## Alternatives rejected

- **Reuse `build_canonical_neighborhood_query_sql`.** It is unbounded.
- **Per-seed statements.** These exceed the 12-statement cap.
- **Fetch evidence for a superset of neighbors and clip in Python.** This can
  starve admitted neighbors.
- **Per-seed `ROW_NUMBER() <= node_limit`.** This violates the greedy fold. The
  grant's counterexample shows it.
- **An extra `SET` or `SHOW` statement.**
- **A client supervisor or subprocess timeout.**
- **Adding `-X` to the psql connector.** It would change existing psql
  handling for a client-layer gap the caller owns.
- **Writing `terminal-failed` for uncertain attempts so pruning can reclaim
  them.** That asserts non-publication without proof.
- **A new reconciliation write, a new public field, a retry, or a change to the
  commit or fencing algorithm.**

## Rollback

Each epic is separable:

- Revert the capability attribute and Epic 1 restores the historical
  `backend_unsupported` behavior. Under RD-2 (a), the SQLite key change is
  reverted separately.
- Revert the witness threading and the old labels return.
- Omit `statement_timeout_ms` and the old defaults return.

There is no schema, data migration or history rewrite. Retained-Python
admissions are append-only; a rollback retires its scope by a forward record.

## Parent disposition before implementation

The current manual roadmap continuation authorizes these ordinary W7 source
changes. Parent selects RD-2(a): use the existing four-part canonical relation
identity in both backends. The metadata hash remains its existing wire field;
schema and graph vocabulary do not change. Production-shaped equal hashes
must preserve distinct relations, and self-loops still deduplicate. Correct
the synthetic SQLite fixture and test both owners.

Epic 2 is accepted with primary-exception custody across secondary cleanup
BaseExceptions as well as ordinary Exceptions. If a primary exists, secondary
settlement/close failures add only categorical notes and never replace it. A
cleanup failure with no primary remains observable. Public result schemas and
original propagating KeyboardInterrupt/SystemExit objects remain unchanged.

RD-1(a), overriding stricter server defaults, is rejected. No startup-option
timeout code is authorized. A safe same-connection control/query alternative
may be separately accepted only with honest statement charging under the
unchanged cap and preserved effective defaults. Until then Epic 3 is held.

Final scoped source proof and an independent resulting-state dispatcher review
remain required. No complete local suite, Python coverage, SDK/application
build, native Rust command, dependency, deployment or public campaign is
authorized by design adoption. This is partial W7. Unsettled retained attempts
remain a named limitation and a separately designed potential follow-up.
