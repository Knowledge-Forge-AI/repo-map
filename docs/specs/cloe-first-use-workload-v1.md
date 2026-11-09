# CLOE first-use workload and evidence contract v1

Status: parent-accepted design under [ADR 0180](../adr/2026/11/0180-reproducible-first-use-workloads-and-evidence.md);
independently reviewed with the refusal-classification correction accepted by the parent.
Implementation and final source acceptance are separate.
Phase `REPOMAP-CLOE-FIRST-USE-WORKLOAD1`. Source parent `cc6c91e1e4170d2775540945e5996d734bc0800e`.
Paths are repository-relative; line facts describe the source parent and are re-read before editing.

## 1. Verified source facts

| Owner | Fact relied on |
|---|---|
| `src/test/support/python/repomap_test_support/retrieval_evaluation_fixture.py` | `MIXED_V1_BINDINGS = (core, companion, feeds, mailbox)` (20). The fixture root is `src/test/fixtures/retrieval_evaluation/mixed-v1` (21–23). `materialize_mixed_v1_working_copy(target, generation=1\|2)` removes its target, copies the four alias trees, writes the `python-sources-v1.json` sources (with generation-2 overrides and the deletion) and generates six companion edge files (88–122). `compute_working_copy_digests` returns `sha256:` and the size per `(alias, rel)` (125–143). Companion has `exclude_paths=["excluded_cache"]` (223) |
| `.../governance3_first_use_sealing.py` | `mixed_inventory(working_copy, aliases=MIXED_V1_BINDINGS)` filters to the given aliases and excludes `companion/excluded_cache` (27–37). `manifest_for_pin(home, pin)` reads the single retained attempt matching the pin's manifest, job and attempt, and returns the manifest and its byte length (40–65). `assert_v2_sealing_counts`: `total = sum(size)` over entries, collision bytes `total − sum` over unique digests; read `4S+C+m`, copy `S`, capture `2S`, store `S+C+m`, write `S+m`, discovery/classification `0` (78–98). `assert_planned_refusal`: `4S+1`, limit `4S`, `worker_launches` 0 (101–114). `assert_mixed_snapshot_equivalence` checks against `scan_multi_source_generations` (117–130) |
| `docs/specs/cloe-resource-governance3-v1.md` §5.6 | `S` is the sum of `s` over canonical selected files. `C` is the bytes of puts whose digest already exists. `m` is the manifest bytes. `m_c = m` only when the manifest put collides. `r` is the bytes of failed R5 attempts. New read total: `4S+C+m+m_c+r` |
| `ops/first_use_local.int.test.py` | Guarded `LocalHarness(..., block_psycopg=True)` children run `sqlite-init`, `refresh-graph --json`, `context-select --pin-publication`, `context-pack`, `--resource-report F --resource-report-schema 2` and `resource-report check`. `--sealing-max-read-bytes 4S` exits 1 with stderr `ERROR: sealing-budget-exceeded:planned_read_bytes`, and the pin is kept. In-process `refresh_local_graph(config, graph, resource_observer=...)` raises `ValueError` on a missing root. A pin packed after a new generation is `stale` / `selection_publication_advanced` |
| `ops/first_use_server.int.test.py` | Declares only `core` and `companion` (`declared_aliases`, `mixed_inventory(..., ("core", "companion"))`). Uses `temporary_postgres()`, `apply_migrations` and `refresh_graph(..., resource_observer=ResourceObserver(report_schema="cloe-resource-view-v2"), sealing_budget=SealingBudget(max_read_bytes=...))`. A refusal is `failure` / `resource_budget_exceeded` / `not_started`. Lexical build, query and revoke run observed. A hit has `locator.source_relative_path == "pkg/pipeline.py"`. After revoke, the result is `UNAVAILABLE` / `projection_absent` |
| `ops/first_use_mixed.int.test.py` | Feeds and mailbox lexical builds refuse with an `ExclusionReason` privacy or retention value and `plan=None`. An empty selection raises `binding-selection-required`. Locations use `CONTEXT_LOCATION_KEYS` |
| `common_lore_index/ops/resource_reports/_codec.py` | `encode_report` and strict `decode_report`. File bounds are 8,193 bytes (v1) and 16,385 bytes (v2). Categories are closed and path-free |
| `common_lore_index/ops/resource_view/_canonical.py`, `ops/sealing_plan.py` | `canonical_bytes(payload, max_bytes)` and `parse_digits`. `cloe-sealing-plan-v1` with `MAX_PLAN_BYTES = 4096`. Its `planned_min_read_bytes` is a `derived_lower_bound`, from a metadata-only read |
| `common_lore_index/artifacts/sealing_governance.py` | `MAX_COUNTER = 2**63-1`. `SealingBudget` defaults to no budget |
| `tools/test_sandbox_contract.py`, `tools/test_sandbox.py` | `active_sandbox()`. The repository is mounted read-only; only `/var/lib/docker`, `/sandbox-scratch` and `/run` are tmpfs (132–139). `INNER_REPORT_ROOT = /sandbox-report/report`. Export bounds: 4,096 members, 64 MiB content, 72 MiB archive (25–29) |
| `tools/test_sandbox_arguments.py` (257–283), `tools/test_sandbox_report.py` | Only `--report` (or the D12 preflight) maps `--report-dir` to the inner root; otherwise nothing creates it. Export accepts regular files and directories, and refuses unsafe paths, duplicates, oversize archives and an existing destination |
| `tools/runner_integration_execution.py` (27–39), CI workflow (265–277) | `candidate_identity` = git `HEAD` plus `source_sha256` over `src/main`, `src/test`, `tools`, `pyproject.toml`. Hosted staging runs `--suite staging --sandbox --report`, so CI137 exports any bundle in its staging artifact |
| `tools/test_report.py` (113–131), `src/test/unit/python/tools/` | `write_html_report` writes `report_root/<suite>/latest` without clearing siblings. Tool unit owners import tools by top-level name |

