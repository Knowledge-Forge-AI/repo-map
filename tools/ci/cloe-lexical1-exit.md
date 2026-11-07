# REPOMAP-CLOE-LEXICAL1 Exit: PostgreSQL-native lexical search, metadata parity, and evaluation v2

Status: NOT ACCEPTED; final source/evidence review and hosted qualification pending for `REPOMAP-CLOE-LEXICAL1` on
`staging` parent `ae636963abcf3c952150bb738b122464cec9399f` under
[ADR 0129](../../docs/adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md)
and [cloe-native-lexical-search-v1.md](../../docs/specs/cloe-native-lexical-search-v1.md).
No public staging push, CI workflow dispatch, runtime image build, or held-out
evaluation execution is performed in this work stage.

## Scope Delivered

### Unit 1: Core PostgreSQL Lexical Lifecycle and Explicit CLI (`cloe_lexical`)

- Forward Liquibase changeset `20261031-001-cloe-lexical-create-derived-schema`
  (`src/main/resources/rdbms/2026/10/31-001-cloe-lexical-create-derived-schema.sql`)
  creates dedicated schema `cloe_lexical` (`cloe-lexical-schema:1`) with tables
  `generations`, `authority`, `documents`, `chunks`, and `omissions`,
  GIN indexes on `chunks.phrase_vector` and `chunks.ranked_vector`, and
  `REVOKE ALL` and `ALTER DEFAULT PRIVILEGES ... REVOKE ALL` from `PUBLIC` and limited roles.
- Role reconciliation in `runtime/database_roles.py` and post-restore
  reconciliation in `runtime/_lexical_restore.py` (hooked into
  `_backup_lifecycle.py` and `_extension_restore_lifecycle.py`) verify DB-owner
  custody, deny `PUBLIC` plus limited roles (`repomap_read_status`,
  `repomap_refresh_publication`, `repomap_coordinator_control`), and invalidate
  and purge restored `cloe_lexical` rows until an explicit rebuild.
- Dedicated Psycopg 3 driver (`storage/lexical_driver.py`) enforces owner-only
  role admission, explicit connect/lock/statement timeouts, and sanitized
  `LexicalStorageError` diagnostics without raw SQL, DSNs, paths, or body text.
- Pre-open privacy-gated capture (`retrieval/lexical_policy.py`,
  `retrieval/lexical_aliases.py`, `retrieval/lexical_capture.py`) computes
  `cloe-lexical-policy-v1`, excludes non-public/metadata-only/ephemeral/email/feed
  bindings and unsupported or symlink files before opening bytes, and splits
  CamelCase/snake_case/kebab-case/dotted/slash tokens (`identifier-path-split-v1`).
- Atomic generation publication (`storage/lexical_population.py`,
  `storage/lexical_lifecycle.py`, `storage/lexical_revoke.py`) populates bounded
  committed owner-checked batches under a shared transaction-scoped lifecycle lock,
  verifies exact document/chunk/omission counts, wall-clock lease and live policy, and flips
  `cloe_lexical.authority`.
- Single-statement fenced query execution (`storage/lexical_fence_sql.py`,
  `storage/lexical_literal_sql.py`, `storage/lexical_query_sql.py`,
  `retrieval/lexical_envelopes.py`) verifies latest complete `run_id`, receipt
  correspondence, `policy_digest`, and per-binding digests inside one read-only
  SQL statement for `ranked_terms`, `normalized_phrase`, and
  `literal_captured_text`, joining same-run `public.*` symbol provenance.
- Opt-in CLI (`cli/_parser_ops_lexical.py`, `cli/ops_lexical_commands.py`,
  `ops/lexical_publication.py`, `ops/lexical_service.py`, `ops/lexical_output.py`)
  exposes `cloe ops lexical-build`, `lexical-query`, and `lexical-revoke` with
  `cloe-ops-lexical-v1` JSON output bounded to `<= 65,536` UTF-8 bytes and
  refuses SQLite Local homes with `postgres-home-required`.

### Unit 2: Request-Pinned PostgreSQL Metadata Navigation Parity

- `storage/postgres_node_locations.py`, `storage/postgres_navigation_sql.py`,
  `storage/postgres_navigation_search.py`, and
  `server/_postgres_investigation_queries.py` implement single-statement
  request-pinned PostgreSQL `node_locations` and `navigation_search` under
  `readback_postgres_authority` over `public.*` tables only (zero `cloe_lexical`
  access), matching SQLite Local wire, admission (`NODE_SCAN_LIMIT=2000`,
  `EVIDENCE_SCAN_LIMIT=10000`, `ADMISSION_CHECK_LIMIT=100000`, `32 MiB`),
  `location_run_id` pre-filter selection, ambiguity, and provenance semantics.

### Unit 3: Truthful Evaluation v2, Historical Attempt-7 Reprojection, and Held-Out Gate

