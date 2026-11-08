# CLOE Server parity v1 (`REPOMAP-CLOE-SERVER-PARITY1`)

- **Status:** Parent-accepted for Epics 1 and 2 after the independent design
  checkpoint and resulting-state corrections. RD-2(a) is selected: four-part
  canonical relation identity in both backends. Epic 3 is held and grants no
  implementation authority until a safe replacement contract is accepted.
- **ADR:** [0168](../adr/2026/11/0168-bounded-server-context-and-refresh-outcomes.md)
- **Roadmap:** a partial W7 selection. See
  [roadmap transition](cloe-roadmap-transition-v1.md).
- **Amends forward:** [cloe-intent-context-v1.md](cloe-intent-context-v1.md),
  the W4 PostgreSQL refusal (OD2/F6). Historical ADRs and outcomes stay
  unchanged.

Line numbers describe the pre-feature source at
`5ce48979661a13cd017bca48fea7f61ac6ec23b8`. Resulting implementation is bound
by the phase commit and review; symbol names are authoritative.

## 1. Authority, scope and preserved boundaries

**Authority:**

- The operator's roadmap continuation authorizes ordinary W7 selections.
- The scope grant selected two epics. The deadline grant is the parent's
  amendment adding a third.
- The post-commit grant makes report uncertainty take precedence over the
  cancellation label.
- The constraints grant corrects earlier draft numbers. It sets
  `EVIDENCE_SCAN_LIMIT=10000`, the greedy counterexample, and the real APIs.

**Preserved; none of these changes:**

- public CLI flags, MCP tools, wire or packet schema, `cloe-resource-view-v1`
  vocabulary, or graph vocabulary;
- DDL, indexes, roles, dependencies or runner policy;
- numeric ceilings: 12 PostgreSQL statements, 16 logical units, 8 scan units,
  5 seeds, 64 edges per seed, 128 neighbors, 256 relations, 10,000 ms
  deadline, `NODE_SCAN_LIMIT=2000` and `EVIDENCE_SCAN_LIMIT=10000`;
- the commit algorithm, fencing, graph authority, coordinator code and
  `storage/staged_publication.py`;
- staged-ingestion semantics, except for the explicitly selected Epic 2
  failure-custody handlers in `storage/_staged_ingestion_stages.py` and
  `storage/staged_ingestion.py`, with the new owned-cleanup helpers;
- SQLite adapter behavior, except the relation-identity correction that RD-2
  (§2.7) offers the parent;
- source-body and private-data policy. Context stays stored-metadata only,
  with no body or filesystem queries; MCP readers stay source-blind.

**Not claimed:**

- latency, physical-work, memory or lock guarantees for the whole operation;
- a cross-statement snapshot;
- model, Local Rust, held-out or installed acceptance;
- any campaign, application start 40, native AMD command 9, or wheel transfers
  21–22.

## 2. Epic 1: PostgreSQL depth-1 context parity

### 2.1 Capability selection (no fabricated capability)

Add one internal predicate in `retrieval/context_packet_builder.py`, which
`context_assembly` already imports:

```python
def port_supports_depth1_expansion(port) -> bool:
    return getattr(port, "supports_depth1_expansion", port.backend != "postgresql") is True
```

`PostgresContextReadAdapter` declares `supports_depth1_expansion = True`. This
is a private class attribute, not a wire field. The predicate replaces the two
backend checks:

- `build_compact_context`: the `graph_investigation` and `postgresql` branch;
- `execute_scans_and_pack`: lines 315–319.

| Port | `graph_investigation` | `ranked_discovery`, depth 1 |
|---|---|---|
| Built-in PostgreSQL adapter, SQLite adapter | Runs natively. `fallback=None` even if `fallback_to` is set. This is today's SQLite semantics. | Expands natively. |
| Port with `backend == "postgresql"` and no attribute, or attribute `False` | Unchanged: `unavailable/backend_unsupported`, or a `FallbackDisclosure` when `fallback_to` is set. | Unchanged: `expansion_backend_unsupported`, partial. |

The builder must also handle expansion `status == "stale"` the same way scan
staleness is handled: a whole-packet `stale` with
`publication_advanced_during_assembly`. Today the builder ignores `stale` from
expansion.

The builder is exactly 400 lines. The implementation factors its three
identical stale exits into one helper to stay within 400.

### 2.2 Adapter interface

The signature is unchanged from `ContextReadPort.expand_seeds_depth1`:
`(seed_keys, *, edge_kinds, node_limit, edge_limit, ledger, expected_identity)`.

**Pre-IO checks:**

- `1..5` distinct seed keys;
- `node_limit` in 1..32 and `edge_limit` in 1..64, each a non-bool `int`;
- otherwise `StorageSchemaError`, which maps to
  `unavailable/accepted_publication_unverified`.

With no edge kinds, return `ok` with `seeds_expanded=k` and no IO. This matches
SQLite.

**Admission** uses existing `WorkLedger` methods only:

- If `can_execute_logical_unit()` or `can_execute_statements(1)` fails, return
  `partial` with the ledger reason, `seeds_expanded=0` and empty results.
- Otherwise call `record_logical_unit()` and `record_statement_start()`, then
  run **one** statement through `_run_sql_object(sql, label="context
  expansion", ledger=ledger)`.
- After success: `seed_expansions_executed += k` and
  `evidence_rows_scanned += kept evidence rows`.

PostgreSQL deliberately charges one logical unit and one statement for the
combined read. SQLite charges `k+1` and `k+1`. Ledger values are not parity
fields.

**Return shape.** This is the existing consumer shape:

```python
{"status": "ok" | "partial" | "stale" | "unavailable", "reason": str | None,
 "seeds_expanded": int, "neighbor_units": [{"node": {...}, "edges": [...]}],
 "seed_to_seed_edges": [...], "edge_limit_hit": int, "node_limit_hit": int,
 "neighbor_locations_incomplete": bool}
```

- Node dicts carry `id, canonical_key, kind, display_name, first_seen_run_id,
  last_seen_run_id, locations`.
- Edge dicts are produced by `incident_edge_record(...)`. This new pure helper
  is extracted from the row loop in `expand_seed_incident_edges` in
  `storage/sqlite_local/context_expansion_queries.py`. The extraction preserves
  behavior, and both backends call the helper. `edge_key` stays the stored
  `identity_metadata_hash`, because the consumer copies it into
  `explanation_ref.identity_metadata_hash`. Deduplication uses the relation
  identity chosen under RD-2 (§2.7), not `edge_key` alone.
- Integer IDs are backend-local and never compared.

### 2.3 The single statement (`storage/postgres_context_expansion_sql.py`, new)

`build_postgres_context_expansion_sql(...)` returns one `WITH RECURSIVE`
statement. All literals use `sql_literal`. The statement reuses
`postgres_repo_predicate_sql(..., context_identity=True)`,
`postgres_accepted_run_cte_sql(context_identity=True)`,
`postgres_accepted_json_sql(context_identity=True)`,
`CONTEXT_DIRECT_EVIDENCE_ROLE_V1` and `transport_budget_sql`.

The bounds column below describes **returned or logical** rows only.