## 2. Boundaries

Real execution runs only in the canonical integration sandbox, on
pytest-owned paths, the guarded harness and `temporary_postgres`; there is no
live, installed, private, default or network target. Witnesses read only the
fixture, the materialized copy, owned homes and stores, and call results.
They run no extra product SQL, and no expected value comes from a report or
plan. Evidence is never graph input and cannot alter publication, pins or
reports; product codecs only decode. Evidence holds no absolute path, host,
port, database name, user, password, environment value, body, snippet, or
query text beyond recipe constants. Aliases come from the closed `mixed-v1`
set; relative paths and digests must be census members.

## 3. Owned source and test layout

New Python owners target 350 lines; each stays at or under 400. Focused
helper modules may split the named first_use_workload families where needed;
all new owners stay within those families and enroll cleanly.

| Path | Responsibility |
|---|---|
| `tools/first_use_workload.py` | CLI with `plan`, `check` and `show`. Exit codes: 0 accepted, 1 rejected or incomplete, 2 usage or unreadable |
| `tools/first_use_workload_recipe.py` | Frozen recipe (§4) and `recipe_digest()` |
| `tools/first_use_workload_census.py` | Plain `hashlib` `fixture_digest` and census digest; census codec; freeze-file comparison (§5) |
| `tools/first_use_workload_records.py` | Closed vocabularies and strict codecs for intent, observation, index and verdict |
| `tools/first_use_workload_bundle.py` | Exclusive writer and bounded non-following reader (§6.4) |
| `tools/first_use_workload_rules.py` | Per-action fact rules and witness arithmetic (§8) |
| `tools/first_use_workload_reconcile.py` | Pure reconciliation and verdict (§9) |
| `src/test/support/python/repomap_test_support/first_use_workload_driver.py` | State machine, spans, CPU scope, cleanup registry and bundle location (§7) |
| `.../first_use_workload_local_steps.py`, `.../first_use_workload_server_steps.py` | Step adapters over `LocalHarness`, in-process Local refresh, `temporary_postgres`, `refresh_graph` and the lexical services |
| `.../first_use_workload_witness.py` | Witnesses that wrap `governance3_first_use_sealing`, plus attempt-root freshness, pin and location facts |
| `src/test/fixtures/first_use_workload/mixed-v1-census-v1.json` | Frozen census |
| `docs/ops/first-use-workflows.md` | New section on workload reproduction and `check` |
| `tools/ci/cloe-first-use-workload1-exit.md` | Exit record: selectors, results and acceptance boundaries; the exact-commit private report binds final owned-file SHA-256 and physical line counts |

Tools may import the product leaves `_canonical` and `_codec`, but never
`repomap_test_support`. Support imports tools by top-level name, as
`resource_report_cli_files.py` already does for `runner_coverage_observer`.
A unit guard asserts that no `common_lore_index` module imports
`first_use_workload*` or `repomap_test_support`. New owners enroll through the same ownership and quality enrollment records
that admitted the governance3 owners; the exit record names them. If
`tools/` falls outside the incumbent Ruff, mypy and length roots, stop rather
than add a root.

## 4. Recipe

The code-owned recipe is the following exact ordered catalog. Local uses
all four aliases, Server only `core, companion`, and mixed all four on each
backend. Every row records one explicitly declared action; a compound action
executes only its listed calls in the listed order, each once. Setup is in
`prepare_ns`; listed owner calls are in `call_ns`; witness work is in
`observe_ns`; owned cleanup is in `cleanup_ns`. No operation is unrecorded.
Every row is required. `sub=0` except Server11, which emits sub0,1,2 in order.
No limits are supplied except the explicit `4S` planned-refusal actions.

