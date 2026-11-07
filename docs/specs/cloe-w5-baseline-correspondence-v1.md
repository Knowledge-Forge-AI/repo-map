# CLOE W5 baseline publication correspondence v1

Status: evaluator-only implementation candidate for the `REPOMAP-CLOE-SEMANTIC1`
comparability continuation under accepted
[ADR 0141](../adr/2026/11/0141-w5-baseline-publication-correspondence.md).
This specification records the evaluator-only baseline-correspondence sidecar,
fenced current-observation lookup, native materialization witness, per-arm
expected-gap classification, and versioned byte-layer breakdown. It does not
claim full W5 completion, accepted scientific criteria, held-out execution, or
hosted successor qualification.

## 1. Honest Execution Envelopes and Evaluator-Only Sidecars

- Product `QueryEnvelope` payloads, `scope.backend`, `requested_mode`,
  `effective_mode`, `match_surface`, `fallback`, `omissions`, and `provenance`
  remain untouched. `native_tools_baseline` continues to report
  `scope.backend == "native_filesystem"` and `captured_projection_reference:*`
  continues to report `scope.backend == "captured_reference"`.
- `BaselineCorrespondenceSidecar` (`schema = "cloe-w5-baseline-correspondence-v1"`)
  is an evaluator-only witness consumed by `verify_baseline_correspondence_sidecar`
  and `baseline_file_metrics_with_correspondence` (and by `baseline_file_metrics`
  when `correspondence_sidecar` is explicitly supplied).
- When `correspondence_sidecar is None`, `baseline_file_metrics` preserves its
  strict envelope-only validation path unchanged for historical reports and
  raw observations.

## 2. Per-Arm Target Pins and Cross-Store Snapshot Correspondence

- Each baseline arm validates against its actual backend's `VerifiedPublicationPin`:
  - `native_tools_baseline`, `current_graph_baseline:sqlite`, and
    `captured_projection_reference:sqlite` bind to the SQLite `VerifiedPublicationPin`
    (`backend == "sqlite"`).
  - `current_graph_baseline:postgresql`, `captured_projection_reference:postgresql`,
    and `postgres_native_fts:postgresql` bind to the PostgreSQL `VerifiedPublicationPin`
    (`backend == "postgresql"`).
- Distinct backend `publication_bundle_id` values across SQLite and PostgreSQL
  are never forced equal. When both `sqlite_pin` and `postgres_pin` are present
  for cross-store comparison, `verify_baseline_correspondence_sidecar` requires
  equal `graph_id`, `generation`, `snapshot_vector`,
  `admitted_public_bindings`, and `denied_bindings`, refusing with
  `cross_store_snapshot_vector_mismatch`, `cross_store_publication_mismatch`, or
  `cross_store_binding_policy_mismatch` otherwise.
  Each store retains its independently verified manifest identity; a manifest ID
  is not required to be identical across stores.
- In two-generation calibration runs, the SQLite fixture home is refreshed in
  place from Generation 1 to Generation 2 (matching PostgreSQL's single-database
  progression) so `sqlite_pin.generation` advances `1 -> 2` in lockstep with
  `task.generation` without relaxing `grade_w5_task_slot` generation guards.

## 3. Matched-Repository Accepted PostgreSQL Readback and Projection Inputs

- `read_postgres_matched_accepted_publication` in
  `retrieval_evaluation_publication_readback.py` (re-exported by
  `w5_semantic_store_support.py`, and `read_postgres_accepted_publication` in
  `retrieval_evaluation_publication.py`) derives the current accepted PostgreSQL
  publication from `postgres_repo_predicate_sql(..., context_identity=True)` and
  `postgres_accepted_run_cte_sql(context_identity=True)` joined with `public.runs`,
  validating the paired portable `RunPublicationReceipt` and populating a
  positive integer `accepted_generation` (`>= 1`, never `None`).
- Both `make_sqlite_readback_adapter` and `make_postgres_readback_adapter` attach
  `ProjectionInputs` bound to that verified `AcceptedPublicationReference`,
  preserving strict `_verify_projection_inputs` enforcement across both stores.
