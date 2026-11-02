# ADR 0133: Intent-aware deterministic navigation, bounded compact context, and advisory source freshness

## Status and authority

Status: Implemented in `REPOMAP-CLOE-CONTEXT1` ([exit report](../../../../tools/ci/cloe-context1-exit.md),
[operations guide](../../../ops/compact-context.md)); authored and accepted for bounded
implementation in design phase `REPOMAP-CLOE-CONTEXT-DESIGN1`. Date: 2026-11-01.

The operator reported `ci passed. carry on with roadmap`, and the parent
independently accepted CI104 attempt 1 on staging
`7babd887cb6b46c2791a22d57baddcdc24914463` following the CI102 and CI103 repair
phases ([ADR 0131](../10/0131-ci102-compatibility-repair-and-twentieth-native-amd-attempt.md)
and [ADR 0132](0132-ci103-measured-child-repair-and-successor-qualification.md)).
CI104 passed all nine jobs, including 14,947 unit tests (88.0% statement and
87.1% branch coverage) and 1,961 measured staging integration tests (89.8%
statement and 81.4% branch coverage). That acceptance qualifies the W3 candidate
only and authorizes advancing to W4 on the approved
[CLOE transition roadmap](../../../specs/cloe-roadmap-transition-v1.md).

Following independent review and parent design acceptance (`DESIGN-ACCEPTANCE.json`),
`REPOMAP-CLOE-CONTEXT1` implements Epics A, B, and C with scoped unit and
containerized integration verification plus the 20-task × 7-arm × 3-repetition
`context-v1` calibration run (`w4-context-calibration-attempt-1`). No dependency
addition, database migration, runtime/image build, criteria acceptance, or
held-out evaluation query execution is performed.

## Context

W2 ([ADR 0127](../10/0127-cloe-retrieval-contracts-and-evaluation.md),
[cloe-retrieval-evaluation-v1.md](../../../specs/cloe-retrieval-evaluation-v1.md))
established the internal six-mode retrieval contract (`cloe-retrieval-query-v1`),
five match surfaces, the bounded in-memory captured-text projection reference,
and the 36-task `mixed-v1` benchmark (24 calibration, 12 held-out). W3
([ADR 0129](../10/0129-postgresql-native-lexical-search-and-publication-pinning.md),
[cloe-native-lexical-search-v1.md](../../../specs/cloe-native-lexical-search-v1.md))
added owner-fenced PostgreSQL native lexical search (`cloe_lexical`), single-statement
request-pinned PostgreSQL metadata parity for `navigation_search` and
`node_locations`, evaluation v2 provenance accounting, and the retained
`w3-calibration-attempt-2` observation (24 tasks × 6 arms × 3 repetitions = 432
query observations with zero execution failures).

Four concrete product gaps remain for W4:

1. **Unranked literal metadata navigation and direct-evidence role coverage:**
   `navigation_search` (`storage/navigation_search.py`,
   `storage/sqlite_local/navigation_queries.py`,
   `storage/postgres_navigation_search.py`) matches escaped `LIKE` substrings
   across `canonical_key`, `kind`, and `display_name` and orders candidates by
   `canonical_key ASC`. It cannot prioritize exact symbol definitions,
   distinguish production definitions from test symbols without a universal test
   penalty, or rank documentation and message artifacts by declared caller
   intent. Furthermore, `_EVIDENCE_ROLE_SQL`
   (`storage/sqlite_local/node_location_queries.py:17-27`) assigns the `direct`
   role only to `python.{module,class,function,method}` and
   `doc.{page,section,adr,skill}`. While Python test modules, classes,
   functions, and methods are canonicalized under those four `python.*` kinds
   (`extractors/languages/python.py:140-161`; `python.test_*` are raw-profile
   observation kinds only), non-Python test canonical kinds (`bats.*`,
   `zunit.*`, `js.test_*`, `ruby.test_*`, `nix.check`) and message canonical
   kinds (`email.*`, `feed.*`) have evidence links in
   `canonical_node_evidence` (`observed`, or `inferred_from_edge` on child nodes
   emitted by `canonicalization/_shell_edge_helpers.py:57-70`) that
   `_EVIDENCE_ROLE_SQL` classifies as `unknown` or `reference`.
   Because `_scope_predicate` (`navigation_queries.py:115-130`) requires
   `direct` evidence for binding/prefix admission, scoped navigation scans
   exclude those non-Python test and message nodes. Widening the shared
   `_EVIDENCE_ROLE_SQL` would alter existing MCP `repomap_navigation_search` and
   `repomap_node_locations` payloads.
2. **No bounded compact-context product path:** `QueryEnvelope` v1 requires all
   hits to share a single `match_surface` and carries only `(binding_id,
   source_relative_path, start_line, end_line)` in `EvaluationLocator` without
   `binding_revision`, `snapshot_id`, or `run_id` (`retrieval/query_contracts.py:85-135,283-339`).
   Existing one-hop context assembly in `tools/related_source_context.py` is a
   repository-local developer helper, not an installed CLI or library contract
   with strict serialized UTF-8 byte admission, identity-preserving
   deduplication, and separate storage-work bounds. In storage, SQLite supports
   depth-1 bounded neighborhoods ([ADR 0083](../10/0083-bounded-configured-neighborhood.md))
   without pre-`LIMIT` edge-kind filtering, while PostgreSQL has an unbounded
   neighborhood query owner (`storage/sql_neighborhood.py`) and refuses bounded
   neighborhood requests (`server/investigation_read_store.py:318-319`).
3. **No reusable source-selection record or productized advisory freshness check:**
   Callers must repeat binding and path-prefix flags per invocation and have no
   supported way to pin an expected publication snapshot across CLI calls or
   perform bounded, opt-in local source freshness checks without conflating
   working-copy drift with database publication staleness (`CapabilityState.STALE`,
   which forbids hits).
4. **Pending evaluation and coverage dispositions:** In `mixed-v1`, proposed v2
   criteria remain unaccepted, the native comparator's 495,781-byte output
   exceeds the proposed 65,536-byte envelope ceiling, the incumbent PostgreSQL
   graph baseline scores 0/1 on the absent-answer task where SQLite scores 1/1,
   all 12 `mixed-v1` held-out tasks remain unexecuted, and CI104's 81.4%
   measured staging branch coverage remains ~0.6 percentage points short of the
   82% target margin.