| Step | Local action and calls | Server action and calls | Mixed action and calls |
|---|---|---|---|
| 1 | `census_verify`: prepare g1 copy, compare frozen inventory | same | same |
| 2 | `sqlite_init`: guarded CLI init | `migrate`: owned PG migration | `sqlite_initial`: CLI init, cold refresh |
| 3 | `sealing_plan`: CLI plan JSON | `sealing_plan`: plan | `postgres_initial`: prepare PG/migrations, cold refresh |
| 4 | `refresh_cold`: CLI refresh with v2 report | `refresh_cold`: in-process refresh, v2 observer | `snapshot_equivalence`: check each home's retained manifest against incumbent scan |
| 5 | `pack_current`: select pinned publication, hide sources, pack, restore sources | `pack_current`: select pin, pack | `pack_mixed`: packs for implementation, docs, messages on each current pin |
| 6 | `refresh_repeat`: unchanged-tree refresh | same | `pack_subset`: select core only, pack on both backends |
| 7 | `refresh_generation`: prepare g2 copy, refresh | same | `privacy_refusal`: remove feeds/mailbox roots, attempt feeds lexical build on PostgreSQL |
| 8 | `pack_stale`: pack with g1 selection | `stale_investigation`: stale pack, graph investigation using a canonical key | `cleanup` |
| 9 | `planned_refusal`: CLI refresh with `--sealing-max-read-bytes 4S` | `planned_refusal`: refresh with `SealingBudget(max_read_bytes=4S)` | — |
| 10 | `missing_refusal`: prepare missing companion, in-process Local refresh | `lexical_build`: core/companion | — |
| 11 | `refresh_recovery`: restore g2 companion, refresh | `lexical_query`: sub0 symbol, sub1 g2 marker, sub2 absent old token | — |
| 12 | `replay_refresh`: prepare one retained after-commit attempt, replay refresh | `lexical_revoke`: revoke, query absence | — |
| 13 | `cleanup` | `cleanup` | — |

Server step2 enters temporary PostgreSQL and writes its home in preparation;
the listed migration is the call. Mixed step3 includes migration among its
listed setup calls. Backend is `sqlite` for every Local row and `postgresql`
for every Server row. Mixed row2 is `sqlite`, row3 `postgresql`, and rows1,
4–8 `mixed`; per-backend fact objects remain distinct. These values describe
only this evidence format, never a new product/resource-report backend.

There are exactly13 Local,15 Server and8 mixed observations. The recipe
contains literal scenario/backend/action/sub/alias tuples, expected outcome
codes and resource-operation labels taken from current owner contracts;
these are constants, never copied from current output. Mixed compound rows
retain distinct per-backend facts. Refusal codes are Local
`sealing-budget-exceeded:planned_read_bytes`, Server
`resource_budget_exceeded`, missing-root `local_value_error` (type only),
and privacy `ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value` or
`ExclusionReason.RETENTION_NOT_AUTHORIZED.value` as the current policy permits.

Pins are independently read before and after calls. A refusal preserves the
whole pin digest; cold publication starts at generation1; each ordinary
repeat, generation-change and recovery publication increments the prior
generation by exactly1. Direct capture selects a new operation identity per
call (`portable_refresh.capture_portable_candidate`); incumbent Local recovery
also publishes after restoring unchanged g2 bytes. Deviations are findings,
not reasons to tune the oracle. Replay preparation itself commits one armed
generation: its preparation pin is prior generation+1; the replay call leaves
that pin unchanged and returns `reconciled_replay`, without a new publication.
Use the existing `resource_view_local.int.test.py` arming technique without a
new abrupt declaration; preserve incumbent assertions and child-environment
measurement handling. All new maintained children use existing authoritative
environment/admission helpers; no ambient coverage copy is introduced.

Manual locations come from public fixture text, all in core:
`RetrievalExecutionPipeline` → `pkg/pipeline.py`;
`GEN2_EXTENSION_ACTIVE_MARKER_2026` → `pkg/gen2_extension.py` (g2 only);
`LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN` is absent from g2. Context keeps
`shared/status_codes.py` alias-qualified. These are fixture readback checks,
not scientific task/evaluation claims. Lexical calls occur only on PostgreSQL;
graph investigation must not return `backend_unsupported`. A required runtime
skip is `skipped/runtime_unavailable`, giving an incomplete verdict.

## 5. Census and intent

`cloe-first-use-census-v1` is committed canonical JSON. Its `fixture_digest`
is SHA-256 over the sorted `(rel, sha256, size)` of the four alias trees and
`python-sources-v1.json`. For generations 1 and 2 it holds entries
`[alias, rel, "sha256:<hex>", size, selected]`, where `selected` is false
only under `companion/excluded_cache/`, and `bytes_total`. For an alias set,
`S` is the sum of selected entry sizes (digest duplicates included), `C` is
`S` minus the size sum over unique selected digests, and `files` is the
selected entry count; each is stored per generation for both §4 alias sets.