- Generator pins use compact identity/receipt adapters rather than enumerating
  canonical nodes and evidence on every fence. Each live revalidation rechecks
  actual graph/binding privacy. Representation validation still reads the
  canonical rows it needs and binds its pin to the compact live adapter.
- The sidecar carries a factory-issued capture of the actual query call and
  independent before/after reads from both stores. Copying a dataclass or
  substituting a different task, arm, envelope, pin, or cost sample cannot
  establish verification. Serialization preserves an already verified capture
  without reopening generation-1 stores after generation 2 is published.

## 4. Native Materialization Witness

- `MaterializedNativeView` carries an optional `NativeMaterializationWitness`
  (`schema = "cloe-w5-native-materialization-witness-v1"`), built by
  `build_native_materialization_witness` and revalidated by
  `verify_native_materialization_witness`.
- The witness recomputes expected bytes for both raw body files (from `store`
  and `manifest` under `policy`) and rendered `.extracted-metadata/<alias>.meta.txt`
  files (via `_render_extracted_metadata_lines` over `bundle`, `manifest`, and
  `policy`), and verifies actual regular files on disk under `view_root`
  (rejecting symlinks, missing/extra files, or byte/digest drift).
- Verification requires the actual manifest, bundle, artifact store, policy,
  independent complete generation alias set, binding map, and surface map.
  A witness cannot validate itself. Task-specific selection remains separate
  from the complete public materialization and denied-binding checks.
- Synthetic caller-mapping strings (`repo:{graph_id}`) are never accepted as
  publication identity (`caller_mapping_not_admitted_for_identity`).

## 5. Fenced Current-Observation Lookup on SQLite and PostgreSQL

- `query_fenced_current_observations` in `tools/retrieval_evaluation_current_observations.py`
  executes evaluator-owned fixed, parameterized `raw_observations` queries fenced
  by the independently read-back accepted `run_id` and `repository_identity` on
  both SQLite and PostgreSQL, revalidated before and after query execution.
- Both `CURRENT_LITERAL_ENUMERATION` and `_traverse_graph_neighborhood`
  (`GRAPH_INVESTIGATION`) in `tools/retrieval_evaluation_graph.py` use
  `query_fenced_current_observations`, excluding deleted Generation-1 rows
  (`cal-23` / `LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN`) in Generation 2 while
  preserving positive Generation-2 rows and unchanged companion binding rows.
- Shared `server/mcp_search_sql.py`, `storage/sqlite_local/investigation_queries.py`,
  canonical navigation historical fallback, and product `InvestigationReadStore`
  semantics remain unchanged.
- The graph-investigation arm still traverses the reference canonical
  neighborhood, whose topology may include historical edges. Only its returned
  raw-observation locators receive the current-publication fence. This is not
  evidence that every traversed canonical edge belongs to the accepted run.
- Binding selection and source prefix apply before bounded pagination.
  Malformed or unknown binding/snapshot metadata refuses; incomplete pages
  disclose omissions and partial capability instead of claiming completeness.
  Both backends validate every matching row independently of the selected page.
  The fixed catalog includes non-ASCII captured-text task `cal-20`; its
  metadata-graph arms remain unavailable for that surface. Locale-sensitive
  non-ASCII matching equivalence between the current-observation readers remains
  unqualified. Other arms retain their actual modes and results.

## 6. Per-Arm Expected-Gap Table and Versioned Byte/Cost Accounting