## Decision

Specify a cohesive three-epic W4 milestone (`REPOMAP-CLOE-CONTEXT1`) governed by
this ADR and the companion specification
[cloe-intent-context-v1.md](../../../specs/cloe-intent-context-v1.md).

### D1. Preserved contracts and new closed W4 contracts

- **Unchanged contracts and boundaries:**
  - All six `QueryMode` values (`exact_identity`, `current_literal_enumeration`,
    `literal_captured_text`, `ranked_discovery`, `graph_investigation`,
    `semantic_discovery`) and five `MatchSurface` values (`captured_text`,
    `stored_metadata`, `graph_topology`, `direct_handoff`, `none`) in
    `common_lore_index.retrieval.query_contracts`.
  - `QueryEnvelope` (`cloe-retrieval-query-v1`), `QueryHit`, `EvaluationLocator`,
    `FallbackDisclosure`, and `OmissionRecord`.
  - The read-only MCP tool catalog, schemas, ordering, `_EVIDENCE_ROLE_SQL` in
    `storage/sqlite_local/node_location_queries.py`, and `InvestigationReadStore`.
  - Existing P1 lexical/body privacy and DB-owner credential isolation.
- **New closed W4 contracts:**
  - `cloe-compact-context-v1`: bounded single-line JSON context packet.
  - `cloe-source-selection-v1`: caller-held reusable source-selection record.
  - `cloe-intent-rank-v1` and `cloe-intent-tiebreak-v1`: deterministic
    lexicographic tier ordering and backend-independent byte tie-break.
  - `cloe-intent-tables-v1`: versioned intent-to-kind affinity table, Python
    test-subject classifier, intent-to-edge-kind expansion table, and isolated
    context direct-evidence role table (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`).
  - `cloe-advisory-freshness-v1`: opt-in bounded structural source-freshness
    observations.

### D2. Explicit mode contract and no implicit mode switching

`cloe ops context-pack` and `ContextRequest` require an explicit `--mode`
(`requested_mode`) selecting one of the six `QueryMode` values. Mode is never
inferred from `--canonical-key` or `--query`.

| Requested `--mode` | Required / allowed target flags | Context v1 execution and surfaces |
|---|---|---|
| `exact_identity` | Requires `--canonical-key`; rejects `--query`, `--intent`, `--expand-depth 1` | Reads `node_locations` for the key. Seed item uses `match_surface="stored_metadata"`. |
| `current_literal_enumeration` | Requires `--query`; rejects `--canonical-key`, `--intent`, `--expand-depth 1` | Preserves existing ascending `canonical_key` scan order (`ordering_policy_version="canonical-key-asc-v1"`). Items use `match_surface="stored_metadata"`. |
| `ranked_discovery` | Requires `--query`; optional `--intent` (default `general`), `--expand-depth 0\|1` (default `0`); rejects `--canonical-key` | Ranks complete candidate scans under `cloe-intent-rank-v1`. Ranked seeds use `item_role="seed"`, `match_surface="stored_metadata"`. When `--expand-depth 1` runs on SQLite, `effective_mode` remains `ranked_discovery` (`fallback=None`) and expanded neighbors/relations use `item_role="neighbor"`, `match_surface="graph_topology"`. |
| `graph_investigation` | Requires `--canonical-key`; `--expand-depth` must be `1` (default `1`); optional `--intent` (default `general`, selecting default edge kinds). Rejects `--query` unless `--fallback-to ranked_discovery` is also set | On SQLite: locates the center seed (`item_role="seed"`, `match_surface="stored_metadata"`) and expands depth-1 typed neighbors (`item_role="neighbor"`, `match_surface="graph_topology"`). On PostgreSQL: returns `status="unavailable"`, `unavailable_reason="backend_unsupported"` unless the caller explicitly passes `--fallback-to exact_identity` (uses `--canonical-key`) or `--fallback-to ranked_discovery` (requires `--query`), recording a `FallbackDisclosure`. |
| `literal_captured_text` | Any | Returns `status="unavailable"`, `unavailable_reason="capability_not_admitted"` with zero storage reads. Body search remains in `cloe ops lexical-query`. |
| `semantic_discovery` | Any | Returns `status="unavailable"`, `unavailable_reason="capability_not_admitted"` with zero storage reads. |

### D3. Epic A — Explicit intent-aware deterministic navigation

1. **Closed caller-declared `NavigationIntent`:** `definition`, `implementation`,
   `tests`, `docs`, `messages`, `general`. Intent is never inferred from query
   text and is rejected in `exact_identity` and `current_literal_enumeration`.
2. **Isolated context direct-evidence role (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`)
   and storage scan reuse:**
   To make scoped selections (`cloe-source-selection-v1` and `--binding` /
   `--path-prefix`) work truthfully for `tests` and `messages` without changing
   MCP `repomap_navigation_search` or `repomap_node_locations`, the context
   query owners (`server/context_read_sqlite.py` and
   `server/context_read_postgres.py`) reuse the existing storage scan and
   locator owners (`storage/sqlite_local/navigation_queries.py`,
   `storage/sqlite_local/node_location_queries.py`,
   `storage/postgres_navigation_sql.py`, `storage/postgres_navigation_search.py`,
   and `storage/postgres_node_locations.py`) via a keyword-only
   `role_sql: str = _EVIDENCE_ROLE_SQL` parameter and pass the isolated SQL role
   predicate `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`. `--query` (`1..200` stripped
   Unicode characters, `<= 800` UTF-8 bytes) and `--offset` (`0..1,000`, a
   subset of `0..10,000`) validate directly through `NavigationSearchQuery`.
   Evaluated before the fallback `WHEN link.link_kind = 'inferred_from_edge'
   THEN 'reference'` branch, `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` classifies a
   `canonical_node_evidence` link as `direct` when:
   - it matches one of the eight MCP direct rules (`link.link_kind = 'observed'`
     for `python.{module,class,function,method}` and
     `doc.{page,section,adr,skill}`);
   - `link.link_kind = 'observed'` and `e.raw_kind = subject.kind` for message
     canonical kinds `email.{mailbox,message,part,attachment_stub,thread_hint,address}`
     (`canonicalization/email_family.py:96,174`) and
     `feed.{document,channel,item,author,category}`
     (`canonicalization/feed_family.py:92`);
   - `link.link_kind = 'observed'` and `e.raw_kind = subject.kind` for explicit
     test/check canonical kinds `js.{test_suite,test_case}`
     (`canonicalization/language_javascript_family.py:103`),
     `ruby.{test_case,test_method}` (`canonicalization/language_family.py:218`),
     `bats.file` (`canonicalization/shell_bats_family.py:219`),
     `zunit.{file,command_under_test}`
     (`canonicalization/shell_zunit_family.py:272,581`), and `nix.check`
     (`canonicalization/nix_family.py:316`);
   - `link.link_kind IN ('observed', 'inferred_from_edge')` for shell test child
     canonical kinds emitted via `_append_two_node_edge`
     (`canonicalization/_shell_edge_helpers.py:57-70`, which links the child
     definition observation to both parent and child with
     `inferred_from_edge` while `e.raw_kind` names the child observation):
     `e.raw_kind = subject.kind` with
     `subject.kind IN ('bats.test_case', 'zunit.suite', 'zunit.test_case',
     'zunit.assertion', 'zunit.expectation', 'zunit.mock', 'zunit.stub')`,
     or `(subject.kind = 'bats.expectation' AND e.raw_kind IN ('bats.assertion',
     'bats.refutation'))`, or `(subject.kind = 'zunit.hook' AND e.raw_kind IN
     ('zunit.setup', 'zunit.teardown', 'zunit.before_each', 'zunit.after_each',
     'zunit.hook'))`.
   MCP query owners continue using `_EVIDENCE_ROLE_SQL` unchanged. The set of
   canonical node kinds with a `direct` rule (`DIRECT_LOCATABLE_CANONICAL_KINDS_V1`)
   is derived programmatically from the `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` rule
   table (verified by unit test, never hand-enumerated). Under any scoped
   request: (a) if `--kind` is passed and any requested kind is outside
   `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`, `context-pack` returns
   `status="unavailable"`, `unavailable_reason="unlocatable_kind_in_scoped_selection"`
   with `scope_complete=False`; (b) whenever any requested `--kind` or active
   intent-affine kind (even without `--kind`) is outside
   `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`, `scope.unlocatable_kind_patterns_excluded`
   lists the sorted excluded pattern tokens,
   `omission_counts.unlocatable_kind_pattern_excluded` counts them,
   `scope.scope_complete` is `False`, and zero-item scoped packets report
   `absence_basis="stored_direct_locatable_metadata_fields_in_selected_scope"`.