The fixture digest binds committed fixture inputs, not the six generated
companion files. Their generator is bound by the full candidate census; their
actual output is bound by the frozen materialized inventory and census digest.
Host check detects generator source drift as candidate_mismatch; support-side
comparison detects unexpected generated output as stale_input.

The driver and a support unit test recompute materialized inventories with
`compute_working_copy_digests`; in `census_verify` any difference refuses as
`stale_input` before execution. The tool cannot import support, so it
recomputes only `fixture_digest` and the census digest. Refreezing after a
fixture change is an explicit, reviewed change; old trials are never rewritten.

`cloe-first-use-intent-v1` holds `recipe_digest`, `census_digest`,
`fixture_digest`, the flat ordered step catalog, `product_digest` and
`candidate_census`. The product digest binds all regular files under
`src/main` and `pyproject.toml`, excluding bytecode/cache directories. The
candidate census uses the exact `candidate_identity.source_sha256` algorithm:
Git-listed tracked/nonignored files under `src/main`, `src/test`, `tools` and
`pyproject.toml`, sorted by raw relative filename, each followed by NUL and
the binary SHA-256 of its bytes, then hashed. It binds all product, tool,
support and test owners; no narrow subset substitutes for it.

Canonical source hashing may read task/gold bytes only as opaque integrity
input. Workload fixture census, materialization, expectations and queries do
not parse or use task catalogs, golds, held-outs or old trials. An open-spy
test isolates the fixture-census path from this separate canonical hashing.
`declared_source_parent` is informational40hex/null, not commit authority.
Precommit proof binds actual bytes without a future commitSHA; the parent's
exact-commit private report later bridges those bytes to the reviewed tree/commit
and records final owner hashes and physical line counts without recursively
hashing the exit record. The driver recomputes identity before and after its
run; drift rejects the evidence. Host `check` of hosted evidence must use the same-attempt
staging `candidate_identity.source_sha256` and recorded merge commit/tree. A
staging head is valid only when its complete candidate census equals that
reported executed tree; otherwise obtain the exact recorded tree. Never repin
an artifact or weaken the check; if the exact tree is unavailable, hosted
acceptance remains pending. Fixture census generation is support-owned; the
pure tool validates only the frozen census and fixture digest, without
duplicating the working-copy generator or importing test support.

## 6. Evidence formats and bounds

Every record is `canonical_bytes` JSON plus exactly one LF. It must re-encode
to identical bytes, have no duplicate keys and only its schema's closed key
set, and nest no deeper than6 containers (root is depth1). The flat step catalog
and per-backend facts fit this bound. JSON integers require `type(value) is
int`, are nonnegative and at most `MAX_COUNTER`; they are never coerced from
bools/strings. `parse_digits` is for CLI digit arguments only. Floats are
refused, and booleans appear only in declared witness fields.

### 6.1 Observation (`cloe-first-use-observation-v1`)

| Key | Content |
|---|---|
| `attempt`, `intent` | 32 lowercase hex from `secrets.token_hex(16)`, one per scenario run; the intent digest |
| `scenario`, `backend`, `step`, `sub`, `action` | From the recipe. `(step, sub)` strictly increases |
| `expectation`, `result` | `result` is one of `pass`, `expected_refusal`, `failure`, `skipped`, `unavailable` |
| `refusal`, `reason` | Closed owner code, and closed skip/unavailable reason; each may be null |
| `spans` | `prepare_ns`, `call_ns`, `observe_ns`, `cleanup_ns`: `time.monotonic_ns` deltas in the test process; null if not reached |
| `cpu` | `parent_process_ns`: `time.process_time_ns` delta for all test-process threads, excluding descendants, PostgreSQL and Docker. `waited_descendants_ns`: `RUSAGE_CHILDREN` utime plus stime delta over the call span, covering all descendants reaped by the test process in it (CLI children, `psql` and harness helpers); grandchildren count only if their own parent waited. Either may be null |
| `facts` | Closed per-action object (§8) |
| `members` | Sorted `[name, sha256, size]` for referenced report and plan members |

There are no keys for peak RSS, PostgreSQL CPU or memory, or physical I/O.

### 6.2 Index and verdict

`intent.json` holds the exact canonical intent. Observations are named
`observation-SS-U.json` (two-digit step, one-digit sub), report members
`reports/report-SS-U.json` and plans `plans/plan-SS-U.json`. All references
use these literal relative component forms; no arbitrary path is accepted.

`index.json` (`cloe-first-use-bundle-v1`) lists every payload member as
`[name, sha256, size]`, sorted by name, with `scenario`, `attempt` and the
intent digest. Payloads are intent, observations, reports and plans only.
The index EXCLUDES itself and `verdict.json`. The only unindexed files
permitted are those two control files. Root/child enumeration must equal
that exact union; no extra file/directory is silently ignored.

