# Cloe Intent-Aware Navigation, Bounded Compact Context, and Advisory Freshness Specification v1

- Status: Implemented in `REPOMAP-CLOE-CONTEXT1` ([exit report](../../tools/ci/cloe-context1-exit.md), [operations guide](../ops/compact-context.md)) following independent design review and parent acceptance in `REPOMAP-CLOE-CONTEXT-DESIGN1` under [ADR 0133](../adr/2026/11/0133-intent-aware-navigation-and-bounded-context.md). Whole-candidate hosted qualification and held-out evaluation remain pending.
- Phase IDs:
  - Design phase: `REPOMAP-CLOE-CONTEXT-DESIGN1` (design only; no runtime implementation or held-out execution)
  - Reserved implementation phase: `REPOMAP-CLOE-CONTEXT1`
- Companion specs and ADRs:
  - [cloe-roadmap-transition-v1.md](cloe-roadmap-transition-v1.md)
  - [cloe-retrieval-evaluation-v1.md](cloe-retrieval-evaluation-v1.md) ([ADR 0127](../adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md))
  - [cloe-native-lexical-search-v1.md](cloe-native-lexical-search-v1.md) ([ADR 0129](../adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md), [ADR 0130](../adr/2026/10/0130-lexical-milestone-staging-campaign.md))
  - [cloe-development-custody-v1.md](cloe-development-custody-v1.md)
  - [cloe-server-parity-v1.md](cloe-server-parity-v1.md) ([ADR 0168](../adr/2026/11/0168-bounded-server-context-and-refresh-outcomes.md)), the parent-accepted partial W7 amendment for PostgreSQL depth-1 parity and truthful refresh outcomes. Its Epic 3 server-timeout proposal remains held; the W4 PostgreSQL refusal remains the historical baseline until the accepted parity implementation qualifies.

## 1. Scope, authority, and preserved contracts

This specification defines the W4 milestone (`REPOMAP-CLOE-CONTEXT1`) across three connected epics:

- **Epic A:** Explicit intent-aware deterministic navigation (`cloe-intent-rank-v1`, `cloe-intent-tiebreak-v1`, `cloe-intent-tables-v1`, `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`).
- **Epic B:** Bounded compact-context packet assembly (`cloe-compact-context-v1`, `skeleton_compaction_v1`, `seeds_then_neighbors_v1`) and callable CLI/library surfaces over existing SQLite Local and PostgreSQL metadata query/publication owners.
- **Epic C:** Explicit reusable source selection (`cloe-source-selection-v1`) and opt-in advisory freshness verification (`cloe-advisory-freshness-v1`), with bounded source excerpts deferred out of W4.

### Preserved contracts and architectural boundaries

1. **Retrieval contract stability ([ADR 0127](../adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md)):**
   - The six `QueryMode` values (`exact_identity`, `current_literal_enumeration`, `literal_captured_text`, `ranked_discovery`, `graph_investigation`, `semantic_discovery`) and five `MatchSurface` values (`captured_text`, `stored_metadata`, `graph_topology`, `direct_handoff`, `none`) in `src/main/python/common_lore_index/retrieval/query_contracts.py` remain unchanged.
   - `QueryEnvelope` (`cloe-retrieval-query-v1`), `QueryHit`, `EvaluationLocator`, `FallbackDisclosure`, and `OmissionRecord` remain unchanged.
2. **Read-only MCP and `InvestigationReadStore` stability:**
   - The read-only MCP tool catalog, tool schemas, ordering (`repomap_navigation_search` ascending `canonical_key`), `_EVIDENCE_ROLE_SQL` in `storage/sqlite_local/node_location_queries.py`, and `server/investigation_read_store.py` (`InvestigationReadStore`) remain unchanged.
3. **Lexical/body privacy and DB-owner credential isolation ([ADR 0129](../adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md)):**
   - Context assembly reads canonical metadata (`canonical_nodes`, `canonical_edges`, `canonical_node_evidence`, `canonical_evidence`, `runs`, `accepted_publication` on SQLite Local; `public.repositories`, `public.runs`, `public.graph_publication_authority`, `public.canonical_nodes`, `public.canonical_edges`, `public.canonical_node_evidence`, `public.canonical_evidence` on PostgreSQL) and `.cloe.toml` graph/binding configuration only. It never uses lexical owner credentials, never queries `cloe_lexical` or SQLite lexical body tables, and never emits source body text.
4. **Zero new dependencies, zero schema migrations, and file-length discipline:**
   - Uses Python stdlib (`json`, `hashlib`, `os`, `stat`, `sqlite3`, `time`, `unicodedata`, `pathlib`) only.
   - All new or modified tracked Python modules must obey `docs/contrib/file-length-profile.md` (`<= 400` physical lines; target `<= 350`).

---

## 2. Product entry points and explicit mode contract

### 2.1 CLI command: `cloe ops context-pack`

Registered in `cli/_parser_ops_context.py` and dispatched to `cli/ops_context_commands.py`:

```text
cloe ops context-pack
  --graph GRAPH_ID
  --mode {exact_identity,current_literal_enumeration,ranked_discovery,graph_investigation,literal_captured_text,semantic_discovery}
  [--canonical-key KEY]
  [--query TEXT]
  [--intent {definition,implementation,tests,docs,messages,general}]
  [--selection PATH]
  [--binding BINDING_ID ...]
  [--path-prefix BINDING_ID=REL_PREFIX ...]
  [--kind KIND ...]
  [--budget-bytes 4096..65536]
  [--max-items 1..50]
  [--locations-per-item 1..5]
  [--offset 0..1000]
  [--expand-depth {0,1}]
  [--expand-seeds 1..5]
  [--node-limit 1..32]
  [--edge-limit 1..64]
  [--edge-kind EDGE_KIND ...]
  [--fallback-to {exact_identity,ranked_discovery}]
  [--freshness {none,check}]
  [--source-root BINDING_ID=ABS_PATH ...]
  [--allow-partial]
```

**Explicit `--mode` matrix (never inferred from `--canonical-key` or `--query`):**

| Requested `--mode` | Target / flag rules | Context v1 behavior and per-item surfaces |
|---|---|---|
| `exact_identity` | Requires `--canonical-key`; rejects `--query`, `--intent`, `--expand-depth 1` | Reads `node_locations` for `--canonical-key`. Seed item uses `item_role="seed"`, `match_surface="stored_metadata"`. |
| `current_literal_enumeration` | Requires `--query` (`1..200` stripped Unicode characters, `<= 800` UTF-8 bytes); rejects `--canonical-key`, `--intent`, `--expand-depth 1` | Preserves existing ascending `canonical_key` scan order (`ordering_policy_version="canonical-key-asc-v1"`). Items use `item_role="seed"`, `match_surface="stored_metadata"`. |
| `ranked_discovery` | Requires `--query` (`1..200` stripped Unicode characters, `<= 800` UTF-8 bytes); optional `--intent` (default `general`), `--expand-depth 0\|1` (default `0`); rejects `--canonical-key` | Ranks complete candidate scans under `cloe-intent-rank-v1`. Ranked seeds use `item_role="seed"`, `match_surface="stored_metadata"`. When `--expand-depth 1` runs on a port that supports expansion (SQLite in W4), `requested_mode == effective_mode == "ranked_discovery"` (`fallback=None`) and expanded depth-1 neighbors/relations use `item_role="neighbor"`, `match_surface="graph_topology"`. The accepted ADR 0168 Epics 1 and 2 amendment extends this capability to the built-in PostgreSQL adapter; source proof and qualification remain pending. |
| `graph_investigation` | Requires `--canonical-key`; `--expand-depth` must be `1` (default `1`); optional `--intent` (default `general`, selecting default edge kinds); rejects `--query` unless `--fallback-to ranked_discovery` is also set | On SQLite: locates center seed (`item_role="seed"`, `match_surface="stored_metadata"`) and expands depth-1 typed neighbors (`item_role="neighbor"`, `match_surface="graph_topology"`). W4 PostgreSQL behavior remains the historical baseline: returns `status="unavailable"`, `unavailable_reason="backend_unsupported"` unless the caller explicitly passed `--fallback-to exact_identity` (uses `--canonical-key`) or `--fallback-to ranked_discovery` (requires `--query`), recording `FallbackDisclosure`. Under the accepted ADR 0168 Epics 1 and 2 amendment ([cloe-server-parity-v1.md](cloe-server-parity-v1.md) §2.1), the built-in PostgreSQL adapter declares a private capability and runs natively with `fallback=None`, exactly as SQLite does today. A port without that capability keeps the W4 refusal and fallback behavior. No W7 closure is claimed. |
| `literal_captured_text` | Any | Returns `status="unavailable"`, `unavailable_reason="capability_not_admitted"` with zero storage reads. Body search remains in `cloe ops lexical-query`. |
| `semantic_discovery` | Any | Returns `status="unavailable"`, `unavailable_reason="capability_not_admitted"` with zero storage reads. |

**CLI exit code contract:**
- `0`: `status == "complete"` (or `status == "partial"` when `--allow-partial` is explicitly passed).
- `3`: `status == "partial"` by default (valid bounded JSON packet emitted on stdout with disclosed omissions, distinct from both exhaustive completeness and failure).
- `1`: `status in {"refused", "stale", "unavailable", "failed", "budget_error"}`.
- `2`: `argparse` CLI syntax/usage error.

### 2.2 CLI command: `cloe ops context-select`