3. **Deterministic subject classification (`cloe-intent-tables-v1`) and no
   universal test penalty:** Because Python test files, classes, functions, and
   methods are stored in `canonical_nodes` with `kind IN ('python.module',
   'python.class', 'python.function', 'python.method')`,
   `classify_subject_intent_family(node, verified_direct_locations)` classifies
   a `python.*` node as `python_test_subject` when any verified direct location
   path satisfies the repository test-path predicate (`tests` or `test` path
   segment, `test_*` filename, or `*_test.py` / `*.test.py` suffix) or when its
   symbol segment is a `python.function`/`python.method` starting with `test_`
   or a `python.class` starting with `Test`.
   - Under `definition` and `implementation`: non-test code definition kinds
     (non-test `python.{module,class,function,method}`, `go.*`, `js.{file,module,function,class,method,component,route}`,
     `ruby.{file,module,class,method,singleton_method,constant,route}`,
     `bash.*`, `zsh.*`, `awk.*`, `powershell.*`, `nix.{app,package,devShell}`,
     `config.*`, `css.*`, `html.*`, `xml.*`) are `intent_kind_affine`;
     `python_test_subject` and explicit test kinds are `intent_kind_neutral`
     (never penalized below docs or messages).
   - Under `tests`: `python_test_subject` and explicit test canonical kinds
     (`bats.{file,test_case,expectation}`, `zunit.{file,suite,test_case,hook,assertion,expectation,command_under_test,mock,stub}`,
     `js.{test_suite,test_case}`, `ruby.{test_case,test_method}`, `nix.check`)
     are `intent_kind_affine`; production code kinds are `intent_kind_neutral`.
   - Under `docs`: `doc.{page,section,adr,skill}` are
     `intent_kind_affine`.
   - Under `messages`: `email.{mailbox,message,part,attachment_stub,thread_hint,address}`
     and `feed.{document,channel,item,author,category}` are `intent_kind_affine`.
   - Under `general`: all kinds are `intent_kind_neutral`.
   - Every default intent edge-kind set (`INTENT_DEFAULT_EDGE_KINDS[intent]` in
     `cloe-intent-tables-v1`) is validated at module load and by unit test as a
     non-empty subset of `CANONICAL_EDGE_KINDS` (`graph/edge_kinds.py`) whose
     members are emitted by repository canonicalizers (including `contains` for
     Bats/ZUnit test cases under `tests` and `defines`/`references` for
     `email.*`/`feed.*` under `messages`).
4. **Six-tier lexicographic ranking (`cloe-intent-rank-v1`) and byte tie-break
   (`cloe-intent-tiebreak-v1`):**
   Candidates are ordered by the integer 5-tuple `(exactness_tier, affinity_tier,
   match_class_tier, evidence_tier, publication_tier)` ascending (where `0` is
   strongest), followed by `cloe-intent-tiebreak-v1` (`canonical_key.encode("utf-8")`
   ascending, then the first verified `_destination` location identity tuple in
   Python). No floating-point or probability scores are emitted (`score` is
   omitted/null; ordinal tier tuples and closed explanation codes are returned).