`verdict.json` (`cloe-first-use-verdict-v1`) contains the recomputed outcome,
per-result counts, closed categories and SHA-256 of final index bytes. The
DAG is payloads → index → verdict; there is no circular digest. All three
stages are exclusive writes in that order. Missing controls or incomplete
writes give `incomplete`; an old stored verdict never supplies acceptance.
`check` recomputes the verdict from payloads/current intent and compares it
with stored bytes. Semantic categories are still collected when a mutated
copy has a stale verdict, so negative tests can assert category membership.

### 6.3 Bounds and basis

| Bound | Value | Basis |
|---|---|---|
| Observation | 8,192 bytes | Bounded pin hashes, at most32 public location refs of ≤96 UTF-8 bytes, phase counters and member refs; no bodies |
| Report / plan member | 8,193 or 16,385 / 4,097 bytes | The existing v1/v2 file bounds and `MAX_PLAN_BYTES`, plus LF |
| Observations per scenario | 24 | 13 rows plus Server row 11's expansion gives at most 15; about 1.6× headroom |
| Census | 1,024 entries per generation; 786,432-byte file | At most 360 bytes per entry, with `rel` at most 255 UTF-8 bytes. The exit records the observed count; freezing stops if the bound is under 4× that count |
| Committed fixture collection | 2,048 directory/file entries; 786,432 bytes per input and canonical row array | Current inputs are 14 files and 17,356 bytes; excess collection or serialization returns a closed refusal |
| Intent, index, verdict | 65,536 bytes each | Up to 128 index rows of at most 400 bytes each, plus fixed keys |
| Bundle | 128 members and 2 MiB per attempt; 3 attempts | 24 × (8,192 + 16,385 + 4,097) < 690 KB, below2MiB including controls. At most 384 members and 6 MiB are added to an export whose 4,096-member / 64 MiB / 72 MiB-archive budget is shared with the existing report (coverage HTML in hosted staging); §12 stops if the measured CI136 staging artifact plus this addition exceeds 75% of any bound |

### 6.4 Bundle custody

The bundle lives at `<base>/first-use-workload/<scenario>-<attempt>/`. The
base is `INNER_REPORT_ROOT` only when `active_sandbox()` is true and that
root already exists as a euid-owned, non-symlink directory (that is, under
`--report`); the driver then creates only the `first-use-workload` child,
mode 0700. An absent inner root selects the pytest temporary directory; an existing
unsafe inner root refuses, rather than silently falling back. The driver
never creates `/sandbox-report`. The writer creates the bundle directory with an exclusive `mkdir`. It opens
members with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600, and writes them fully
and bounded. It never overwrites, renames over or deletes, and writes the
index and verdict last. An interrupted write leaves the bundle `incomplete`;
it is never repaired.

The reader anchors the selected root with an owned, non-symlink directory
descriptor and traverses `reports`/`plans` using descriptor-relative
`O_DIRECTORY|O_NOFOLLOW` opens. Member opens are relative to those held
descriptors with `O_NOFOLLOW|O_NONBLOCK`; before/after `fstat` verifies
regular type, identity/version, ownership, mode and bounded size. Unsupported
descriptor anchoring is an explicit refusal, not a path-following fallback.
Leaf components must match the exact forms above (ASCII lowercase/digits/
hyphens plus `.json`); slash is allowed only between the two known directory
names and their declared leaves. Reject symlinks in any component, special
files, group/other-writable files, duplicate/unknown names and extra directories.
Limits cover control files too. No data file is opened before path/type/size
admission, and encoded control data is checked before trusting any member name.

### 6.5 Shared export disposition

Authenticated CI136 staging ZIP metadata has7members and18,301,666
uncompressed bytes. Three maximum bundles add384members and6,291,456bytes:
391members and24,593,122bytes combined, below75% of existing member/content
bounds. Even allowing4KiB framing per member leaves ample72MiB archive
headroom. This is a forecast, not qualification of CI137's final archive.
Current export accepts bounded regular-file trees and the staging validator
reads its named contract; the added tree changes no schema or gate. The
hosted staging artifact will include these bundles. Exact host export/check
proof and unchanged canonical final export enforcement remain required.

## 7. Execution and cleanup state machine

Each step moves through `pending → preparing → calling → observing → cleaning
→ recorded`; each scenario through `intent_built → census_verified → rows
recorded → scenario_cleanup → bundle_written → reconciled`.

1. **Preparing** (materialize, enter `temporary_postgres`, write the home,
   arm a replay, snapshot a pin) is timed into
   `prepare_ns`.