| CTE | Definition | Bound |
|---|---|---|
| `matched_repo` | `repositories` with `repository_identity = literal`, `LIMIT 1`. | ≤1 |
| `accepted_run` | The existing context accepted-run CTE: complete, portable, authority-guarded latest run. | ≤1 |
| `seed_input(seed_ord, seed_key)` | `VALUES` in caller order. | ≤5 |
| `seed_window` | For each seed, `CROSS JOIN accepted_run`, then two `LATERAL` windows joined to `canonical_nodes`. See the window definition after this table. | ≤650 |
| `seed_ranked` | `row_number() OVER (PARTITION BY seed_ord ORDER BY edge_kind COLLATE "C", direction_rank, neighbor_key COLLATE "C", edge_key COLLATE "C")` and `count(*) OVER (PARTITION BY seed_ord)`. | ≤650 |
| `kept` | `seed_rank <= edge_limit`, with `step = row_number() OVER (ORDER BY seed_ord, seed_rank)`. | ≤320 |
| `fold` | `WITH RECURSIVE` walk over `kept` by step (§2.4). | ≤321 rows |
| `admitted` | Rows of `kept` whose fold action is `new`. | ≤128 |
| `selected_run` | Per admitted neighbor: `COALESCE(max(run_id) FILTER (WHERE run_id = acc.run_id), max(run_id))` over all its evidence links. This is SQLite `evidence_sql`'s `selected`. | ≤128 |
| `neighbor_evidence` | The 20 columns in SQLite `evidence_sql` order, plus `node_id` and `subject_canonical_key`. See the evidence definition after this table. | ≤10,001 |
| `transport_budget` | `transport_budget_sql('seed_window', 'neighbor_evidence', 'accepted_run')`. | 100,000 rows / 32 MiB |

**`seed_window` rows.** Two `LATERAL` windows per seed:

- **Outgoing** (`direction_rank 0`):
  - Filter: `e.repository_id = acc.repository_id`, `e.graph_key_version = 1`,
    `e.source_canonical_key = seed`, and `e.edge_kind IN (sorted unique
    literals)`.
  - Neighbor: the target node, joined on repository and `graph_key_version 1`.
  - Order: `edge_kind`, `target_canonical_key`, `identity_metadata_hash`, all
    `COLLATE "C"`.
  - `LIMIT edge_limit+1`.
- **Incoming** (`direction_rank 1`): symmetric, using the target index and the
  source node.
- Self-loops are **not** excluded. SQLite keeps them in both windows and dedupes
  them by relation identity.
- Edge confidence is cast with `::text`.
- Each row also carries `edge_identity`, the fold's deduplication key. Under
  RD-2 option (a) it is
  `json_build_array(source_canonical_key, edge_kind, target_canonical_key,
  identity_metadata_hash)::text`. JSON array encoding is injective, so no
  separator character can collide. This is the same 4-tuple as W4
  `_rel_identity` and the PostgreSQL unique key. Under option (b) it is
  `identity_metadata_hash`.

**`neighbor_evidence` rows:**

- Joins: `canonical_node_evidence` (`canonical_node_id`,
  `canonical_evidence_id`); `canonical_evidence` with the same repository, the
  selected run and `graph_key_version 1`; `runs`; and a `LEFT JOIN
  raw_observations` on (`repository_id`, `run_id`, `ordinal`).
- Filter: `WHERE (CONTEXT_DIRECT_EVIDENCE_ROLE_V1) = 'direct'`.
- Order: `subject.canonical_key COLLATE "C"`, then `raw_observation_ordinal`,
  then `evidence_key COLLATE "C"`, then `link_kind COLLATE "C"`.
- `LIMIT 10001`.

The outer `json_build_object` returns:

- `has_accepted` and `transport_overflow`;
- `accepted`, withheld on overflow;
- `truncated_seeds`: the count of seeds with more than `edge_limit` rows;
- `relation_limit_hits` and `node_limit_hits`: counts of fold actions;
- `edges`: kept rows whose action is in {`seed_to_seed`, `existing`, `new`},
  with their action, `json_agg … ORDER BY step`;
- `evidence`: `json_agg … ORDER BY` the same order as the evidence window.

Ordering uses `COLLATE "C"`. On a UTF-8 database this equals SQLite `BINARY`
order and the Python UTF-8 byte sort. The integration fixture asserts
`server_encoding = 'UTF8'`.

Every SQL statement already carries repository and accepted identity. This one
does too, so a second repository with the same canonical keys cannot
contribute rows.

### 2.4 Greedy fold contract

The `fold` CTE has columns `(step, seed_ord, seed_new, seen text[], rejected
text[], admitted text[], action)`.

- **Base row:** `(0, -1, 0, '{}', '{}', '{}', 'start')`.
- **Recursive step:** join `kept k ON k.step = f.step + 1`.
- Compute `base = CASE WHEN k.seed_ord = f.seed_ord THEN f.seed_new ELSE 0 END`.
  Compute it in a `LATERAL` subselect over `f`/`k` columns, or with an
  equivalent inline expression.

**Every step**, whatever its action, sets `step := k.step` and
`seed_ord := k.seed_ord`. `seed_new` becomes `base + 1` on `new` and `base` on
every other action. Arrays not named in the table carry forward unchanged.
Setting `seed_ord` on every step is what resets the per-seed count at a seed
boundary, including when a seed's first rows are `skip` or `node_limit`.

The action is the first matching row of this table, evaluated top to bottom.
`id` is the row's `edge_identity` (§2.3).

| Condition | Action | Array change |
|---|---|---|
| `id = ANY(seen)` or `id = ANY(rejected)` | `skip` | none |
| `cardinality(seen) >= 256` | `relation_limit` | `rejected := rejected || id` |
| `neighbor_key = ANY(seed array)` | `seed_to_seed` | `seen := seen || id` |
| `neighbor_key = ANY(admitted)` | `existing` | `seen := seen || id` |
| `base >= node_limit` or `cardinality(admitted) >= 128` | `node_limit` | none (the edge is not added to `seen`) |
| otherwise | `new` | `seen := seen || id`, `admitted := admitted || neighbor_key` |

This is the loop in `SqliteContextReadAdapter.expand_seeds_depth1`
(`seed_nbr_count` is `seed_new`), with the deduplication key chosen under RD-2.
Per-seed `node_limit` charges only **new** global admissions.

**Counterexample (must pass):**

- Setup: seed 0 admits A and B. Seed 1 sees A, B and C. `node_limit` is 2.
- Expected: A and B are `existing` for seed 1 and consume no slot, so C is
  admitted.
- A per-seed `ROW_NUMBER() <= node_limit` design would lose C.

**Seed-boundary case (must pass):** seed 0's last row is `new` with
`seed_new = node_limit`. Seed 1's first row is `skip` and its second is a new
neighbor. The new neighbor must be admitted, because `base` restarts at 0.

**Counters:**

- `edge_limit_hit = truncated_seeds + relation_limit_hits`.
- `node_limit_hit = node_limit_hits`.

The fold's logical work is bounded: at most 320 steps, with arrays of at most
256, 320 and 128 elements.

### 2.5 Payload validation, formatting and status mapping

The parser lives in the same new module. It validates the payload as a closed
shape:

- **Types:** booleans and non-negative ints.
- **Actions:** from the closed set.
- **Row bounds:** at most `k*edge_limit` edges, at most 128 `new` rows, and at
  most 10,001 evidence rows.