5. **Ambiguity preservation and complete-scan prerequisite:**
   Equal-tier top candidates (`exactness_tier`, `affinity_tier`,
   `match_class_tier`) set `ambiguity.status="ambiguous"` with `tied_top_count`;
   all tied candidates remain eligible in tie-break order and any dropped by
   item/byte caps increment `ambiguous_alternative_omitted_by_budget`. Ranking
   operates only over complete candidate scans; if any scan unit hits
   `NODE_SCAN_LIMIT` (`2,000`), `EVIDENCE_SCAN_LIMIT` (`10,000`), or admission
   work caps (`100,000` checks / `32 MiB`), that scan unit yields zero ranked
   items and records omission `candidate_scan_incomplete` with a narrowing hint.

### D4. Epic B — Bounded compact context, work ledger, and relation support

1. **Hard serialized UTF-8 byte budget (`4,096..65,536`, default `16,384`):**
   Every packet is serialized with `json.dumps(..., ensure_ascii=False,
   separators=(",", ":"), allow_nan=False) + "\n"`. The budget bounds the entire
   UTF-8 byte sequence including the trailing newline, and
   `work_ledger.actual_bytes` is resolved by a 3-step self-referential integer
   fixpoint so its decimal value equals `len(serialized_utf8)`. Strings are never
   sliced mid-character and JSON is never truncated. Individual oversized or
   non-UTF-8-encodable stored strings are replaced with `null` and recorded with
   `oversize_field_withheld` or `unencodable_field_withheld` (field caps:
   `display_name <= 512` bytes, `source_relative_path <= 1,024` bytes,
   `canonical_key <= 4,096` bytes).
2. **Measured envelope and bounded minimal error:** The legal budget range is
   4096..65536, default16384. Compact only designated caller echoes and measure
   every actual required skeleton including provenance, diagnostics and newline.
   The example is a measured fixture, not a universal size maximum. A legal
   budget that cannot fit required identity returns the fixed-vocabulary minimal
   error within512 bytes; never truncate required identifiers to force a fit.
   Resolve actual_bytes by bounded reserialization and recheck after admission.
3. **Strict rank-prefix admission (`seeds_then_neighbors_v1`) and `_destination`
   deduplication:**
   All admitted seed items are packed in rank order before any depth-1 neighbor
   units, followed by omission detail records. No lower-ranked item is admitted
   past a skipped higher-ranked item. Item deduplication keys on `(graph_id,
   backend, accepted_run_id, publication_bundle_id, canonical_key)`. Location
   deduplication directly reuses the `_destination` identity shape from
   `server/_navigation_groups.py` (`source_binding_id`, `binding_revision`,
   `snapshot_id`, `source_relative_path`, `run_id`, `publication_relation`,
   `path_namespace`, `graph_path`) plus `(start_line, end_line)`. Locations
   across different bindings, revisions, snapshots, or runs at the same relative
   path remain distinct; withheld or unverified locations (`_destination is None`)
   never deduplicate.
4. **Separate work and statement bounds across SQLite and PostgreSQL:**
   - **Scan units (`MAX_SCAN_UNITS = 8`):** A request or selection may specify
     `1..8` bindings and `0..4` path prefixes per binding, provided the total
     expanded `(binding_id, path_prefix)` scan-unit count is at most `8`. Any
     request or selection exceeding `8` scan units is refused before database
     reads with `status="refused"`, `refusal_code="scan_unit_limit_exceeded"`.
   - **Expansion and batched neighbor locations (SQLite only):** `--expand-depth`
     is `0` or `1` (`>= 2` is refused). Up to `--expand-seeds` (`1..5`, default
     `3`) top admitted seeds expand via a new incident-selective SQLite query
     owner (`storage/sqlite_local/context_expansion_queries.py`) that pushes the
     intent's `CANONICAL_EDGE_KINDS` subset into the indexed `canonical_edges`
     predicates before `LIMIT` (`--node-limit 1..32` default `8`,
     `--edge-limit 1..64` default `16`, aggregate caps `128` neighbors and `256`
     edges). Direct locations for all admitted neighbor nodes across all
     expanded seeds are fetched in **at most one batched SQL statement**
     (`batch_neighbor_direct_locations`, bounded by `EVIDENCE_SCAN_LIMIT = 10,000`).
   - **Statement, VM-step, and wall-clock caps:** `work_ledger` accounts for
     `config_revalidations_executed` (`0` or `1`), `logical_read_units` (`<= 16`:
     1 accepted-identity/selection-revalidation read + up to 8 scan units + up
     to 5 seed expansions + 1 batched neighbor-location read + 1 margin), and
     backend-specific `sql_statements_executed`
     (`MAX_SQL_STATEMENTS_SQLITE = 36`, `MAX_SQL_STATEMENTS_POSTGRES = 12`,
     counting selection/accepted-identity readback, up to 8 scan statements,
     node-location readback, and 2 statements of margin), plus
     `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT` via `sqlite3.Connection.set_progress_handler`
     and a `10,000 ms` wall-clock deadline checked between statements.
   - **PostgreSQL expansion policy choice:** Although PostgreSQL has an
     unbounded neighborhood query owner (`storage/sql_neighborhood.py`), calling
     it and slicing rows in Python would violate Epic B's bounded-storage-work
     invariant. Therefore, on PostgreSQL, `--expand-depth 1` in
     `ranked_discovery` retains all ranked seeds, sets
     `expansion.state="unavailable"`, `expansion.reason="backend_unsupported"`,
     records omission `expansion_backend_unsupported`, and sets
     `scope_complete=False`.
   - **Consistency:** SQLite executes the entire assembly inside one
     `read_transaction` (`consistency_mode="single_read_transaction"`).
     PostgreSQL executes one self-contained statement per scan unit and verifies
     identical `accepted_publication` `(generation, run_id,
     publication_bundle_id)` across all statements
     (`consistency_mode="per_statement_identity_checked"`); any mid-assembly
     publication advancement returns `status="stale"`,
     `reason="publication_advanced_during_assembly"` with zero items.

### D5. Epic C — Reusable source selection and optional advisory freshness