2. **Calling** performs only the cataloged owner call(s), once in declared order.
   `expected_refusal` requires the exact recipe-declared raised exception type,
   returned result/refusal code, or CLI exit status plus stderr code. Thus Local
   planned refusal is exit1 plus its fixed stderr code; Server is the returned
   failure/resource-budget/not-started tuple; privacy is returned refused plus
   its fixed policy code; missing-root is the raised ValueError type. A
   nonmatching return, exception or code is `failure`. Nothing is retried.
3. **Observing** runs witnesses that never change the call's result. A
   witness `Exception` is `failure` with reason `witness_failed`.
4. **Cleaning** touches only resources this attempt registered, in reverse
   order, once per callback. A failed early release retains a bounded failure
   label and is never retried. The final recipe `cleanup` row is unconditional:
   its registered callbacks (including temporary PostgreSQL exit) run in
   `cleanup_ns` before its final leftovers/harness witnesses in `observe_ns`.
   This terminal row's order is preparing → calling → cleaning → observing →
   recorded; ordinary rows retain the usual order. Cleanup errors never
   replace an originating operation/process-control exception, and callbacks
   continue after a cleanup error. Any cleanup failure prevents acceptance.
5. **Interrupts.** A row-originating `KeyboardInterrupt` or `SystemExit`,
   or a cleanup control exception with no earlier primary,
   propagates with its original identity and writes no verdict. After an
   ordinary primary failure, a later cleanup control exception is recorded as
   bounded `cleanup_failed` evidence while owned cleanup continues; it never
   replaces the original primary failure.
6. **Required failure.** Remaining ordinary rows are recorded once as
   `unavailable/not_reached`; the final cleanup row still executes and records
   its actual timing/outcome. Bundle writing follows; the test fails citing
   verdict categories only. A row interrupt propagates its original object
   after registered cleanup and writes no verdict; a bundle may be absent.

## 8. Facts and witness arithmetic

Every action has exactly its defined fact keys; mixed actions contain one
closed fact object per named backend. A `Pin` is null before publication,
otherwise `{generation, pin_sha256, manifest_sha256}`. The hashes are derived
from the actual accepted-publication map and retained manifest via the current
readback helpers; only hashes/generation are retained, never raw private maps.
Before and after pins are read independently of the operation's return value.

| Action class | Closed facts |
|---|---|
| `census_verify` | generation, aliases, S, C, files, inventory_sha256; exact equality to the committed census projection |
| `sqlite_init`, `migrate` | backend, initialized; a true value is a driver witness checked against real setup, not an authenticity certificate |
| `sealing_plan` | inventory_bytes, inventory_files, planned_min_read_bytes; referenced canonical plan member |
| refresh actions, `sqlite_initial`, `postgres_initial` | outcome, pin_before, pin_after, preparation_pin, attempt_root_fresh, inventory_sha256, manifest_bytes; referenced v2 report where declared |
| `planned_refusal`, `missing_refusal`, `privacy_refusal` | code, pin_before, pin_after; referenced report where declared |
| pack actions and `stale_investigation` | status, reason, observed_locations, canary_free, encoded_bytes, max_bytes, investigation_supported; locations are bounded public `[alias,relative]` refs, with intent tags for mixed packs |
| `lexical_build`, `lexical_query`, `lexical_revoke` | result, hits, observed_locations, revoked_generations, unavailable_reason |
| `snapshot_equivalence` | backend, inventory_sha256, manifest_snapshot_sha256, incumbent_snapshot_sha256 |
| `cleanup` | leftovers, forbidden_events, shim_invocations |

Observed public location refs are deduplicated and sorted within each named
backend/intent projection. More than32 total refs in an observation refuses as
`unbounded`; no silent truncation may hide presence/absence or scope evidence.

Unused fields within a class have explicit null/empty values; no arbitrary
extra fact is accepted. The recipe fixes per-action required/null fields.
Reconciliation computes expected-location presence, forbidden-location absence
and alias-scope validity from observed public refs and manual recipe constants;
it does not trust producer booleans for those predicates. Canary absence,
initialization and cleanup are explicitly driver witnesses: format validation
cannot establish their truth without code review and real execution evidence.

S and C use the row's declared alias projection and exclusion policy. S sums
all selected file sizes, including equal-digest files; C is S minus the sum of
one size per unique digest in a proven fresh per-attempt artifact store. m is
the actual retained manifest length. m_c=0 requires a newly created attempt
and initially empty store, not just an unchanged final inventory. The recipe
uses exclusively owned, stable fixture copies and expects r=0. Equal before/
after inventory alone is not proof of no transient retry; r=0 is this explicit
fixture-control assumption. Any observed counter mismatch rejects the case;
no general no-retry claim or new product telemetry seam follows.