- **Membership:** each evidence `node_id` belongs to an admitted neighbor.

Any violation raises `StorageSchemaError`.

Then, in order:

1. `has_accepted` is false: return `stale/publication_advanced_during_assembly`.
   This is the existing node-lookup treatment of `publication_absent`.
2. `transport_overflow`: return `partial/work_budget_exhausted` with
   `seeds_expanded=0` and no neighbors or relations. No data is used, so no
   seed is reported as expanded.
3. Identity is checked with `_compare_postgres_accepted_identities(expected,
   accepted)`:
   - malformed: `unavailable/accepted_publication_unverified`;
   - mismatch: `stale/publication_advanced_during_assembly`.
4. Edges: `seed_to_seed` rows go to `seed_to_seed_edges`. `existing` and `new`
   rows attach to their neighbor, in step order. Neighbor units follow
   admission order.
5. Evidence is limited to the first 10,000 rows. Each JSON evidence object
   is converted by the existing `_evidence_tuple_from_json(raw,
   context_identity=True)` in `storage/postgres_navigation_search.py`. That
   adapter returns the 20 location columns plus `node_id`, so the evidence
   object keys must be exactly the ones it reads. Then
   `_direct_location(t[:20], accepted_run_id, snapshot_vector=<accepted
   vector>, context_identity=True)` formats the row. That is SQLite's
   `batch_neighbor_direct_locations` call, including `source_identity_status`,
   run, publication and vector provenance, and the raw payload hash. More than
   10,000 rows gives `neighbor_locations_incomplete=True` with
   `partial/evidence_scan_limit`.

**Failure mapping:**

| Failure | Result |
|---|---|
| Any status above | As stated above. |
| Private `_StatementDeadlineExceeded` (Epic 3, §4.4) | `partial/deadline_exceeded`. |
| `StorageSchemaError` | `unavailable/accepted_publication_unverified` (the existing adapter mapping). |
| `RuntimeError` or `OSError` | `unavailable/database_unavailable`. |
| `KeyboardInterrupt` or `SystemExit` | Propagates untouched. |

A parser or closed-shape failure is never relabelled `deadline_exceeded`,
even when Python-side time has passed the deadline. Only failures raised by
the built-in executor call itself can be (§4.4).

### 2.6 Honest limits

**Physical work is not bounded:**

- Each `LATERAL` window reads and sorts every incident edge of the seed in the
  requested kinds. The existing source and target indexes provide selection by
  incident edge, not the full kind/neighbor/hash order.
- `selected_run` reads every evidence link of up to 128 neighbors.
- `neighbor_evidence` sorts all their direct rows before applying `LIMIT`.
- Row limits bound only returned windows and transport.

**What does bound execution duration:** only Epic 3's server statement timeout,
once RD-1 is disposed.

**Parity scope:**

- PostgreSQL is atomic: under exhaustion it expands zero seeds, while SQLite
  may complete a prefix.
- Transport overflow is PostgreSQL-only.
- Packet serialization differs by `backend`, `consistency_mode` and the ledger.
  Parity is therefore asserted on admitted content with budget headroom. Byte
  boundaries are tested per backend.

### 2.7 Reserved decision RD-2: relation identity in the parity oracle

**Evidence (independent review B1, checked against source):**

- SQLite expansion selects `e.identity_metadata_hash AS edge_key`
  (`context_expansion_queries.py`). `SqliteContextReadAdapter.expand_seeds_depth1`
  deduplicates globally on that value alone (`seen_edge_keys`,
  `rejected_edge_keys`).
- `identity_metadata_hash(metadata)` is
  `sha256_text(canonical_json_text(metadata))` (`storage/row_helpers.py:47-48`).
  It hashes only the identity metadata, not the endpoints or the kind.
- Canonicalizers commonly emit `identity_metadata = {}`, for example
  `_upsert_config_edge` and `_upsert_css_edge` in
  `canonicalization/edge_helpers.py`. The reviewer cites further families.
  All such edges share one hash value.
- So on production-shaped data, after the first such edge is admitted, every
  other edge with the same hash is skipped as already seen. These skips are not
  counted as omissions. A seed can lose almost all its relations silently.
- W4's own relation identity, `_rel_identity` in
  `retrieval/context_admission.py:243-247`, is the 4-tuple
  `(source_key, edge_kind, target_key, identity_metadata_hash)`. The reviewer
  cites the PostgreSQL unique key as the same 4-tuple.
- The W4 SQLite fixture uses synthetic unique hashes (cited by the reviewer;
  this revision did not reopen the fixture), which hides the defect.

**Options:**

- **(a), recommended:** deduplicate on the 4-tuple in both backends. In SQLite
  this changes the `seen_edge_keys`/`rejected_edge_keys` key in
  `expand_seeds_depth1` from `edge_key` to the 4-tuple. It is a Local behavior
  correction toward W4's stated relation identity. It needs updated SQLite
  non-regression tests and a roadmap note.
- **(b):** keep SQLite unchanged and replicate hash-only deduplication in
  PostgreSQL, recording it as a known limitation of both backends. Parity then
  holds, but `graph_investigation` stays degraded on real data.

**Gate.** Option (a) widens Epic 1 into a Local output change, so the parent
decides it at design acceptance. The fold's key is the only part that depends
on RD-2. Everything else in Epic 1 is the same under either option. Epic 1
source work starts only after RD-2 is disposed.

**Required proof under either option:** a parity case whose edges use the real
`identity_metadata_hash({})` value shared by several relations (§6.1 case 9).

## 3. Epic 2: Truthful Server refresh outcomes and exception custody

### 3.1 Witness

New pure module `storage/publication_phase_witness.py`. It does no IO and no
logging.

```python
class PublicationPhase(enum.IntEnum):
    NOT_ENTERED = 0; FINAL_TRANSACTION = 1; ROLLED_BACK = 2
    COMMIT_ATTEMPTED = 3; RECONCILING = 4; COMMITTED = 5; RETURNED = 6

@dataclass
class PublicationPhaseWitness:
    phase: PublicationPhase = PublicationPhase.NOT_ENTERED
    def advance(self, phase: PublicationPhase) -> None:  # max(); never raises
```

**Rules:**

- One witness exists per `_refresh_graph_call`.
- The private witness keyword remains optional at lower seams for compatibility:
  - `_refresh_graph_impl(..., _publication_witness=)`;
  - `execute_portable_refresh(..., publication_witness=)`;
  - the module-level seam `portable_refresh.run_staged_portable_refresh`, which
    forwards `**kwargs`;
  - `storage.staged_ingestion.run_staged_portable_refresh(...,
    publication_witness=None)`;
  - `_run_staged_full_refresh_admitted`.
- The public `execute_portable_refresh` creates an internal witness when its
  optional argument is omitted and always forwards that witness through the
  staged publisher. It must not classify a post-return fault from a fabricated
  `NOT_ENTERED` default.
- The witness is in-process, owned by the parent. It is never serialized and
  never read from a worker. Observers neither own nor fabricate it.
- A lower-level helper explicitly invoked without a witness cannot infer a
  precommit failure; it preserves missing-witness/`NOT_ENTERED` evidence. The
  public path never relies on that absence.