- Empty resolved binding scope in `retrieval/projection_query.py` and
  `tools/retrieval_evaluation_reference.py` now returns `unavailable_envelope`
  (`empty_resolved_binding_scope`, `scope_complete=False`) instead of claiming
  complete-scope absence.
- Evaluation v2 (`tools/retrieval_evaluation_slots_v2.py`,
  `tools/retrieval_evaluation_summary_v2.py`,
  `tools/retrieval_evaluation_criteria_v2.py`,
  `tools/retrieval_evaluation_reprojection.py`) records per-slot
  `requested_mode`, `effective_mode`, the full nested `fallback`,
  `match_surface`, omissions and `query_style`, grouping
  quality and cost requirements by unpooled cells so body fallbacks are never
  credited as stored-metadata retrieval.
- Immutable historical `calibration-attempt-7` journal records are reprojected
  offline into `mixed-v1/baseline/w3/calibration-attempt-7-reprojected-v2.json`
  and `mixed-v1/baseline/w3/criteria-proposal-v2-from-attempt-7.json` without
  mutating any W2 artifact or executing queries.
- `tools/retrieval_evaluation_fts.py` and `tools/retrieval_evaluation_w3.py`
  wire the 6th evaluation arm (`postgres_native_fts:postgresql`) and predeclared
  W3 calibration declaration/recipe artifacts. Corrected-source declaration/recipe2 accompany attempt2; the
  first declaration/recipe and actual observation remain at their original source.
- `tools/retrieval_evaluation_heldout.py` and `tools/retrieval_evaluation_admission.py`
  enforce a versioned parent acceptance receipt over the immutable proposed v2
  criteria, exact completed calibration artifacts and matching source closure,
  while keeping held-out execution hard-blocked
  during calibration (`held_out_queries_executed == 0`).

## Resulting-state scoped evidence

The final source, retained W3 fixture and CI102 grant combination passes
256 scoped unit cases in27 selected file owners and
32 disposable-container integration cases in13 file owners.
The grant/proof owner uses a fake executor to verify admission protocol; it is
not application execution or a system-suite result. Source bytes and resource
sets are preserved. Initial dispatcher145/10 counts were superseded by concrete
parent corrections and are not used to qualify this resulting state.

Unit command: `python3 tools/run_tests.py --suite unit --no-coverage --jobs 1 --`
followed by these exact selected files:

    src/test/unit/python/repomap_kg/retrieval/lexical_policy_and_capture.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/lexical_envelopes_and_cli.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/lexical_storage_and_navigation.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/evaluation_v2_and_heldout.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_query.unit.test.py
    src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py
    src/test/unit/python/repomap_kg/runtime/arch7e_declarative_database_roles.unit.test.py
    src/test/unit/python/repomap_kg/storage/migrations.unit.test.py
    src/test/unit/python/repomap_kg/storage/package_structure.unit.test.py
    src/test/unit/python/repomap_kg/local_db_backup/init_lifecycle.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_schema.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_grading.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_criteria.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_execution.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_harness.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_comparability.unit.test.py
    src/test/unit/python/tools/ci/retained_python_projection.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/historical_evidence_boundaries.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/heldout_custody_boundaries.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_lifecycle_boundaries.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_build_lease_boundaries.unit.test.py
    src/test/unit/python/repomap_kg/storage/postgres_navigation_admission.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_output_boundaries.unit.test.py
    src/test/unit/python/tools/ci/d12_system_grant.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_restore_local_plan.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_query_scope_boundaries.unit.test.py
    src/test/unit/python/repomap_kg/storage/lexical_bigint_lock_boundaries.unit.test.py

Integration command: `python3 tools/run_tests.py --suite int --no-coverage
--jobs 1 --pg-container-port 55433 --` followed by these exact files (the parent
also pins the existing smoke-image reference for canonical setup; no smoke suite
is executed):

    src/test/int/python/repomap_kg/retrieval/projection_publication.int.test.py
    src/test/int/python/repomap_kg/retrieval/corpus_publication.int.test.py
    src/test/int/python/repomap_kg/retrieval/lexical_postgres_lifecycle.int.test.py
    src/test/int/python/repomap_kg/retrieval/postgres_navigation_and_w3_eval.int.test.py
    src/test/int/python/repomap_kg/retrieval/evaluation_baselines.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_lifecycle_boundaries.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_build_lease_boundaries.int.test.py
    src/test/int/python/repomap_kg/storage/postgres_navigation_admission.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_output_boundaries.int.test.py
    src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_restore_local_plan.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_query_scope_boundaries.int.test.py
    src/test/int/python/repomap_kg/storage/lexical_bigint_lock_boundaries.int.test.py

The final parent publication checks require complete retained static
enforcement with zero cohort regressions, compile/topology/length/suppression/
export0.0.3/whitespace checks and a redacted changed-file privacy scan. New23
product owners and clean tool/test cohorts preserve every old numerical debt,
tool/length section, prior record and authority prefix. No new suppression or
baseline genesis is used. Independent final source/evidence/grant review is
mandatory before publication; its private receipt binds the exact candidate.