| Check | Rule |
|---|---|
| Plan | `planned_min_read_bytes=4S+1`, inventory bytes S |
| Ordinary publish | actual v2 read `4S+C+m+m_c+r`, copy S, capture2S, store `S+C+m+m_c`, write `S+m`; fresh-store/stable-source conditions above must hold |
| Discarded reads | discovery/classification0 with `call_meter_exact`; classification limit applies=false. Incumbent snapshot equivalence independently retains ordinary-discovery identity |
| Planned refusal | explicit limit4S, lower bound4S+1, launches0, sealing reads0, complete pin digest unchanged |
| Report identity | strict existing codec, expected recipe resource-operation/backend/outcome labels; no home/root/fixture canary text |
| Pins/readback | exact predeclared generation transition and pin relation (§4), manual locations and scope, actual encoded-byte bound; no current-output-derived oracle |

Witness I/O and CPU are not charged to the product's sealing meter. They are
visible in `observe_ns`; source-binding/materialization work is in preparation.
No value is promoted to whole-operation/physical PostgreSQL cost.

## 9. Reconciliation

### 9.1 Algorithm

`reconcile(intent_bytes, bundle) -> Verdict` is pure. In order, it decodes
every record, checks index digests against member bytes, requires one
`attempt` and one `intent`, matches scenario and backend to the intent,
requires complete and strictly ordered `(step, sub)`, and then applies the
expectation/result rules and §8 to the facts and decoded members.

The outcome is `accepted` only when every required row is `pass` or
`expected_refusal`, every skip is on a non-required row, nothing failed, and
every witness is present. A missing row, member or witness, or a skipped
required row, gives `incomplete`. Anything else gives `rejected`.

### 9.2 Closed refusal categories

The path-free categories are `unreadable`, `unsafe_input`, `too_large`,
`not_canonical`, `malformed`, `invalid_domain`, `stale_input`,
`intent_mismatch`, `candidate_mismatch`, `cross_attempt`, `cross_backend`,
`out_of_order`, `missing_step`, `partial_bundle`, `tampered_member`,
`unbounded`, `witness_missing`, `witness_mismatch`, `report_mismatch`,
`pin_not_preserved` and `unexpected_failure`.

### 9.3 Real-bundle negatives

Once its bundle is written and accepted, each owner copies it to a separate
pytest directory and mutates only the copy. Local and Server apply the first
two mutations; mixed, the only two-backend bundle, applies all six. Each
test asserts that the required category is among the verdict's categories.

| Mutation | Required category |
|---|---|
| One flipped byte | `tampered_member` |
| One dropped member | `partial_bundle` |
| One observation canonically re-encoded with a different `attempt` (index updated) | `cross_attempt` |
| One `sqlite` observation canonically re-encoded with `backend = postgresql` (index updated) | `cross_backend` |
| An intent with a changed `candidate_census` | `candidate_mismatch` |
| An intent with a changed `product_digest` | `candidate_mismatch` |

## 10. Developer surface

| Command | Behavior |
|---|---|
| `python3 tools/first_use_workload.py plan [--source-parent HEX40]` | Pure; prints the intent to stdout |
| `python3 tools/first_use_workload.py check --bundle DIR` | Recomputes intent and verdict, prints `<outcome> <scenario> <categories>`, exits 0/1/2 |
| `python3 tools/first_use_workload.py show --bundle DIR [--json]` | Prints a bounded per-step table of spans, CPU scope labels, results and refusals; never sums them |

## 11. Verification plan

**Contract-led verification.** Define intended outcomes and refusal cases
before or alongside implementation. Use a failing reproducer for a discovered
bug when useful; do not spend executions proving that an absent module fails.
The §9.2 matrix, frozen-census comparison and real §9.3 bundle mutations must
exercise the actual implementation and distinct failure boundaries.

**Unit owners.** Under `src/test/unit/python/tools/`:

| Owner | Covers |
|---|---|
| `first_use_workload_records.unit.test.py` | Codecs, duplicates, depth, floats and booleans, canonical re-encoding |
| `first_use_workload_census.unit.test.py` | g1/g2 materialized in tmp equal the frozen census; the exclusion; alias constants match support; non-fixture paths refused; an open spy proves no task, gold or held-out path is opened |
| `first_use_workload_bundle.unit.test.py` | Exclusive writes; symlink, FIFO, oversize, unknown-name, nested-directory and identity-swap refusals |
| `first_use_workload_rules.unit.test.py` | Formula terms, `m_c`/`r` gating, report mismatches |
| `first_use_workload_reconcile.unit.test.py` | Every §9.2 category; skip visibility; a verdict-only bundle; expected values copied without witnesses → `witness_missing` |
| `first_use_workload_cli.unit.test.py` | Exit codes, path-free output, deterministic `plan`, the product import guard |

`src/test/unit/python/repomap_kg/ops/first_use_workload_driver.unit.test.py`
uses fakes to cover primary-over-cleanup precedence, `KeyboardInterrupt` and
`SystemExit` identity, `not_reached` after a required failure, no retry, and
both bundle-base branches (existing owned inner root; absent root → pytest
temporary directory, with no `/sandbox-report` creation).