| Phase | Set by (program order) | What it proves |
|---|---|---|
| `FINAL_TRANSACTION` | `staged_ingestion`: first statement inside the `try` that precedes `_run_system_test_publication_pause(handoff)` | Publication transaction may have started; COMMIT not yet sent. |
| `ROLLED_BACK` | Same handler, immediately after `connection.rollback()` returns | Final transaction rolled back; no COMMIT was sent. |
| `COMMIT_ATTEMPTED` | Immediately before the final `connection.commit()` (both branches) | Outcome uncertain from here on. |
| `RECONCILING` | Before `reconcile_commit_unknown` in the commit handler; and in `_run_staged_full_refresh_admitted` before calling `_handle_existing_stage_state` when `existing_state` is `"published"` or `"commit_unknown"` | A prior or current commit may exist. For `"published"` the database already records the stage as published, so a later failure (for example `"staged published receipt is missing"`, `_staged_ingestion_stages.py:319-324`) must never be reported as `not_started`. |
| `COMMITTED` | Where `transaction_committed = True` is set | COMMIT returned. Witness only. Later cleanup faults can escape as the original cleanup error; existing storage handlers may wrap other faults. The witness carries publication uncertainty independently of exception class. |
| `RETURNED` | `execute_portable_refresh`, immediately after the publisher returns a `LoadSummary` | Publication committed, or a replayed or reconciled run matched. |

### 3.2 Classification (new pure `ops/_refresh_outcome.py`)

`classify_refresh_failure(phase, error) -> (publication_state, error_category)`
applies the first matching row. Uncertainty precedes the cancellation label.

| # | Condition | `publication_state` |
|---|---|---|
| 1 | `phase == RETURNED` | `commit_unknown` |
| 2 | `StorageCommitUnknownError`, or `is_commit_unknown` | `commit_unknown` |
| 3 | `phase` ∈ {`FINAL_TRANSACTION`, `COMMIT_ATTEMPTED`, `RECONCILING`, `COMMITTED`} | `commit_unknown` |
| 4 | `phase == ROLLED_BACK` | `rolled_back` |
| 5 | otherwise | `not_started` |

**`error_category`:**

| Error | Category |
|---|---|
| `KeyboardInterrupt`, or an error whose direct `__cause__` is a `KeyboardInterrupt` | `cancelled` |
| Otherwise, when `commit_unknown` | `publication_unknown` |
| Otherwise | `PortableRefreshError.category`, else `worker_crash` (existing) |

The `__cause__` rule covers the storage commit handler and the post-transaction
handler, which raise `StorageCommitUnknownError(...) from error` and so hide a
Ctrl-C. Only the direct cause is consulted. With it, `refresh_enabled_graphs`
stops after an interrupt that storage converted. `publication_state` stays
`commit_unknown`, and §3.4 still reports `commit_unknown` ahead of `cancelled`.

`result` is always `failure`.

**Callers:**

- `_refresh_graph_impl`'s existing catch of `OSError`, `StorageSchemaError`,
  `ValueError` and `PortableRefreshError`.
- `_refresh_graph_call`'s `KeyboardInterrupt` handler. It remains the only
  converter of interrupts.
- Other exception types and `SystemExit` propagate unchanged.

Keeping `cancelled` for interrupts preserves `refresh_enabled_graphs`, which
stops on cancellation. `refresh_terminal` already maps `commit_unknown` to
`publication_unknown` for the coordinator.

Row 3 for `FINAL_TRANSACTION` is deliberately conservative. No COMMIT was sent,
but the rollback was not witnessed, and the vocabulary has no
"not committed, unconfirmed" state.

### 3.3 Exception custody

1. **Final-transaction handler in `staged_ingestion`:**
   - Run `rollback()` first. If rollback raises, do not call
     `mark_failed_before_publication()` or `commit()`; preserve the unsettled
     transaction phase and let classification remain conservative.
   - Only after rollback returns may `mark_failed_before_publication()` and its
     final metadata `commit()` run. If any of those operations raises an
     `Exception`, add a note to the primary (type name only) and re-raise the
     **primary** object.
   - Secondary `BaseException` instances also preserve the primary object;
     attach only a categorical type note. Cleanup with no primary remains
     observable.
   - A rollback failure therefore cannot issue a later commit or commit a
     partial failed-publication transaction; it remains `commit_unknown` until
     existing reconciliation proves the outcome.
2. **`execute_portable_refresh`, publisher raised:**
   - Call `mark_terminal(accepted=False)` only when the phase is in
     {`NOT_ENTERED`, `ROLLED_BACK`} and the error is not commit-unknown.
     Otherwise leave the retained attempt uncertain for receipt
     reconciliation.
   - A secondary `BaseException` from `mark_terminal` or `validated.close()`
     becomes a note on the primary.
   - The primary object (`is`-identical, including `KeyboardInterrupt` and
     `SystemExit`) is re-raised.
3. **`execute_portable_refresh`, after `RETURNED`:**
   - Call `mark_terminal(accepted=True)`. It is **never** followed by
     `accepted=False`.
   - If it raises, call `validated.close()` with the same note rule and
     propagate the original error.
   - The refresh layer classifies that as `commit_unknown`.
   - A normal-return cleanup fault is therefore observable and is never a
     silent success.
4. `PortableRefreshOutcome` and `OpsRefreshGraphResult` are unchanged.
   `outcome.summary.run_id` remains the run identity. No new database read
   follows a commit.

**Limitation: unsettled retained attempts.** Today only
`StorageCommitUnknownError` leaves a retained attempt without a terminal mark.
This design also leaves it unmarked after a post-return fault and after an
interrupt in `FINAL_TRANSACTION`, `COMMIT_ATTEMPTED` or `RECONCILING`. No
source shows anything settling such a record later:

- `_prune_expired_terminal_attempts` removes only terminal retention classes
  (`ops/_portable_retention.py:266-283`);
- direct mode uses a fresh random operation ID per call, so the attempt
  directory is never reused;
- no source shows coordinator reconciliation writing the portable retained
  record.

So the attempt's sealed objects and workspace stay on disk until an operator
removes them. The design accepts this rather than add a reconciliation write,
which the scope forbids. Writing `terminal-failed` instead would assert
non-publication without proof. A test asserts the retained state (§6.2).

The retained namespace lock is nonblocking. Namespace-wide contention may leave
an already-published refresh unsettled as `commit_unknown`, or may fail capture
while preserving the attempt. No new bounded-wait policy is introduced; the
existing refusal and reconciliation boundaries remain authoritative.

Secondary cleanup notes can live on the original exception in `__cause__`
when an existing storage wrapper propagates a different exception. No flattened
note placement or uniform exception-class guarantee is added for callers that
omit a witness. Asynchronous interrupts between rollback return and the next
Python instruction are not atomic with witness advancement; uncertain phases
remain conservative.

### 3.4 Report projection

In `ops/resource_view/_observer_reporting.py::finish_server`, the order becomes:

1. committed success: `committed`;
2. `publication_state == "commit_unknown"`: `commit_unknown`;
3. category `cancelled`: `cancelled`;
4. failure: `failed`;
5. otherwise: `unclassified`.

Observer, report-sink and clock faults stay in the observer's existing degrade
path. They never set a publication state, a rollback, a retry or evidence.

`refresh.py` imports `finish_server` from `resource_view/_projections.py`,
which delegates to the observer. The edit belongs in `_observer_reporting.py`.
Tests drive it through the public `refresh_graph(..., resource_observer=)`
hook, not the private function.