1. **Reusable source selection:** Exclusive-create caller records contain graph,
   configured logical repository and backend; exact binding/revision/policy/source-
   definition fields and prefixes; optional full expected-publication pin
   (generation, accepted_run_id, bundle, job, attempt, manifest and extraction
   receipt), and selected snapshot IDs. The fingerprint covers every declared
   field, including repository_id. Revalidate all fields against current config
   and accepted-store evidence. Unknown required pin provenance is unavailable;
   no root paths, caller trust flag or body authority are serialized. Logical
   repository identity is configured_repository_identity(graph), repo1:<graph_id>;
   PostgreSQL numeric keys remain local. See the exact corrected spec contract.
2. **Optional advisory freshness:** Default zero target-source opens;
   explicit caller roots only. Use root-anchored directory descriptors and
   no-follow relative opens for every component, with regular-file/UTF-8 and
   actual byte/file/span bounds. V1 observes file presence and span availability
   only; qualified/synthetic canonical display names are not lexical change
   evidence. Failed optional checks preserve indexed items and never refresh or
   set publication STALE. See the normative corrected spec section5.2.

### D6. Product entry points and CLI exit contract

- `cloe ops context-pack`: emits one bounded `cloe-compact-context-v1` JSON line
  on stdout. Exit codes:
  - `0`: `status == "complete"` (or `status == "partial"` when the caller
    explicitly passes `--allow-partial`).
  - `3`: `status == "partial"` by default (usable bounded packet with valid
    items and disclosed omissions, distinct from both exhaustive completeness
    and failure).
  - `1`: `status in {"refused", "stale", "unavailable", "failed", "budget_error"}`.
  - `2`: `argparse` CLI syntax/usage error.
- `cloe ops context-select`: validates scope against live on-disk config and
  writes one `cloe-source-selection-v1` JSON file (`0` on success, `1` on
  refusal/unavailable/failed, `2` on `argparse` error).
- Library API: `common_lore_index.retrieval.context_assembly.build_compact_context`.
- MCP surface: unchanged (verified by catalog snapshot regression tests).

## Alternatives and dispositions

| Alternative | Disposition | Rationale |
|---|---|---|
| Mutate `QueryEnvelope` (`cloe-retrieval-query-v1`) or add a v2 query envelope | Rejected | Would break W2/W3 envelope consumers and conflate single-surface ranked hit lists with mixed-surface (`stored_metadata` + `graph_topology`) context packets. |
| Change MCP `repomap_navigation_search` ordering or widen shared `_EVIDENCE_ROLE_SQL` | Rejected | Would alter accepted MCP tool behavior and catalog contracts; isolated `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` in context owners preserves MCP unchanged. |
| Infer `--mode` from `--canonical-key` or `--query`, or infer intent from query strings | Rejected | Violates explicit mode/intent transparency and creates ambiguous flag combinations. |
| Floating-point or weighted linear relevance scores | Rejected | Introduces non-obvious weight tuning and hides why one item outranked another; lexicographic tiers with factual codes are deterministic and auditable. |
| Call PostgreSQL's unbounded neighborhood query and clip rows in Python | Rejected | Violates Epic B's requirement that database candidate/edge work is bounded separately from output bytes. |
| Truncate strings or slice serialized JSON to meet `--budget-bytes` | Rejected | Produces invalid JSON or corrupted identifiers/paths. |
| Store source selections inside `.cloe.toml` or include `root_path` in selection files | Rejected | Turns caller query selections into config mutations or leaks host paths into portable selection artifacts. |
| Filesystem `mtime` freshness or universal `name_not_in_span` across all node kinds | Rejected | `mtime` is unreliable across checkouts/containers; `python.module`, `doc.page`, and `email.*`/`feed.*` display names need not appear literally in spans. |
| Portable artifact-store digest freshness | Deferred | Requires retained portable store access at query time; W4 keeps default context metadata-only and optional freshness local-root-mapped. |
| PostgreSQL bounded incident-selective neighborhood parity | Deferred (OD2) | Candidate for W7 scale/query governance or separate operator selection. |
| Bounded caller-local source excerpts | Deferred (OD4) | W4 integrates metadata-only context and structural freshness first without creating a new body-exposure surface. |

## Verification, evidence, and rollback

- **Implementation phase (`REPOMAP-CLOE-CONTEXT1`) verification:** Requires
  exact scoped unit and disposable-container integration selectors with
  `--no-coverage` (covering both SQLite Local and PostgreSQL), complete retained
  static enforcement with one guarded forward-only ownership/selection/scope
  admission for the new `common_lore_index` modules (`<= 400` physical lines,
  targeting `<= 350`), and zero new dependencies or migrations.
- **Controlled W4 evaluation (`context-v1`):** Define a new public-safe
  evaluation instrument under `src/test/fixtures/retrieval_evaluation/context-v1/`
  reusing the immutable `mixed-v1` corpus bytes plus controlled multi-binding /
  high-degree / multibyte context fixtures across 30 frozen tasks (20
  calibration, 10 held-out; held-out tasks remain unexecuted) and 7 arms over 3
  repetitions (`w4-context-calibration-attempt-1`, 420 observations). All W2 and
  W3 baseline and attempt archives remain byte-for-byte immutable, and the 12
  `mixed-v1` held-out tasks remain unexecuted.
- **Coverage target:** Hosted CI owns complete-population coverage. New
  real-boundary integration tests in `REPOMAP-CLOE-CONTEXT1` must also close the
  remaining ~0.6 percentage-point staging branch margin (`100 * covered >= 82 *
  total`) without weakening any gate, denominator, or exclusion.
- **Rollback:** A forward corrective phase uses the existing exact retention/scope-retirement procedures, preserving published authority/cohort prefixes and debt. Never delete historical admission records, reset a baseline or rewrite history.

## Independent plan-review dispositions (REPOMAP-CLOE-CONTEXT-DESIGN1)

The bound plan proposal (`sha256=e04636fa40582710ea76ba4f8f8252504bd55198f8f1149a186ff23e2600a06a`)
is **amended** in this ADR and the companion specification to incorporate all
eight findings (`F1`–`F8`) from the independent plan review:

