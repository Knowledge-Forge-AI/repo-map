# Public-text calibration technical design and declaration 2

Status: declaration-2 source implementation and final review, 2026-11-11.
The operator selected public-text input and approved document-only generation 2.
Declaration 1's stop remains history; B-AUTH is resolved. Foundation source
is accepted, and later comparison/report/driver source has scoped executable
proof and independent review. Final composed source and private-host acceptance
remain separate gates before the sole native attempt. No model, held-out,
scientific, publication or hosted-CI acceptance is asserted here.
Phase: `REPOMAP-CLOE-PUBLIC-TEXT1`. Source baseline:
`c31fdfbc6bd7c65df75b1e473be2a3f0134233be`.

Parents: [ADR0182](../adr/2026/11/0182-public-text-semantic-calibration.md)
and [the calibration protocol](cloe-public-text-semantic-calibration-v1.md).
This document owns declaration 2, its authority history and the foundation
pointer. The remaining study/report technical contract is owned canonically by
[the study contract](cloe-public-text-study-v1.md). Where sections 7–11 below
earlier described the same subjects, they now point there and that contract
governs. Neither document widens either parent.

## 1. Authority, history and what this design decides

The operator selected the recommended route with "proceed". That selected the
captured-public-text input class (`canonical-node-public-text-v2` over the
already captured, policy-authorized `mixed-v1` calibration material) and the
conditional `PUBLICTEXT-CAL1` allocation: at most two generator-worker
invocations, one study-owned pgvector materialization, no retry, exact
ADR0136 BGE/ONNX/twenty-wheel artifacts. It selected no task, gold, held-out,
query mode, scientific criterion or production admission.

### 1.1 Declaration 1 stopped (historical, unchanged)

Declaration 1 required at least one applicable non-denied public-text query in
each generation. Its model-free task census stopped it before substantive
implementation:

| Fact | Value |
|---|---|
| Calibration records matching retained task digests | 24 of 24 |
| Generation 1 tasks / ranked-discovery upper bound | 23 / 4 (cal-01, cal-02, cal-03, cal-13) |
| Generation 2 tasks / ranked-discovery upper bound | 1 / 0 (cal-23, `current_literal_enumeration` over `extracted_metadata`) |
| Guard that refuses cal-23 | `tools/retrieval_semantic_generator_inputs.py:149-150`, `unsupported_semantic_query_mode` |
| Body, model, held-out reads; source/test runs; builds; learned slot | all zero; slot unreserved |

The stop stands. It is not reinterpreted as a pass and declaration 1 is not
continued.

### 1.2 Operator amendment and unchanged allocation

The first checkpoint raised B-AUTH because the selected packet explicitly
included the per-generation query floor. The operator subsequently selected
"A: Permit document-only generation 2" in the concrete amendment. This
resolves the authority question directly; parent interpretation is not used
as substitute authority. The amendment changes only that floor.

Declaration 2 keeps all 24 tasks, fixed queries, labels, golds, both publication
generations and three repetitions. Generation 1 has exactly four existing
ranked-discovery tasks that passed the model-free body-policy census.
Generation 2 remains document-only for model inference, following ADR0136.
Its incumbent baseline operations still execute in their original modes;
only inapplicable learned-query cells remain unavailable/refused. No task is
relabelled or removed and no cross-generation learned-query claim is made.

The entirely unspent PUBLICTEXT-CAL1 allocation stays at two generation workers,
one study materialization and no retry. Model/dependency pins, all byte/record
and transport caps, runtime/platform, corpus, privacy and production exclusions
are unchanged. No scientific criterion or held-out use is selected.

## 2. Declaration 2

Freeze before implementation:

1. **Generation 1 (query generation).** Public-text queries are exactly the
   fixed ranked-discovery tasks whose body-mode admission succeeds (upper bound
   four). Every other generation-1 task keeps its unavailable/refused cell for
   every learned arm, with its existing reason.