**Integration owners** implement the §4 columns. Their deltas over the
incumbents: recipe order, the repeat pin relation, g2 lexical presence and
absence, subset scope, per-home snapshot equivalence, `m_c`/`r` gating,
scoped spans/CPU, cleanup accounting and reconciliation with real-bundle
negatives. Incumbent JSON, table and provenance checks are not re-asserted.

**Selectors.** Use `--no-coverage` only; brace groups expand to one path each (bash or zsh):

```text
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/tools/first_use_workload_{records,census,bundle,rules,reconcile,cli}.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workload_{driver,call_returns,cleanup_precedence}.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py \
  src/test/unit/python/repomap_kg/ops/sealing_plan.unit.test.py

python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
  src/test/int/python/repomap_kg/ops/first_use_workload_{local,server,mixed}.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_{local,server,mixed}.int.test.py \
  src/test/int/python/repomap_kg/ops/sealing_plan_cli.int.test.py \
  src/test/int/python/repomap_kg/ops/resource_report_v2_{local,server}_cli.int.test.py
```

The runner persists its staging contract report before pytest; that existing
write creates the inner report root under `--report`. The driver does not
create it. Required host checks expose any missing export rather than silently
accepting the temporary-directory branch.

The existing runner refuses `--report --no-coverage`. Local scoped runs
therefore use `--no-coverage` without `--report`; the real bundles and negatives
are checked inside the canonical sandbox before disposal. No report-policy
change, local coverage or D12-preflight workaround is authorized.

CI137's existing hosted staging command enables coverage and `--report`, so
its artifact must retain all three bundles. Host `check` of those exact-source
exported bundles remains a required post-CI acceptance gate. A source-tested
candidate may be published once to obtain that evidence, but neither export
nor bounded first-use qualification is accepted before the hosted check.
Export refusal blocks that acceptance; no automatic waiver follows. No
complete local suite, image pull/build, native parser/model or held-out run
is selected.

## 12. Acceptance and stop conditions

**Acceptance requires** (1) both selector sets passing, three `accepted`
bundles validated in the sandbox and the §9.3 negatives refused; (2) host
`check` accepting all three exact-source hosted bundles after CI (pending at
source-candidate publication; a missing gate blocks milestone acceptance); (3) Ruff,
mypy, compileall, length, privacy/topology, suppression and both diff checks
passing for changed files, with no debt growth; (4) product, report and plan
bytes and the CLI, MCP and runner surfaces unchanged; and (5) an exit record
that names the exact-commit private report for final owner hashes and physical
line counts, and claims no installed, W6, full-W7 or efficiency result.
Freeze final exit and binding metadata before final local scoped proof.
Record final owner hashes and physical line counts in the exact-commit private
report rather than rewriting the exit afterward. The private report may hash
the exit like every other source owner; the exit never embeds its own hash. Hosted CI137 produces final-source exported bundles; host check
uses the same-attempt candidate source SHA and recorded merge commit/tree. A
staging head is acceptable only after complete candidate-census equality;
otherwise obtain the exact executed tree, with no artifact repinning or
weakened check.
Keep exported reports outside src/main, src/test and tools (or gitignored), so
they cannot enter the canonical source census. A pending hosted export is
explicitly unaccepted, not a local proof substitute or report-policy waiver.

Bounded first-use acceptance means the recipe reconciles on the source
candidate (§5 digests). W8 installed, held-out evaluation and full W7 stay open.

**Stop and report, without widening scope,** if a manual or backend
expectation fails on the incumbent; a witness needs product SQL or a new
product seam; replay arming cannot be reused without changing an incumbent
assertion; export needs a runner change; an owner exceeds 400 lines after a
reasonable split; `tools/` lies outside the quality roots; the census
would parse/use task, gold or held-out data beyond canonical opaque source hashing; an existing inner root is unsafe; or staging-report or retained-member tooling refuses the extra
`first-use-workload/` tree, or §6.3 headroom fails for the CI136 artifact.

## 13. Size and coverage forecast

Approximate lines: tools 2,300, support 1,400, unit tests 3,300, integration
tests 1,300, census 200–600 and docs 500 (about 9,000–10,500; the exact-commit
private report records the final physical line count and owner hashes). Real
refresh, sealing, context and lexical branches may
reduce the 501-branch 82% integration deficit; the forecast proves no coverage.

## 14. What would make this design wrong

It is wrong if the incumbent misses a manual expectation (that finding
outranks the harness); if `--report` cannot carry sibling members without a
runner change; if waited-descendant CPU is unattributable even when serial
(it becomes `unavailable`, never an estimate); if operators need evidence
without a checkout (a W8 decision); or if the bounds are routinely approached.