- **F1 (major — direct evidence role for `tests` and `messages` under scoped
  selections):** Resolved in D3. Clarified that Python test symbols are stored in
  `canonical_nodes` as `python.{module,class,function,method}` (which already
  have `direct` evidence and are classified as `python_test_subject` by
  `cloe-intent-tables-v1`), authorized the isolated
  `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` predicate in the new context query owners
  for `email.*`, `feed.*`, and non-Python test canonical kinds without touching
  MCP `_EVIDENCE_ROLE_SQL`, added SQLite depth-1 test-edge traversal, and
  specified `unavailable_reason="unlocatable_kind_in_scoped_selection"` when an
  explicit `--kind` has no direct-evidence producer under a scoped selection.
- **F2 (work and statement accounting across bindings, prefixes, and neighbor
  locations):** Resolved in D4. Enforced `MAX_SCAN_UNITS = 8` across all
  `(binding_id, path_prefix)` pairs (refusing `> 8` up front with
  `scan_unit_limit_exceeded`), added a single batched SQLite direct-location
  statement (`batch_neighbor_direct_locations`) for all admitted neighbors, and
  specified exact logical read units (`<= 16`) and backend-specific SQL
  statement ceilings (`MAX_SQL_STATEMENTS_SQLITE = 36`,
  `MAX_SQL_STATEMENTS_POSTGRES = 12`).
- **F3 (explicit `--mode`, PostgreSQL fallback target, and mixed surfaces under
  expansion):** Resolved in D2. Required an explicit `--mode` on `context-pack`
  and `ContextRequest`, supported `--fallback-to exact_identity` (using
  `--canonical-key`) and `--fallback-to ranked_discovery` (requiring `--query`)
  for PostgreSQL `graph_investigation`, and specified per-item `match_surface`
  (`stored_metadata` on seeds, `graph_topology` on depth-1 expanded
  neighbors/relations).
- **F4 (initial lexical/symlink proposal):** Superseded by the parent structural-only and directory-descriptor correction; the original kind-wide anchor guarantee was false.
- **F5 (Historical initial-draft response; superseded below: minimum legal budget vs echoed caller strings in skeleton):**
  Resolved in D4. Specified `skeleton_compaction_v1` (withholding oversized
  `target_echo` and `selected_binding_ids`/`path_prefixes` arrays while
  retaining fixed-width `target_sha256`, counts, and `selection_fingerprint`),
  set `MIN_BUDGET_BYTES = 4,096` from the measured maximally compacted skeleton
  (`<= 3,072` bytes), and defined the Minimal Standard Request Class that fits
  uncompacted (`< 3,584` bytes) within `4,096` bytes.
- **F6 (minor — PostgreSQL unbounded neighborhood vs bounded policy refusal):**
  Resolved in D4. Explicitly recorded that PostgreSQL has an unbounded
  neighborhood query owner and that reporting `expansion_backend_unsupported` is
  a policy choice to preserve storage-work bounds rather than an absence of
  neighborhood SQL.
- **F7 (minor — reuse `_destination` location identity shape):** Resolved in D4.
  Reused the exact `_destination` dictionary keys from
  `server/_navigation_groups.py` plus `(start_line, end_line)` for location
  deduplication and tie-breaking.
- **F8 (minor — distinct CLI exit code for usable `partial` packets):** Resolved
  in D6. Assigned exit code `3` to usable `partial` packets by default (`0` when
  `--allow-partial` is passed), keeping `0` for `complete`, `1` for
  `refused`/`stale`/`unavailable`/`failed`/`budget_error`, and `2` for
  `argparse` usage errors.

## Independent work-review dispositions (closeout)

All ten advisory findings (`MAJOR 1`–`3`, `MODERATE 4`–`6`, `MINOR 7`–`10`) from
the pre-final independent work review are accepted and resolved in place:

- **MAJOR 1 (Historical initial-draft response; superseded below: byte-budget contradiction and `actual_bytes` fixpoint):** Derived
  `MIN_BUDGET_BYTES = 4,096` (`4,096..65,536`, default `16,384`) from the
  measured full `cloe-compact-context-v1` skeleton (`<= 3,072` bytes maximally
  compacted; `< 3,584` bytes uncompacted for the Minimal Standard Request Class),
  specified the 3-step self-referential integer fixpoint for
  `work_ledger.actual_bytes`, and set the §4.1 example's `actual_bytes` to its
  exact compact UTF-8 length (`2,674` bytes).
- **MAJOR 2 (edge kinds absent from `CANONICAL_EDGE_KINDS`):** Replaced all
  non-canonical edge kinds in `cloe-intent-tables-v1` with canonicalizer-backed
  members of `CANONICAL_EDGE_KINDS` (`graph/edge_kinds.py`), including
  `defines`/`references` for `messages` (`email_family.py`, `feed_family.py`),
  `defines`/`links_to`/`references`/`contains`/`embeds`/`styles` for `docs`, and
  `calls`/`contains`/`declares`/`defines`/`depends_on`/`exposes_script`/`imports`/`includes`/`loads`/`method_of`/`references`/`replaces_module`/`requires_module`/`sources`/`workspace_uses`
  for `definition`/`implementation`, enforced by a module-load subset assertion
  and unit test.