- `W5_EXPECTED_BASELINE_GAPS_BY_ARM` and `is_expected_baseline_gap` classify
  non-verified baseline slots by arm and reason without inventing file credit:
  - `cal-09`, `cal-10`, `cal-12`, `cal-24`: `("not_applicable", "file_metric_not_applicable")`
    across all six baseline arms.
  - `cal-21`, `cal-22`: `("gap", "refused:binding_privacy_not_authorized")`
    for native, captured-reference and FTS arms. The approved public-only graph
    omits the denied mailbox binding, so its graph arms retain
    `("gap", "unavailable:captured_text_surface_unsupported_by_metadata_graph")`.
    This unavailable outcome does not attest a privacy refusal; no file credit
    is assigned. Tests of actual private bindings retain their refusal guards.
  - `cal-04`..`cal-08`, `cal-11`, `cal-14`, `cal-15`, `cal-18`..`cal-20` on
    `current_graph_baseline:sqlite` and `current_graph_baseline:postgresql`:
    `("gap", "unavailable:captured_text_surface_unsupported_by_metadata_graph")`.
  - `cal-16`, `cal-17` on `captured_projection_reference:sqlite` and
    `captured_projection_reference:postgresql`:
    `("gap", "unavailable:non_body_feed_or_mailbox_excluded_from_text_projection")`.
  - `cal-16`, `cal-17` on `postgres_native_fts:postgresql`:
    `("gap", "unavailable:non_body_feed_or_mailbox_excluded_from_lexical_index")`.
- `EvaluatorByteBreakdownV1` (`schema = "cloe-w5-byte-accounting-v1"`) and
  `CorrespondenceCostSample` separate `raw_process_stdout_bytes` (such as
  `cal-07`'s 495,781 raw `git grep` stdout bytes under the unchanged 1 MiB
  process cap), `decoded_candidate_count`, `returned_hit_count`,
  `serialized_envelope_bytes`, `correspondence_verification_bytes_read`,
  `correspondence_verification_ns`, and `correspondence_failures` while keeping
  legacy `ByteLayerAccounting` field semantics and `criteria_v2`
  (`status = "proposed_for_parent_review"`) unchanged.
- Known artifact and materialized-file bytes are recorded separately. Opaque
  verification and database wire I/O remain unknown (`null`), never fabricated
  from serialized objects. Graph execution records identify fence/query time
  as components of execution time, including failed work, rather than adding
  overlapping intervals to a total.
  Native byte-work zeros for correspondence mean that layer performs no separate
  verification; the sidecar's cost sample owns that work. A zero
  `direct_selected_text_bytes` means no direct evaluator text read on the process
  path, not zero filesystem I/O inside the native process.

### Observed calibration limits

The fresh paired calibration preserves deviations from the expected-gap table.
For cal-21/22 the public-only fixture omits mailbox: native/reference observations
are available-empty rather than refused (18 false safety flags), and graph
observations are unavailable rather than refused (12 false safety flags). Their
original envelopes, zero metric dictionaries where present and safety flags
remain unchanged. None establishes successful privacy refusal or retrieval quality.
Only the 6 FTS observations record the explicit refusal; actual private-binding
negative tests remain separate. No frozen task, query, gold or expected-gap entry
was altered to fit these outcomes.

FTS cal-19 returns normalized prefix `shared` for task prefix `shared/`. The strict
sidecar retains 3 `envelope_source_scope_mismatch` gaps without file metrics;
normalization equivalence remains unqualified. See the operational exit for actual
metric populations and result-v2 sizes. These residuals remain open under the
bounded evidence milestone rather than receiving invented credit.

## 7. Opt-in Result Version and Retained Evidence

The optional experiment enables `cloe-w5-semantic-experiment-v2` before freezing
its source archive. Supplementary framed results retain cell identity,
correspondence status and measured work. Strict decoding rejects malformed,
duplicate, oversized, unbound, or noncanonical records. The six legacy journal
members remain unchanged, and their exact hashes bind the supplementary result.
Ordinary callers keep the legacy result path unless explicitly enabled.
Completed V2 results require every planned cell, baseline correspondence and
native byte-work repetition. Failed results may retain partial work. Cell and
sidecar identities, backend pairs, verification flags and cost value/types must
agree. Each V2 result stays within 4 MiB and all V2 frames within 8 MiB; mixed
stdout uses the existing 96 MiB artifact-log envelope. These transport bounds
do not change the native search process cap or any scientific criterion.
Decoding checks transport consistency and does not authenticate live publication
state or award grading credit. The supported grading path verifies concrete
issued captures and registered sidecars before collecting serialized results.
Legacy journals are finalized and emitted before supplementary V2 failures can
escape. Validated categorical failure codes preserve the primary error; V2
validation/emission failures remain secondary to primary, cleanup and attribution
failures, with available raw artifacts retained on every finalization path.