## Retained calibration and interpretation

The corrected-source `w3-calibration-attempt-2` was declared inside the cached native ARM
SDK before querying, with a pre-query source/input archive and immutable raw
declaration/report/terminal/manifest/journal/archive. Six arms ×24calibration
tasks ×3repetitions produce432query observations,144graded slots and1010journal
records. All execution failures and divergent-task counts are zero. Refused,
unavailable, partial and weak quality cells remain visible; this is no claim of
superiority or accepted utility. The v2 criteria remain proposals. All12held-out
tasks remain unexecuted and separately gated.

Historical attempt7 is preserved byte-for-byte. Its v2 report is an offline
projection of actual journal envelopes and graded slots, with the entire raw
hash chain and exact source/archive membership verified. It executes no query
and does not qualify the W3 source. Native/reference metadata-intent fallbacks
remain body-scan evidence; summary cells do not reclassify them as metadata.

The PostgreSQL arm first selects an authorized public two-binding view and
retains evaluator exclusions/omissions and full scope. Its provenance explicitly
discloses evaluator prechecks; these do not prove backend exclusion enforcement
against bindings absent from that view. View-publication and lexical-build
times are separate, own aggregate input bytes are observed, and unknown physical
or total cost remains null. Future held-out acceptance uses a versioned parent
receipt over unchanged proposed criteria and exact completed source-bound raw
artifacts. Live input bytes are revalidated immediately before materialization.

## Correctness boundaries and publication

Build attempts use distinct owned IDs, durable wall-clock leases, bounded
committed batches and shared lifecycle locks. Failures clean only their owned
rows; cleanup failures surface. Final activation rechecks custody, policy,
receipt, lease and exact counts. Restore clears body-derived readiness and
reconciles table/sequence custody. Query remains read-only. SQL metadata
transport bounds count detoasted serialized row bytes before aggregation.

JSON including its CLI newline is bounded after partial projection. Oversized
identity/provenance that cannot fit truthfully fails through bounded stderr and
exit1. Partial build/revoke outputs also exit1. A mutation may already have
completed before serialization refusal; inspect current state before retrying.
Multi-prefix matching discloses the full union rather than the first prefix.

Hosted CI state: AVAILABLE, as set by the operator. One ordinary staging push
through existing draft PR23 is authorized by the current roadmap request and
ADR0130's recorded parent interpretation. It expects the automatic
`repomap-release-qualification` CI102attempt1 campaign. No remote mutation occurs
as part of the scoped proofs. Until publication, the campaign is not requested;
after publication, its exact same-attempt executed evidence remains pending.
CI101 qualifies only predecessor ae636963, not this source. Eighteen native AMD
starts remain spent; exactly one nineteenth is reserved, no twentieth or retry.

Complete local Python unit, integration, smoke, staging, system and combined
suites and Python project coverage remain intentionally unselected. Local
evidence proves selected boundaries only. Hosted CI owns complete populations,
native AMD execution and the requested two-point margins above hard coverage
gates. No local app/SDK build, new dependency, image recipe, supplier acceptance,
live deployment, main promotion, tag or held-out execution is performed.

## Independent-review correction and retained limits

The source review identified restore keyword forwarding, safe segment prefixes,
in-aggregate ordering, BIGINT lexical locks and native library bounds. New
regressions reproduced those failures before correction; final scoped proof
includes their corrected source and the new attempt-specific recipe behavior.
Production restore no longer sniffs mock attributes or silently drops its purge
flag. Prefix normalization is shared by request and executor; file-or-descendant
semantics and literal percent handling are proved on actual PostgreSQL.

Native lease and actual final-fence lock expressions prove contention, release,
distinct keys and signed BIGINT range. The incumbent namespace19042 staged
publisher separately refuses large IDs before lexical code. Full end-to-end
large-ID graph publication is unqualified and W7-owned; the genuine full
publication/build/query/revoke positive uses ordinary accepted IDs. No publisher
or evidence rows are fabricated, and no foreign keys are rewritten for proof.
Full-graph policy freshness remains conservative: unrelated binding policy edits
can stale a generation. The operator guide states that stricter utility boundary.

Attempt1 and its complete raw source archive remain unchanged. Attempt2 was
predeclared only after these correcting changes and has separate recipe/output
paths; this is correction-driven observation, not score selection. Criteria
acceptance must later disposition native comparator495781outputbytes against
a proposed65536ceiling and PostgreSQL graph absent-answer0/1 vsSQLite1/1.
Those visible limitations do not become accepted floors or superiority claims.

The initial audit producer invented source identifiers; its PASS narrative was
rejected. Independent source review and actual parent-owned receipts control
acceptance. The unused first CI102 binding is retained and explicitly refused
after zero-allocation supersession. Revised binding2 preserves all18spent starts,
maximum19, CI102attempt1 and the single publication; no retry is granted.