```text
cloe ops context-select
  --graph GRAPH_ID
  --binding BINDING_ID [--binding BINDING_ID ...]
  [--path-prefix BINDING_ID=REL_PREFIX ...]
  [--pin-publication]
  --output PATH
```

- Validates `--graph` and `1..8` bindings against fresh on-disk config and (when `--pin-publication` is passed) current accepted database readback.
- Enforces `0..4` path prefixes per binding and `scan_unit_count <= 8` total `(binding_id, path_prefix)` pairs.
- Writes one `cloe-source-selection-v1` JSON file using `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` (refusing to overwrite existing files). Stores **no filesystem root paths**.
- Exits `0` on success, `1` on refusal/unavailable/failed, `2` on `argparse` error.

### 2.3 Library API, read ports, and reuse of existing storage scan owners

- **Entry point:** `common_lore_index.retrieval.context_assembly.build_compact_context(request: ContextRequest, port: ContextReadPort, *, freshness: FreshnessCheckConfig | None = None) -> CompactContextPacket | ContextBudgetError`.
- **Direct reuse of `NavigationSearchQuery`, `NodeLocationsQuery`, and existing scan/locator owners:**
  - `--query` (`1 <= len(query.strip()) <= 200` Unicode characters, hence `1..800` UTF-8 bytes) and `--offset` (`0..1,000`, a strict subset of `NavigationSearchQuery`'s `0..10,000`) validate directly through `NavigationSearchQuery` (`storage/navigation_search.py:32-42`).
  - Existing storage builders (`storage/sqlite_local/navigation_queries.py`, `storage/sqlite_local/node_location_queries.py`, `storage/postgres_navigation_sql.py`, `storage/postgres_navigation_search.py`, and `storage/postgres_node_locations.py`) accept a keyword-only `role_sql: str = _EVIDENCE_ROLE_SQL` parameter. Existing MCP and CLI callers omit `role_sql` and continue using `_EVIDENCE_ROLE_SQL` unchanged; the context adapters pass `role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1`.
- **`ContextReadPort` implementations and per-backend `snapshot_manifest_id` provenance:**
  - `SqliteContextReadAdapter` (`server/context_read_sqlite.py`): executes all reads inside one `read_transaction` (`consistency_mode="single_read_transaction"`). Its initial accepted-publication query (`1` SQL statement, `1` logical read unit) joins `accepted_publication a JOIN runs r ON r.id = a.run_id` (`storage/sqlite_local/schema.py:39-74`) to read `(a.generation, a.run_id, r.publication_bundle_id, r.snapshot_manifest_id, r.snapshot_vector_json)`, supplying both the run-level `publication.snapshot_manifest_id` and the per-binding `(binding_id, binding_revision, snapshot_id)` vector used for `cloe-source-selection-v1` revalidation. It then reuses `navigation_candidates` / `node_locations` with `role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1`, calls `storage/sqlite_local/context_expansion_queries.py` for incident-selective depth-1 expansion, fetches all neighbor direct locations in **at most one batched SQL statement** (`batch_neighbor_direct_locations`), and enforces `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT` via `sqlite3.Connection.set_progress_handler`.
  - `PostgresContextReadAdapter` (`server/context_read_postgres.py`): executes one self-contained JSON statement per scan unit (`consistency_mode="per_statement_identity_checked"`), reusing `read_postgres_navigation_search_with_executor` / `read_postgres_node_locations_with_executor` with `role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1` and projecting `r.snapshot_manifest_id` and `r.snapshot_vector_json` from `public.runs` in the `accepted_run` CTE (`storage/postgres_navigation_sql.py:101-141`) so run-level `snapshot_manifest_id` and per-binding `(binding_id, binding_revision, snapshot_id)` are present even on zero-candidate scans. Verifies identical `accepted_publication` `(generation, run_id, publication_bundle_id, snapshot_manifest_id)` across all statements. W4's refusal remains the historical baseline; under the accepted ADR 0168 Epics 1 and 2 amendment ([cloe-server-parity-v1.md](cloe-server-parity-v1.md) §2.3), it executes one self-contained statement (`storage/postgres_context_expansion_sql.py`). That statement covers all `<= 5` seeds' edge windows, the greedy neighbor admission, and the admitted neighbors' direct locations, with full accepted-identity comparison (`stale` on drift). Source proof and whole-candidate qualification remain pending.
- **Shared projection helper:** extracts one public, non-paging member-projection function in `server/_navigation_groups.py` reused by both `group_page` and context adapters so `_identity`, `_destination`, `sanitize_jsonable`, and private markers behave identically.

---

## 3. Epic A: Explicit intent-aware deterministic navigation

### 3.1 Closed `NavigationIntent` and isolated direct-evidence role (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`)

1. **`NavigationIntent` (`retrieval/intent_policy.py`):**
   - Closed 6-value enum: `definition`, `implementation`, `tests`, `docs`, `messages`, `general`.
   - Caller-declared only; never inferred from query text; rejected in `exact_identity` and `current_literal_enumeration`.
2. **Isolated context direct-evidence role (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`):**
   - Passed via `role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1` only from `server/context_read_sqlite.py` and `server/context_read_postgres.py`; MCP `_EVIDENCE_ROLE_SQL` is untouched.
   - Evaluated **before** the fallback `WHEN link.link_kind = 'inferred_from_edge' THEN 'reference'` branch, `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` classifies a `canonical_node_evidence` link as `direct` when:
     - `link.link_kind = 'observed'` and it matches one of the 8 existing MCP direct rules (`python.{module,class,function,method}` and `doc.{page,section,adr,skill}`), OR
     - `link.link_kind = 'observed'` and `e.raw_kind = subject.kind` for message canonical kinds `email.{mailbox,message,part,attachment_stub,thread_hint,address}` (`canonicalization/email_family.py:96,174`) and `feed.{document,channel,item,author,category}` (`canonicalization/feed_family.py:92`), OR
     - `link.link_kind = 'observed'` and `e.raw_kind = subject.kind` for explicit test/check canonical kinds `js.{test_suite,test_case}` (`canonicalization/language_javascript_family.py:103`), `ruby.{test_case,test_method}` (`canonicalization/language_family.py:218`), `bats.file` (`canonicalization/shell_bats_family.py:219`), `zunit.{file,command_under_test}` (`canonicalization/shell_zunit_family.py:272,581`), and `nix.check` (`canonicalization/nix_family.py:316`), OR
     - `link.link_kind IN ('observed', 'inferred_from_edge')` for shell test child canonical kinds emitted via `_append_two_node_edge` (`canonicalization/_shell_edge_helpers.py:57-70`, which attaches `inferred_from_edge` to both parent and child while `e.raw_kind` names the child observation):
       - `e.raw_kind = subject.kind` with `subject.kind IN ('bats.test_case', 'zunit.suite', 'zunit.test_case', 'zunit.assertion', 'zunit.expectation', 'zunit.mock', 'zunit.stub')` (`shell_bats_family.py:84,269`; `shell_zunit_family.py:107,119,185,197,209,321,365,641,688,730,738`), OR
       - `subject.kind = 'bats.expectation' AND e.raw_kind IN ('bats.assertion', 'bats.refutation')` (`shell_bats_family.py:132,450`), OR
       - `subject.kind = 'zunit.hook' AND e.raw_kind IN ('zunit.setup', 'zunit.teardown', 'zunit.before_each', 'zunit.after_each', 'zunit.hook')` (`shell_zunit_family.py:131-137,410`).
   - **Programmatically derived locatable kind set (`DIRECT_LOCATABLE_CANONICAL_KINDS_V1`) and scoped truthfulness:**
     - `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` is the `frozenset` of `subject.kind` values derived directly from the structured rule table that generates `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` (never hand-enumerated; verified by unit test). Under `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`, all `docs` (`doc.*`), `tests` (`python_test_subject`, `bats.*`, `zunit.*`, `js.test_*`, `ruby.test_*`, `nix.check`), and `messages` (`email.*`, `feed.*`) affine kinds are in `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`.
     - Canonical kinds outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` (such as non-Python code kinds `go.*`, `js.function`, `ruby.class`, `bash.*`, `zsh.*`, `nix.package`, or `tool`, `env`, `external.url`) have no `direct` evidence role in `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` and cannot satisfy a binding/prefix scope predicate.
     - Under any request scoped by binding or path prefix:
       1. If the caller passes `--kind` and **any** requested kind is outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`, `context-pack` returns `status="unavailable"`, `unavailable_reason="unlocatable_kind_in_scoped_selection"`, `scope_complete=False`.
       2. Whenever any requested `--kind` or (when `--kind` is omitted) any kind in the active intent's affine family (or the wildcard pattern `*` under general or intent-less literal enumeration) is outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`, `scope.unlocatable_kind_patterns_excluded` records the sorted excluded pattern tokens, `omission_counts.unlocatable_kind_pattern_excluded` increments by `len(unlocatable_kind_patterns_excluded)` with a corresponding `OmissionRecord`, `scope.scope_complete` is set to `False`, and zero-item scoped packets set `absence_basis="stored_direct_locatable_metadata_fields_in_selected_scope"`.

### 3.2 Subject classification, affinity tables, and canonical edge subsets (`cloe-intent-tables-v1`)

1. **Deterministic Python test-subject classifier (`classify_subject_intent_family`):**
   - Because Python test files, classes, functions, and methods are stored in `canonical_nodes` as `python.{module,class,function,method}` (`extractors/languages/python.py:140-161`; `python.test_*` are raw-profile observation kinds only), `classify_subject_intent_family(node, verified_direct_locations)` classifies a `python.{module,class,function,method}` node as `python_test_subject` iff:
     - any verified direct location path has a `tests` or `test` path segment, a `test_*` filename, or a `*_test.py` / `*.test.py` suffix, OR
     - its symbol segment is a `python.function`/`python.method` starting with `test_` or a `python.class` starting with `Test`.
2. **Kind affinity table (`cloe-intent-tables-v1`, no universal test penalty):**
   - Every candidate receives `affinity_tier = 0` (`intent_kind_affine`) if it belongs to the active intent's affine family, and `affinity_tier = 1` (`intent_kind_neutral`) otherwise:
     - `definition` and `implementation`: non-test `python.{module,class,function,method}`, `go.*`, `js.{file,module,function,class,method,component,route}`, `ruby.{file,module,class,method,singleton_method,constant,route}`, `bash.*`, `zsh.*`, `awk.*`, `powershell.*`, `nix.{app,package,devShell}`, `config.*`, `css.*`, `html.*`, `xml.*` are `intent_kind_affine` (`0`). `python_test_subject` and explicit test kinds are `intent_kind_neutral` (`1`), never penalized below docs or messages.
     - `tests`: `python_test_subject`, `bats.{file,test_case,expectation}`, `zunit.{file,suite,test_case,hook,assertion,expectation,command_under_test,mock,stub}`, `js.{test_suite,test_case}`, `ruby.{test_case,test_method}`, and `nix.check` are `intent_kind_affine` (`0`).
     - `docs`: `doc.{page,section,adr,skill}` are `intent_kind_affine` (`0`).
     - `messages`: `email.{mailbox,message,part,attachment_stub,thread_hint,address}` and `feed.{document,channel,item,author,category}` are `intent_kind_affine` (`0`).
     - `general`: all kinds are `intent_kind_neutral` (`1`).
3. **Intent-to-edge-kind expansion table (`cloe-intent-tables-v1`, validated subset of `CANONICAL_EDGE_KINDS`):**
   - Every default edge-kind set `INTENT_DEFAULT_EDGE_KINDS[intent]` is validated at module load (and by unit test in `intent_policy.unit.test.py`) as a non-empty subset of `CANONICAL_EDGE_KINDS` (`graph/edge_kinds.py`) whose edge kinds are emitted by canonicalizers in `common_lore_index.canonicalization`:
     - `definition` / `implementation`: `calls`, `contains`, `declares`, `defines`, `depends_on`, `exposes_script`, `imports`, `includes`, `loads`, `method_of`, `references`, `replaces_module`, `requires_module`, `sources`, `workspace_uses`.
     - `tests`: `asserts`, `command_under_test`, `contains` (`bats.file` -> `bats.test_case` in `shell_bats_family.py:272`; `zunit.file` -> `zunit.suite`/`zunit.test_case` in `shell_zunit_family.py:324,356`), `defines`, `expects`, `has_assertion`, `has_hook`, `has_test_case` (`zunit.suite` -> `zunit.test_case` in `shell_zunit_family.py:356`), `imports`, `loads`, `references`, `refutes`, `tests_command`, `uses_fixture`, `uses_helper`, `uses_mock`, `uses_stub`.
     - `docs`: `contains`, `defines` (`document_markdown_family.py:112`, `document_family.py:112`), `embeds`, `links_to` (`document_markdown_family.py:238`), `references` (`document_family.py:189`), `styles` (`document_css_family.py:262`).
     - `messages`: `defines` (`email_family.py:104`, `feed_family.py:99`), `references` (`email_family.py:181,258`, `feed_family.py:146,223`).
     - `general`: all `CANONICAL_EDGE_KINDS` (disclosed in `expansion.edge_filter_mode="all_canonical_edge_kinds"`).

### 3.3 Six-tier lexicographic ranking (`cloe-intent-rank-v1`) and byte tie-break (`cloe-intent-tiebreak-v1`)

Candidates in `ranked_discovery` are ordered by the ascending integer 5-tuple `(exactness_tier, affinity_tier, match_class_tier, evidence_tier, publication_tier)` followed by `cloe-intent-tiebreak-v1` (`score` is always `null`):

| Tier | Field | Ordinal values (`0` is strongest) and closed explanation codes |
|---|---|---|
| 1 | `exactness_tier` | `0` (`exact_match_group`) when `match_class_tier in {0, 1, 2}`; `1` (`partial_match_group`) when `match_class_tier in {3, 4, 5, 6}` |
| 2 | `affinity_tier` | `0` (`intent_kind_affine`); `1` (`intent_kind_neutral`) |
| 3 | `match_class_tier` | `0` (`display_exact`), `1` (`display_casefold_exact`), `2` (`key_terminal_exact`: query preceded by a non-`\w` char at end of `canonical_key`), `3` (`display_prefix`), `4` (`display_substring` casefold), `5` (`key_substring` casefold), `6` (`kind_only`) |
| 4 | `evidence_tier` | `0` (`direct_verified`: `>= 1` verified direct location), `1` (`direct_unverified`), `2` (`no_direct_evidence`), `3` (`identity_withheld`) |
| 5 | `publication_tier` | `0` (`current_publication`: `accepted_run`), `1` (`historical_publication`) |
| 6 | `cloe-intent-tiebreak-v1` | `(canonical_key.encode("utf-8"), first_verified_destination_tuple)` ascending in Python |

**Ambiguity preservation and complete-scan prerequisite:**
- When `>= 2` candidates share the top `(exactness_tier, affinity_tier, match_class_tier)` tuple, `ambiguity` reports `{"status": "ambiguous", "tied_top_count": N}`; all tied candidates remain eligible in `cloe-intent-tiebreak-v1` order, and any tied candidate dropped by `--max-items` or `--budget-bytes` increments omission `ambiguous_alternative_omitted_by_budget`.
- Ranking operates **only** over complete candidate scans. If any scan unit hits `NODE_SCAN_LIMIT = 2,000`, `EVIDENCE_SCAN_LIMIT = 10,000`, or admission work caps (`100,000` checks / `32 MiB`), that scan unit yields zero ranked items, sets `scope_complete=False`, and records omission `candidate_scan_incomplete` with a narrowing hint (`binding`, `path_prefix`, or `kind`).

---

## 4. Epic B: Bounded compact-context packet (`cloe-compact-context-v1`)

### 4.1 Wire schema, field caps, and minimal budget error

Every non-error packet is serialized with `json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"` in declared key order. The example below is a measured fixture; its current compact UTF-8 length including newline is 2764 bytes (`work_ledger.actual_bytes == 2764`):

```json
{
  "schema": "cloe-compact-context-v1",
  "status": "complete",
  "requested_mode": "ranked_discovery",
  "effective_mode": "ranked_discovery",
  "fallback": null,
  "consistency_mode": "single_read_transaction",
  "request": {
    "mode": "ranked_discovery",
    "intent": "tests",
    "target_kind": "query",
    "target_echo": "build_compact_context",
    "target_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "target_echo_withheld": false,
    "offset": 0,
    "max_items": 12,
    "locations_per_item": 2,
    "expand_depth": 1,
    "expand_seeds": 3,
    "budget_bytes": 16384
  },
  "scope": {
    "graph_id": "repo",
    "backend": "sqlite",
    "selection_source": "selection_file",
    "selection_fingerprint": "select_ctx1:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    "selected_binding_count": 1,
    "path_prefix_count": 1,
    "scan_unit_count": 1,
    "unlocatable_kind_patterns_excluded": [],
    "scope_echo_complete": true,
    "selected_binding_ids": [
      "bind1:aaaa"
    ],
    "path_prefixes": [
      {
        "binding_id": "bind1:aaaa",
        "prefix": "src/test/"
      }
    ],
    "scope_complete": true,
    "repository_id": "repo1:repo"
  },
  "publication": {
    "generation": 1,
    "accepted_run_id": 1,
    "publication_bundle_id": "bundle1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "snapshot_manifest_id": "manifest1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "ordering": {
    "ordering_policy_version": "cloe-intent-rank-v1",
    "tie_break_version": "cloe-intent-tiebreak-v1",
    "intent_tables_version": "cloe-intent-tables-v1",
    "admission_layout": "seeds_then_neighbors_v1",
    "ambiguity": {
      "status": "unambiguous",
      "tied_top_count": 0
    }
  },
  "expansion": {
    "state": "completed",
    "reason": null,
    "edge_filter_mode": "intent_default",
    "seeds_expanded": 0,
    "neighbors_admitted": 0,
    "relations_admitted": 0
  },
  "omission_counts": {
    "output_budget": 0,
    "item_limit": 0,
    "location_limit": 0,
    "ambiguous_alternative_omitted_by_budget": 0,
    "expansion_node_limit": 0,
    "expansion_edge_limit": 0,
    "expansion_backend_unsupported": 0,
    "candidate_scan_incomplete": 0,
    "unlocatable_kind_pattern_excluded": 0,
    "oversize_field_withheld": 0,
    "unencodable_field_withheld": 0
  },
  "work_ledger": {
    "config_revalidations_executed": 1,
    "logical_read_units": 2,
    "max_logical_read_units": 16,
    "sql_statements_executed": 4,
    "max_sql_statements": 36,
    "scan_units_executed": 1,
    "max_scan_units": 8,
    "seed_expansions_executed": 0,
    "max_seed_expansions": 5,
    "candidate_rows_scanned": 0,
    "evidence_rows_scanned": 0,
    "sqlite_vm_steps_estimate": 4000,
    "elapsed_ms": 12,
    "actual_bytes": 2764,
    "sqlite_progress_callbacks": 4,
    "sqlite_progress_interval_ops": 1000
  },
  "freshness": {
    "schema": "cloe-advisory-freshness-v1",
    "state": "not_requested",
    "files_checked": 0,
    "bytes_read": 0,
    "counts": {
      "changed_observed": 0,
      "no_change_observed_with_limits": 0,
      "not_checked": 0,
      "unavailable": 0
    }
  },
  "absence_basis": "stored_direct_locatable_metadata_fields_in_selected_scope",
  "items": [],
  "neighbors": [],
  "relations": [],
  "omissions": []
}
```

**Field caps and UTF-8 sanitization (`retrieval/context_budget.py`):**
- Strings are never sliced mid-character and JSON is never truncated.
- Any stored string containing lone surrogates (not strict UTF-8 encodable) or exceeding its byte cap (`display_name <= 512` UTF-8 bytes, `source_relative_path <= 1,024` bytes, `canonical_key <= 4,096` bytes) is replaced with `null` and increments `unencodable_field_withheld` or `oversize_field_withheld`.
- Zero-item packets set `absence_basis: "stored_metadata_fields_in_selected_scope"` when unscoped and `"stored_direct_locatable_metadata_fields_in_selected_scope"` when scoped by binding or path prefix (never claiming whole-source or body-text absence).

**Skeleton echo compaction (`skeleton_compaction_v1`), `4,096`-byte minimum legal budget, and `budget_error` envelope:**
- `MIN_BUDGET_BYTES=4096`, `MAX_BUDGET_BYTES=65536`, default16384. The example is a measured fixture, not a universal maximum: required IDs and diagnostics have variable byte lengths. Recompute the actual maximally compacted skeleton for every request.
- `request` always carries `target_sha256` (`"sha256:<64-hex>"`). When `budget_bytes < 6,144` and `len(target_utf8) > 128`, or whenever retaining `target_echo` would cause the empty-collection skeleton to exceed `budget_bytes`, `target_echo` is set to `null` with `target_echo_withheld=True`.
- `scope` always carries `selected_binding_count`, `path_prefix_count`, `scan_unit_count`, and `selection_fingerprint` (`"select_ctx1:<64-hex>"`). When `budget_bytes < 6,144` and the combined UTF-8 representation of `selected_binding_ids` and `path_prefixes` exceeds `256` bytes, or whenever retaining them would cause the skeleton to exceed `budget_bytes`, both arrays are set to `null` with `scope_echo_complete=False`.
- Compaction withholds only designated caller echoes; it never truncates or removes required provenance. If the compacted required skeleton still exceeds the legal requested budget, emit `budget_error/reason=required_envelope_does_not_fit` within its own512-byte bound.
- The documented compact example fits4096 bytes. There is no guaranteed item headroom for every legal identifier combination. Exact-boundary tests must cover long valid provenance and a legal budget that returns the bounded minimal error.
- **Bounded `budget_error` envelope:** `required_min_bytes` is the exact UTF-8 byte length (including `\n`) of the maximally compacted skeleton for the request (or `null` when `reason == "invalid_budget_type"`). In `build_compact_context`, if `type(raw_budget) is not int` (e.g. `bool`, `float`, `str`, `None`), `reason` is `"invalid_budget_type"` and `budget_bytes` is `null`. If `type(raw_budget) is int` and `raw_budget < 4096 or raw_budget > 65536`, `reason` is `"budget_out_of_range"`, with `budget_bytes` echoed only when `-999_999_999 <= raw_budget <= 999_999_999` (else `null`). On the CLI, a non-integer string argument to `--budget-bytes` is rejected by `argparse` (`type=int`) with exit code `2`, while an out-of-range integer argument emits the fixed-vocabulary `budget_error` envelope (`<= 512` UTF-8 bytes, no caller strings) and exits `1`:
  ```json
  {"schema":"cloe-compact-context-v1","status":"budget_error","reason":"budget_out_of_range","budget_bytes":2048,"min_budget_bytes":4096,"max_budget_bytes":65536,"required_min_bytes":2580}
  ```

### 4.2 Rank-prefix admission (`seeds_then_neighbors_v1`), `_destination` deduplication, and stored relations

1. **Admission order (`seeds_then_neighbors_v1`) and `actual_bytes` fixpoint:**
   - **Step 1 (Skeleton):** Reserve counter widths from work/item limits and compute base skeleton bytes.
   - **Step 2 (Seed items as strict rank prefix):** Slice ranked seeds by `[offset : offset + max_items]`. For each seed in rank order, attach up to `--locations-per-item` (`1..5`, default `2`) verified direct locations (with embedded per-location freshness observation when `--freshness check` is active). Admit the seed if the serialized packet stays `<= budget_bytes` (or retry with `1` location before stopping). **Never skip a higher-ranked seed to admit a smaller lower-ranked seed.**
   - **Step 3 (Depth-1 neighbor units and stored relations on SQLite):** Bounded database discovery expands the first `expand_seeds` ranked candidates before output admission and fetches direct locations in **at most one batched SQL statement** (`batch_neighbor_direct_locations`); its actual work remains reported if output admission later withholds a seed. Admit neighbor units (`neighbor` node + at least one stored `relation` connecting it to an admitted item) in `(seed_rank_index, edge_kind, neighbor_canonical_key)` order while `serialized_bytes <= budget_bytes`. A returned neighbor already present as an admitted seed contributes its eligible relations without a duplicate node. Explicit edge-kind inputs are a lexical set. Only admitted endpoints support emitted relations; completeness describes this bounded result, not the entire graph.
   - **Step 4 (Omission detail records):** Admit `OmissionRecord` details in prefix order while `serialized_bytes <= budget_bytes` (`omission_counts` in the skeleton always reflects exact totals).
   - **Step 5 (Self-referential `actual_bytes` fixpoint and final byte check):** Set `work_ledger["actual_bytes"] = 0`, serialize to UTF-8, and converge the exact length including newline in at most 3 iterations. Admission reserves all final variable fields before any freshness source reads. Finalization may compact optional echoes, but never removes inspected records. A measured required-envelope overflow returns the minimal budget error; an unexpected optional overflow is an internal invariant failure. The empty-envelope floor uses final counters, including sampled work.
2. **Identity-preserving deduplication:**
   - **Items / neighbors:** deduplicate on `(graph_id, backend, accepted_run_id, publication_bundle_id, canonical_key)`.
   - **Locations:** deduplicate on the exact `_destination` dictionary keys from `server/_navigation_groups.py:27-30` (`source_binding_id`, `binding_revision`, `snapshot_id`, `source_relative_path`, `run_id`, `publication_relation`, `path_namespace`, `graph_path`) plus `(start_line, end_line)`. Locations at the same relative path under different bindings, revisions, snapshots, or runs remain distinct. Overlapping spans are never merged. Withheld or unverified locations (`_destination is None`) never deduplicate with any other location.
3. **Stored relation support:**
   - Every entry in `relations[]` is backed by a stored `canonical_edges` row (`edge_kind in CANONICAL_EDGE_KINDS`) where **both** `source_key` and `target_key` are present in `items[] ∪ neighbors[]` (for example, a `bats.file` -> `contains` -> `bats.test_case` edge produced by `canonicalization/shell_bats_family.py:272`):
     ```json
     {
       "source_key": "bats.file:tests/cli.bats",
       "edge_kind": "contains",
       "target_key": "bats.test_case:tests/cli.bats#invokes%20context-pack",
       "match_surface": "graph_topology",
       "support": {
         "basis": "stored_canonical_edge",
         "confidence": "high",
         "conflict": false,
         "first_seen_run_id": 1,
         "last_seen_run_id": 1,
         "explanation_ref": {"source_key": "bats.file:tests/cli.bats", "edge_kind": "contains", "target_key": "bats.test_case:tests/cli.bats#invokes%20context-pack", "identity_metadata_hash": "sha256:..."}
       }
     }
     ```
   - No relation is ever inferred from lexical similarity or file co-occurrence.

### 4.3 Separate work and statement limits (`retrieval/context_work.py`)

| Limit constant | Value / Range | Behavior on exhaustion / violation |
|---|---|---|
| `MAX_BINDINGS` | `1..8` | Up-front refusal (`status="refused"`, `refusal_code="binding_limit_exceeded"`) |
| `MAX_PREFIXES_PER_BINDING` | `0..4` | Up-front refusal (`status="refused"`, `refusal_code="prefix_limit_exceeded"`) |
| `MAX_SCAN_UNITS` | `8` total `(binding_id, path_prefix)` pairs | Up-front refusal (`status="refused"`, `refusal_code="scan_unit_limit_exceeded"`) |
| `NODE_SCAN_LIMIT` / `EVIDENCE_SCAN_LIMIT` | `2,000` nodes / `10,000` evidence rows / `100,000` admission checks (`32 MiB`) | Scan unit yields 0 ranked items, records `candidate_scan_incomplete`, sets `scope_complete=False` |
| `--max-items` | `1..50` (default `12`) | Omission `item_limit`, `status="partial"` |
| `--expand-depth` | `0..1` (default `0`, or `1` in `graph_investigation`) | `>= 2` refused (`invalid_expand_depth`) |
| `--expand-seeds` | `1..5` (default `3`) | Bounds seeds expanded on SQLite and capable PostgreSQL ports |
| `--node-limit` / `--edge-limit` | `1..32` (default `8`) / `1..64` (default `16`) per seed; aggregate `128` neighbors / `256` edges | Omission `expansion_node_limit` / `expansion_edge_limit`, `status="partial"` |
| `MAX_LOGICAL_READ_UNITS` | `16` (`1` accepted-identity & selection DB check + `<= 8` scan units + `<= 5` seed expansions + `1` batched neighbor-location read + `1` margin) | Stops further reads, records `work_budget_exhausted`, `status="partial"` |
| `MAX_SQL_STATEMENTS_SQLITE` | `36` (`1` accepted-identity & selection DB check + `<= 8×2` scan statements + `<= 5×3` seed expansion statements + `1` batched neighbor-location statement + `3` margin) | Stops further statements, records `statement_limit`, `status="partial"` |
| `MAX_SQL_STATEMENTS_POSTGRES` | `12` (`1` accepted-identity & selection DB check + `<= 8` single-statement `execute_json_readback` scans + `1` single-statement `node_locations` or batched seed-expansion/neighbor-location read + `2` margin) | Stops further statements, records `statement_limit`, `status="partial"` |
| `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT` | Initial calibration hypothesis (250 callbacks/statement at a 1000-operation interval; 250000 operations is an estimate via `set_progress_handler`) | Interrupts statement, discards partial statement rows, records `work_budget_exhausted`, `status="partial"` |
| `WALL_CLOCK_DEADLINE_MS` | `10,000 ms` (checked between statements; ADR 0168's Epic 3 server statement-timeout proposal is held and does not add a startup option) | Stops further statements, records `deadline_exceeded`, `status="partial"` |

**PostgreSQL bounded neighborhood policy choice (historical W4 baseline and W7 forward amendment):**
- *Historical W4 baseline (`REPOMAP-CLOE-CONTEXT1`):* Although PostgreSQL had an unbounded neighborhood query owner (`storage/sql/neighborhood.py`), executing an unbounded neighborhood scan and clipping rows in Python would have violated Epic B's bounded-storage-work invariant. Therefore, in W4, `--expand-depth 1` in `ranked_discovery` on PostgreSQL retained all ranked seeds, set `expansion.state="unavailable"`, `expansion.reason="backend_unsupported"`, recorded omission `expansion_backend_unsupported`, and set `scope_complete=False` (`status="partial"`).
- *Accepted W7 forward amendment for Epics 1 and 2 (`REPOMAP-CLOE-SERVER-PARITY1`, [cloe-server-parity-v1.md](cloe-server-parity-v1.md) §2):* ADR 0168 accepts the bounded parity design without changing the W4 historical records. The design does not reuse `build_canonical_neighborhood_query_sql`. The built-in PostgreSQL adapter runs one statement, costing 1 SQL statement and 1 logical unit:
  - per-seed, per-direction windows limited to `edge_limit + 1` rows;
  - the SQLite greedy admission replayed as a bounded `WITH RECURSIVE` walk of at most 320 steps, with the 256-relation and 128-neighbor caps and per-seed `node_limit` charged only for new neighbors;
  - direct locations for exactly the admitted neighbors, using the SQLite selected-run rule and order, limited to `EVIDENCE_SCAN_LIMIT + 1 = 10,001` rows.

  These limits bound returned rows, not physical scans or sorts. Execution
  duration remains bounded only by the existing between-statement ledger checks;
  the startup-option server statement-timeout proposal is rejected/held under
  ADR 0168 RD-1 and is not part of this contract.

---

## 5. Epic C: Explicit source selection (`cloe-source-selection-v1`) and advisory freshness (`cloe-advisory-freshness-v1`)

### 5.1 Reusable source selection (`cloe-source-selection-v1`)

```json
{
  "schema": "cloe-source-selection-v1",
  "graph_id": "repo",
  "backend": "sqlite",
  "scan_unit_count": 2,
  "bindings": [
    {
      "binding_id": "bind1:aaaa",
      "revision": 1,
      "snapshot_id": "snap1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "selection_policy_id": "select1:bbbb",
      "source_definition_id": "srcdef_01",
      "path_prefixes": [
        "src/main/python/",
        "src/test/unit/python/"
      ]
    }
  ],
  "expected_publication": {
    "accepted_run_id": 1,
    "publication_bundle_id": "bundle1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "snapshot_manifest_id": "manifest1:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "generation": 1,
    "job_id": "context-fixture-job",
    "attempt": 1,
    "extraction_receipt_id": "receipt1:0000000000000000000000000000000000000000000000000000000000000000"
  },
  "selection_fingerprint": "select_ctx1:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  "repository_id": "repo1:repo"
}
```

- **Framing, integer `revision`, and multi-binding `snapshot_manifest_id` provenance:**
  - `selection_fingerprint` (`select_ctx1:<64-hex>`) is a length-framed SHA-256 digest over the canonical fields (`schema`, `graph_id`, `repository_id`, `backend`, `scan_unit_count`, sorted `bindings`, and `expected_publication`). It is **not** a corpus or publication identity and grants **no** authorization.
  - Each entry in `bindings[]` records `revision` as an exact `int >= 1` (`type(revision) is int`, matching `_destination` in `server/_navigation_groups.py:24`) and `snapshot_id` (`str | null`, populated from the binding's entry in `runs.snapshot_vector_json` when `--pin-publication` is active, else `null`).
  - Under both single-binding and multi-binding selections, `expected_publication.snapshot_manifest_id` (and `publication.snapshot_manifest_id` in `cloe-compact-context-v1`) is the single run-level `runs.snapshot_manifest_id` (`runs.snapshot_manifest_id` on SQLite Local, `public.runs.snapshot_manifest_id` on PostgreSQL) for `accepted_run_id`, while per-binding snapshot identities live in `bindings[].snapshot_id` (verified against `runs.snapshot_vector_json`).
- **Revalidation on every `context-pack` call:**
  - Closed schema parse (unknown fields or non-strict types, including non-`int` or `bool` `revision`, are refused with `invalid_selection_record`); recomputed fingerprint must match `selection_fingerprint` (else `selection_fingerprint_mismatch`).
  - On-disk config revalidation (`work_ledger.config_revalidations_executed = 1`) and accepted database readback (`1` logical read unit and `1` SQL statement, shared with the packet's initial accepted-identity read) verify every binding's `revision`, `selection_policy_id`, `source_definition_id`, and (when pinned) `snapshot_id` in `runs.snapshot_vector_json` (else `selection_binding_changed` or `selection_binding_missing`).
  - If `expected_publication` is non-null and differs from the live accepted publication `(generation, accepted_run_id, publication_bundle_id, job_id, attempt, snapshot_manifest_id, extraction_receipt_id)`, `context-pack` returns `status="stale"`, `reason="selection_publication_advanced"` with zero items.

### 5.2 Optional advisory freshness (`cloe-advisory-freshness-v1`)

Default `--freshness none` opens no target source files. Opt-in checks require
explicit caller-owned `--source-root BINDING_ID=ABSOLUTE_PATH` mappings; never
infer roots from configuration or cwd. Only finally admitted, direct, current,
identity-verified locations under selected bindings are eligible. Reserve bounded
observation slots during byte admission before any source read.

Open the caller-selected root directory once and anchor traversal to that directory
descriptor. Open each relative directory with `os.open(part, O_RDONLY | O_DIRECTORY |
O_NOFOLLOW, dir_fd=parent_fd)` and the terminal component with `O_RDONLY | O_NOFOLLOW |
O_NONBLOCK` relative to its parent descriptor. Check every descriptor and close it
on all exits. Reject symlinks below the root, non-directory intermediate components,
and non-regular terminal files. A terminal absolute-path open after a chain of
`lstat` checks is insufficient: an attacker can replace a parent between those
operations. Require a deterministic component-swap regression proving the outside
file is never opened. If the host lacks required directory-fd/no-follow support,
return `unavailable/platform_unsupported`; never silently remove the guards.

The lexical relative-path grammar remains exactly that of `tools/portable_handoff`
(`_relative`), including Unicode spelling; do not add NFC rewriting or collapse
invalid traversal/empty segments into accepted paths. Rejecting in-root symlinks
is an explicit stricter filesystem policy than that helper's existing resolver.

Bounds are 65,536 actual bytes per file,80 lines per span,16 files and262,144
aggregate actual bytes per request. Count all bytes read, including any probe;
never read beyond the remaining allocation. Validate regular-file size and strict
UTF-8/no-NUL content under these limits. Failed optional checks leave indexed
items available. Do not emit source text, content digests, absolute paths or raw
exceptions. Freshness never refreshes and never sets publication `STALE`.

V1 is **structural observation only**. There is no `ANCHOR_GUARANTEED_KINDS` table
or `name_not_in_span` change test. Canonical names may be qualified or synthetic:
Python `C.f` need not appear in its `def f` span, Ruby nested names are qualified,
and empty Markdown headings can synthesize a name. Report:

- `changed_observed`: `file_missing` or `span_beyond_eof` in the caller mapping;
- `no_change_observed_with_limits`: `structural_span_only_no_lexical_anchor`, or
  `file_presence_and_utf8_only` when no span exists;
- `not_checked`: not requested, ineligible or allocation exhausted;
- `unavailable`: unmapped/missing root, symlink, unsafe/nonregular file, invalid
  UTF-8, file-size limit, platform limitation or read failure.

These observations prove neither unchanged content nor semantic currency. Any
future producer-specific lexical-anchor or retained-digest policy needs separate
design and evidence. Source excerpts remain outside W4.

---

## 6. Implementation owners, test selectors, and negative test matrix

### 6.1 Planned implementation owners (`REPOMAP-CLOE-CONTEXT1`, `<= 400` lines, target `<= 350`)

- **Product (`src/main/python/common_lore_index/`):**
  - `retrieval/context_contracts.py`
  - `retrieval/intent_policy.py`
  - `retrieval/intent_ranking.py`
  - `retrieval/context_budget.py`
  - `retrieval/context_assembly.py`
  - `retrieval/context_work.py`
  - `retrieval/source_selection.py`
  - `retrieval/advisory_freshness.py`
  - `server/context_read_sqlite.py`
  - `server/context_read_postgres.py`
  - `storage/sqlite_local/context_expansion_queries.py`
  - `cli/_parser_ops_context.py`
  - `cli/ops_context_commands.py`
  - Narrow edits: `cli/parser.py` (calling `add_ops_context_commands(ops_subcommands, add_ops_config_arguments)` alongside `add_ops_lexical_commands` at line 163), `cli/_ops_baselines_dispatch.py` (delegating to `dispatch_ops_context_command` at line 179), keyword-only `role_sql: str = _EVIDENCE_ROLE_SQL` parameter in `storage/sqlite_local/navigation_queries.py`, `storage/sqlite_local/node_location_queries.py`, `storage/postgres_navigation_sql.py`, `storage/postgres_navigation_search.py`, and `storage/postgres_node_locations.py`, plus extracting one public non-paging member-projection helper in `server/_navigation_groups.py`.
- **Tools and test support:**
  - `tools/retrieval_evaluation_context.py`
  - `tools/retrieval_evaluation_context_catalog.py`
  - `src/test/support/python/repomap_test_support/context_fixture.py`
  - `src/test/fixtures/retrieval_evaluation/context-v1/` (reusing `mixed-v1` corpus bytes unchanged plus controlled multi-binding / high-degree / multibyte fixtures).

### 6.2 Exact scoped unit and containerized integration selectors

- **New and regression unit selectors:**
  ```bash
  python3 tools/run_tests.py --suite unit --no-coverage -- \
    src/test/unit/python/repomap_kg/retrieval/context_contracts.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/intent_policy.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/intent_ranking.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/context_budget.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/context_assembly.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/source_selection.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/advisory_freshness.unit.test.py \
    src/test/unit/python/repomap_kg/storage/context_expansion_queries.unit.test.py \
    src/test/unit/python/repomap_kg/cli/ops_context_commands.unit.test.py \
    src/test/unit/python/tools/retrieval_evaluation_context.unit.test.py \
    src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py \
    src/test/unit/python/repomap_kg/cli/sqlite_mcp_transport.unit.test.py \
    src/test/unit/python/repomap_kg/retrieval/lexical_storage_and_navigation.unit.test.py
  ```
- **New and regression containerized integration selectors:**
  ```bash
  python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
    src/test/int/python/repomap_kg/retrieval/context_sqlite_publication.int.test.py \
    src/test/int/python/repomap_kg/retrieval/context_postgres_publication.int.test.py \
    src/test/int/python/repomap_kg/retrieval/context_cli.int.test.py \
    src/test/int/python/repomap_kg/retrieval/advisory_freshness_filesystem.int.test.py \
    src/test/int/python/repomap_kg/retrieval/context_evaluation.int.test.py \
    src/test/int/python/repomap_kg/storage/navigation_search.int.test.py \
    src/test/int/python/repomap_kg/storage/navigation_boundary_contracts.int.test.py \
    src/test/int/python/repomap_kg/storage/postgres_navigation_admission.int.test.py \
    src/test/int/python/repomap_kg/retrieval/postgres_navigation_and_w3_eval.int.test.py \
    src/test/int/python/repomap_kg/storage/sqlite_mcp_transport.int.test.py
  ```

### 6.3 Required negative test matrix

- **Privacy & isolation:** private markers applied and withheld identities (`_destination is None`) never merged; packets and selection files contain zero body text and zero filesystem root paths; MCP tool catalog snapshot and `InvestigationReadStore` unchanged; lexical tables/credentials never touched; default packet (`--freshness none`) succeeds identically after the local source tree is deleted on disk.
- **Stale publication:** pinned `cloe-source-selection-v1` mismatch (`selection_publication_advanced` -> `status="stale"`, zero items); PostgreSQL mid-assembly publication drift across scan units (`publication_advanced_during_assembly` -> `status="stale"`, zero items); SQLite single-transaction snapshot consistency during concurrent publish.
- **Ambiguity & identity collision:** equal-tier top candidates (`exactness_tier`, `affinity_tier`, `match_class_tier`) set `ambiguity.status="ambiguous"` with `tied_top_count` and count budget drops in `ambiguous_alternative_omitted_by_budget`; identical `source_relative_path` across two bindings, two revisions, two snapshots, and a historical run remain distinct locations.
- **Unsupported backend & explicit mode/fallback:** missing `--mode` exits `2`; A PostgreSQL port without depth-one capability in `graph_investigation` without `--fallback-to` returns `unavailable`/`backend_unsupported`; `--fallback-to exact_identity` and `--fallback-to ranked_discovery` (requiring `--query`) populate `FallbackDisclosure`; `literal_captured_text` and `semantic_discovery` return `unavailable`/`capability_not_admitted`; A PostgreSQL port without depth-one capability with `--expand-depth 1` retains seeds and records `expansion_backend_unsupported` (`status="partial"`, exit `3` by default, `0` with `--allow-partial`).
- The built-in PostgreSQL adapter supports depth-one expansion under ADR 0168; unsupported-port refusal cases above use an explicitly incapable port, and do not describe the built-in adapter.
- **Malformed & budget boundary inputs:** CLI non-int string `--budget-bytes` exits `2` (`argparse`); CLI out-of-range integer `< 4096` or `> 65536` and library `bool`, `float`, `str`, or huge `int` (`> 999,999,999` echoed as `budget_bytes: null`) emit `budget_error` (`<= 512` bytes, exit `1`); exactly measure compaction for long query/binding provenance and legal4096-byte requests, admitting either a valid bounded packet or the bounded minimal error; `actual_bytes` self-referential fixpoint converges across the `9,999 -> 10,000` digit boundary without exceeding `budget_bytes`; 4-byte UTF-8 and combining characters landing on `budget_bytes` and `budget_bytes - 1` never slice code points; lone surrogates become `null` (`unencodable_field_withheld`); `> 8` `(binding_id, path_prefix)` pairs refused up front (`scan_unit_limit_exceeded`); `INTENT_DEFAULT_EDGE_KINDS` validated as subset of `CANONICAL_EDGE_KINDS`; `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` matches `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`; scoped selection + `--kind tool` returns `unavailable`/`unlocatable_kind_in_scoped_selection`; scoped selection without `--kind` under `definition` discloses `unlocatable_kind_patterns_excluded`, `unlocatable_kind_pattern_excluded`, and `scope_complete=False`.
- **Expansion & work exhaustion:** high-degree seed hits `--node-limit` / `--edge-limit`; SQLite `set_progress_handler` triggers `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT` and discards partial statement rows; statement ceiling (`36` SQLite / `12` PostgreSQL) and `10,000 ms` deadline yield `status="partial"`; scan unit exceeding `2,000` nodes yields zero ranked items and `candidate_scan_incomplete`.
- **Freshness safety & truthfulness:** Real extractor/canonicalizer cases for qualified Python/JS/Ruby names, empty Markdown headings and synthetic test names remain structurally inconclusive, never false name-based drift. Prove symlink/parent-component swaps cannot open outside files; FIFO/nonregular files, Unicode path parity, exact byte/file/span limits and failed checks preserve indexed items.

---

## 7. Controlled W4 evaluation (`context-v1`), falsification conditions, and coverage target

- **Instrument `context-v1` (`src/test/fixtures/retrieval_evaluation/context-v1/`):**
  - **30 frozen tasks:** 20 calibration tasks and 10 held-out tasks across 9 task families (`definition`, `implementation`, `tests`, `docs`, `messages`, `ambiguous`, `duplicate-path identity`, `relation expansion`, and `budget/multibyte`). **All 10 `context-v1` held-out tasks and all 12 `mixed-v1` held-out tasks remain unexecuted.**
  - **7 arms × 20 calibration tasks × 3 repetitions = 420 observations (`w4-context-calibration-attempt-1`):**
    1. `native_tools_baseline`
    2. `current_graph_navigation_sqlite`
    3. `current_graph_navigation_postgres`
    4. `intent_navigation_sqlite`
    5. `intent_navigation_postgres`
    6. `compact_context_16k_sqlite`
    7. `compact_context_16k_postgres`
  - **Measured metrics:** exact gold locator rank, ambiguity preservation, duplicate-path identity preservation, exact serialized UTF-8 bytes (`<= budget_bytes`), admitted/omitted counts by reason, SQL statements (`<= 36` SQLite, `<= 12` PostgreSQL), edges, labelled SQLite progress-handler estimates, source reads (`0` when `freshness=none`), and raw timing samples. No token-savings, superiority, or p95 claims are made.
  - **Preserved W2/W3 facts:** `w3-calibration-attempt-2` (24 tasks × 6 arms × 3 repetitions = 432 observations, zero execution failures) and all W2/W3 archives remain immutable; proposed future criteria remain unaccepted; the native comparator's `495,781`-byte output above the `65,536`-byte ceiling and the incumbent PostgreSQL graph `0/1` vs SQLite `1/1` absent-answer discrepancy remain named dispositions.
  - **Staging 82% branch coverage margin:** CI104 measured staging integration recorded `81.4%` branch coverage (~130 branches below `100 * covered >= 82 * total` on ~21.3k branches). The new real-boundary integration suites (`context_sqlite_publication.int.test.py`, `context_postgres_publication.int.test.py`, `context_cli.int.test.py`, `advisory_freshness_filesystem.int.test.py`, `context_evaluation.int.test.py`) must close that ~0.6 percentage-point margin through authentic product-boundary execution, never by weakening gates or exclusions.

### What would falsify this specification during `REPOMAP-CLOE-CONTEXT1`

1. Realistic scoped queries routinely exceed `NODE_SCAN_LIMIT = 2,000` candidates, causing `candidate_scan_incomplete` on ordinary navigation tasks.
2. PostgreSQL single-statement navigation parity rows omit `_destination` identity fields required for location deduplication.
3. `sqlite3.Connection.set_progress_handler` fails to bound incident-selective neighborhood scans on high-degree nodes.
4. Any returned packet exceeds its requested byte budget, reports a false actual_bytes value, or a minimal budget error exceeds512 bytes. A legal requested budget that cannot fit required provenance must return the bounded error; it does not authorize omission of required identity.
5. `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` or `classify_subject_intent_family` fails to locate `tests` or `messages` targets under scoped selections in `context-v1`.
6. Calibration shows `cloe-intent-rank-v1` yields zero rank improvement over ascending `canonical_key` order on intent-targeted tasks.

---

## 8. Dispositions of independent review findings and operator decisions (`OD1`–`OD7`)

### Independent plan-review dispositions (`F1`–`F8`, `amend`)

- **F1 (major — direct evidence role for `tests` and `messages` under scoped selections):** Resolved in §3.1–3.2. Clarified that Python test symbols are stored in `canonical_nodes` as `python.{module,class,function,method}` (which already have `direct` evidence and are classified as `python_test_subject` by `cloe-intent-tables-v1`), added isolated `CONTEXT_DIRECT_EVIDENCE_ROLE_V1` in `server/context_read_sqlite.py` and `server/context_read_postgres.py` for `email.*`, `feed.*`, and non-Python test canonical kinds without altering MCP `_EVIDENCE_ROLE_SQL`, wired SQLite depth-1 test-edge traversal, and defined `unlocatable_kind_in_scoped_selection` for kinds outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`.
- **F2 (work and statement accounting across bindings, prefixes, and neighbor locations):** Resolved in §4.2–4.3. Capped total `(binding_id, path_prefix)` pairs at `MAX_SCAN_UNITS = 8` (refusing `> 8` up front with `scan_unit_limit_exceeded`), added a single batched SQLite direct-location query (`batch_neighbor_direct_locations`) for all admitted neighbors, and specified `logical_read_units <= 16`, `MAX_SQL_STATEMENTS_SQLITE = 36`, and `MAX_SQL_STATEMENTS_POSTGRES = 12`.
- **F3 (explicit `--mode`, PostgreSQL fallback target, and mixed surfaces under expansion):** Resolved in §2.1. Required `--mode` on `cloe ops context-pack` and `ContextRequest`, supported `--fallback-to exact_identity` (using `--canonical-key`) and `--fallback-to ranked_discovery` (requiring `--query`) for PostgreSQL `graph_investigation`, and specified per-item `match_surface` (`stored_metadata` on seeds, `graph_topology` on depth-1 neighbors/relations).
- **F4 (initial kind-restricted lexical proposal):** The initial response was superseded by the parent counterexamples and structural-only policy in section5.2; kind-wide literal-name guarantees were false. The descriptor-anchored policy also replaces the initial lstat/absolute-open proposal.
- **F5 (Historical initial-draft response; superseded below: minimum legal budget vs echoed caller strings in skeleton):** Resolved in §4.1. Specified `skeleton_compaction_v1` (withholding oversized `target_echo` and `selected_binding_ids`/`path_prefixes` while keeping fixed-width `target_sha256`, counts, and `selection_fingerprint`), derived `MIN_BUDGET_BYTES = 4,096` from the measured maximally compacted skeleton (`<= 3,072` bytes), and defined the Minimal Standard Request Class (`< 3,584` bytes uncompacted) at `4,096` bytes.
- **F6 (minor — PostgreSQL unbounded neighborhood vs bounded policy refusal):** Resolved in §4.3. Recorded as historical W4 baseline that `storage/sql/neighborhood.py` (live owner: `build_canonical_neighborhood_query_sql` in `storage/sql_canonical.py`) exists for unbounded PostgreSQL neighborhoods and that `expansion_backend_unsupported` was a W4 policy choice to preserve storage-work bounds. The accepted partial W7 amendment is in [cloe-server-parity-v1.md](cloe-server-parity-v1.md); source proof and qualification remain pending.
- **F7 (minor — reuse `_destination` location identity shape):** Resolved in §4.2. Reused the exact `_destination` dictionary keys from `server/_navigation_groups.py` plus `(start_line, end_line)`.
- **F8 (minor — distinct CLI exit code for usable `partial` packets):** Resolved in §2.1. Assigned exit code `3` to usable `partial` packets by default (`0` with `--allow-partial`).

### Independent work-review dispositions (`MAJOR 1`–`3`, `MODERATE 4`–`6`, `MINOR 7`–`10`, closeout)

- **MAJOR 1 (Historical initial-draft response; superseded below: byte-budget contradiction and `actual_bytes` fixpoint):** Resolved in §4.1–4.2 and §7. Derived `MIN_BUDGET_BYTES = 4,096` (`4,096..65,536`, default `16,384`) from the measured full `cloe-compact-context-v1` skeleton (`<= 3,072` bytes maximally compacted; `< 3,584` bytes uncompacted for the Minimal Standard Request Class), defined the 3-step self-referential integer fixpoint for `work_ledger.actual_bytes`, and set `actual_bytes: 2674` in the §4.1 example to match its exact compact UTF-8 byte length.
- **MAJOR 2 (nonexistent edge kinds in `cloe-intent-tables-v1`):** Resolved in §3.2 and §6.3. Replaced all non-canonical edge kinds with canonicalizer-backed members of `CANONICAL_EDGE_KINDS` (`graph/edge_kinds.py`), including `defines`/`references` for `messages` (`email_family.py`, `feed_family.py`), `contains`/`defines`/`embeds`/`links_to`/`references`/`styles` for `docs`, and `calls`/`contains`/`declares`/`defines`/`depends_on`/`exposes_script`/`imports`/`includes`/`loads`/`method_of`/`references`/`replaces_module`/`requires_module`/`sources`/`workspace_uses` for `definition`/`implementation`, enforced by a module-load subset assertion and unit test.
- **MAJOR 3 (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1` raw kinds and link kinds for Bats/ZUnit):** Resolved in §3.1. Matched actual canonicalizer raw kinds (`bats.test_case` in `shell_bats_family.py:84,269`; `zunit.test_case` in `shell_zunit_family.py:119,365`) and included `inferred_from_edge` child definition links emitted by `_append_two_node_edge` (`canonicalization/_shell_edge_helpers.py:57-70`) before the fallback `reference` branch.
- **MODERATE 4 (`contains` in `tests` edge set and §4.2 relation example):** Resolved in §3.2 and §4.2. Added `contains`, `defines`, `refutes`, `expects`, `has_assertion`, `has_hook`, `loads`, `imports`, and `references` to the `tests` edge set and updated the §4.2 relation example to use a real `bats.file` -> `contains` -> `bats.test_case` edge (`shell_bats_family.py:272`).
- **MODERATE 5 (scoped truthfulness and derived `DIRECT_LOCATABLE_CANONICAL_KINDS_V1`):** Resolved in §3.1 and §4.1. Added `nix.check`, `email.address`, `bats.expectation`, and `zunit.{hook,assertion,expectation,command_under_test,mock,stub}` to `CONTEXT_DIRECT_EVIDENCE_ROLE_V1`, derived `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` programmatically from the role table, and required `scope.unlocatable_kind_patterns_excluded`, `omission_counts.unlocatable_kind_pattern_excluded`, and `scope.scope_complete=False` whenever any active candidate kind in a scoped scan is outside `DIRECT_LOCATABLE_CANONICAL_KINDS_V1` (even when `--kind` is omitted).
- **MODERATE 6 (CLI registration and dispatch owners):** Resolved in §6.1. Replaced the nonexistent `cli/ops_parser.py` and `cli/ops_commands.py` references with `cli/parser.py` (line 163) and `cli/_ops_baselines_dispatch.py` (line 179).
- **MINOR 7 (`budget_error` echo bounds and CLI string budget exit code):** Resolved in §4.1 and §6.3. Bounded `budget_error.budget_bytes` to integers in `-999_999_999..999_999_999` (else `null` with `reason="invalid_budget_type"` or `"budget_out_of_range"`), keeping `budget_error <= 512` bytes, and distinguished CLI non-int string budgets (`argparse` exit `2`) from CLI out-of-range integer budgets and library non-int budgets (`budget_error` exit `1`).
- **MINOR 8 (selection revalidation read accounting):** Resolved in §4.1, §4.3, and §5.1. Added `config_revalidations_executed` to `work_ledger`, counted selection/accepted database readback in `logical_read_units` (`<= 16`) and SQL statement ceilings, and set `MAX_SQL_STATEMENTS_POSTGRES = 12`.
- **MINOR 9 (`NavigationSearchQuery` reuse and query/offset bounds):** Resolved in §2.1 and §2.3. Reconciled `--query` (`1..200` stripped Unicode chars, `<= 800` UTF-8 bytes) and `--offset` (`0..1,000` subset of `0..10,000`) with `NavigationSearchQuery` (`storage/navigation_search.py:32-42`) and specified reuse of existing SQLite and PostgreSQL navigation/location query owners via `role_sql: str = _EVIDENCE_ROLE_SQL`.
- **MINOR 10 (`binding_revision` type and `snapshot_manifest_id` provenance):** Resolved in §1, §2.3, §4.1, and §5.1. Changed `cloe-source-selection-v1` `revision` to `int >= 1` (`_navigation_groups.py:24`), replaced `source_runs` references with `runs` / `public.runs`, and specified run-level `runs.snapshot_manifest_id` vs per-binding `(binding_revision, snapshot_id)` from `runs.snapshot_vector_json`.

### Deferred choices and parent-owned acceptance decisions (`OD1`–`OD7`) and rollback

- **OD1:** Whether a metadata-only read-only MCP context tool follows W4 calibration (proposed: no in W4).
- **OD2:** PostgreSQL bounded incident-selective neighborhood parity remains a W7 concern, not a W4 closure. ADR 0168 accepts the bounded Epics 1 and 2 design in [cloe-server-parity-v1.md](cloe-server-parity-v1.md) §2; source proof and qualification remain pending.
- **OD3:** Whether a per-binding explicit opt-in to use the configured `root_path` for advisory freshness is acceptable (proposed: require explicit `--source-root BINDING=ABS_PATH` in W4).
- **OD4:** Whether a future milestone admits bounded caller-local source excerpts under P1 public-dev policy (excluded from W4).
- **OD5:** Accepting [ADR 0133](../adr/2026/11/0133-intent-aware-navigation-and-bounded-context.md), its initial limits (`4,096..65,536` bytes, `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT`, `10,000 ms` deadline), and the `context-v1` task/arm declaration before `REPOMAP-CLOE-CONTEXT1`.
- **OD6:** Future criteria acceptance and held-out execution for both `mixed-v1` (12 tasks) and `context-v1` (10 tasks).
- **OD7:** Any `REPOMAP-CLOE-CONTEXT1` hosted CI campaign or build allocation.
- **Rollback:** A forward corrective phase follows existing retention and exact scope-retirement procedures. Preserve all published authority/cohort prefixes and numerical debt; never delete historical admission rows or reset a baseline/genesis. No schema migration or history rewrite is involved.


## Parent resulting-state corrections before implementation

The initial dispatcher completed both independent checkpoints but its closeout
terminal was invalid JSON framing; APGR refused auxiliary repair. Its prose is
not phase acceptance. The parent retained all three document preimages, verified
cleanup and preserved source/index custody, then made these corrections for fresh
independent review. Existing W2/W3 archives, criteria and debt remain untouched.

- Wire backend values reuse QueryScope: `sqlite` / `postgresql`; `sqlite_local`
  remains an implementation module name. QueryMode and MatchSurface stay unchanged.
- Configured adapters bind graph, repository and backend to actual accepted-store
  readback. A caller flag or selection fingerprint is never accepted-store proof.
  Compare the complete existing AcceptedPublicationReference identity (graph,
  repository, backend, run, bundle, job, attempt, generation) and additionally any
  asserted manifest/extraction-receipt IDs and unique binding/revision/snapshot
  vector entries. Missing required pin provenance gives an explicit unavailable
  result; do not manufacture it. Untrusted selection JSON cannot set trusted_caller.
  Config establishes source_definition_id/selection_policy_id; the accepted vector
  establishes revision/snapshot. Never equate generation counters across backends.
- Context-only metadata projections and role overrides are internal trusted code
  inputs. Their defaults must preserve the legacy MCP payload field sets and role
  behavior exactly, including accepted_publication's existing three fields. Test
  serialized payloads as well as the tool catalog. Extra context identity fields
  must be opt-in/internal, never leak through unchanged default query owners.
- SQLite progress reports are labelled estimates (`callbacks * configured interval`),
  not exact executed VM-instruction counts. Report callback counts/interval and
  actual statements; stop at the approved callback allocation per statement plus
  deadline. Account for config/identity/selection reads in the work ledger.
- Freshness reserves its worst-case bounded observation bytes before source opens,
  uses descriptor-anchored traversal and structural-only evidence as section5.2.
- Initial reviewer-disposition measurements describe their actual draft fixtures,
  not universal size proofs. Every final packet and minimal error is remeasured.
- OD5 is parent design acceptance under the current human-approved W4 continuation,
  following fresh independent review. OD7 is a later parent-bound single milestone
  campaign under the standing staging authority, never an automatic retry. OD1-4
  and OD6 remain deferred choices; none is needed to implement the bounded CLI/
  library scope. No new human permission gate is inferred from proposal wording.


### Exact pin and measurement clarifications

Selection graph/repository/backend must match configured accepted-store identity.
The non-null expected_publication is a full pin: generation, accepted_run_id,
publication_bundle_id, job_id, attempt, snapshot_manifest_id and
extraction_receipt_id. Map generation to AcceptedPublicationReference.accepted_generation,
accepted_run_id to run_id, and job/attempt to stored publication_job_id/
publication_attempt. Revalidation compares every field and each pinned binding's
revision/snapshot; do not reduce a full pin to labels. Missing full pin provenance
is unavailable. Unpinned selections keep expected_publication and snapshot_id null
and follow the current accepted state while revalidating config policy fields.

SQLite work_ledger.sqlite_progress_callbacks and sqlite_progress_interval_ops are
observations/configuration. sqlite_vm_steps_estimate is their product, explicitly
an approximation, never an exact instruction count. Required provenance is never
removed for a universal headroom promise. The updated example is remeasured by
the parent; earlier numeric examples in historical review dispositions describe
their original draft only.


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
roadmap continuation. OD7 remains a later parent binding of one milestone
campaign. MCP additions, configured-root shortcuts, excerpts and
held-out/criteria acceptance remain deferred. ADR 0168 is parent-accepted for
the bounded PostgreSQL parity and truthful-refresh Epics 1 and 2; its source
proof and whole-candidate qualification remain pending. Epic 3's startup-option
timeout remains rejected/held and is not an accepted W7 closure.



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


### Independent-review correction clarification

Owned SQLite reads use the canonical read-only transaction manager and the full
configured graph binding. Fixed storage preflight is separate from the36 context
product-statement ceiling. Ordinary database/schema failures are unavailable;
only actual ledger-induced interrupts are exhaustion. Context historical vectors
are validated before normalization or scoped admission. Final empty-envelope
sizing includes post-work omissions before any freshness read.

Where LF-based and splitlines-based conventions disagree about whether the
requested span exceeds EOF, advisory freshness returns `unavailable` with reason
`line_semantics`. It preserves structural verdicts where both conventions agree.
Generated SQLite and PostgreSQL fixture content is identity-bound, not archived
as database-content proof; source/native-manifest custody is
`fixture_manifest_only`.

Omission counters retain their category units: field-withheld observations count
inspected formatted fields, limit counters count encountered limit events, and
output-budget counters count considered output admission units (including atomic
neighbor/first-relation units). Categories can overlap and do not form a distinct
node/edge cardinality total. Incomplete-scan counters mark uncertain scan units;
their partial status never asserts a complete global result.


### Accepted partial W7 amendment: PostgreSQL bounded expansion parity (ADR 0168)

Status: parent-accepted for ADR 0168 Epics 1 and 2; implementation proof and
whole-candidate qualification remain pending. W4 behavior above remains the
historical baseline, and no W7 closure is claimed.

Under `REPOMAP-CLOE-SERVER-PARITY1`
([ADR 0168](../adr/2026/11/0168-bounded-server-context-and-refresh-outcomes.md),
[cloe-server-parity-v1.md](cloe-server-parity-v1.md)), OD2 and F6 are amended
forward. The historical W4 records, ADR 0133 and the retained
`w4-context-functional-attempt-7` artifacts are not altered.

- A private port capability replaces the two backend checks in
  `build_compact_context` and `execute_scans_and_pack`. The built-in PostgreSQL
  adapter has the capability. Ports without it keep `backend_unsupported`, the
  explicit `FallbackDisclosure` and `expansion_backend_unsupported`.
- `PostgresContextReadAdapter.expand_seeds_depth1` returns the existing consumer
  shape (`ok`/`partial`/`stale`/`unavailable`) from one statement. The packet
  builder treats expansion `stale` as a stale packet
  (`publication_advanced_during_assembly`).
- Limits are unchanged:
  - `MAX_SQL_STATEMENTS_POSTGRES = 12`, `MAX_LOGICAL_READ_UNITS = 16`;
  - 5 seeds, 64 edges per seed, 128 neighbors and 256 relations;
  - `EVIDENCE_SCAN_LIMIT = 10,000` plus a 1-row lookahead.
- Consistency remains `per_statement_identity_checked`. Physical work and
  whole-request latency are not bounded by these limits.
- Relation deduplication during expansion follows selected RD-2(a)
  ([cloe-server-parity-v1.md](cloe-server-parity-v1.md) §2.7): both backends
  use this specification's 4-tuple relation identity
  `(source_key, edge_kind, target_key, identity_metadata_hash)`. The prior
  SQLite hash-only behavior and RD-2(b) are rejected-alternative history.
- The ADR 0168 startup-option server statement-timeout proposal remains
  rejected/held under RD-1. Existing between-statement ledger checks remain;
  no startup-option timeout or additional W7 authority is implied.