- **MAJOR 3 (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1` raw kinds and link kinds for
  Bats/ZUnit):** Corrected the predicate to match actual canonicalizer emissions
  (`bats.test_case` in `shell_bats_family.py:84,269`; `zunit.test_case` in
  `shell_zunit_family.py:119,365`) and included `inferred_from_edge` child
  definition links emitted via `_append_two_node_edge`
  (`_shell_edge_helpers.py:57-70`) before the fallback `reference` branch.
- **MODERATE 4 (`contains` edge in `tests` intent and §4.2 relation example):**
  Added `contains`, `defines`, `refutes`, `expects`, `has_assertion`, `has_hook`,
  `loads`, `imports`, and `references` to the `tests` edge set and updated the
  §4.2 relation example to use a real `bats.file` -> `contains` ->
  `bats.test_case` edge (`shell_bats_family.py:272`).
- **MODERATE 5 (scoped truthfulness and derived locatable kind set):** Added
  `nix.check`, `email.address`, `bats.expectation`, and
  `zunit.{hook,assertion,expectation,command_under_test,mock,stub}` to
  `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`, derived `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`
  programmatically from the role table, and required disclosing
  `unlocatable_kind_patterns_excluded`,
  `unlocatable_kind_pattern_excluded`, and `scope_complete=False` whenever
  a scoped scan's active candidate kinds include any kind outside
  `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` (even without `--kind`).
- **MODERATE 6 (CLI registration and dispatch owners):** Corrected the narrow
  CLI edit owners to `cli/parser.py` (`add_ops_context_commands` alongside
  `add_ops_lexical_commands` at line 163) and `cli/_ops_baselines_dispatch.py`.
- **MINOR 7 (`budget_error` echo bounds and CLI string budget exit code):**
  Bounded `budget_error.budget_bytes` to integers in `-999_999_999..999_999_999`
  (else `null` with `reason="invalid_budget_type"` or `"budget_out_of_range"`),
  keeping `budget_error <= 512` bytes, and distinguished CLI non-int string
  budgets (`argparse` exit `2`) from CLI out-of-range integer budgets and
  library non-int budgets (`budget_error` exit `1`).
- **MINOR 8 (selection revalidation read accounting):** Added
  `config_revalidations_executed` to `work_ledger`, counted selection/accepted
  database readback in `logical_read_units` (`<= 16`) and SQL statement ceilings,
  and set `MAX_SQL_STATEMENTS_POSTGRES = 12`.
- **MINOR 9 (`NavigationSearchQuery` reuse and query/offset bounds):** Reconciled
  `--query` (`1..200` stripped Unicode chars, `<= 800` UTF-8 bytes) and
  `--offset` (`0..1,000` subset of `0..10,000`) with `NavigationSearchQuery` and
  specified reuse of existing SQLite/PostgreSQL navigation and location owners
  via `role_sql: str = _EVIDENCE_ROLE_SQL`.
- **MINOR 10 (`binding_revision` type and `snapshot_manifest_id` provenance):**
  Fixed `cloe-source-selection-v1` `revision` to `int >= 1`, replaced
  `source_runs` references with `runs` / `public.runs`, and specified run-level
  `runs.snapshot_manifest_id` vs per-binding `(binding_revision, snapshot_id)`
  from `runs.snapshot_vector_json`.


## Parent resulting-state disposition

The corrected specification's final parent-disposition section governs initial
draft size examples, provenance trust, legacy payload preservation, progress
estimates, structural-only freshness, descriptor-anchored path handling and
immutable retirement. Initial claims of universal3072-byte skeleton bounds are
superseded: a legal requested budget that cannot fit required identity returns
the bounded minimal error. No required identity is truncated to force a fit.

This remains a design candidate pending fresh independent review and parent
acceptance under the approved W4 roadmap continuation. Its initial failed
dispatcher terminal narrative grants no implementation or publication authority.
No package dependency, schema, new MCP tool, source excerpt, held-out query,
criteria acceptance or complete local Python suite is added.


## Final parent disposition of the resulting-state review

These decisions resolve the four moderate and five minor findings from the
independent resulting-state checkpoint. They narrow or clarify the proposed
contract; they add no dependencies, schema or body exposure.

1. Docs affinity is exactly `doc.page`, `doc.section`, `doc.adr`, `doc.skill`.
   Other document kinds remain neutral and acquire no new direct-evidence role.
2. Affinity tables contain finite exact-kind or terminal-prefix pattern tokens.
   A token such as `go.*` denotes a prefix language; it does not enumerate a
   nonexistent canonical node-kind catalog. For scoped requests, compare these
   tokens with the finite direct-role kind set. An exact token outside that set
   or an open prefix not wholly provably covered is excluded conservatively.
   `scope.unlocatable_kind_patterns_excluded` is the sorted unique token list;
   `omission_counts.unlocatable_kind_pattern_excluded` counts tokens, never nodes.
   General and intent-less literal enumeration use `*` unless an explicit kind
   restricts the request. Scoped general/definition/implementation and scoped
   literal enumeration without an explicit directly locatable kind are therefore
   partial by design (exit3, or0 with allow-partial). Docs/tests/messages use their
   closed exact affinity kinds. An explicitly unlocatable kind is unavailable.
   Absence claims remain limited to declared directly locatable metadata fields.
3. Preserve the36-statement SQLite ceiling and count real statements. Existing
   navigation_candidates costs3 statements, including its accepted-identity read;
   node_locations costs5. The initial full identity read is additional. The
   theoretical maximum1+8*3+5*3+1=41 does not fit36: individual maxima are not a
   promise that every combination completes. Intercept actual query execution
   before statement37, retain completed admitted units, discard incomplete units
   and return partial/statement_limit without retry. Enforce and test this at the
   connection/executor boundary, not by a guessed per-call counter. PostgreSQL
   remains capped at12. No statement/debt ceiling is raised.
4. Wire repository_id is configured_repository_identity(graph), `repo1:<graph_id>`,
   on both backends. PostgreSQL numeric primary keys remain local lookup keys.
   SQLite uses local_graph_binding and exact accepted run/receipt; PostgreSQL
   reuses the identity-pinned public metadata lookup pattern of
   read_accepted_graph_publication, never the evaluation support's unscoped
   latest-receipt helper. A same-database second repository must not swap a pin.
   Context projections include job/attempt, manifest/receipt and vector evidence
   internally; all default legacy payload fields remain unchanged.
5. Full expected_publication includes generation, accepted_run_id, bundle ID,
   job_id, attempt, manifest ID and extraction receipt ID. Fingerprinting includes
   repository_id and every declared field. Compare every full pin field plus
   graph/repository/backend and selected revision/snapshot/config-policy evidence.
   Missing nullable PostgreSQL job/attempt provenance makes strong pinning
   unavailable; never fabricate it or reuse a global latest receipt.
6. SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT denotes a250-callback allowance per statement at
   a1000-operation interval. The250000 figure is an estimate. Report callbacks,
   interval and labelled product; PostgreSQL progress fields are null.
7. Reject invalid/out-of-range budgets before config, selection, database or source
   reads, with required_min_bytes=null. For a legal budget, compute the exact
   required skeleton after metadata/config admission, before any source opens.
   If it cannot fit, emit the bounded minimal error with that measured length.
8. Product relative-path validation is owned by retrieval.advisory_freshness (or
   its cohesive product sibling), with parity tests against the developer helper;
   product code never imports tools. Spans over80 lines are not_checked/line_limit
   before target-source opens. Selection input is at most65536 actual bytes,
   opened no-follow/nonblocking and checked as regular; oversized/raced input
   refuses. Source observation applies to all finally admitted eligible seed and
   neighbor locations, with reserved observation bytes before reads.
9. Context contracts lock exact non-empty element key order before implementation
   proof: item_id, item_role, canonical_key, kind, display_name, subject_family,
   match_surface, rank, match_class, rank_tiers, rank_reasons, identity_state,
   locations, omitted_location_count. Neighbor-only ranking fields are null/empty.
   Locations reuse the destination identity keys, then start_line,end_line,
   evidence_link_kind,evidence_raw_kind,evidence_confidence,freshness. Optional
   freshness objects use state,reason,limits,inspected_span. Existing stored
   relation support fields are preserved; no invented relationship evidence.

OD5 is satisfied by parent acceptance of this corrected design under the current
roadmap continuation. OD7 is later parent binding of one milestone campaign.
MCP additions, PostgreSQL bounded expansion parity, configured-root shortcuts,
excerpts and held-out/criteria acceptance remain deferred. Implementation source
and whole-candidate qualification remain pending.



### Normative section alignment

The initial context projection reads full job/attempt/manifest/receipt and vector
evidence internally in addition to the existing marker. Graph/repository/backend
are bound to configured accepted-store identity on every read. All full pin fields
are compared across PostgreSQL statements; missing nullable job/attempt makes a
requested strong pin unavailable. Public default query responses keep exactly
their legacy fields. Do not use PostgreSQL physical repository keys as logical IDs.

The exclusion list contains finite pattern tokens, not hypothetical canonical
node kinds. The python_test_subject classifier family expands to its four
declared Python canonical kinds only for coverage calculation. General/intent-less
literal enumeration without --kind uses the open token *. No canonical node-kind
catalog is assumed. All exact docs/tests/messages affinity entries are covered by
the direct-role table; open-prefix code/general patterns remain conservative.

The governed SQLite statement ceiling is 36, counting every actual query in the
assembly including owners' repeated identity reads. The initial one-scan ledger
therefore counts4 statements. Maximal independent settings may exceed36 and
produce partial/statement_limit; never execute statement37 or fake a counter.
The progress callback limit is 250 per statement at interval 1000; steps are labelled
estimates. PostgreSQL progress fields are null. Hard output/work bounds remain.

Invalid/out-of-range budgets are refused before I/O with required_min_bytes=null;
valid-budget required_min_bytes is measured after metadata/config admission and
before optional source opens. Selection input is no-follow/nonblocking regular
file data, capped at 65536 actual bytes. Spans longer than 80 lines are
not_checked/line_limit before source opens. Product path validation belongs to
retrieval.advisory_freshness (or its product sibling); tools is parity-test input
only, never a product import. Finally admitted eligible seeds and neighbors both
receive bounded reserved observations. Initial numeric review dispositions are
historical, not current normative size or work claims.


## Implementation closeout

REPOMAP-CLOE-CONTEXT1 implements the final parent design disposition. The earlier
pending statements above describe design checkpoints. The public exit records
source scope and candidate boundaries; the introducing commit records exact
final scoped selectors/results and independent resulting-state review. Parent
corrections include strict raw publication parsing, one root descriptor per
binding/request, pre-source byte reservation, actual SQLite statement/progress
guards and real native/PostgreSQL evaluation controls. Structural SQLite read
protocols add no schema SQL or migration change. Context commands join the
early routing boundary in cli/main.py; the historical central dispatcher and
its closed resolver source identity remain unchanged. No new dependency, MCP/body
surface or numerical debt is admitted. ADR0134 governs one public staging
campaign; whole-candidate hosted qualification remains pending.


## Independent-review correction disposition

Before publication, owned SQLite context readers reuse the canonical read-only
transaction manager with the configured full graph binding. Its fixed storage
preflight (runtime, regular file, escaped URI, query-only, exact schema, WAL and
binding) remains separate from the already budgeted context product SQL; every
context product statement retains the pre-execute guard and the existing36 cap.
Ordinary storage/schema failures are unavailable, while genuine ledger-induced
interrupts remain exhausted. Unavailable responses propagate through candidate,
location and expansion assembly without becoming usable partial answers.

Historical evidence vectors are validated strictly before context normalization,
including scoped admission. Legacy default navigation behavior is unchanged.
Final empty-envelope sizing refreshes omission counters and reserves the complete
post-admission result before any source reads. Guarded SQLite connections expose
only their required metered execute and pure function-registration interfaces.

Source producers use different line conventions. For structural EOF checks, if
LF-based and splitlines-based counts disagree about the requested end line, the
observation is unavailable with reason `line_semantics`; it cannot claim either
no change or drift. Agreement preserves existing structural verdicts. This is a
conservative advisory clarification, with no global extraction-line migration.

The evaluation archive retains source/native-manifest bytes. Generated SQLite
and PostgreSQL contents are bound by publication identity, not archived as
database-content proof. That remains the `fixture_manifest_only` limit.


### Final omission-accounting correction

A returned neighbor that is already an admitted seed contributes its stored
relations without duplicating the node. Returned records that cannot be admitted
receive exact observed output-budget counts, including the remaining ordered
stream after first budget failure; endpoints and relation de-duplication remain
mandatory. Aggregate seed-to-seed relation cap hits are reported. Storage
expansion remains bounded discovery before output admission, with actual work
reported even when later output admission withholds a seed; it is not freshness
I/O and does not infer global graph completeness.

The normative edge-kind order is lexical, as specified by the existing neighbor
ordering tuple. Explicit edge-kind inputs are a set, not caller-defined priority.
Instrumentation may lower the SQLite progress interval only to1; its reported
interval matches the installed handler. These corrections grant no new graph
vocabulary, dependency, build slot, scientific acceptance or hosted retry.