2. **Generation 2 (document-only).** Fresh v1 and public-text document vectors,
   import, publication-fencing and cleanup observations. Zero query inference.
   cal-23 keeps every original baseline operation and explicit unavailable/refused learned-query cell. No retrieval
   utility, query metric or cross-generation query comparison is claimed.
3. **Floors (efficiency, not science; operator-amended).**
   - F1, before substantive implementation: the model-free gen-1 body-policy
     census (section 4) finds >=1 ranked task whose every selected binding has
     no body-mode denial. Otherwise stop; nothing is built.
   - F2, before reservation: generation 1 has >=1 admitted public-text query
     and >=1 eligible public-text document; generation 2 has >=1 eligible
     public-text document. Missing data is a stop, never a partial run.
4. **Allocation.** One `PUBLICTEXT-CAL1` attempt: worker 1 = generation 1,
   worker 2 = generation 2, one study pgvector materialization. The declaration-1
   stop consumed nothing.
5. **No adaptation.** Window, span rule, arms, repetitions and caps are frozen
   here. Nothing is tuned after applicability, vectors or results are seen.

## 3. Canonical foundation contract (sections 3–6)

The [foundation contract](cloe-public-text-foundation-v1.md) owns the exact
module, admission, captured-reader, span, descriptor, encoding and census
interfaces and their scoped proof selectors. Sections 4–6 referred to below
are in that contract; they are not duplicated here. Its implementation
checkpoint is independent of these later comparison/report proposals.

## 7. Dual-arm generic request