### 3.5 Coordinator and Local

**Coordinator:** no change.

- `refresh_terminal` emits `commit_unknown` with `publication_unknown`.
- `_dispose_terminal` marks reconciliation required.
- When termination is proved and a reader exists, `_reconcile_current` resolves
  an exact matching receipt to `succeeded`.
- A mismatch, an absent receipt, lost ownership or an unresolved readback stays
  non-success.
- `run_refresh_worker` downgrades to `not_started` only on its own phase-file
  proof, as today.

**Local:** shares only `capture_portable_candidate`, which is unchanged. Local
refresh owners are non-regression selectors.

## 4. Epic 3: Remaining-budget server statement timeout

### 4.1 Interfaces

| Owner | Change |
|---|---|
| `retrieval/context_work.py` | New `WorkLedger.remaining_statement_budget_ms() -> int \| None`, computed as `math.floor(deadline_ms - (clock() - start) * 1000)`. Uses the same clock, start and deadline. Never rounds up; never resets per statement. If the value is below 1, it sets `exhausted_reason` to `deadline_exceeded` and returns `None`. This is one millisecond stricter than `check_deadline()`, which uses `elapsed > deadline`: at exactly `elapsed == deadline` no whole millisecond remains, and sending 0 would disable the timeout. The boundary is deliberate and unit-tested. |
| `server/context_read_postgres.py` | `_run_sql_object(sql, *, label, ledger)`. The custom executor branch is unchanged: no budget, no thread, no wrapper. The built-in branch computes the budget immediately before `execute_json_readback(..., statement_timeout_ms=budget)`. It raises a private `_StatementDeadlineExceeded` in two cases only: the budget is `None` (before IO), or `execute_json_readback` itself raised `StorageSchemaError`, `RuntimeError` or `OSError` and `not ledger.check_deadline()` (chained `from` the original). The class subclasses `Exception` directly, so no `StorageSchemaError`/`RuntimeError`/`OSError` handler matches it. The method runs inside the storage executor lambdas. Those readers parse after the executor returns, so parser failures stay outside this rule. Each adapter method catches `_StatementDeadlineExceeded` first and returns `exhausted` (or `partial` for expansion) with `deadline_exceeded`. |
| `storage/readback_driver.py` | Optional `statement_timeout_ms: int \| None = None` on the `PgJsonReadbackConnector` protocol, both connectors, `execute_json_readback` and `execute_json_readback_with_driver`. The keyword is forwarded **only when not `None`**, so default callers and registered doubles stay compatible. |
| `storage/readback_credentials.py` | `validate_statement_timeout_ms`: a non-bool `int` in 1..2,147,483,647, else a bounded `StorageSchemaError` before IO. `resolve_statement_timeout_options(existing, budget_ms)`. `statement_budget_psql_environment(password, budget_ms, psql_args)`. `statement_budget_psycopg_params(params, budget_ms)`. |

`readback_driver.py` is 397 lines. A behavior-preserving extraction is
required; it is chosen after the patch-seam inventory and leaves the existing
module names importable.

### 4.2 Startup-option composition and stricter inheritance

- **Shared tokenizer.** Extract a private tokenizer from
  `_resolve_diagnostic_options`. Diagnostic output stays byte-identical, pinned
  by a unit test.
- **No read-only injection.** `resolve_statement_timeout_options` uses the same
  grammar but **does not** add or alter `default_transaction_read_only`.
- **Recognized `statement_timeout` assignments:** `-c name=value`,
  `-cname=value` and `--name=value`. The name matches case-insensitively, with
  `-` treated as `_`, as PostgreSQL does. Accepted values are
  `\d+(\.\d+)?(us|ms|s|min|h|d)?`; no unit means milliseconds.
- **Merge rules for `statement_timeout`:**
  - Several assignments: PostgreSQL applies the last one, so it is the
    effective value. All are removed and one is appended.
  - Inherited `0` (disabled): use the budget.
  - Inherited positive: if its exact value in milliseconds is at most the
    budget, keep the inherited token unchanged. Otherwise use the budget. No
    rounding is needed to decide which is stricter.
  - Absent: append the budget.
- **Other options:** every unrelated token is preserved verbatim, in order.
- **Psycopg:** inherited options come from `PGOPTIONS` in the environment. The
  merged value is set as `params["options"]`.
- **psql:** a private child environment copy gets
  `PGOPTIONS = merged`. When a password is supplied, it starts from
  `psql_environment(password)`, so the existing scrubbing of
  `PGPASSWORD`/`REPOMAP_PG_PASSWORD` is kept. `os.environ` is never mutated.
- **Refusal.** A bounded `StorageSchemaError` is raised before IO, so the
  budget is never silently disabled or weakened at the startup-option layer,
  when:
  - inherited options contain a backslash, so libpq's whitespace splitting
    is ambiguous;
  - a recognized `statement_timeout` assignment has a value outside the
    accepted grammar, or `-c` has no following token;
  - `PGSERVICE` is set, because service-file `options` outrank `PGOPTIONS`
    and cannot be seen without reading files;
  - any connection value contains `=` or starts with `postgres://` or
    `postgresql://`, because conninfo expansion could carry options;
  - psql args fall outside the flag/value grammar of
    `_psycopg_connection_params_from_psql_args`.
- **Compatibility change.** These refusals apply only to built-in PostgreSQL
  context reads. Today the same configurations run without any budget. After
  this change, a context read with `PGSERVICE` set, a conninfo-shaped
  connection value, psql args outside that grammar, or an unparseable
  inherited `statement_timeout` becomes `unavailable`. Other readback callers are unaffected. The change has its own
  unit and integration assertions (§6.3) and a roadmap note.
- **psql client layer (caller-owned, disclosed).** The psql connector runs
  without `-X` (`readback_driver.py:74`). A user's `~/.psqlrc` or `PSQLRC`
  file runs after startup and can `SET statement_timeout`, which can weaken or
  disable the budget. `REPOMAP_PSQL_COMMAND` may name any executable whose
  basename is `psql` (`server/_ops_records.py:80-90`), including a wrapper
  that does not forward `PGOPTIONS`. Like custom executors, both are client
  configuration the caller owns. The design does not add `-X` or inspect the
  wrapper, because either would change existing psql handling. On this path
  the guarantee is therefore that RepoMap *delivers* the budget as a startup
  option. It is not a claim that the session keeps it. The Psycopg path has
  neither gap.
- **Privacy.** No option string, credential or exception text reaches a report.
- **Statement count.** Startup options add no statement. No `SET` or `SHOW` is
  issued, the 12-statement cap is unchanged, and `connect_timeout` and
  `default_transaction_read_only` are untouched.

### 4.3 Reserved decision RD-1: server-side defaults

**Evidence.** PostgreSQL applies startup options with source `PGC_S_CLIENT`,
which outranks `ALTER DATABASE`, `ALTER ROLE` and configuration-file sources.
`process_startup_options` runs before `process_settings`, and the
lower-priority values are ignored. A stricter server-side default is therefore
replaced for these sessions. Observing it needs an extra statement, which is
forbidden.

**Options (historical, neither accepted):**

