# Intent-Aware Navigation, Bounded Compact Context, and Advisory Freshness Operations (`cloe-compact-context-v1`)

`cloe ops context-select` and `cloe ops context-pack` provide reusable source
selection (`cloe-source-selection-v1`), explicit intent-aware deterministic
navigation (`cloe-intent-rank-v1`, `cloe-intent-tiebreak-v1`,
`cloe-intent-tables-v1`), bounded single-line JSON context packets
(`cloe-compact-context-v1`), and opt-in structural source freshness checks
(`cloe-advisory-freshness-v1`) across SQLite Local and PostgreSQL Server Engine
([ADR 0133](../adr/2026/11/0133-intent-aware-navigation-and-bounded-context.md),
[specification](../specs/cloe-intent-context-v1.md)).

## Authority, Privacy, and Contract Boundaries

1. **Preserved Retrieval and MCP Contracts**: The six `QueryMode` values and
   five `MatchSurface` values in `cloe-retrieval-query-v1` ([ADR 0127](../adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md)),
   the read-only MCP tool catalog and schemas, `InvestigationReadStore`, and the
   default `_EVIDENCE_ROLE_SQL` payload behavior for `repomap_navigation_search`
   and `repomap_node_locations` remain unchanged.
2. **Metadata-Only Storage Access and Credential Isolation**: Context assembly
   reads accepted canonical metadata (`canonical_nodes`, `canonical_edges`,
   `canonical_node_evidence`, `canonical_evidence`, `runs`, and publication
   pointers) and `.cloe.toml` configuration only. It never uses `cloe_lexical`
   owner credentials, never queries `cloe_lexical` or SQLite lexical tables, and
   never emits source file excerpts.