The worker, its protocol, `WORKER_SOURCE_FILES` and the response parser are
unchanged; their source closure digest is therefore unchanged. The builder,
record ids, partition order, identity manifest and request encoding are
specified canonically in [study contract section 4](cloe-public-text-study-v1.md#4-dual-arm-request).
History: an earlier draft here used `v1.d.NNNN` v1 ids. The study contract
replaces them with `"v1." + original_record_id`, which preserves v1 texts and
ids recoverably. It also binds the current PostgreSQL pin, the task pins and
the study identity into `input_identity`.

Combined bounds per generation: <=500 records, <=8 MiB request, <=1 MiB per
text, <=8 MiB aggregate text, <=512-byte record id. Worst case with the ~80
historical v1 documents per generation: 80 + 80 documents + 8 queries; a
4,096-byte excerpt of control bytes becomes 24 KiB of model text and about
28 KiB after ASCII request escaping, so 80 such records stay under 2.5 MiB of
the 8 MiB request cap. The census records actual counts and bytes.

### 7.1 Dual-arm sealing and per-arm split

The production sealer cannot accept the combined response, and it is not
bypassed. Unchanged `seal_generation_result`
(`retrieval_semantic_generator_output.py:172-193`) requires
`response.request_records == inputs.records` and equal `input_identity` and
`representation_report_identity` with one v1 `PublicGenerationInput`.
`_validate_cost_against_inputs` (122-147) binds cost to those same records.
The combined request has renamed v1 ids, extra `ptx` records and a new
identity, so it fails every one of these checks by design. Therefore no
calibration vector, v1 or v2, becomes a `GeneratedEnrichmentArtifact`. No
calibration vector reaches `import_generation` (`w5_experiment_postgres.py:166-184`)
or production `build_embedding_import_sql`.

The study-only seal `seal_dual_arm_result` is specified in
[study contract sections 5–7](cloe-public-text-study-v1.md#5-study-only-seal).
That section owns:
- the numbered check order, including aggregate token, overflow and
  truncation reconciliation that the raw parser does not perform;
- per-arm truncation, where v1 keeps its own-record refusal and v2 keeps every
  vector as `token_partial`;
- the five completeness facts;
- the cost split.

History and correction: the earlier cost rule here treated token counts as
shared. The verified response carries tokens per record, so per-arm tokens
are exact derived sums. Only load, inference and total seconds are shared
once, and per-arm time remains `{"unknown": "shared_worker_cost"}`. Values are
never pro-rated.

**Import destination.** v1 calibration vectors are imported only as the
study's `canonical-node-v1` batch. Public-text vectors are imported only as
the `canonical-node-public-text-v2` batch, in the study relations of
[study contract section 8](cloe-public-text-study-v1.md#8-study-sql-schema-and-ownership).
Production-reader parity for v1 is proven in integration with synthetic
vectors. The calibration claims study-reader v1 cells with that proven
parity, not production-reader observation of calibration vectors. No
historical vector, score or receipt is imported.

## 8. Study PostgreSQL boundary

The study SQL schema, ownership, import, exact and observed-ANN reads, index
handling and cleanup are specified canonically in
[study contract sections 8–9](cloe-public-text-study-v1.md#8-study-sql-schema-and-ownership).
Subsections 8.1–8.5 below are retained as design history. Where they differ,
the study contract governs.

### 8.1 Why not production objects; TEMP only inside one transaction

`EmbeddingProfile.validate()` and the disposable schema's
`CHECK (representation_version = 'canonical-node-v1')`
(`semantic_candidate_import.py:71`) correctly refuse v2. They stay unchanged.
No persistent study state lives in `TEMP` objects. Every support call is a
separate `psql` process (`w5_experiment_postgres.py:78-94`), so session-scoped
objects would vanish between import and read. A psycopg session is
unnecessary. The study contract does use one invocation-owned `TEMP ... ON
COMMIT DROP` result table, but only inside a single psql transaction for an
observed ANN cell. That relies on the existing database TEMP privilege, checked
first; no grant is added.

### 8.2 Principal and rights (already granted)

`repomap_w5_hnsw_owner` (`DEFAULT_OWNER_IDENTITY`,
`retrieval_semantic_ann_sql.py:30`) receives in the existing disposable
install (`w5_experiment_postgres.py:156-162`): ownership of the two enrichment
tables, `USAGE, CREATE` on `repomap_enrichment`, `USAGE` on `repomap_vector`
and `EXECUTE` on its functions, and `SELECT` on `repositories`, `runs`,
`canonical_nodes`, `canonical_evidence`, `canonical_node_evidence`. That is
sufficient. Study objects are created, written, indexed, read and dropped only
as this role. No `GRANT`, role, schema, extension or harness policy change is
added; the reader role is not given access to study tables. The precondition
check reads `has_schema_privilege(owner, 'repomap_enrichment', 'CREATE')`
and refuses (gate 3) if false.

### 8.3 Objects (history; superseded)

The study contract replaces the per-arm table pairs below with one
`ptx_batch_<h>` and one `ptx_entry_<h>` relation per study. An `arm`
discriminator is enforced by CHECK and foreign-key constraints, and each
batch gets its own owned partial HNSW index. The earlier draft was:
per attempt, `h = sha256(attempt_identity | owner)[:24]`, exact names:
`repomap_enrichment.ptx_rebuilds_<h>`, `ptx_embeddings_<h>`, and per rebuild
`ptx_hnsw384_<32 hex>`. DDL mirrors the disposable enrichment tables (same
columns, dimension, unit-norm, digest and 1..500 row checks), with the
representation check set from a closed constructor value. The calibration
uses `canonical-node-public-text-v2` for the public-text arm and a separately
named `canonical-node-v1` control table pair for the v1 arm (section 7.1),
which is also the integration differential control. Each table gets
`COMMENT 'cloe-public-text-study:<attempt_identity>'`.

### 8.4 Reads

Query SQL reuses `accepted_candidate_publication_sql`, `sql_literal` and the
accepted-link predicate unchanged, and adapts only: table names, study-profile
filters, and the role wrapper `BEGIN READ ONLY; SET LOCAL ROLE
"repomap_w5_hnsw_owner"; ... COMMIT;`. Distance, tie-break
(`distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"`), limit
20, evidence limit 5, evidence ordering, status values and the receipt,
repository, binding, snapshot, profile and input-digest fences match
`build_candidate_query_sql`. Imports use the same fences and refuse caller SQL
fragments; identifiers are fixed-pattern, values pass `sql_literal`.

### 8.5 HNSW, cleanup and parity

One per-batch 384-D cosine partial index, default settings only. Superseded
observation rule: the earlier draft used plain `EXPLAIN (FORMAT JSON)` and
`not_run/index_not_selected`. That does not bind a plan to the rows actually
returned. The study contract instead runs one psql transaction:
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` of a TEMP `CREATE TABLE AS`, then
it selects exactly those materialized rows. An unselected owned index is
`unavailable/index_not_selected`, with no exact fallback. No planner forcing
or tuning. Exact cosine order is the correctness reference.

Cleanup, after all reads: for each owned index then table, read
`pg_class`/`pg_namespace`/`pg_description` and require exact name, schema,
owner and comment; `DROP INDEX`/`DROP TABLE ... RESTRICT`; read back absence.
Anything foreign or mismatched is left untouched and recorded
`cleanup_failed:<reason>`. A cleanup failure blocks a `complete` report.

Differential control (pgvector integration only, synthetic vectors): identical
v1 vectors imported through production `build_embedding_import_sql` and
through the control table pair must yield the same results from the
production reader and the study reader: exact order, ties, evidence expansion
and statuses (`stale_publication`, `enrichment_unavailable`). The existing
`_scope_for_query` binding refusals (`source_scope_refused`,
`unknown_source_binding`) wrap both readers identically. The calibration does
not repeat the production half, because its vectors cannot be sealed for the
production importer (section 7.1).

### 8.6 One study, sequential current publications

After source proof, review, task-side census and inert bank/SDK checks, start
one study-owned pgvector materialization and one disposable PostgreSQL cluster.
Install the existing fixture schema/roles once. No extra core cluster is used
to precompute requests and no accepted publication is copied between backends.

For generation 1: publish its unchanged fixture into that cluster; read the
current PostgreSQL pin, retained capture and spans; construct descriptors and
the combined request; complete all source/document/cap/time checks; reserve
and launch worker 1 outside the privileged sandbox; revalidate the same current
publication, recompute descriptors, seal/import into the study tables, and run
the frozen incumbent/vector/fusion observations and three repetitions.

Then publish generation 2 in the same cluster. Prove that reads under the old
generation-1 pin refuse as stale. Build fresh generation-2 documents and its
combined document-only request, with zero query records. Launch worker 2,
revalidate/recompute/import, retain original incumbent baseline execution and
the explicitly unavailable/refused learned-query cells, and observe ownership,
publication fencing and cleanup. No learned retrieval metric is claimed there.

Clean all exact study indexes and relations before the cluster is removed;
[study contract section 12](cloe-public-text-study-v1.md#12-study-lifecycle-one-cluster-generation-1-to-generation-2)
owns the state machine.
Include failed preparation/worker/query/cleanup work; do not discard prior
attempts or grant another materialization. Both workers and all reads bind to
their original PostgreSQL publication, not to a later reconstruction.

## 9. Work estimate (frozen calculation, gate 5)

Inputs from retained Optional15 terminal receipts per generation: load seconds
`L0`, inference seconds `I0`, records `N0`, mean `token_count_used` `t0`; and
the existing unchanged worker deadline `D` cited from the controller source at
freeze. Missing any input stops.

For BGE-small (`d = 384`, FFN `4d`), per-layer work is proportional to
`12nd^2 + 2n^2d`. The 512-token scale factor is
`S = 512(12d + 1024) / (t0(12d + 2 t0))`. Per-record bounds:
`u_meta = I0/N0`, `u_ptx = 2 * S * I0/N0` (2x unmodelled overhead).
`E = L0 + (N_v1_docs + Q_v1) * u_meta + (N_ptx_docs + Q_ptx) * u_ptx`.
Require `E + 60 <= D` (60 seconds of fixed headroom inside the unchanged deadline). Otherwise stop; no warm-up, longer timeout or split.
The result is a disclosed estimate, never a measured upper bound. The
retained kernel already pads to 512 tokens; S is a conservative policy
allowance rather than measured tensor-width scaling. The study contract
section 13 separately gates the real synthetic lifecycle's generation
transition within the existing 600-second supervisor initialization wait.
[Study contract section 13](cloe-public-text-study-v1.md#13-native-envelope)
freezes `D = 550` from `TIMEOUT_POLICY`, the retained g1/g2 inputs, and the
resulting per-generation maximum record counts.

## 10. Report `cloe-public-text-calibration-v1`

The closed report grammar, 12-arm population, 864-cell count algebra, states,
canonical bytes and caps are specified canonically in
[study contract section 11](cloe-public-text-study-v1.md#11-report-cloe-public-text-calibration-v1).
The summary below is retained as history. A strict writer/reader in
`tools/retrieval_public_text_report.py` references, and never rewrites,
historical paired V1/V2 reports, the dossier factory and their CLI defaults. Reuse candidates, each imported unchanged only
where its contract fits and pinned by a test: `canonical_json_bytes`,
`load_journal`, `MEMBER_NAMES`, `MAX_REPORT_BYTES`, `MAX_RESULT_BYTES`,
`verify_raw_component`, `capture_file`, `owned_path`, `verify_unchanged`.
The historical `validate_component_dossier` top-level factory is explicitly
not reused; its narrow compatible field validators are used as described
in the study contract. Where a primitive is bound to the historical
v1-only shape, the report adds a narrow strict codec instead of widening it.

Content: declaration-2 identity, census digest, source and artifact closure,
per-generation document counts per arm, exclusions by closed reason,
verification and excerpt bytes, the full task x arm x repetition cell matrix
(`completed`, `refused`, `unavailable`, `failed`, `not_run`, `unknown`) with
original component member hashes, cost layers with shared work counted once,
cleanup and fencing records. Counts are `{"value": n}` or `{"unknown":
reason}`; unknown never becomes zero. The reader recomputes every hash, count,
applicability and arm correspondence and refuses on any difference. Public
output contains excerpt digests, offsets and counts, never excerpt text;
original bundles with excerpts stay in phase-owned private evidence.

## 11. Exact scoped source proof

The foundation's canonical selector list and source obligations are in
[foundation section 8](cloe-public-text-foundation-v1.md#8-exact-proof-owners).
That list owns all six foundation unit files and both core integration files.
The core integration owners prove span correspondence for BOTH SQLite and
PostgreSQL, without requiring the optional pgvector profile.

Later slices' exact new source owners and unit, core-integration and
`requires_pgvector` selectors are frozen in
[study contract sections 2 and 15](cloe-public-text-study-v1.md#15-exact-proof-selectors).
They do not replace the foundation selectors.

- Foundation: literal X1-X17, all Cc escapes, strict descriptor types and
  privacy, unchanged old decisions, supplemental body refusal, full observed
  span/manifest/artifact correspondence, global projection admission and read
  accounting, independent recomputation, stale complete-reference refusals.
- Later request/response: deterministic IDs and identities, raw verified
  response closure, dual-arm sealer refusals, honest truncation and shared
  costs, exact bank and record caps, old v1 parity.
- Later report: strict schema, all task/arm/repeat cells, unknown costs,
  unavailable/refused states, cleanup failure and public-safe serialization.
- Later pgvector: invocation-owned tables and exact cleanup, no new grants,
  import fences, order/ties, production-control parity, stale publication and
  index-not-selected behavior. Synthetic vectors prove SQL only; no
  cross-backend accepted-reference equality is attempted.

Branch recovery: before writing regression tests, take the CI139 hosted
coverage artifact's missing-arc list for the touched/adjacent owners
(`retrieval_evaluation_admission_w5.py`, `publication_binding.py`,
`projection_build.py`, `_store_filesystem.py`, `semantic_candidate_sql.py`,
`semantic_candidates.py`, `w5_experiment_postgres.py`,
`w5_semantic_store_support.py`) and add behavior-level
tests for real failure branches there, aiming at the 22 unit / 502
integration arc shortfalls. This design does not claim which arcs are missing;
the mapping is recorded in the implementation exit. No denominator, threshold
or policy change and no assertion padding. Hosted CI alone measures margins.

No complete local suite, smoke, staging, system or coverage run is authorized.

## 12. Implementation and execution gates

- P0 is resolved: the operator explicitly approved document-only generation 2.
  The class/allocation remain unchanged and declaration 1 stays stopped.
- P1 is resolved at source: both accepted-evidence readers exist. The new
  support companion must prove row/span correspondence in both backend tests;
  actual missing spans exclude pairs without fallback.
- P2: use the current PostgreSQL compact adapter plus the published capture
  inputs. Any missing/stale receipt or artifact closure refuses; no backend copy.
- P3 task-side floor is resolved: four fixed generation-1 ranked queries pass
  the declared body policy. Repeat actual-publication admission before reads.
- P4: one study/cluster hosts both generations sequentially (section 8.6).
- P5: freeze actual retained timing inputs, unchanged worker deadlines and the
  disclosed work estimate before learned reservation; no longer timeout.
- P6 inert availability is resolved: all 30 model artifacts match retained
  hashes and the existing native ARM SDK matches its retained/current recipe.
  Fresh conditional artifact/license/security/runtime admission still precedes
  execution; no substitution, SDK/application build or new acquisition.
- Each implementation epic needs a conforming independent design checkpoint
  and parent acceptance of its owned contract. Source proof, final composed
  review and all runtime gates precede the single learned attempt.

## 13. Residual technical proof

B-AUTH is closed by the operator's explicit floor amendment. No new reserved
input/runtime class, dependency or budget is proposed. Technical correctness
and observed execution are still unaccepted. Missing source correspondence,
body authority, admitted documents, defensible timing, conditional runtime
admission or safe cleanup remain hard stops under the protocol.

The foundation epic (admission, captured readers, descriptors, encoding and
census) is independent of model execution and does not select a production
import policy. Its exact source/test ownership is accepted separately from
the later comparison/sealing/report epic contracts. No intermediate public CI
or completion claim is made for this technical preparation.

## 14. What would make this design wrong

- `check_correspondence` or `store.read` can pass without full-object
  verification for the calibration store type.
- `canonical_evidence` spans are not populated for observed rows, or are
  byte or zero-based rather than one-based inclusive lines.
- On files that pass the section 6.3 line-convention guard, extractor line
  numbers are still not 1-based LF/CRLF lines (for example, an extractor
  counts some other byte as a break).
- The maintained `build_captured_text_projection` reads bodies outside its own
  pre-open policy, or its `raw_line_count` does not follow
  `projection_text.py:20-24`.
- A calibration vector can only be observed through the production importer,
  so the study v1 batch route (study contract section 8) cannot carry the v1 arm.
- Any item in [study contract section 16](cloe-public-text-study-v1.md#16-what-would-make-this-contract-wrong).
- The worker or kernel rejects text this encoder emits, or changes behavior
  for long inputs beyond disclosed truncation.
- The disposable owner lacks `CREATE` on `repomap_enrichment` in the actual
  harness, or study reads need a new grant.
- The combined request cannot fit unchanged caps, or the estimate fails.
- Reusing `admit_w5_task` changes any serialized v1 decision.

## 15. Incremental acceptance

Implement the model-independent foundation only after its own conforming
checkpoint and parent acceptance. Comparison/request/sealing/SQL and strict
reporting are subsequent connected epics with their own technical and source
proof. Batch the accepted epics for a substantial final public milestone;
this decomposition grants no intermediate CI, extra allocation or new class.