- **(a), rejected:** accept and disclose. These values are session defaults,
  not ceilings, and the read role can already `SET` them. The request budget is
  at most 10,000 ms, and every stricter value at the startup-option layer is
  preserved.
- **(b):** descope Epic 3.

**Gate.** Epic 3 remains held. No startup-option timeout code, additional
statement or implementation authority is granted by this specification. Any
future safe replacement requires a separate parent disposition.

### 4.4 Classification, cleanup and limits

| Situation | Result |
|---|---|
| Budget unavailable (below 1 ms) before IO | `exhausted/deadline_exceeded`; assembly produces the existing `partial`. |
| The built-in `execute_json_readback` call raises, and `not ledger.check_deadline()` | `exhausted` (scan, identity or lookup) or `partial` (expansion), with `deadline_exceeded`. |
| A storage parser or identity check fails after the executor returned | Existing mapping, never relabelled, even if the deadline has passed. |
| Fails without proven expiry | Existing mapping: `StorageSchemaError` gives `accepted_publication_unverified`; `RuntimeError`/`OSError` give `database_unavailable`. This covers a stricter inherited timeout, a cancel, SQLSTATE 57014 and a refusal. No driver text or SQLSTATE is parsed, and psql stderr is not parsed. |
| `KeyboardInterrupt` or `SystemExit` | Unchanged; propagates. |

**Disclosed consequence of the existing mapping.** The Psycopg connector turns
every driver exception into a sanitized `StorageSchemaError`
(`readback_driver.py:114-119`). A query cancelled by a stricter inherited
timeout, before the request deadline, therefore surfaces as
`unavailable/accepted_publication_unverified`, not `database_unavailable`. The
deadline grant keeps that existing classification, and this design does not
change it. The label does not claim the publication is actually unverified.

Because the budget is floored, a cancel can rarely arrive up to 1 ms before the
ledger deadline. Such a cancel is honestly classified as unavailable.

**Cleanup.** The existing owners keep cleanup. Psycopg uses `with
psycopg.connect(...)`, which closes on any exception. psql runs with
`ON_ERROR_STOP` and exits, and `run_psql` owns the process. No client timeout,
process-group supervisor, retry or cancel protocol is added.

**What the timeout does not bound:**

- connection or subprocess startup;
- Python assembly;
- network transfer;
- custom executors;
- whole-request latency;
- rows scanned, memory or locks.

## 5. Owners, line budgets and quality enrollment

| File | Epic | Change | Line constraint |
|---|---|---|---|
| `retrieval/context_assembly.py` | 1 | predicate | ≤400 |
| `retrieval/context_packet_builder.py` | 1 | predicate, stale expansion, stale helper | stays ≤400 |
| `server/context_read_postgres.py` | 1, 3 | attribute, expansion, budget plumbing | ≤400 (about 370 forecast) |
| `storage/postgres_context_expansion_sql.py` | 1 | **new**: builder and parser | about 280 |
| `storage/sqlite_local/context_expansion_queries.py` | 1 | extract `incident_edge_record` | behavior-preserving |
| `server/context_read_sqlite.py` | 1 | RD-2 (a) only: 4-tuple deduplication key | Local behavior correction; ≤400 |
| `storage/publication_phase_witness.py` | 2 | **new** | about 50 |
| `storage/staged_ingestion.py` | 2 | witness marks, handler custody | ≤400 |
| `ops/_refresh_outcome.py` | 2 | **new**: classifier and post-return settlement helper | about 110 |
| `ops/_portable_refresh_custody.py` | 2 | **new**: owned cleanup, conservative settlement and fresh Server root preparation | ≤400 |
| `storage/_staged_refresh_custody.py` | 2 | **new**: ordered resource cleanup preserving the explicit primary | ≤400 |
| `ops/portable_refresh.py` | 2 | witness, settlement through helper | ≤400 (383 today) |
| `ops/refresh.py` | 2 | witness creation, classifier use | ≤400 (390 today; replace inline labels) |
| `ops/resource_view/_observer_reporting.py` | 2 | precedence | small |
| `retrieval/context_work.py` | 3 | `remaining_statement_budget_ms` | small |
| `storage/readback_credentials.py` | 3 | tokenizer and composition | about 200 |
| `storage/readback_driver.py` | 3 | keyword forwarding, extraction | ≤400 |

**Pure versus IO:**

- **Pure:** the builder and parser, the fold, the witness, the classifier,
  option composition and the ledger budget.
- **IO stays in the existing owners:** connectors, the staged publisher, and
  retention.

**Quality enrollment:**

- New modules are enrolled clean (Ruff F, mypy, file length) in the
  retained-Python baseline and scope-transition documents named by
  `BASELINE_PATH`/`SCOPE_PATH` in
  `repomap_test_support/retained_ratchet_fixture.py`. One forward record covers
  phase `REPOMAP-CLOE-SERVER-PARITY1`.
- The literal `FORWARD_ADMISSIONS` tuple in
  `src/test/unit/python/tools/ci/retained_python_projection.unit.test.py`
  appends `"REPOMAP-CLOE-SERVER-PARITY1"`. This is the CI127 failure class.
- Edited modules add no debt.
- Every quality, debt and history prefix, every inventory and denominator, and
  every suppression is preserved. No ratchet is weakened.

## 6. Tests and exact implementation selectors

The planned owner names have been reconciled to the actual implementation.
The exact scoped unit and integration owners below cover the selected
contracts; their final observed results and correction-review disposition
belong in the phase commit. These selectors and the criteria below are not a
whole-population or coverage claim. Required cases remain acceptance criteria
until their actual results are recorded. No complete local suite is selected.
Integration uses the existing disposable container sandbox and real PostgreSQL
and SQLite fixtures. Public command forms omit private report destinations.