3. **Isolated Context Direct-Evidence Role (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`)**:
   Context read adapters pass `role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1` as an
   internal trusted parameter to existing SQLite and PostgreSQL navigation/locator
   query owners. Its derived `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` set covers 34
   canonical node kinds across Python (`python.{module,class,function,method}`),
   documentation (`doc.{page,section,adr,skill}`), messages
   (`email.{mailbox,message,part,attachment_stub,thread_hint,address}`,
   `feed.{document,channel,item,author,category}`), and non-Python tests/checks
   (`js.{test_suite,test_case}`, `ruby.{test_case,test_method}`,
   `bats.{file,test_case,expectation}`,
   `zunit.{file,suite,test_case,hook,assertion,expectation,command_under_test,mock,stub}`,
   `nix.check`).

## CLI Workflow

### Create a Reusable Source Selection (`cloe ops context-select`)

```bash
cloe ops context-select --config /path/to/repomap.rpl.toml \
  --graph <graph-id> \
  --binding <binding-id> \
  --path-prefix <binding-id>=src/pkg \
  --pin-publication \
  --output /path/to/selection.json
```

- Validates `--graph`, `1..8` bindings, `0..4` normalized relative path prefixes
  per binding, and `scan_unit_count <= 8` total `(binding_id, path_prefix)` scan
  units against live configuration and accepted database publication state.
- Records logical `repository_id` (`repo1:<graph-id>`), `backend` (`sqlite` or
  `postgresql`), per-binding policy provenance (`source_definition_id`,
  `selection_policy_id`, `privacy_classification`, `retention_mode`), and a
  length-framed `select_ctx1:<64-hex>` SHA-256 `selection_fingerprint`.
- When `--pin-publication` is passed, pins the full 7-field
  `expected_publication` (`generation`, `accepted_run_id`,
  `publication_bundle_id`, `job_id`, `attempt`, `snapshot_manifest_id`,
  `extraction_receipt_id`) and each selected binding's `(binding_revision,
  snapshot_id)` from the accepted run's snapshot vector. If nullable PostgreSQL
  `publication_job_id` or `publication_attempt` provenance is absent, strong
  pinning refuses rather than fabricating provenance.
- Writes the JSON artifact with `os.open(..., os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)`
  (never overwriting existing files) and stores **no filesystem root paths**.

### Assemble a Bounded Compact Context Packet (`cloe ops context-pack`)

```bash
cloe ops context-pack --config /path/to/repomap.rpl.toml \
  --graph <graph-id> \
  --mode ranked_discovery \
  --query "InvoiceService" \
  --intent definition \
  --selection /path/to/selection.json \
  --budget-bytes 16384 \
  --max-items 10 \
  --locations-per-item 3 \
  --expand-depth 1
```

#### Explicit `--mode` Contract

`--mode` (`requested_mode`) is required and never inferred from `--canonical-key`
or `--query`:

- `exact_identity`: requires `--canonical-key`; rejects `--query`, `--intent`,
  and `--expand-depth 1` (unless explicitly testing backend expansion policy in
  library calls).
- `current_literal_enumeration`: requires `--query` (`1..200` stripped Unicode
  characters, `<= 800` UTF-8 bytes); preserves ascending `canonical_key` scan
  order (`canonical-key-asc-v1`); rejects `--canonical-key`, `--intent`, and
  `--expand-depth 1`.
- `ranked_discovery`: requires `--query`; accepts `--intent`
  (`definition`, `implementation`, `tests`, `docs`, `messages`, `general`,
  default `general`) and `--expand-depth {0,1}` (default `0`). Ranks complete
  candidate scans under `cloe-intent-rank-v1` (5-tier integer tuple
  `(exactness_tier, affinity_tier, match_class_tier, evidence_tier,
  publication_tier)` plus `cloe-intent-tiebreak-v1` UTF-8 key and verified
  `_destination` tie-break) without a universal test penalty.
- `graph_investigation`: requires `--canonical-key`; defaults to
  `--expand-depth 1`. On SQLite Local, locates the center seed and expands
  depth-1 incident edges filtered by the intent's `CANONICAL_EDGE_KINDS` subset
  before `LIMIT`. On PostgreSQL, returns `status: "unavailable"`,
  `reason: "backend_unsupported"` unless `--fallback-to exact_identity` or
  `--fallback-to ranked_discovery` (with `--query`) is explicitly supplied.
- `literal_captured_text` and `semantic_discovery`: return
  `status: "unavailable"`, `reason: "capability_not_admitted"` with zero
  database reads.

#### Selection Revalidation and Scoped Locatability

- `--selection PATH` is opened with `os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK`,
  verified via `fstat` as a regular file, and capped at `65,536` actual bytes.
- Every call revalidates the selection's `selection_fingerprint`, logical
  `repository_id`, `backend`, live binding configuration, and (when pinned) all
  7 `expected_publication` fields plus per-binding `(binding_revision,
  snapshot_id)`.
- Under scoped requests (`--selection`, `--binding`, or `--path-prefix`), kind
  tokens outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` (including open prefixes
  such as `*` or `go.*` under `general`, `definition`, or `implementation`) are
  reported in `scope.unlocatable_kind_patterns_excluded` and
  `omission_counts.unlocatable_kind_pattern_excluded`, setting
  `scope.scope_complete: false` and `status: "partial"`.

#### Opt-In Advisory Source Freshness (`--freshness check`)

```bash
cloe ops context-pack --config /path/to/repomap.rpl.toml \
  --graph <graph-id> \
  --mode exact_identity \
  --canonical-key "py:pkg.billing.InvoiceService" \
  --freshness check \
  --source-root core-src=/abs/path/to/checkout
```

- Requires `--source-root BINDING_ID=ABS_PATH` for inspected bindings.
- Traverses each relative path component from an anchored root directory
  descriptor using `os.open(..., os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=...)`
  and opens the leaf file with `os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK`.
- Enforces `FRESHNESS_MAX_FILES_PER_REQUEST = 16`, `FRESHNESS_MAX_FILE_BYTES = 65,536`,
  `FRESHNESS_MAX_AGGREGATE_BYTES = 262,144`, and `FRESHNESS_MAX_SPAN_LINES = 80` (spans over 80
  lines return `state: "not_checked"`, `reason: "line_limit"` before opening the
  file).
- Reserves worst-case observation JSON bytes for all finally admitted eligible
  seed and neighbor locations before reading any source file.
- Reports structural-only verdicts (`no_change_observed_with_limits`,
  `changed_observed`, `not_checked`, or `unavailable`) without altering
  publication `status` or emitting source text.

## Byte Budget, Work Ledger, and Exit Codes

- **Hard UTF-8 Byte Budget (`4,096..65,536`, default `16,384`)**: Validated
  before config, selection, database, or source I/O. Every packet is serialized
  as single-line JSON plus `\n` with `work_ledger.actual_bytes == len(utf8_bytes)`
  via a 3-step integer fixpoint. If a legal budget cannot fit the required
  identity skeleton even after `skeleton_compaction_v1`, `context-pack` emits a
  bounded `<= 512`-byte `cloe-compact-context-v1` minimal `budget_error` JSON
  object with measured `required_min_bytes` and exits `1`.
- **Storage Work Bounds**:
  - SQLite Local (`consistency_mode: "single_read_transaction"`): hard ceiling of
    `36` actual SQL statements enforced at the connection trace/progress
    boundary before statement `37` executes, `250` progress callbacks per
    statement at a `1,000` VM-op interval, and at most `1` batched SQL statement
    for neighbor direct locations.
  - PostgreSQL (`consistency_mode: "per_statement_identity_checked"`): hard
    ceiling of `12` SQL statements with full publication identity comparison
    across statements.
- **Exit Codes**:
  - `0`: `status == "complete"` (or `status == "partial"` when `--allow-partial`
    is passed).
  - `3`: `status == "partial"` by default (valid bounded JSON emitted on stdout
    with disclosed omissions).
  - `1`: `status in {"refused", "stale", "unavailable", "failed", "budget_error"}`.
  - `2`: `argparse` CLI syntax or usage error.

When producer line conventions disagree about whether a span extends beyond EOF,
structural freshness reports `unavailable` / `line_semantics`. Owned SQLite opens
use canonical fixed storage preflight; the36-statement context product-query
budget remains separately metered. Ordinary database/schema failures are
unavailable rather than work-budget partial results.

Explicit edge kinds form a lexical set. A returned relation between two admitted
seeds is retained even when only one was expanded, without duplicating the other
seed as a neighbor. Omission counters describe their category units and can
overlap; they are not a distinct-node cardinality total.

## First-use workflow

See [First-use workflows](first-use-workflows.md) for the bounded mixed-v1
Local and Server walkthrough. It demonstrates alias-qualified metadata
provenance, pinned-selection staleness and source-blind packets without
adding body authorization. Installed and native qualification are pending.