```sh
python3 tools/run_tests.py --suite unit --no-coverage --jobs 1 -- \
  src/test/unit/python/repomap_kg/artifacts/filesystem_store_no_create.unit.test.py \
  src/test/unit/python/repomap_kg/cli/retained_attempt_commands.unit.test.py \
  src/test/unit/python/repomap_kg/ops/portable_refresh_outcome_custody.unit.test.py \
  src/test/unit/python/repomap_kg/ops/refresh_outcome_witness.unit.test.py \
  src/test/unit/python/repomap_kg/ops/retained_attempt_artifacts.unit.test.py \
  src/test/unit/python/repomap_kg/ops/retained_attempt_custody.unit.test.py \
  src/test/unit/python/repomap_kg/ops/retained_attempt_locking.unit.test.py \
  src/test/unit/python/repomap_kg/ops/retained_attempt_recovery.unit.test.py \
  src/test/unit/python/repomap_kg/retrieval/context_assembly.unit.test.py \
  src/test/unit/python/repomap_kg/retrieval/context_relation_identity.unit.test.py \
  src/test/unit/python/repomap_kg/storage/context_expansion_queries.unit.test.py \
  src/test/unit/python/repomap_kg/storage/context_work_boundaries.unit.test.py \
  src/test/unit/python/repomap_kg/storage/postgres_context_expansion.unit.test.py \
  src/test/unit/python/repomap_kg/storage/staged_refresh_custody.unit.test.py \
  src/test/unit/python/repomap_kg/ops/portable_refresh_routing.unit.test.py \
  src/test/unit/python/repomap_kg/ops_refresh/arch4a_complete_publication.unit.test.py \
  src/test/unit/python/repomap_kg/ops_refresh/refresh_execution.unit.test.py \
  src/test/unit/python/repomap_kg/storage/general1_staged_ingestion_contracts.unit.test.py \
  src/test/unit/python/repomap_kg/storage/scale8_staged_ingestion.unit.test.py \
  src/test/unit/python/repomap_kg/storage/retained_publication_readback.unit.test.py \
  src/test/unit/python/tools/ci/retained_python_projection.unit.test.py \
  src/test/unit/python/tools/ci/python_retention_dynamic.unit.test.py \
  src/test/unit/python/repomap_test_support/test_cov5k_r2_fix2_dynamic_targets.unit.test.py
python3 tools/run_tests.py --suite int --no-coverage --jobs 1 --pg-container-port 55433 -- \
  src/test/int/python/repomap_kg/retrieval/context_postgres_expansion.int.test.py \
  src/test/int/python/repomap_kg/retrieval/context_postgres_publication.int.test.py \
  src/test/int/python/repomap_kg/ops/server_refresh_outcome_custody.int.test.py \
  src/test/int/python/repomap_kg/ops/server_retained_attempt_recovery.int.test.py \
  src/test/int/python/repomap_kg/ops/server_retained_attempt_recovery_custody.int.test.py \
  src/test/int/python/repomap_kg/storage/scale8_staged_ingestion_recovery.int.test.py \
  src/test/int/python/repomap_kg/coordinator/portable_durable_readback.int.test.py::test_worker_produced_portable_bundle_durable_publication_readback_and_reconciliation[core] \
  src/test/int/python/repomap_kg/retrieval/context_sqlite_publication.int.test.py::test_sqlite_expansion_progress_limit_and_statement_37_interception \
  src/test/int/python/repomap_kg/retrieval/context_freshness_bounds.int.test.py::test_sqlite_expansion_keeps_relation_to_admitted_nonexpanded_seed \
  src/test/int/python/repomap_kg/retrieval/context_postgres_evidence_bound.int.test.py
```

The literal `FORWARD_ADMISSIONS` and closed dynamic-target owners are
selected with their actual source commitments. New PostgreSQL evidence-bound
and retained-recovery owners enter the same clean inventory without new debt.
Local regression proof is the exact selected SQLite nodes; whole Local and
first-use populations remain deliberately unselected. Existing staged
recovery and durable publication readback owners supply the related committed,
reconciled and rollback paths. Final campaign-grant proof is a separate,
post-binding exact selection and excludes its unrelated materialization node.

### 6.1 Epic 1 tests

**Unit:**

- Builder input refusal before IO.
- Literal escaping: a seed containing a quote.
- Every relation filtered by repository and accepted identity; limits
  `edge_limit+1`, 256, 128 and 10,001.
- Parser: a closed-shape violation becomes `StorageSchemaError`; mapping to
  `ok`, `partial` (evidence or transport), `stale` (absent or mismatched) and
  `unavailable` (malformed).
- Ledger: one statement and one unit, `seed_expansions += k`, and pre-IO
  exhaustion.
- Capability matrix: the built-in adapter, a PostgreSQL double without the
  attribute, and an attribute set to `False`.
- Builder stale handling.
- Byte-identical `incident_edge_record` output for SQLite.
- Fold state: the seed-boundary case (§2.4), and `transport_overflow` returning
  `seeds_expanded=0`.
- A parser closed-shape failure after the deadline has passed stays
  `unavailable/accepted_publication_unverified`.
- RD-2 (a) only: SQLite `expand_seeds_depth1` keeps distinct relations that
  share one hash, and still deduplicates a self-loop seen in both windows.

**Integration (real PostgreSQL plus SQLite).** Packet admitted-content parity
for `graph_investigation` and `ranked_discovery` at depth 1:

1. the greedy counterexample;
2. more than 64 incident edges per direction, more than 128 neighbors and more
   than 256 relations across 5 seeds, including self-loops and seed-to-seed
   edges;
3. mixed bindings, prefixes and current/historical-run direct-location
   provenance, including `source_identity_status` and payload hash;
4. cross-repository poison in the same database;
5. publication advanced between seed lookup and expansion, giving `stale`;
6. absent and malformed accepted publication;
7. more than 10,000 admitted-neighbor evidence rows gives PostgreSQL
   `partial/evidence_scan_limit` with bounded public source locations. For the
   same large fixture SQLite reaches its unchanged VM-progress ceiling first,
   returns `partial/work_budget_exhausted`, and emits no incomplete neighbors
   or relations. This is a disclosed backend resource difference, not a claim
   of identical physical work or overflow reasons;
8. the PostgreSQL statement ledger stays at or below 12, with expansion equal
   to 1; SQLite retains its existing 36-statement ceiling;
9. production-shaped hashes: several relations whose stored hash is the real
   `identity_metadata_hash({})` value, which also satisfies the PostgreSQL
   `^[0-9a-f]{64}$` check. Under RD-2 (a) both backends admit all of them.
   Under (b) both drop the same ones, and the limitation is asserted
   explicitly.

### 6.2 Epic 2 tests

**Unit:**

- Witness monotonicity, and `advance` never raises.
- All classifier rows.
- A `KeyboardInterrupt` injected at each phase.
- `SystemExit` identity propagates.
- A lower-level helper called explicitly without a witness cannot infer a
  precommit failure; the public default creates and forwards an internal
  witness, and a post-return fault is `commit_unknown`.
- A post-return `mark_terminal(accepted=True)` failure never writes
  `terminal-failed` and is classified `commit_unknown`.
- `mark_terminal(accepted=False)` and `validated.close()` failures become notes
  on an `is`-identical primary.
- Final-handler custody uses a fake connection: a `mark_failed` failure leaves
  the primary intact and the phase at `ROLLED_BACK`; an interrupt inside
  reconciliation gives `RECONCILING`.
- `existing_state == "published"` with a missing receipt gives `RECONCILING`
  and `commit_unknown`, never `not_started`, and no `terminal-failed` mark.
- A rollback failure in the final handler preserves the primary, does not call
  `mark_failed_before_publication()` or `commit()`, and remains unsettled.
- A `StorageCommitUnknownError` whose `__cause__` is a `KeyboardInterrupt` gives
  `commit_unknown`/`cancelled`, and `refresh_enabled_graphs` stops.
- An unsettled retained attempt: after a post-return fault, the retained record
  has neither terminal class, and `_prune_expired_terminal_attempts` leaves it.
- `finish_server` precedence, driven through the public
  `refresh_graph(..., resource_observer=)` hook.

**Integration (`server_refresh_outcome_custody`, real temporary PostgreSQL):**

1. The post-commit grant regression:
   - Inject the original `KeyboardInterrupt` object after the real staged
     publisher returns, optionally together with a `validated.close` error.
   - Assert that the accepted publication is complete, the retained attempt is
     not `terminal-failed`, the result is `failure`/`commit_unknown`/
     `cancelled`, and the resource report outcome is `commit_unknown`.
   - Assert that `refresh_terminal` and the existing coordinator store
     reconciliation yield `succeeded`.
   - Assert exactly one capture, worker and publisher invocation.
2. Interrupt through `authority.before_publication`: the outcome is
   `rolled_back`/`cancelled`, and the run and stage are failed in the database.
3. Interrupt during capture: `not_started`/`cancelled`.
4. A fault injected into `mark_failed_before_publication` after rollback: the
   primary is preserved and the outcome is `rolled_back`.
5. A mismatched or absent receipt is not promoted to success.
6. Under umask `002`, first-owned publication-root creation is mode `0700`
   before attempts or shared locks; an existing `0755` anchor is admitted, but
   an existing group-writable root is refused/held without chmod or permission
   migration.

### 6.3 Epic 3 tests (held; not activation or proof)

Epic 3's selectors remain a rejected/held proposal only. They do not authorize
source work or constitute pass evidence while RD-1 is held.

**Unit:**

- Default forwarding is unchanged, and the keyword is absent when `None`.
- Strict admission: bool, float, 0 and negative are rejected.
- The budget decreases across calls; zero is never sent; no reset or
  escalation; the `elapsed == deadline` boundary returns `None`.
- Stricter inherited values in us, ms, s, min, h and d, fractional values,
  `-c`, `-cname=` and `--name=` forms, and case and dash spellings; the last of
  several assignments wins; backslash and bad-value refusal; unrelated tokens
  preserved verbatim.
- `PGSERVICE` and conninfo refusal, asserted as the compatibility change for
  context reads only. Non-context readback with the same environment is
  unchanged.
- A failure raised by the parser after the executor returned is not relabelled
  `deadline_exceeded`.
- Password scrubbing.
- Exactly one statement executed by a fake Psycopg connection, and one psql
  stdin.
- Custom executor bypass.
- Ledger-based classification.
- The 12 and 16 ceilings are unchanged.

**Integration, both connectors, selected through `REPOMAP_STORAGE_PG_CONNECTOR`.**
psql cases set `PSQLRC` to an empty test file, because a user's psqlrc is
caller-owned (§4.2).

1. Normal context succeeds.
2. A `current_setting('statement_timeout')` probe through the real connector
   shows the composed budget, `default_transaction_read_only` unchanged, and
   no `SET`.
3. A delayed read via `pg_sleep` (test-substituted SQL, `deadline_ms=1500`)
   is cancelled and gives `deadline_exceeded`.
4. A stricter `PGOPTIONS` stays stricter, gives a non-deadline classification,
   and is not weakened.
5. A subsequent independent read succeeds.
6. No owned backend remains in `pg_stat_activity`.
7. `pg_roles` and `pg_db_role_setting` are unchanged.
8. With `PGSERVICE` set, the context read is `unavailable` before any backend
   connects, which is the compatibility change.

## 7. Size forecast (meaningful LOC, no padding)

| Part | Production | Tests | Docs |
|---|---:|---:|---:|
| Epic 1 | 430–540 | 950–1,200 | — |
| Epic 2 | 290–370 | 850–1,050 | — |
| Epic 3 | 200–260 | 550–700 | — |
| Exit, ops and spec updates | — | — | 200–300 |
| **Total** | **920–1,170** | **2,350–2,950** | **200–300** |

The total is about 3.5k–4.4k. Under RD-2 (b) Epic 1 is about 40 lines
smaller. It cannot reach 10k without padding. The third
epic is already added. Remaining W7 items need separate selection; these
grants do not cover them. Those items are worker attribution, numeric
governance and whole-I/O governance. Nothing further is justified.

## 8. Alternatives and rollback

See ADR 0168. In addition, a Python fold over superset rows was rejected
because it is unbounded and starves evidence. A contextvar witness was
rejected because it is implicit and global.

**Rollback per epic:**

- Epic 1: remove the attribute and predicate.
- Epic 2: stop passing the witness; the classifier then sees `NOT_ENTERED`.
- Epic 3: stop passing `statement_timeout_ms`.

There is no data or schema rollback. Retained-Python scope retirement is a
forward record.

## 9. What would make this design wrong

- Real PostgreSQL parity cases diverge from SQLite in admitted neighbors,
  relations, omissions or locations, apart from the documented atomicity,
  transport and byte-boundary differences.
- `LATERAL`, or the recursive step with a `LATERAL` subselect, is rejected by
  the pinned PostgreSQL 16, and no equivalent inline form exists.
- `COLLATE "C"` order differs from SQLite `BINARY` on a fixture.
- Any path can commit after the witness reports `ROLLED_BACK` or
  `NOT_ENTERED`.
- Any path writes `terminal-failed` after `RETURNED`.
- The coordinator's matching receipt does not resolve to `succeeded`.
- Startup-option application needs a statement, or weakens a value set at the
  startup-option layer.
- A fold step that does not set `seed_ord` and `seed_new` as §2.4 states
  still passes the parity cases. That would mean the cases are too weak.
- Parity case 9 passes on SQLite only because the fixture's hashes are
  synthetic.
- The storage navigation and location readers catch executor exceptions
  themselves. That would break the `_StatementDeadlineExceeded` path in §4.1.
- RD-1 is rejected and no alternative remains.

## 10. Reserved decisions and stops

- **RD-1 (§4.3)** gates Epic 3 only.
- **RD-2 (§2.7)** gates Epic 1 source work. Only the fold key and the SQLite
  correction depend on it.

Epic 2 does not depend on either. Nothing else is reserved. Ordinary W7
choices need no further approval ceremony; the parent's design acceptance is
the next gate.

## 11. Independent review disposition

One independent design review ran against
`5ce48979661a13cd017bca48fea7f61ac6ec23b8`. This revision dispositions it as
follows. No second independent review followed.

| Finding | Disposition | Where |
|---|---|---|
| B1: the SQLite oracle deduplicates on the hash alone | Accepted as evidence; offered to the parent as RD-2, recommending the 4-tuple | §2.3, §2.4, §2.7, §6.1 |
| S1: unsettled retained attempts have no settling owner | Accepted as a disclosed limitation, with a test | §3.3, §6.2 |
| S2: the deadline relabel is too broad | Accepted: only executor-raised failures; Psycopg mapping disclosed | §2.5, §4.1, §4.4 |
| S3: fold state is underspecified | Accepted: every step sets `seed_ord` and `seed_new`; seed-boundary case | §2.4, §6.1 |
| S4: psqlrc and psql wrappers on the psql path | Accepted as disclosure; `-X` not added | §4.2 |
| S5: refusals regress working configurations | Accepted: grammar widened, refusals narrowed, compatibility change asserted | §4.2, §6.3 |
| S6: `published` with a missing receipt is reported `not_started` | Accepted: `RECONCILING` for both existing states | §3.1, §6.2 |
| A1: name the JSON-to-row adapter | Accepted | §2.5 |
| A2: `seeds_expanded` on transport overflow | Accepted: 0 | §2.5 |
| A3: a Ctrl-C converted by storage loses `cancelled` | Accepted: direct `__cause__` | §3.2 |
| A4: the zero-budget boundary | Accepted: deliberate 1 ms stricter boundary | §4.1 |
| A5: where the precedence edit goes | Accepted: tests use the public hook | §3.4 |

## Parent implementation entry

ADR0168 accepts Epics1–2 and selects RD-2(a). References to option(b) above
are rejected-alternative history. Epic3 startup composition and its selectors
are held, unimplemented proposals. The parent primary-custody rule governs
where any earlier ordinary-Exception wording differs. No source, test,
coverage, native or installed result is implied by this design acceptance.
