# Public-text study implementation contract

Status: independently reviewed technical contract, with parent dispositions
below. Source implementation and native execution remain separate gates.
Date: 2026-11-11. Phase: `REPOMAP-CLOE-PUBLIC-TEXT1`. Source baseline:
`c31fdfbc6bd7c65df75b1e473be2a3f0134233be`.

This document is the canonical owner of the remaining technical contract:
selected-task loading, the dual-arm request, the study-only seal, study SQL,
observed ANN, fusion/grading, the report, the native envelope and their proof
selectors. [ADR0182](../adr/2026/11/0182-public-text-semantic-calibration.md)
and [declaration 2](cloe-public-text-calibration-implementation-v1.md) keep
the authority, history and allocation. The
[foundation contract](cloe-public-text-foundation-v1.md) keeps the accepted
admission/capture/descriptor/census interfaces. Where implementation-design
sections 7–11 still describe the earlier draft of these subjects, they point
here, and this document governs.

Foundation source is accepted with scoped proof. Independent technical review is complete. The parent disposed its concrete
findings in sections 3, 10, 11, 13–15 below before source implementation.
Resulting-source review and native admission remain required. It grants no extra worker,
materialization, retry, dependency, runner class, image build, build trigger
or publication. It executes nothing. Old module behaviour, the 24 fixed tasks,
their golds and queries, and the three repetitions are unchanged.

## 0. Decisions frozen here

| Subject | Decision | Section |
|---|---|---|
| Task source | Selected-only loader over the hash-pinned raw catalog; 24 calibration records decoded, no held-out object | 3 |
| Request | One unchanged `cloe-w5-native-generation-request-v1` per generation; four ordered partitions; caps apply to the combined request | 4 |
| Seal | New study-only seal over a real `VerifiedWorkerResponse`; no production artifact, no old sealer | 5 |
| Truncation | v1 keeps its original own-record refusal; v2 keeps all vectors as `token_partial`; five distinct completeness facts | 6 |
| Cost | Per-arm records/bytes/tokens derived exactly; shared timings once; per-arm time unknown | 7 |
| SQL | One batch + one entry relation per study under the existing HNSW owner in `repomap_enrichment`; per-batch owned HNSW index | 8 |
| ANN | One psql transaction: `EXPLAIN ANALYZE` of a TEMP CTAS, then the exact materialized rows | 9 |
| Fusion | v2 enters the unchanged RRF only as validated `raw_file_hits`; new typed serializer | 10 |
| Report | `cloe-public-text-calibration-v1`; 12 arms x 24 tasks x 3 repetitions = 864 cells; 32 MiB cap | 11 |
| Lifecycle | One cluster, g1 to g2, explicit state machine, exact cleanup | 12 |
| Native | Original bridge, deadlines 550/600/120/600, frozen estimate | 13 |
| Privacy | Disposition of source-review-2 findings F1–F5 before learned corpus inspection | 14 |
| Proof | Exact new owners and selectors | 15 |

## 1. Verified existing APIs (unchanged; line references at the baseline)

- `parse_worker_request` (`tools/retrieval_semantic_generator_worker_protocol.py:125-184`)
  accepts exactly `schema, attempt_id, input_identity,
  representation_report_identity, publication_identity,
  artifact_profile_identity, records`. It requires 1–500 records of exactly
  `{record_id, text, mode}`, unique ids of at most 512 characters, mode
  `document|query`, and no C0 or DEL characters. Kernel validation adds
  `MAX_RECORD_TEXT_BYTES` 1 MiB, `MAX_TOTAL_TEXT_BYTES` 8 MiB and
  `MAX_RECORD_ID_BYTES` 512 (`retrieval_semantic_generator_kernel_contracts.py:24-29`).
  The request has no representation-version field.
- `parse_verified_worker_response` (`retrieval_semantic_generator_output_parser.py:30-309`)
  joins the request, report, terminal, declaration, manifest and archive
  hashes. It requires `terminal.status == "completed"`, a three-way
  source-closure equality and archive inputs equal to the raw request. It then
  returns a `VerifiedWorkerResponse` with `_sealed_identity`.
  `_parse_generation` (`retrieval_semantic_generator_output_receipt.py:245-389`)
  already checks the following:
  - 384 finite values per vector;
  - exact `int` token fields, with `bool` excluded;
  - `before > 0`, `used == min(before, 512)` and
    `truncated == (overflow > 0) == (before > 512)`;
  - `input_records`, `input_bytes` and `model_input_bytes` (with
    `QUERY_PREFIX`), plus non-negative finite seconds and
    `total >= load + inference - 1e-6`;
  - `status == "partial"` iff `partial`.

  It does **not** check the following, and the study seal must add these
  checks:
  - unit norm;
  - aggregate `token_count_before_limit`, `token_count_used`,
    `overflow_chunks` and `truncated_records` against the per-record sums;
  - `partial == any(truncated)`.
- The production `seal_generation_result` (`retrieval_semantic_generator_output.py:172-349`)
  performs exactly those added checks (232-288), but only for one v1
  `PublicGenerationInput` (186-194, 207-209). `GeneratedEnrichmentArtifact.require_importable`
  refuses any truncation (56-62). Both stay byte-unchanged.
- `SemanticCost` (`retrieval_semantic_generator_kernel_contracts.py:75-86`) has
  three timing fields, which are shared across all records.
- `execute_sql`, `_output` and `_json_object` (`src/test/support/python/repomap_test_support/w5_experiment_postgres.py:78-105`)
  each start a new `psql` process. `install_candidate_schema` (134-163)
  creates the three disposable roles and the enrichment schema. It gives
  `repomap_w5_hnsw_owner` table ownership, `USAGE, CREATE` on
  `repomap_enrichment`, vector usage and execute, and `SELECT` on five
  canonical tables.
- Production import (`semantic_candidate_import.py:110-189`) and exact query
  (`semantic_candidate_sql.py:42-124`) are v1-only.
  `CHECK (representation_version = 'canonical-node-v1')` is at import.py:71
  and the unit-norm check at 91.
- The existing HNSW SQL (`tools/retrieval_semantic_ann_sql.py:244-395`) hard-codes
  `repomap_enrichment.embeddings` and `rebuilds`. It freezes
  `REPEATABLE READ READ ONLY`, `hnsw.ef_search = 40` and
  `hnsw.iterative_scan = strict_order` (364-369). It also explains and reads
  in two separate statements (372-395). The study does not inherit that
  pairing.
- `fuse_arm_observations_rrf` (`tools/retrieval_semantic_fusion.py:152-268`)
  accepts `AdmittedArmObservation.raw_file_hits`. That path
  (`retrieval_semantic_arm_validation.py:275-288`) checks the
  `FileIdentityTuple`, denied/admitted/selected bindings and the snapshot. It
  never calls `canonical_node_v1_digest`; only the `vector_candidates` path
  does (308-309). `FileFusionResult.to_dict` labels every result
  `canonical-node-v1` (fusion.py:104-107).
- `compute_file_level_ranking_metrics` and `assert_calibration_split_only`
  are at `retrieval_semantic_file_projection.py:29-36` and 202-242.
- Reusable primitives: `verify_raw_component` (`retrieval_semantic_raw_component.py:34-74`);
  `validate_binding`, `validate_counts` and `validate_component`
  (`retrieval_semantic_component_dossier_contract.py:38-90`);
  `MAX_DOSSIER_BYTES = 64 KiB`; `canonical_json_bytes`, `digest_json` and
  `ExperimentCell`; `EXPERIMENT_ARMS` and `TIMEOUT_POLICY`
  (`retrieval_semantic_experiment_contracts.py:24-39`). The report size cap
  comes from `MAX_REPORT_BYTES` (32 MiB), via `MAX_PAIR_REPORT_V2_BYTES`
  (`retrieval_semantic_pair_v2_report.py:41`).
  `validate_component_dossier` (dossier_contract.py:93-123) fixes the two
  `w5-semantic-g{n}` generations and the old schema. It is the historical top
  factory and is not reused.

## 2. New source and test owners

Each new source file has at most 400 physical lines, uses only the standard
library plus existing repository modules, and adds no dependency, parser
framework, runner option or `src/main` change.

| Owner | Contents |
|---|---|
| `tools/retrieval_public_text_tasks.py` | section 3 pins and loader |
| `tools/retrieval_public_text_request.py` | section 4 dual-arm input and request bytes |
| `tools/retrieval_public_text_response.py` | section 5–7 seal, truncation, cost |
| `tools/retrieval_public_text_study_schema.py` | section 8 names, study identity, study profile, refusal codes, table DDL and the pure catalog SQL expressions (child item grammar, fingerprint, owned-index catalog query) |
| `tools/retrieval_public_text_study_catalog.py` | section 18.2 relation readback and creation record, `StudyCatalog` inventory fence and index registration, owned-index DDL and catalog check, cleanup and per-object absence SQL |
| `tools/retrieval_public_text_study_queries.py` | section 8 batch validation and import SQL; section 9 exact/ANN statements, payload check and plan-node check |
| `tools/retrieval_public_text_fusion.py` | section 10 v2 projection, v1 arm label, fusion composition, typed serializer, grading |
| `tools/retrieval_public_text_report_cells.py` | section 11 cell grammar and count algebra |
| `tools/retrieval_public_text_report_contracts.py` | section 18.4 closed report schemas, codes, disclosures and the functional marker |
| `tools/retrieval_public_text_report_joins.py` | section 18.4 generation/cell/cleanup joins and section 18.5 evidence-context verification |
| `tools/retrieval_public_text_report.py` | section 11 builder/writer/reader and census/preparation/request/component/seal adapters |
| `src/test/support/python/repomap_test_support/w5_public_text_postgres.py` | psql execution; sealed-entry joins (`v1_entries`, `v2_entries`, `sealed_batch`); exact read; ANN transaction SQL, five-record parse and classification; cleanup runner |
| `src/test/support/python/repomap_test_support/w5_public_text_artifacts.py` | section 18.6 synthetic study inputs and raw seven-member protocol artifacts, parsed only by the unchanged parser |
| `src/test/support/python/repomap_test_support/w5_public_text_study.py` | section 12 state machine driver (section 19) |
| `src/test/support/python/repomap_test_support/w5_public_text_journal.py` | section 11 canonical component journal adapter and the section 19 failure receipt |
| final-driver owners | the twelve owners and their unit owners named in section 19.1 |

Source-owner correction (resulting-source windows): the 400-line ceiling
moved import SQL to the queries owner and the five-record parser to the
support owner. Retrieval repair 2 (section 18) then moved the catalog
readback, fences, index catalog and cleanup/absence SQL into the new catalog
owner, and the report's closed schemas and joins into two report helper
owners. Each helper has a matching unit owner. Contracts are otherwise
unchanged except where section 18 states a correction.

The foundation follow-up delta (section 14) changes only these existing
foundation owners: `retrieval_public_text_privacy.py`,
`retrieval_public_text_excerpt.py`, `retrieval_public_text_admission.py`,
`retrieval_public_text_contracts.py`, `retrieval_public_text_descriptors.py`
and `retrieval_public_text_census.py`. The section 1 owners, the generic
worker and its closure, the parser/receipt/sealer, fusion, file projection,
production SQL, `w5_experiment_postgres.py`, fixtures, the task catalog,
dependencies and the runner stay unchanged.

## 3. Selected-only task loader

`load_task_catalog` and `TaskCatalog.from_mapping`
(`tools/retrieval_evaluation_schema.py:241-250`) decode all 36 tasks, including
the 12 held-out tasks. They are not called.

```python
TASK_PINS_SCHEMA = "cloe-public-text-selected-task-pins-v1"
CATALOG_FILE_SHA256 = "10a34e261ee625dbfffb31e30d450bca270878291890f165e6031a86b3bf6d38"
HISTORICAL_SEMANTIC_CATALOG_IDENTITY = "sha256:8da52c1a477a78ba5f467892690e2f59045326d18ba371d693dda157736a80a1"
ORIGINAL_MANIFEST_SHA256 = "33b417da06658f8aac3be851d4df5ad3655b2cbd1157d2009b0da65cbffa1155"
SELECTED_TASKS: tuple[tuple[str, int, str], ...]  # the 24 registered (task_id, generation, task_sha256), verbatim

@dataclass(frozen=True)
class SelectedTaskPins:  # closed; held_out_decoded must be False
    catalog_file_sha256: str; historical_semantic_catalog_identity: str
    original_manifest_sha256: str; tasks: tuple[tuple[str, int, str], ...]
    def identity(self) -> str  # digest_json of the closed mapping

@dataclass(frozen=True)
class SelectedTaskSet:
    pins: SelectedTaskPins
    tasks: tuple[EvaluationTask, ...]  # pin order
    def for_generation(self, generation: int) -> tuple[EvaluationTask, ...]
    def retained_digests(self, generation: int) -> dict[str, str]

class TaskSelectionRefusal(ValueError): code: str  # closed codes below
def parse_task_pins(raw: bytes) -> SelectedTaskPins
def load_selected_calibration_tasks(catalog_path: Path, pins: SelectedTaskPins,
                                    *, max_bytes: int = 4 * 1024 * 1024) -> SelectedTaskSet
```

The pins equal the registered task-pins input. That input has 24 ids,
`cal-01`..`cal-24`, all in generation 1 except `cal-23`, which is generation
2. A unit test compares the module constants with `parse_task_pins` of that
input shape.

The raw byte hash and the historical semantic identity are distinct schemes.
The loader recomputes only the raw byte hash. It carries the historical
identity under its own name, and never recomputes it or compares it with the
raw hash.

Algorithm:

1. Open the catalog with `O_NOFOLLOW`, require a regular file, and read at most
   `max_bytes + 1` bytes. `fstat` must agree before and after the read.
   Require `sha256(raw) == CATALOG_FILE_SHA256`.
2. Run a byte-level structural locator. It is not a value parser and never
   builds a Python value for an unselected element. It tracks only JSON
   string and escape state and object/array depth (maximum depth 64), and
   refuses control bytes inside strings. Requirements:
   - one top-level object with no duplicate keys;
   - `schema_version` decoded as one JSON string and equal to
     `TASK_CATALOG_SCHEMA_VERSION`;
   - exactly one `tasks` array whose elements are objects;
   - locate each element's top-level `task_id` string token lexically;
     compare its raw bytes with the canonical ASCII JSON encodings of the
     24 selected ids. Never JSON-decode any unselected token or body.
     Escaped selected-id tokens cannot match the fixed hash-pinned catalog.

   A non-selected token is compared and discarded. It is never stored, logged or
   counted in any output. Every other byte, including all held-out bodies, is
   skipped lexically. A missing or duplicate selected id, a non-string
   `task_id` or trailing non-whitespace refuses.
3. Decode each selected span, in pin order, with `json.loads`. Use a
   duplicate-refusing `object_pairs_hook` and a `parse_constant` that refuses.
   Then require:
   - `EvaluationTask.from_mapping` succeeds (schema.py:162-187);
   - `split == "calibration"`;
   - `generation` equals the pinned generation;
   - `retrieval_public_text_census.retained_task_sha256(task)` equals the pinned ASCII-scheme digest.
4. Re-read the file and require the same hash and `fstat` identity.

Closed codes: `task_pins_invalid`, `task_catalog_unavailable`,
`task_catalog_changed`, `task_catalog_hash_mismatch`, `task_catalog_structure`,
`task_selected_missing`, `task_selected_duplicate`, `task_selected_invalid`,
`task_split_mismatch`, `task_generation_mismatch`, `task_digest_mismatch`.

The retained task scheme is sorted compact JSON with `ensure_ascii=True`;
the original v1 query scheme uses `ensure_ascii=False` and UTF-8. Both have
`allow_nan=False` and no trailing LF. The census keeps its existing
`task_sha256` (v1) and adds `retained_task_sha256`; loader/pins/task-set use
the retained digest. Request correspondence checks each separately and its
manifest names and binds both maps. cal-20 proves the distinction. Neither
original task bytes nor registered pins nor v1 decisions change.

Gold values are used only by the trusted grading step after inference. Gold
and question values never influence document selection, request size, order
or applicability. The native request contains only document texts and the
admitted original generation-1 query texts, up to four from the fixed candidate
set. At least one admitted public-text query is required; none is added in
generation 2.

## 4. Dual-arm request

```python
DUAL_ARM_INPUT_SCHEMA = "cloe-public-text-dual-arm-input-v1"
ARM_V1, ARM_PTX = "canonical-node-v1", "canonical-node-public-text-v2"
PARTITIONS = ("v1.document", "ptx.document", "v1.query", "ptx.query")

@dataclass(frozen=True)
class DualArmRecord:
    record_id: str; arm: str; mode: SemanticMode
    source_identity: str            # v1 doc: v1 input_digest; ptx doc: descriptor identity; query: task_sha256
    v1_record_id: str | None        # original v1 id for v1 records
    task_id: str | None

@dataclass(frozen=True)
class DualArmInput:
    generation: int; attempt_id: str; study_identity: str
    v1: PublicGenerationInput; preparation: PublicTextPreparation
    census: PublicTextCensus; tasks: SelectedTaskSet; pin: VerifiedPublicationPin
    records: tuple[SemanticText, ...]; layout: tuple[DualArmRecord, ...]
    input_identity: str; representation_report_identity: str
    publication_identity: str; artifact_profile_identity: str
    def manifest(self) -> dict[str, object]   # public; no text

def build_dual_arm_input(*, generation, attempt_id, study_identity, v1_input, preparation,
                         census, tasks, publication_pin, artifact_profile_identity) -> DualArmInput
def encode_dual_arm_request(value: DualArmInput) -> bytes
```

- **v1 arm.** Use the unchanged `PublicGenerationInput`. Every v1 record keeps
  its original text and mode byte-for-byte. Its id becomes
  `"v1." + original_record_id`, which keeps the original id recoverable.
  These ids supersede the draft `v1.d.NNNN` form.
- **v2 documents.** Id `ptx.d.NNNN`, a four-digit ordinal in
  `preparation.documents` order. The text is `PublicTextDocument.model_text`.
- **v2 queries.** Id `ptx.q.<task_id>`, only for census tasks with
  `public_text_state == "admitted"`. The text is byte-identical to that task's
  v1 query text, and the record is separate.
- **Order.** The four partitions in the order above. No task is relabelled.
  Generation 2 contains documents only.
- **Identities.**
  - `input_identity = digest_json(manifest)`. The manifest binds the schema,
    phase, generation and `study_identity`. For v1 it binds `input_identity`
    and `representation_report_identity`. It binds the preparation identity
    `digest_json(preparation.to_dict())`, the `census_identity`, the
    `privacy_scope_id`, the task-pin identity and both catalog identities.
    It binds the current PostgreSQL pin `digest_json(pin.to_dict())`, the
    partition map and the version strings. Finally, for each record it binds
    `[record_id, arm, mode, sha256(text), source_identity]`.
  - `representation_report_identity = digest_json({"v1": ..., "public_text": preparation identity})`.
  - `publication_identity = preparation.publication_identity`. The builder
    requires `v1.provenance.to_dict() == pin.to_dict()`.
  - `artifact_profile_identity` is unchanged.
- **Bytes.** Encode with
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`.
  The builder round-trips the bytes through the unchanged
  `parse_worker_request` and requires equal records.
- **Caps.** The combined request must stay within 500 records, 8 MiB request
  bytes, 1 MiB per text, 8 MiB total text and 512 bytes per id. Any breach
  stops before reservation. There is no split, filter or hidden partition.
  The worst case is 80 + 80 documents + 8 queries, which is far inside the
  caps (declaration-2 section 7 arithmetic).

The generic request schema, worker, kernel, `WORKER_SOURCE_FILES` and source
closure stay unchanged.

## 5. Study-only seal

```python
@dataclass(frozen=True)
class SealedRecord:
    record_id: str; arm: str; mode: SemanticMode; source_identity: str
    vector: tuple[float, ...]; token_count_before_limit: int; token_count_used: int
    overflow_chunks: int; truncated: bool

@dataclass(frozen=True)
class ArmSeal:
    arm: str
    capability: Literal["complete", "token_partial", "refused"]
    refusal: str | None
    records: tuple[SealedRecord, ...]
    counts: Mapping[str, int]          # records, documents, queries
    exact_cost: Mapping[str, int]      # section 7
    truncated_document_identities: tuple[str, ...]
    truncated_query_task_ids: tuple[str, ...]
    publication_coverage: Literal["complete", "partial"]

@dataclass(frozen=True)
class StudyGenerationSeal:
    generation: int; attempt_id: str; response_identity: str
    receipt_digests: Mapping[str, str]  # request/report/terminal/declaration/manifest/archive/admission
    input_identity: str; representation_report_identity: str
    publication_identity: str; artifact_profile_identity: str
    global_status: Literal["complete", "partial"]; global_partial: bool
    shared_cost: SemanticCost; arms: Mapping[str, ArmSeal]; seal_identity: str

class StudySealRefusal(ValueError): code: str
def seal_dual_arm_result(expected: DualArmInput, response: VerifiedWorkerResponse,
                         *, refresh: Callable[[], DualArmInput], scope: PrivateMarkerScope
                         ) -> StudyGenerationSeal
```

Checks run in this order. The first failure refuses the whole generation; the
attempt is retained and never repaired.

1. `type(response) is VerifiedWorkerResponse`, `status == "completed"`, and
   `response._sealed_identity == _response_identity(response)`. This is the
   same comparison as output.py:182-185. No `VerifiedWorkerResponse` is
   constructed. (`study_response_identity`)
2. `response.request_records == expected.records`, including text and mode.
   `attempt_id` and the four request identities must be equal.
   (`study_request_mismatch`)
3. Rebuild the expected input through `build_dual_arm_input` from its
   actual owner objects. Require identical manifest, input identity, layout
   and records; a stored identity string alone cannot authenticate a changed
   layout. Then current revalidation from `refresh()`:
   - `expected.v1.require_current()` succeeds;
   - `require_unchanged_recomputation(expected.preparation, fresh.preparation, scope=scope)`
     succeeds;
   - the fresh `input_identity`, pin `to_dict()`, task-set identity, layout
     and records are equal.

   (`study_current_revalidation_failed`, `study_descriptor_set_changed`)
4. `response.generation` is a `SemanticGeneration`. The record, embedding,
   document and query counts equal the layout. (`study_record_identity_mismatch`)
5. Per record, in strict zip order:
   - id and mode are equal;
   - `checked_vector(vector, 384)` succeeds (finite unit vector; same
     function as output.py:244);
   - token fields are exact `int` (so `bool` is refused), with
     `before > 0`, `used == min(before, 512)`, `overflow >= 0` and
     `truncated == (overflow > 0) == (before > 512)`.

   (`study_vector_invalid`, `study_token_invariant`)
6. Aggregate reconciliation against `generation.cost`:
   - `input_records == N`;
   - `input_bytes` and `model_input_bytes` recomputed from `expected.records`
     with `QUERY_PREFIX` on queries;
   - `token_count_before_limit`, `token_count_used` and `overflow_chunks`
     equal the per-record sums;
   - `truncated_records` equals the count of `truncated`;
   - `partial == (truncated_records > 0)` and `status` matches;
   - seconds are finite and non-negative, with `total + 1e-6 >= load + inference`.

   (`study_cost_records`, `study_cost_bytes`, `study_cost_tokens`,
   `study_partial_state`, `study_cost_seconds`)
7. Split by layout. Each arm's records are one-to-one with its expected
   records, and v1 ids map back to the original v1 ids. (`study_arm_coverage`)
8. Apply section 6 per arm.
9. `seal_identity = digest_json` of the public seal mapping, which has no text
   and no vectors.

The seal never calls `seal_generation_result`, never constructs
`GeneratedEnrichmentArtifact`, never builds a v2 `EmbeddingProfile`, and never
omits fields to pass an old check. Negative unit cases mutate every aggregate
field, because the raw parser alone accepts those mutations.

## 6. Token truncation and the five completeness facts

The worker truncates at 512 tokens. A combined request may legitimately carry
truncated records, so this contract resolves the result per arm:

- **v1 arm.** If any v1 record is truncated, the v1 arm is `refused` with
  `v1_own_record_truncated`. This matches the original
  `incomplete_generation_cannot_import` rule (output.py:56-62). The study
  imports no v1 vector for that generation, and all of its v1 cells are
  refused with that reason. Per-record flags stay in the seal.
- **v2 arm.** If any v2 record is truncated, the arm is `token_partial`. Every
  returned vector is retained and imported, and models the fixed 512-token
  prefix. Every v2 exact, ANN and fusion cell carries
  `capability: "partial"`, `incomplete: true` and `truncated: true`. The
  generation's v2 `scope_status` is `"incomplete"`. Truncated documents
  (descriptor identities) and truncated queries (task ids) are listed
  separately. No complete, untruncated or scientific claim is possible. If no
  v2 record is truncated, the arm is `complete`.
- The global `partial` and `status` are stored verbatim. They are never
  changed, and no vector is silently dropped.

The report keeps these five facts separate, and none is derived from another:

1. `worker_terminal`: `completed | failed | not_run`.
2. `records_returned`: `{"value": embedding_count == record_count}`.
3. `token_partial`: per arm, from that arm's own records.
4. `publication_coverage`:
   - v1 comes from `PublicGenerationInput.partial_publication_coverage`;
   - v2 is `partial` when the preparation has any exclusion or when
     `document_count < v1_verified_pair_count`.
5. `retrieval_truncated`: per cell, from query `limit`/`ann_scan_limit`, the
   arm candidate cap (`MAX_ARM_CANDIDATES`) or the fusion `max_results` cap.

## 7. Cost attribution

- **Per arm, exact.** `records`, `documents`, `queries`, `input_bytes` (the
  actual study id plus text UTF-8 bytes), `model_input_bytes`,
  `token_count_before_limit`, `token_count_used`, `overflow_chunks` and
  `truncated_records` are summed from that arm's verified records. The two
  arms' sums must equal the global `SemanticCost` field by field, and this is
  asserted.
- **Shared once.** `load_seconds`, `inference_seconds`, `total_seconds` and
  the report `elapsed_seconds` sit in one `shared` object that both arms
  reference. `SemanticCost` itself keeps its original three timing fields.
  The report owner reads `elapsed_seconds` from the actual raw component
  report, validates it and joins its digest to the seal; absent is unknown,
  never zero or inferred from the other timings.
- **Per arm, unknown.** Time is `{"unknown": "shared_worker_cost"}`. Opaque
  device, database and network I/O is `{"unknown": "not_observed"}`.

No proration exists, and no estimate is labelled measured. This supersedes
the declaration-2 statement that token counts are shared: they are per-record
fields of the verified response.

## 8. Study SQL schema and ownership

The schema below is a set of rules, not a list of options. Every statement
runs as `repomap_w5_hnsw_owner` (`DEFAULT_OWNER_IDENTITY`) in the existing
`repomap_enrichment` schema, through the role prefix `SET ROLE "<owner>";` in
one `run_psql` process per step. The unchanged `install_candidate_schema` may
create its standard disposable roles and schemas. The study adds:

- no role, `GRANT`, `REVOKE`, schema, extension, default privilege or harness
  policy;
- no production SQL, profile or `src/main` change;
- no `IF NOT EXISTS`, `CASCADE`, `ALTER ... OWNER` or `ANALYZE`.

The reader and writer roles never receive study access.

**Names.**
- `study_identity = digest_json({"schema": "cloe-public-text-study-v1",
  "phase", "allocation": "PUBLICTEXT-CAL1", "declaration": 2,
  "task_pins_identity", "q_source_closure", "nonce": 32 random hex})`.
- `h = sha256(study_identity + "|" + owner)[:24]` (hex).
- The relations are `repomap_enrichment.ptx_batch_<h>` and
  `repomap_enrichment.ptx_entry_<h>`.
- `batch_id = "ptx1-g<g>-<v1|ptx>-" + sha256(study_identity|g|arm)[:16]`.
- The per-batch index is `ptx_hnsw384_<sha256(study_identity|batch_id|owner)[:32]>`.

**`ptx_batch_<h>` columns.**
- Text columns: `batch_id` (primary key), `study_identity`, `arm`,
  `repository_identity`, `receipt_identity`, the four receipt generations,
  `publication_bundle_id`, `snapshot_manifest_id`, `profile_identity`,
  `model`, `model_version`, `generator`, `generator_version`,
  `representation_version`, `normalization`, `metric`, `privacy_class`,
  `input_identity`, `seal_identity` and `capability`.
- `generation integer`, `run_id bigint`, `dimensions integer`,
  `row_count integer`.
- Checks: `arm IN (v1, v2 labels)`, `representation_version = arm`,
  `generation BETWEEN 1 AND 2`, `run_id > 0`, `dimensions = 384`,
  `normalization = 'l2-unit'`, `metric = 'cosine'`,
  `privacy_class = 'public'`, `capability IN ('complete','token_partial')`,
  `NOT (arm = v1 AND capability <> 'complete')`,
  `row_count BETWEEN 1 AND 500`, and digest patterns on `input_identity` and
  `seal_identity`.
- Unique: `(batch_id, arm, dimensions)` and
  `(study_identity, generation, arm)`.

**`ptx_entry_<h>` columns.**
- `batch_id`, `arm`, `canonical_key`, `source_binding_id`, `snapshot_id`,
  `input_digest`, `descriptor_identity`, `truncated boolean`,
  `dimensions integer` and `embedding repomap_vector.vector`.
- Primary key: `(batch_id, canonical_key, source_binding_id)`.
- Foreign key: `(batch_id, arm, dimensions)` references the batch unique key.
- Checks: a digest pattern on `input_digest`;
  `(arm = v1 AND descriptor_identity IS NULL AND NOT truncated) OR
  (arm = v2 AND descriptor_identity IS NOT NULL AND descriptor_identity ~ digest)`
  (section 18.1); `vector_dims = dimensions`;
  and `abs(vector_norm - 1) < 0.00001`.

**Profiles.**
- The v1 arm uses the production `EmbeddingProfile` exactly as the old sealer
  builds it (output.py:324-330). That profile is v1, so no allowlist changes.
- The v2 arm uses
  `StudyEmbeddingProfile(model, model_version, generator, generator_version,
  representation_version=ARM_PTX, normalization, metric, dimensions=384)`.
  Its identity is
  `digest_json({"schema": "cloe-public-text-study-profile-v1", **fields})`.
  It is never passed to production builders.

**Creation.** One transaction, `BEGIN ISOLATION LEVEL SERIALIZABLE`:

1. A `DO` block refuses unless `current_user` is the owner.
2. The same block refuses unless
   `has_schema_privilege(current_user, 'repomap_enrichment', 'CREATE')`.
3. The same block refuses unless both `to_regclass` lookups return NULL
   (before-absence).
4. Two `CREATE TABLE` statements.
5. `COMMENT ON TABLE`, setting each comment to
   `'cloe-public-text-study:v1:' || study_identity || ':batch'` or `':entry'`.
6. One JSON readback, then `COMMIT`.

The readback returns, per relation: OID, schema, name, owner name, `relkind`,
`relpersistence`, the comment, and a `definition_sha256`. The fingerprint is
`sha256` over the ordered `attname|format_type|attnotnull` rows plus the
sorted `pg_get_constraintdef` rows.

Python requires:
- owner equals the owner role;
- `relkind = 'r'` and `relpersistence = 'p'`;
- the exact comment;
- the exact column `(name, type)` tuple above;
- the exact constraint-kind multiset.

It records the creation identity (OIDs plus fingerprints) privately in the
study ledger. All later fences compare against that record.

**Import.** One transaction per batch, mirroring production import.py:148-188:

1. A `DO` fence: `current_user`, the accepted publication
   (`accepted_candidate_publication_sql`), and relation OIDs, owners,
   comments and fingerprints equal to the creation record.
2. Insert the batch row.
3. `INSERT ... SELECT` entries with the same `canonical_nodes` and
   evidence-existence predicate as production. The predicate checks the
   current run, repository, binding and snapshot.
4. A `DO` count check: the batch's entry count equals `len(entries)`, which
   equals `row_count`. Otherwise `RAISE`, which rolls back the whole batch.
5. `COMMIT`.

Before any SQL is issued:
- v2 entries must equal sealed descriptors in `canonical_key`,
  `source_binding_id`, `snapshot_id`, `input_digest` and descriptor identity.
  The snapshot must also equal `pin.snapshot_by_binding()`.
- v1 entries use the v1 representation `input_digest`.

Values use `sql_literal`. Identifiers are fixed-pattern only; no caller SQL,
table or role is accepted.

**Index.** After each batch import there is one owned partial index:

```sql
CREATE INDEX "<index>" ON repomap_enrichment."ptx_entry_<h>" USING hnsw
  ((embedding::repomap_vector.vector(384)) repomap_vector.vector_cosine_ops)
  WHERE batch_id = '<batch_id>' AND dimensions = 384;
```

It uses default build parameters. It gets the comment
`cloe-public-text-study:v1:<study_identity>:hnsw:<batch_id>`. A catalog
readback with the shape of `build_hnsw_index_catalog_sql` (study names)
checks:
- `hnsw` access method;
- `vector_cosine_ops` operator class;
- the exact expression and predicate;
- valid and ready;
- owner, comment and OIDs.

**Cleanup.** Cleanup is always attempted once creation has succeeded,
including on failure paths. It runs one transaction:

1. A `DO` fence re-reads every recorded index and both tables. Name, schema,
   OID, owner, comment and fingerprint must equal the record, and the complete
   child-object inventory must equal the recorded one before any drop
   (section 18.2).
2. `DROP INDEX ... RESTRICT` for each index.
3. `DROP TABLE ptx_entry ... RESTRICT`, then `DROP TABLE ptx_batch ... RESTRICT`.
4. `COMMIT`.

A separate readback then proves absence by both name and recorded OID.

- A fence mismatch drops nothing and records
  `cleanup_failed:relation_identity_changed`.
- A preexisting, foreign or replaced object is never dropped.
- If creation never committed, cleanup proves absence only.

Any cleanup failure blocks positive report acceptance. Docker resources
remain the canonical runner's own exact responsibility.

## 9. Exact and observed-ANN reads

**Exact.**
- Mirror `build_candidate_query_sql` (semantic_candidate_sql.py:42-124) with
  three substitutions:
  - study relation names;
  - the filters `batch.study_identity`, `batch.arm`, `entry.arm` and
    `batch_id`;
  - the study profile fields.
- Add one in-statement fence: if the catalog OID of each study relation
  differs from its recorded literal, the statement returns
  `study_relation_changed`.
- Distance, tie order, limit 20, evidence limit 5, evidence order and the
  accepted-link predicate are identical. The statuses are
  `stale_publication`, `enrichment_unavailable` and `ok`.
- The wrapper is
  `SET ROLE "<owner>"; BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; <statement>; COMMIT;`.
- Binding refusals go through the unchanged `_scope_for_query` semantics
  first.

**Observed ANN.** An ANN cell is credited only if the plan and the rows come
from the same execution. Each ANN observation is one `run_psql` process with
argv
`[psql_command, *psql_args, "-qAt0", "-v", "ON_ERROR_STOP=1"]`. The `-0` flag
makes the record separator NUL, so a multi-line JSON plan cannot be confused
with a result row.

```sql
SET ROLE "repomap_w5_hnsw_owner";
BEGIN ISOLATION LEVEL REPEATABLE READ;              -- read-write: the TEMP CTAS is DDL
SET LOCAL hnsw.ef_search = '40';                    -- existing frozen arm settings
SET LOCAL hnsw.iterative_scan = 'strict_order';
SELECT <preflight json>;                            -- record 1: TEMP privilege, OIDs, fingerprint
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
  CREATE TEMP TABLE ptx_ann_<16 hex> ON COMMIT DROP AS <study ANN statement>;  -- record 2
SELECT result FROM ptx_ann_<16 hex>;               -- record 3: the rows that execution produced
SELECT <postflight json>;                           -- record 4: OIDs, fingerprint, temp relpersistence 't'
COMMIT;
SELECT to_regclass('pg_temp.ptx_ann_<16 hex>') IS NULL;  -- record 5: dropped at commit
```

The study ANN statement mirrors `build_hnsw_ann_statement` (ann_sql.py:244-361)
with the section 8 relations and filters. It keeps an ORDER BY expression
identical to the index expression, `FETCH FIRST ann_scan_limit ROWS WITH TIES`,
and `ranked LIMIT query.limit`. Its single output column is named `result`.
The temporary name is
`ptx_ann_ + sha256(study_identity|batch_id|task|repetition)[:16]`. It is
private to the session and disposable cluster.

Outcomes:

- **TEMP privilege absent.** A separate preflight call first reads
  `has_database_privilege(current_database(), 'TEMP')`. If it is false, the
  cell is `unavailable/temp_privilege_absent` and nothing runs. No grant is
  ever added.
- **Output shape.** Exactly five NUL-terminated records are required.
  Otherwise the cell is `failed/ann_output_shape`.
- **Plan check.** Record 2 must be a one-element JSON list with `Plan`. The
  tree must contain a node with `Node Type` `Index Scan`,
  `Index Name == <owned index>`, `Relation Name == ptx_entry_<h>` and
  `Actual Loops >= 1`. Otherwise the cell is
  `unavailable/index_not_selected` and is not filled from exact results.
- **Fences.** Records 1 and 4 must match the creation record and the current
  publication. A mismatch is `refused/study_relation_changed`.
- **Result.** Record 3 is parsed like the existing ANN JSON. Status `ok` with
  at most `limit` candidates is `completed`. Any other known status is
  `unavailable/<status>`.
- **Default planner.** No `enable_*`, cost or statistics setting is applied,
  and no `ANALYZE` is run. Autovacuum is not controlled, so the plan is
  observed, not predicted. HNSW may remain unselected at this scale.

The plan bytes and result bytes are kept privately. Only their sha256 and
length are public.

Concrete API (resulting source): every study psql process also passes `-X`
and runs without inherited `PGOPTIONS`. Exact and ANN rows carry the
production columns plus `descriptor_identity` (NULL for v1). Records 1 and 4
are `{stage, current_user, temp_privilege, relations_unchanged,
index_unchanged, accepted, temp_persistence}`; any fence failure, including a
non-current publication, is `refused/study_relation_changed`. Classification
order is shape, fences, plan, result. A batch without a registered owned
index is always `unavailable/index_not_selected`; `observe_ann` takes no index
argument and the full child-object fence applies (section 18.3).

PostgreSQL 16 documents that `ANALYZE` executes the statement and keeps its
side effects, including `CREATE TABLE AS`. It also documents that CTAS
evaluates its query once and can drop a temporary table at commit.
Sources:
- [EXPLAIN](https://www.postgresql.org/docs/16/sql-explain.html)
- [CREATE TABLE AS](https://www.postgresql.org/docs/16/sql-createtableas.html)

This is documentation, not an executed-SQL claim. The method is selected only
after the section 15 pgvector proof runs the real transaction. That proof must
show that the rows in record 3 equal a recomputation over the same data, that
an index scan appears in the plan, and that the TEMP table is gone after
commit.

## 10. Fusion and grading

- **v1 vectors.** v1 exact and ANN candidates enter fusion through the
  unchanged `vector_candidates` path with `kind`, `display_name` and
  `input_digest` all present, so `canonical_node_v1_digest` runs.
- **v2 vectors.** `project_public_text_candidates(rows, *, preparation:
  PublicTextPreparation, seal: ArmSeal, pin: VerifiedPublicationPin,
  selected_binding_ids, scope: PrivateMarkerScope) -> tuple[tuple[FileIdentityTuple, int, str], ...]`
  (corrected: `ArmSeal` carries only descriptor identities, so the actual
  preparation descriptor map, its frozen scope and the task's selected
  bindings are explicit inputs) checks each row independently before any
  RRF code sees it; evidence must include the descriptor's `evidence_key`
  with a non-withheld path:
  - `(canonical_key, source_binding_id)` maps to one sealed v2 descriptor;
  - `input_digest`, `snapshot_id` and the descriptor snapshot are equal and
    match the pin snapshot;
  - the binding is admitted, not denied, and inside the task's selected
    bindings;
  - there is at least one evidence item whose metadata binding and snapshot
    match and whose path is not withheld.

  It then projects exactly as arm_validation.py:310-327 does, without the v1
  digest call. The result enters as `AdmittedArmObservation(arm_id, "vector",
  verified_pin=pin, raw_file_hits=..., incomplete=<v2 partial>,
  truncated=<v2 token_partial>)`.
- **Hybrid.** `hybrid_rrf:<representation>` has exactly two inputs:
  the current PostgreSQL native-FTS lexical observation and that
  representation's `exact_vector` observation. This preserves
  `w5_experiment_vector.run_vector_task` (lines 130–151) and
  `retrieval_semantic_experiment_evaluator.grade_vector_arm` (lines 241–254):
  `(lexical_arm, vector_arm)`. No native-filesystem, SQLite or captured
  reference arm is inserted into this fusion. All fusion calls the
  unchanged `fuse_arm_observations_rrf` with the actual
  `VerifiedPublicationPin`. `allow_explicit_single_arm_fallback` stays
  `False`, so a refusal is visible.
- **Concrete API.** v1 rows enter via `v1_vector_arm`, which calls the
  unchanged `build_candidate_rows_arm` and only relabels the arm
  `exact_vector:canonical-node-v1`/`hnsw_vector:canonical-node-v1`.
  `fuse_study_arms` accepts one vector arm or exactly
  (`postgres_native_fts:postgresql`, exact vector). `grade_fusion` returns the
  12 metrics or `None`.
- **Serializer.** `public_text_fusion_to_dict(result, *, representations:
  Mapping[str, str]) -> dict` emits `cloe-public-text-fusion-v1`. It has the
  `FileFusionResult` fields plus a per-arm `representation_version`, and no
  single top-level version. `FileFusionResult.to_dict` is never used for
  study output.
- **Grading.** Grading uses the unchanged `compute_file_level_ranking_metrics`
  with the task, so `assert_calibration_split_only` runs, and
  `DEFAULT_CUTOFFS` (1, 3, 5, 10). That yields 12 metric keys. Partial or
  truncated cells keep their flags. Grading never upgrades capability.
  Unknown is `null`, never zero.

## 11. Report `cloe-public-text-calibration-v1`

**Arms, closed and ordered (12).**
- The six incumbent `EXPERIMENT_ARMS` labels, verbatim: `native_tools_baseline`,
  `current_graph_baseline:sqlite`, `current_graph_baseline:postgresql`,
  `captured_projection_reference:sqlite`,
  `captured_projection_reference:postgresql`, `postgres_native_fts:postgresql`.
- Then `exact_vector:canonical-node-v1`, `hnsw_vector:canonical-node-v1`,
  `hybrid_rrf:canonical-node-v1`, `exact_vector:canonical-node-public-text-v2`,
  `hnsw_vector:canonical-node-public-text-v2` and
  `hybrid_rrf:canonical-node-public-text-v2`.

Incumbent arms run in their original modes with their original stores. No
learned input is prepared from SQLite, and no cross-backend id equality is
assumed.

**Cell algebra.**
- Tasks per generation: |T1| = 23 and |T2| = 1. There are 3 repetitions.
- `cells = (23 + 1) x 12 x 3 = 864`.
- Each `(generation, arm)` group has exactly `|Tg| x 3` cells.
- Each cell has exactly one state from `completed`, `refused`, `unavailable`,
  `failed`, `not_run` and `unknown`. The state counts must sum to 864.
- All `cal-23` learned cells carry their original v1 or census
  `unavailable`/`refused` decision and reason.
- Generation-1 learned query cells are executable only for admitted tasks. Every other
  generation-1 learned cell keeps its existing reason.

**Cell fields (closed).**
`generation, task_id, task_sha256, arm, repetition, state, reason{source,code}|null,
capability (complete|partial|null), incomplete, truncated, retrieval_truncated,
publication_coverage (complete|partial|unknown), metrics (12 keys)|null,
result {sha256,length}|null, plan {sha256,length,index_selected}|null (hnsw arms only)`.

`reason.source` is one of `v1_decision`, `public_text_decision`, `study`,
`sql`, `fusion`, `native` or `experiment`. `code` matches
`^[a-z0-9_.:-]{1,96}$`. Every `study` code is enumerated in the module.

**Top level (closed).**
- Identity and provenance: `schema, phase, declaration (2), study_identity,
  task_pins {three catalog identities, selected_task_set_identity,
  tasks[24 {task_id, generation, task_sha256}]}, source {q_source_closure,
  artifact_profile_identity, model_revision}, arms[12]`.
- `generations[2]`, each with:
  - publication, census and preparation identities;
  - exclusion counts by closed reason;
  - request `{input_identity, records, documents per arm, queries per arm,
    bytes}`;
  - `component` (a `validate_component`-compatible object, joined through
    unchanged `verify_raw_component`);
  - `seal`, which carries the section 6 facts and section 7 cost;
  - imports, indexes and fences.
- Then `cells[864], cleanup{status, objects[]}, acceptance, disclosures,
  counts, observation_status`.

**Canonical component journal producer.**
`w5_public_text_journal.py` owns the adapter, with exact public interfaces
`begin_component_journal(root, *, attempt_id, generation, source_files,
request_raw, admission_raw, component_source_closure) -> AttemptJournal`
and `finish_component_journal(journal, *, response, raw_members,
status, failure_code=None) -> JournalArtifact`. It uses unchanged
`retrieval_evaluation_attempts.admit_attempt`, append and finish
filesystem primitives, then unchanged `load_journal`. No in-memory
`JournalArtifact` is fabricated. The declaration carries the actual
controller-admission digest and identical source/component closures;
source_manifest binds the actual request/admission and source bytes. The
report's seven component digests are computed from the actual raw members;
record counts come from the real parsed response. Independent
`verify_raw_component` must reconcile them through `canonical_anchors`.
Failure before a real component produces `not_recorded` with an explicit
reason and never a synthetic successful component. The old nine-arm report
builder and full top-level dossier validator are not called. Adapter unit
tests exercise actual filesystem journal creation/loading and digest
mismatches; a scoped core integration owner proves canonical readback.

**Concrete report API (resulting source).** Each generation row is closed:
`generation, publication_identity, census, preparation, request,
component_status{state, reason}, component, elapsed_seconds, seal, imports,
indexes, fences`. `census.tasks[]` carries `retained_task_sha256` and
`v1_query_task_sha256` under their own names; only the retained digest joins
the pins and cells. `seal` is the verbatim public study seal
(`StudyGenerationSeal.to_dict()`, no text or vectors); the reader recomputes
`seal_identity` and joins receipt digests and counts to the component's
verified digests/counts. `task_pins.task_digest_schemes` names the two
schemes. `cleanup.objects[]` is `{kind, absent}` only. The reader accepts only
the registered task pins. `build_report(*, study_identity,
selected_task_set_identity, source, generations, cells, cleanup, scope=None)`,
`write_report(path, report)` and `read_report(path)` are the entry points.

**Counts and status.**
- Counts are `{"value": n}` or `{"unknown": reason}`.
- `acceptance` reuses `ACCEPTANCE` with every flag `False`.
- `observation_status` is `all_cells_observed` only if no cell is `unknown`,
  both seals exist and cleanup is `clean`. Otherwise it is `incomplete`. No
  status means scientific or production acceptance.

**Bytes and identity.**
- The writer produces `canonical_json_bytes(report) + b"\n"`, refuses more
  than `MAX_REPORT_BYTES` (32 MiB), and writes with exclusive create.
- The report identity is the sha256 of those bytes.
- The reader reads at most 32 MiB, requires canonical equality, and
  recomputes every count, the cell algebra, arm correspondence and every
  join.
- The per-generation component object stays within `MAX_DOSSIER_BYTES`
  (64 KiB).

**Privacy.** The public report holds hashes, offsets, counts and closed
reasons only. Excerpts, model texts, vectors, plans, result rows and private
marker values stay in phase-owned private evidence.

Historical paired V1/V2 reports, the dossier factory and their CLIs are
referenced and never rewritten. Where a primitive is bound to the v1-only
shape, the report adds a narrow codec in its own owner. No generic framework
is added.

## 12. Study lifecycle (one cluster, generation 1 to generation 2)

Every state below must succeed before the next. A failure moves to
`failed(<state>)` or `stopped(<gate>)`, keeps everything already observed, and
still runs `cleanup` once `TABLES_CREATED` has been reached. Nothing is retried
or re-reserved.

1. `DECLARED`: compute `study_identity`. Freeze the Q source closure and the
   task pins.
   Native entry requires `tasks.pins == registered_task_pins()` and all 24
   retained task objects before any reservation. Synthetic pin sets accepted
   by source-level primitives confer no native authority.
2. `CLUSTER_READY`: the one study materialization and one disposable cluster.
   Run unchanged `install_candidate_schema`.
3. `G1_PUBLISHED`: publish the unchanged generation-1 fixture. Read the
   current PostgreSQL pin.
4. `G1_PREPARED`: run the selected loader, census (floor F2),
   `prepare_public_text_generation` and the v1 `PublicGenerationInput`, all
   against PostgreSQL.
5. `G1_FROZEN`: build the request and check the caps and the section 13
   estimate. Write the private ledger entry `reserved` for worker 1.
6. `G1_WORKER`: the bridge component runs. The response is parsed with
   unchanged `parse_verified_worker_response`.
7. `G1_SEALED`: `seal_dual_arm_result` with fresh recomputation.
8. `TABLES_CREATED`: the section 8 creation.
9. `G1_IMPORTED`: import both batches (v1 only if not refused) and create
   their indexes.
10. `G1_OBSERVED`: all 23 x 12 x 3 cells, with incumbent arms in their
    original modes.
11. `G2_PUBLISHED`: publish generation 2 in the same cluster.
12. `G1_STALE_PROVEN`: under the g1 pin, `revalidate_current()` refuses
    before any vector SQL is issued. A no-vector batch readback shows the g1
    batches are no longer current.
13. `G2_PREPARED` and `G2_FROZEN`: as states 4–5. The request is
    document-only (zero query records). Write the ledger entry `reserved`
    for worker 2.
14. `G2_WORKER` and `G2_SEALED`.
15. `G2_IMPORTED`: imports, indexes, and a profile/batch readback under the
    g2 pin (compatibility).
16. `G2_OBSERVED`: 1 x 12 x 3 cells. The six incumbent arms run their
    original operations; the six learned arms carry their unavailable or
    refused decisions.
17. `CLEANED`: section 8 cleanup and absence proof.
18. `REPORTED`: the section 11 report is written.

Both workers and all reads bind to their original PostgreSQL publication.
Learned inputs are never prepared under SQLite and later rebound.

## 13. Native envelope

The original bridge is reused. Its five private controller modules were
inspected from source and never executed: bridge model, bridge worker,
optional runtime, bridge runner and bridge supervisor.

**Model container.** `model_command` uses:
- `docker create --pull=never`, `--network=none`, `--read-only`,
  `--cap-drop=ALL` and `--security-opt=no-new-privileges`;
- `--pids-limit 64`, 2 GiB memory and 1 CPU;
- tmpfs `/scratch` (768m, exec) and `/tmp` (64m, noexec);
- exactly six bind mounts (artifacts, request and admission read-only; the
  worker source and bridge entry read-only; owned output read-write);
- the offline environment variables.

**Install.** The worker installs exactly 20 hash-pinned wheels into
`/scratch/deps` with `--no-index --only-binary=:all: --require-hashes
--no-deps --no-compile --no-cache-dir --target`, under a 120 s pip timeout. It
then checks the distribution closure and the numpy, onnxruntime and
tokenizers versions. This is not an image build, and no image build is added.

**Session.**
- `run_generation_session` requires exactly two configs with attempt ids
  `w5-semantic-g1` and `w5-semantic-g2`, and stops after the first
  non-completed result.
- `run_component` returns after exact model-container cleanup and response
  transport, without requiring the canonical runner to exit.
- Both configs therefore share one authenticated outer canonical runner and
  one cluster.
- The legacy attempt ids and fixed container labels remain labels only.
  Study authority comes from `study_identity`, the request identities, the
  controller admission `phase` (`REPOMAP-CLOE-PUBLIC-TEXT1`), the
  `gate_references` (study and slot-reservation digests) and fresh nonces.
  Optional15 budget authority is never reused.

**Runner.** `launch_canonical_runner` accepts only the absolute venv Python
running `-I -B tools/run_tests.py --suite int --jobs 1 --pg-test-profile
pgvector --no-coverage -- <exact selectors>`. The only selector is the
section 15 learned study test.

**Adaptation and freeze.** The supervisor config sets
`model_timeout_seconds = 550` explicitly; the class default of 300 s is not
the allocation. The current private controller adds only request-bound
admission/reservation wiring: after the actual request is parsed and frozen,
a factory checks its generation, exact source/task/allocation/caps and
reserves that worker once, then returns admission carrying the reservation
and study digests. Old Optional15 allocation helpers never execute. All
ownership, source, offline-install, cleanup and deadlines stay unchanged.
Before reservation,
the five private module hashes, the Q closure and the SDK recipe are frozen
in the private ledger. Private paths, engine, image and container ids never
enter public files.

**Deadlines (unchanged).**
- `TIMEOUT_POLICY` (experiment_contracts.py:24-28): controller admission
  120 s, model 550 s, component response 600 s.
- Supervisor: readiness 120 s, initialization 600 s.

**Generation transition gate.** The source-inspected
`w5_bridge_protocol._wait_ready` (lines 104–152) starts its deadline from
`initialization_timeout_seconds = 600` on every `run_component` call,
including generation 2. It does not use `readiness_timeout_seconds` for
this wait. The separate 120-second admission/readiness settings remain
unchanged. Thus g1 response transport through g2 readiness has 600 seconds.

Before reserving worker 1, a synthetic-vector pgvector functional test runs
the SAME production study driver, all 24 fixed tasks, all 12 arms and all
three repetitions, genuine incumbent operations, both publications and
the same SQL imports/indexes/ANN statements. It replaces ONLY the bridge
worker with a deterministic synthetic response, marks all outputs
`functional_only` and asserts zero native worker reservations. It records
the monotonic interval from g1 response through the g2 readiness callback,
including seal, SQL, all 828 g1 cells, refresh and preparation. Require
observed interval +120 seconds headroom <=600 seconds. This preflight is
source/SQL evidence, not model timing or relevance evidence; it introduces
no learned warm-up or extra model worker. Freeze its exact source closure,
record/task counts and observed interval before worker 1. A source change
affecting this path invalidates the observation. Runtime may still fail its
600-second wait; no extension or retry follows. Fake-clock unit tests
prove the gate rejects missing, stale, nonfinite, over-budget or
source-mismatched observations before any reservation.

**Estimate (gate 5, frozen).** Declaration-2 section 9 gives the formula:
`S = 512(12d+1024)/(t0(12d+2t0))`, `u_meta = I0/N0`, `u_ptx = 2 S u_meta`
and `E = L0 + (N_v1 + Q_v1) u_meta + (N_ptx + Q_ptx) u_ptx`. The study
requires `E + 60 <= 550`. Inputs come from the original raw native basis,
whose report hashes match the paired source:

| | N0 | tokens | t0 | I0 (s) | L0 (s) | u_meta (s) | S | u_ptx (s) | max N_ptx+Q_ptx |
|---|---|---|---|---|---|---|---|---|---|
| g1 | 84 | 4972 | 59.190 | 21.906863506 | 0.103777409 | 0.260796 | 10.3075 | 5.37636 | 87 |
| g2 | 80 | 4861 | 60.763 | 20.993532145 | 0.100966081 | 0.262419 | 10.0341 | 5.26629 | 89 |

- The maximum assumes v1 equals N0 records:
  `floor((490 - L0 - N0 u_meta) / u_ptx)`.
- At most one v2 document exists per v1 pair (80 per generation).
- g1 worst case, 80 + 4 v2 records: E is about 473.6 s, so E + 60 is about
  533.6 s, which is within 550 s.
- g2 worst case, 80 v2 records: E is about 442.4 s, so E + 60 is about
  502.4 s.

The actual counts are frozen before reservation, and the inequality is
recomputed with them. The retained runtime already pads every input tensor
to 512 tokens (`retrieval_semantic_generator_runtime.py:197–203,236–253`),
and its hash matches both retained source manifests. The factor S is an
additional conservative policy allowance, NOT a measured or necessary
59-to-512 tensor-width scaling. Non-padding token totals do not establish
runtime scaling, and fixed tensor width does not guarantee equal cost. These are disclosed estimates, not measured per-arm
time or a runtime guarantee.

## 14. Foundation follow-up delta (disposes source-review-2 F1–F5)

These changes precede any learned corpus inspection. They are frozen
independently of any outcome. They are small stdlib changes with no new
parser, dependency or framework. The product `src/main` redactor stays
separate and unchanged.

1. **Structured metadata ids.** `is_safe_public_metadata` stops applying the
   body assignment heuristic. It keeps the length, `Cc`/`Cs`,
   `is_sanitized_public_string` (private markers) and credential-URI checks,
   and adds a PEM check.
   - It applies to `canonical_key`, `kind`, `display_name`,
     `source_relative_path` and the selected `evidence_key`.
   - Colon-delimited ids such as `...:token:...` are therefore no longer
     systematically refused.
2. **Body predicate (excerpts).** `credential_shaped_text` becomes:
   - `_CREDENTIAL_URI = (?i)\b[a-z][a-z0-9+.-]{0,31}://[^\s/?#@:]+:[^\s/?#@]+@`.
     This covers HTTP and every other scheme with `user:password@`.
   - `_CREDENTIAL_ASSIGNMENT = (?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credentials?|authorization)[a-z0-9_.-]*["']?\s*[:=]\s*[^\s,;]+`.
     This covers key compounds such as `aws_secret_access_key=`.
   - `_PEM_PRIVATE_KEY = -----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----`.

   Inputs are at most 4096 bytes for excerpts and 1024 characters for
   metadata, which bounds backtracking. Token-only userinfo (`user@host`) is
   not treated as a credential; that is a disclosed coverage limit.
3. **Conservative body ambiguity.** A credential-shape match in an excerpt
   gets a new pair reason, `public_text_excerpt_credential_shape_excluded`.
   It is distinct from `EXCERPT_PRIVACY_REFUSED`, which stays the reason for
   marker, sanitizer and control failures. The report discloses it as a
   conservative coverage exclusion, and does not claim that every match is a
   real secret. It applies to annotation, default and comparison text as
   well. It is never relaxed after learned data.
4. **Closed descriptor failures.** `_document` wraps `PublicTextDescriptor(...)`
   construction, catching `ValueError` and `TypeError` but not
   `PublicTextRefusal`. A failure raises the new whole-preparation refusal
   `public_text_descriptor_construction_refused`. A row is never silently
   dropped because of a code or invariant error.
5. **Stale and race proof.**
   - `build_public_text_census` calls `pin.revalidate_current()` at entry and
     before return, and maps a failure to `PUBLICATION_REVALIDATION_FAILED`.
   - Core integration publishes g1, takes its pin, publishes g2, and asserts
     that both `prepare_public_text_generation` and `build_public_text_census`
     refuse under the old pin.
   - A unit test advances the publication between two verified object reads
     and asserts that the whole preparation refuses.
   - A unit test changes object bytes between reads and asserts
     `ARTIFACT_INTEGRITY_REFUSED` for that group.

**Numbered gate order (normative).**
- Pre-body gates (`admit_document_pair`):
  - G1 body policy declared and allowed;
  - G2 manifest binding;
  - G3 binding exclusion;
  - G4 span-row selection;
  - G5 span endpoints;
  - G6 metadata privacy, which now includes `evidence_key`;
  - G7 manifest entry;
  - G8 artifact pre-open.
- Body phase:
  - B1 projection membership, truncation, record match and span link;
  - B2 per-object verified read, with pin revalidation before and after;
  - B3 line convention and span mapping;
  - B4 excerpt privacy (marker, sanitizer or control failure is
    `EXCERPT_PRIVACY_REFUSED`; a credential shape is the conservative
     reason). Classification precedence is marker, credential shape, then
    maintained sanitizer; a simultaneous shape/sanitizer hit remains a
    conservative exclusion. All outcomes refuse admission;
  - B5 model-text encoding;
  - B6 descriptor construction (a failure refuses the whole preparation).

All task and v1 decisions and every exclusion row are retained.

## 15. Exact proof selectors

All selectors use the canonical runner form already used for the foundation
selectors ([foundation section 8](cloe-public-text-foundation-v1.md#8-exact-proof-owners)),
always with `--no-coverage`. pgvector selectors add `--suite int --jobs 1
--pg-test-profile pgvector`, which is the exact form the retained bridge
runner validates. Synthetic vectors prove SQL and contracts only. No complete
local suite, smoke, staging or coverage run is authorized.

**Unit.** These are new, except that the four foundation files gain cases.

| Selector | Required behaviour |
|---|---|
| `src/test/unit/python/tools/retrieval_public_text_tasks.unit.test.py` | pins equal the registered input; hash mismatch; duplicate/missing selected id; held-out bytes never reach `json.loads` (spy); split/generation/digest refusals; change between reads |
| `src/test/unit/python/tools/retrieval_public_text_request.unit.test.py` | ids, partition order, byte-identical v1 texts, identity manifest, generation-2 zero queries, every cap at the boundary, `parse_worker_request` round trip |
| `src/test/unit/python/tools/retrieval_public_text_response.unit.test.py` | each numbered seal refusal; every token/overflow/truncation aggregate mutation (count, byte and seconds mutations are already refused by the unchanged parser); `bool` tokens; non-unit vector; v1 own-record truncation refuses v1 only; v2 `token_partial` keeps every vector; five facts independent; per-arm sums equal global; time unknown |
| `src/test/unit/python/tools/retrieval_public_text_study_schema.unit.test.py` | creation/import/index/cleanup identities and exact schema constraints |
| `src/test/unit/python/tools/retrieval_public_text_study_queries.unit.test.py` | fixed names and identifier patterns; no `IF NOT EXISTS`, `CASCADE`, `GRANT`, `ANALYZE` or `enable_*`; DDL checks; import fences/count `DO`; exact/ANN statement equivalence with production substitutions; five-record parsing; plan-node check |
| `src/test/unit/python/tools/retrieval_public_text_fusion.unit.test.py` | v2 projection refusals; parity with `vector_candidates` projection on v1-shaped rows; serializer never emits a single v1 label; fallback disabled |
| `src/test/unit/python/tools/retrieval_public_text_report_cells.unit.test.py` | every cell field/state and exact population algebra, duplicate/missing tuples |
| `src/test/unit/python/tools/retrieval_public_text_study.unit.test.py` | every driver state, injected failure at each transition, cleanup exactly once after creation, no reservation on preflight refusal, no retry, g2 document-only |
| `src/test/unit/python/tools/retrieval_public_text_journal.unit.test.py` | real filesystem journal and raw-member join, digest/count/closure mismatches, incomplete component not_recorded |
| `src/test/unit/python/tools/retrieval_public_text_report.unit.test.py` | closed schema; 864-cell algebra; unknown is not zero; each state; cleanup failure blocks; 32 MiB/64 KiB caps; canonical bytes; no private value; parser-backed positive report; structural versus evidence-verified read; functional marker |
| `src/test/unit/python/tools/retrieval_public_text_study_catalog.unit.test.py` | section 18.2 readback/children/inventory fence, index identity binding, closed index catalog, cleanup ordering and per-object absence |
| `src/test/unit/python/tools/retrieval_public_text_report_contracts.unit.test.py` | section 18.4 recursive closed schemas, strict types/digests, seal recomputation, functional marker |
| `src/test/unit/python/tools/retrieval_public_text_report_joins.unit.test.py` | section 18.4 joins (census, preparation, request, seal, component, imports, indexes, fences, cells, cleanup) and section 18.5 evidence verification |
| existing `retrieval_public_text_{privacy,admission,descriptors,census}.unit.test.py` | section 14 items 1–5 and the gate order |

**Core integration (no pgvector).**
- `src/test/int/python/tools/retrieval_public_text_tasks.int.test.py`: the
  real catalog hash, decoding exactly 24 records, and every digest.
- Existing `retrieval_public_text_census.int.test.py` and
  `retrieval_public_text_capture.int.test.py`: the stale-generation advance
  for preparation and census.

- `src/test/int/python/tools/retrieval_public_text_journal.int.test.py`:
  real private temporary journal, unchanged load and raw-member join with
  synthetic fixtures, never native-origin evidence.

**pgvector integration (`requires_pgvector`, synthetic vectors).**
`src/test/int/python/tools/retrieval_public_text_postgres.int.test.py` covers:
- before-absence;
- owner, comment, OID and fingerprint;
- no new grant or role (catalog diff);
- import fences and an exact count rollback;
- order and ties equal to the production reader for identical v1 vectors
  (production import vs. study v1 batch), with `stale_publication` and
  `enrichment_unavailable` parity;
- the real one-transaction ANN, with plan and rows from the same execution
  and the TEMP table absent after commit;
- `index_not_selected` and `temp_privilege_absent` handling;
- g1 batches stale after g2 publication;
- RESTRICT cleanup with absence proof, and refusal of foreign or replaced
  objects.

The same pgvector source-proof selector also runs
`src/test/int/python/repomap_kg/storage/semantic_candidate_runtime_boundaries.int.test.py`
(unchanged product guards only: no-vector schema guard, extension without
enrichment schema, absent/foreign publication, reader/spoofed-principal
import, unknown-node exact-count rollback, malformed latest receipt without
historical fallback). The core selector
`src/test/int/python/repomap_kg/retrieval/public_text_custody_regressions.int.test.py`
proves missing retained manifest object (both backends), missing retained
result/manifest reference with live roots, and the pre-migration lexical
probe. The queries unit owner also covers the support owner's five-record
parser and ANN classification; the fusion unit owner covers its sealed-entry
joins.

`src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py`
also exercises the actual driver end-to-end with the synthetic bridge,
all fixed tasks/arms/repetitions, g1-to-g2 interval, both actual publications,
stale-g1 refusal, failure cleanup and absence readback. This is the section
13 transition-gate source-proof owner. It does not reserve learned slots.

**Learned (not source proof).**
`src/test/int/python/tools/retrieval_public_text_study.int.test.py` (pgvector)
is the single `PUBLICTEXT-CAL1` selector. It is selected only after source
acceptance, independent review and native admission.

The CI139 branch-arc recovery obligations in declaration-2 section 11 remain.
They do not change thresholds or policy.

## 16. What would make this contract wrong

- The raw parser, receipt or sealer differs from the cited lines, for example
  if the parser already reconciles aggregates or the production sealer could
  accept a combined input.
- `parse_worker_request` refuses a `v1.`-prefixed original id, or an original
  v1 id exceeds 509 characters.
- PostgreSQL forbids, or does not execute once, an analyzed TEMP CTAS inside a
  read-write `REPEATABLE READ` transaction; or `psql -0` does not
  NUL-separate the plan and the row; or the plan does not name the partial
  index when it is used.
- The disposable owner lacks `CREATE` on `repomap_enrichment` or TEMP on the
  database without a new grant.
- The original `hybrid_rrf` composition cannot accept a substituted vector
  observation without changing its source.
- The supervisor's readiness and initialization waits cannot cover the g1
  observations before the g2 readiness.
- The catalog cannot be located structurally (for example, `task_id` absent
  from some element) without JSON-decoding an unselected token or body.
- A section 14 predicate changes any serialized v1 decision.

## 17. Residuals

This contract makes no learned-relevance, ANN-acceleration,
held-out/scientific, production D15, full W5–W8 or release claim. The sample
is small, English-oriented and capped. The privacy predicates are
conservative shape rules. The excluded-coverage counts are disclosed, and are
not evidence that a secret exists. All runtime gates of declaration 2
(P5/P6, conditional artifact, licence, security and runtime admission)
precede the single learned attempt.

## 18. Retrieval repair 2 (resulting-source review F1–F9 and parent checks)

This section corrects the resulting-source contracts. It changes no task,
gold, mode, pin, repetition, worker, study, retry, dependency, runner or
product file, and it grants no native, model or reservation authority. Where
it conflicts with sections 8–11, this section governs.

### 18.1 SQL corrections (parent checks)

- The entry check for the public-text arm is
  `(arm = v2 AND descriptor_identity IS NOT NULL AND descriptor_identity ~ digest)`.
  A NULL descriptor otherwise satisfies the regex check vacuously. The
  pgvector owner proves a real rollback: an update that nulls a v2 descriptor
  fails and leaves the rows unchanged.
- A batch capability is bound to the actual sealed arm, never inferred from
  documents. `sealed_batch(names, seal: StudyGenerationSeal, arm, profile, *,
  pin, v1_input=None, preparation=None) -> StudyBatch` takes the generation,
  `seal_identity`, `input_identity` and capability from that seal and the
  entries from `v1_entries`/`v2_entries`. `validate_batch` accepts a v2
  `token_partial` batch whose documents are all untruncated (query-only
  truncation). A truncated document still requires `token_partial`. v1 is
  always `complete` and untruncated. A unit case builds this seal through the
  unchanged parser (section 18.6).

### 18.2 Catalog owner and child-object fences (F4, F5, F8)

`retrieval_public_text_study_catalog.py` exposes:

```python
@dataclass(frozen=True)
class ChildIndex: relation: str; oid: int; name: str; item: str   # constraint-backed index
@dataclass(frozen=True)
class CreationRecord: names: StudyNames; batch: RelationIdentity; entry: RelationIdentity
                      children: tuple[ChildIndex, ...]
@dataclass(frozen=True)
class IndexIdentity: name: str; batch_id: str; oid: int; table_oid: int; item: str
@dataclass(frozen=True)
class StudyCatalog:
    record: CreationRecord; indexes: tuple[IndexIdentity, ...] = ()
    def with_index(self, index: IndexIdentity) -> StudyCatalog
    def index_for(self, batch_id: str) -> IndexIdentity | None
    def expected_items(self) -> tuple[str, ...]
    def fence_sql(self) -> str
def parse_relation_state(payload, names) -> CreationRecord
def build_create_sql(names) -> str
def build_index_sql(catalog, batch_id) -> str
def parse_index_catalog(payload, catalog, batch_id) -> IndexIdentity
# schema owner: index_item_sql, inventory_items_sql, rls_item, fingerprint_sql,
#               index_comment, index_catalog_sql(names, batch_id)
def cleanup_objects(names, catalog) -> tuple[tuple[str, str, int | None], ...]
def build_cleanup_sql(catalog) -> str
def absence_sql(names, objects) -> str
def parse_absence(payload, names, objects) -> tuple[bool, ...]
```

- **Inventory.** One SQL item grammar describes every child of the two
  recorded relations: each index (OID, name, table OID, `pg_get_indexdef`,
  valid/ready/live, comment, owner, persistence), every non-internal trigger,
  rule and policy, and one row-level-security item per relation. The index
  definition text carries the access method, opclass, expression, predicate,
  uniqueness and storage options.
- **Creation.** The readback records the three batch and one entry
  constraint indexes. Each must be a valid, ready btree with no predicate or
  expression, on the exact key columns of its primary or unique constraint.
  The relation's children must be exactly those indexes plus RLS `false|false`.
  Any trigger, rule, policy or extra index at creation refuses with
  `study_catalog_children`.
- **Fence.** `StudyCatalog.fence_sql()` is the relation fence (OID, schema,
  name, kind, persistence, owner, comment, fingerprint) AND an exact,
  order-free inventory equality against `expected_items()`: the recorded
  constraint indexes, the registered owned HNSW indexes and both RLS items.
  Index creation, import, exact read, both ANN flights and cleanup use it.
  Therefore an unknown index or trigger/rule/policy, enabled RLS, or an
  in-place change to an index's definition, opclass, predicate, options,
  comment, owner or readiness refuses every relevant use and cleanup.
- **Registration.** Indexes enter only through `parse_index_catalog` and the
  immutable `StudyCatalog.with_index`. The identity must equal the derived
  name for its batch, the recorded entry OID and its catalog item. There is no
  hidden mutable registry, and a caller-supplied index argument is never
  trusted: ANN reads look up `query.catalog.index_for(query.batch_id)`.
- **Closed index catalog (F8).** The payload must have exactly the closed key
  set, including `item`, with strict types. Missing, extra or malformed fields
  refuse with `study_index_catalog`, never a `KeyError`.
- **Cleanup.** One transaction: the full catalog fence runs in a `DO` block
  before any `DROP`, because `DROP TABLE ... RESTRICT` removes the tables' own
  indexes and internal triggers without asking. Then each registered HNSW index
  is dropped, then the entry and batch tables. A mismatch drops nothing and
  records `cleanup_failed:relation_identity_changed`. Absence is read back per
  object (batch, entry, each constraint index, each registered index), by name
  and by recorded OID. `CleanupResult.objects[]` reports each object's own
  absence, never one aggregate copied to every object. Without a creation
  record, only the two relation names are checked.

### 18.3 Observed ANN and fusion inputs (F3, F4, F6, F7)

- `StudyQuery` carries `catalog: StudyCatalog` instead of a bare creation
  record. `observe_ann(postgres, query, pin, *, task_id, repetition,
  ann_scan_limit=None)` takes no index argument.
- If the batch has no registered owned index, the transaction still runs and
  its plan is kept, but the cell is always `unavailable/index_not_selected`
  with `index_selected: false`, even if the plan names the derived index.
- With a registered index, both flights require the full catalog fence and
  that index's exact catalog item. The plan check then uses the registered
  name and the entry relation.
- The pgvector owner asserts the positive case directly. With the owned index,
  the default planner (no forcing, no `ANALYZE`, no warm-up) must give
  `completed` with `index_selected: true`. The completed rows must equal the
  plan-execution rows and an exact recomputation over the same data, and the
  TEMP table must be absent. A separate unindexed v1 batch proves the genuine
  `unavailable/index_not_selected` default-planner case.
- `project_public_text_candidates(rows, *, preparation, seal, pin, task,
  scope) -> PublicTextProjection`. Selected bindings come from the unchanged
  `selected_public_binding_ids(task)`, as on the v1 path. The returned
  projection is a closed, module-validated object. It binds the hits, the
  task's retained digest, the selected bindings, the seal digest, the
  preparation identity, the publication identity, the scope id and the arm
  capability.
- `public_text_vector_arm(kind, projection, *, seal, pin, task)` accepts only
  that projection and requires each of those correspondences again. Raw tuples
  and caller binding lists are refused (`public_text_projection`).
- `v1_vector_arm` requires the exact study row shape: the closed `ROW_KEYS`
  with `descriptor_identity` NULL. The unit and pgvector owners call it on
  real study rows, so the unchanged kind, display name and `input_digest`
  checks (`canonical_node_v1_digest` path) run.
- The hybrid stays exactly (current native FTS, exact vector), with fallback
  `False`.

### 18.4 Report: closed schemas, joins and the functional marker (F1, F8)

`retrieval_public_text_report_contracts.py` owns the closed schemas;
`retrieval_public_text_report_joins.py` owns the joins. The report owner keeps
its builder, writer, reader and adapters and re-exports
`PublicTextReportRefusal`.

- **Top level** adds a mandatory strict `functional_only: boolean`.
  `build_report(*, study_identity, selected_task_set_identity, source,
  functional_only, generations, cells, cleanup, scope=None)` requires a real
  `bool`. A missing, non-bool or inconsistent value refuses.
- **Fences** per generation are closed: `{execution_kind, creation, inventory,
  publication}`. `execution_kind` is `synthetic_functional` when
  `functional_only` is true, else `native`. It must match in both
  generations. The other states are `verified|failed|not_reached`,
  `verified|changed|not_reached` and `current|stale|not_checked`. Acceptance
  flags stay all `False` in both modes. A `false` flag never proves model
  origin or native acceptance; private controller receipts remain required.
  The native controller rejects every `functional_only: true` frame, root or
  report before any real reservation.
- **Closed nested shapes** (strict `int`/`bool`, `sha256:` digests and closed
  code patterns):
  - census `{census_identity, status, document_count, v1_verified_pair_count,
    tasks[{task_id, retained_task_sha256, v1_query_task_sha256,
    v1_learned_state, v1_learned_reason, public_text_state,
    public_text_reason}]}`;
  - preparation `{preparation_identity, document_count,
    v1_verified_pair_count, exclusion_counts}`;
  - request `{input_identity, records, documents{v1,ptx}, queries{v1,ptx},
    bytes, request_sha256}`, or `null` before freezing;
  - seal: the full public study seal, recursively closed. The reader
    recomputes `seal_identity`, every per-arm count and token sum, the
    capability/refusal/`token_partial` rule, the truncated identity lists and
    global partial/status. Record ids follow the four partition patterns;
  - imports `[{arm, batch_id, capability, row_count, seal_identity}]`;
  - indexes `[{arm, batch_id, state: "created"}]`;
  - cleanup `{status, reason, objects[{kind, absent}]}`, where kind is
    `batch|entry|constraint_index|index`.
- **Joins.**
  - Census and preparation agree on document and verified-pair counts and on
    status.
  - The request equals the seal in input identity, request digest and per-arm
    document/query counts. Its v2 counts equal the preparation documents and
    the admitted census queries. Generation 2 has no queries.
  - The seal equals the component digests and counts, the source artifact
    profile and the generation publication.
  - Imports need a seal, an importable arm with the same capability, the
    arm's document count and verified creation and inventory fences. Indexes
    need an import of the same batch.
  - A completed learned cell needs an admitted census decision, an importable
    sealed arm, its import (and, for HNSW, its index), verified fences, a
    current publication and the arm's publication coverage. So missing
    imports, indexes or fences can never credit a completed cell.
  - Cleanup objects must be exactly the recorded inventory when creation was
    verified (batch, entry, four constraint indexes and each created index).
    A clean status requires every object absent.
- **Privacy.** No free text, excerpt, vector, plan, row or extra field can
  enter a closed shape. Both the builder/writer and the reader refuse
  host-path shapes. The writer, and the reader when given a scope, refuse
  private markers.
- **Cells (F8).** Every `result` is closed `{sha256, length}` and every
  `plan` is closed `{sha256, length, index_selected}`, with strict values in
  every state. Non-HNSW plans are `null`.

### 18.5 Structural read versus raw-evidence verification (F2)

```python
@dataclass(frozen=True)
class ReportEvidence:
    components: Mapping[int, tuple[JournalArtifact, Mapping[str, bytes]] | None]
    tasks: SelectedTaskSet
    scope: PrivateMarkerScope | None = None
@dataclass(frozen=True)
class ReportRead:
    report: dict[str, Any]; identity: str
    verification: Literal["structural_only", "raw_evidence_verified"]
def read_report(path, *, evidence: ReportEvidence | None = None) -> ReportRead
def read_verified_report(path, evidence: ReportEvidence) -> ReportRead
```

- Without evidence, the reader is structural only. A stored
  `artifact_correspondence_verified: true` is never reasserted as raw
  verification. The public disclosure states
  `builder_structural_only_reader_structural_only_without_evidence_context`.
- With evidence, for each generation:
  - the actual journal and model members are re-verified by unchanged
    `verify_raw_component`, and the recomputed component evidence must equal
    the stored one;
  - the members are re-parsed by the unchanged
    `parse_verified_worker_response`, and the seal's response identity,
    request identities, records, tokens, partial state and shared timings must
    equal that response;
  - the actual selected task objects bind both task maps. The pins must be the
    registered pins, the set identity must match, and every census row's
    `retained_task_sha256` (ASCII) and `v1_query_task_sha256` (UTF-8) must
    equal the digests recomputed from the actual task object;
  - a non-supplied component requires `None` evidence.
- The retained ASCII schemes and every registered pin stay unchanged. A
  positive study closeout must call `read_verified_report`.

### 18.6 Synthetic artifacts helper

`w5_public_text_artifacts.py` is test support only. It has no model, database
or network operation, and it never imports a `.test.py`.

- It builds a synthetic study input from the public fixture: publication,
  preparation, census, v1 input and `DualArmInput`.
- It writes the actual seven raw protocol members for that exact request
  bytes, through the real attempt-journal framing. These are request,
  controller admission, declaration, report, source manifest, sources archive
  and terminal.
- It writes a real component journal through unchanged `admit_attempt` and
  `load_journal`.
- Vectors, tokens and truncation are explicit synthetic values. Only the
  unchanged parser creates the `VerifiedWorkerResponse`. No accepted response
  or `GeneratedEnrichmentArtifact` is fabricated, and nothing claims model
  origin.
- The later functional driver may reuse it. This repair adds no driver.

## External callback failure closure

Only external current-readback/reader/refresh call boundaries catch arbitrary
`Exception`, and map it to a closed whole-preparation or whole-generation
refusal without publishing the callback message. KeyboardInterrupt/SystemExit
remain outside that catch. No internal failed invariant becomes an admitted
row or a silently dropped document.

## Parent correction of remaining retrieval joins

Every sealed query source identity joins its census retained task digest.
Raw-evidence verification also compares the actual request query text with
the original selected task's exact question; it does not trust a digest-shaped
label alone. The positive report fixture uses the registered task objects
with a pure artifact-backed public-binding fixture in
`w5_public_text_registered_fixture.py`. Existing fixtures and tasks are frozen.
Both generation-row and seal-generation types are exact integers, never bool.

`build_report` and default `read_report` perform structural validation only.
Only the actual component helper or a read supplied with genuine evidence
performs raw verification; the public disclosure says so. The projection
consumer requires the exact factory-issued object, making token-preserving
dataclass replacement invalid. This is an in-process contract, not hostile
Python caller confinement. Publication fence state is captured at observation
time; the later stale-g1 proof remains separate. If creation commits but its
readback is refused, cleanup drops nothing unknown, reports objects present,
and the enclosing disposable cluster still receives its owned teardown.

## 19. Final driver source contract

This section was written before the final-driver source. It names the exact
owners, selectors and interfaces of the section 12 lifecycle. Sections 11–13
and 18 keep the data, states, budgets and report. Where this section is more
specific, it governs. It grants no native reservation, model run, study
materialization, build, acquisition, retry or publication.

### 19.1 Owners

There are twelve new source owners, each at most 400 physical lines, using
only the standard library or existing repository modules. Each has the unit
owner `src/test/unit/python/tools/retrieval_public_text_<suffix>.unit.test.py`,
where `<suffix>` is the name after `retrieval_public_text_` or `w5_public_text_`.

| Owner | Public interface |
|---|---|
| `tools/retrieval_public_text_allocation_io.py` | `AllocationRefused`, `canonical_receipt_bytes`, `receipt_digest`, `seal_receipt`, `locked_root(root, *, create, allowed)`, `read_receipt(root, name)`, `write_receipt(root, name, payload)` |
| `tools/retrieval_public_text_allocation.py` | `StudySpec`, `WorkerSpec`, `reserve_study`, `reserve_worker`, `finish_worker`, `finish_study`, `read_state` |
| `tools/retrieval_public_text_native_gate.py` | `PREFIX`, `stale_g1_proof(...)`, `gate_frame(...)`, `encode_gate`, `format_gate`, `decode_gate`, `validate_native_gate`, `read_actual_gate(log_path, *, generation, nonce, request_sha256)` |
| `tools/retrieval_public_text_native_inputs.py` | `LEARNED_SELECTOR`, `NativePaths`, `create_native_paths`, `copy_worker_view`, `canonical_argv`, `child_environment` |
| `tools/retrieval_public_text_preflight.py` | `BASIS`, `checked_counts`, `estimate_generation`, `transition_observation`, `check_transition_observation` |
| `tools/retrieval_public_text_sources.py` | `PUBLIC_TEXT_EVALUATOR_PATHS`, `SourceClosure`, `worker_closure(repo_root)`, `evaluator_closure(repo_root, base_files)`, `require_unchanged(repo_root, closure)` |
| `w5_public_text_generation.py` | `materialize_generation(workspace, database, generation) -> GenerationResources`, `prepare_generation_inputs(...) -> PreparedGeneration` |
| `w5_public_text_baselines.py` | `make_runner(resources)`, `run_incumbent_cells(resources, runner, task, *, journal) -> IncumbentRun` (cells, lexical outcomes, failed-operation count) |
| `w5_public_text_journal.py` | `begin_component_journal`, `record_operation`, `finish_component_journal`, `StudyFailureReceipt`, `write_failure_receipt`, `cleanup_fields(cleanup, error)` |
| `w5_public_text_functional.py` | `SyntheticDelivery.admit(exchange)`, `SyntheticDelivery.respond(exchange)` |
| `w5_public_text_learned.py` | `LearnedGeneration`, `learned_cells(...)`, `old_batch_status(...)` |
| `w5_public_text_study.py` | `StudyEnvironment`, `StudyOutcome`, `run_public_text_study(environment)` |

The functional supplier extends the existing synthetic artifacts helper with
two optional keyword arguments, `source_files` and `admission_raw`. They replace
its one toy worker source only on the functional path. Its unit defaults stay
unchanged. No new raw-response framework is added, and no generic worker,
parser or transport changes.

### 19.2 Selectors

| Role | Selector | Profile |
|---|---|---|
| Functional full driver | `src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py::test_public_text_functional_lifecycle` | existing `requires_pgvector` |
| Single learned owner | `src/test/int/python/tools/retrieval_public_text_study.int.test.py::test_public_text_semantic_study` | existing `requires_pgvector` |
| Core journal | `src/test/int/python/tools/retrieval_public_text_journal.int.test.py` | core |

These names supersede earlier preparation notes. The source-proof selector
lists name the functional selector and exclude the learned owner. The learned
owner runs the same driver with `functional_only: false`. It never installs
the synthetic supplier, so without the external private supervisor it stops
at the unchanged 120-second controller-admission wait. It then records a
failed study with its private failure receipt and fails, never passing empty.
Neither pgvector owner is part of ordinary core CI.

The private host launches the learned owner with the existing source-proof
form only:

```text
<abs venv python> -I -B tools/run_tests.py --suite int --no-coverage --jobs 1
  --pg-test-profile pgvector --pg-container-port 55433
  --smoke-image-reference <frozen diagnostic runtime>
  --report-dir <phase report dir> -- <learned selector> -s
```

Both the diagnostic runtime override and port 55433 already exist. They
prevent any fallback cache or base acquisition.

### 19.3 Driver order (both modes)

`run_public_text_study` is one driver. For each generation it runs these
steps in order, and only raw delivery differs between the modes:

1. `ComponentExchange.publish_request(attempt_id, request, expected_source_closure=worker)`
   with the actual dual-arm request.
2. The driver prints exactly one generation frame:
   `PREFIX + canonical frame JSON + LF`. The frame is built from
   `exchange.nonce` and `exchange.ready.request_sha256` and printed before
   readiness.
3. `exchange.emit_request_readiness()`.
4. Functional mode only: `SyntheticDelivery.admit(exchange)` writes the
   admission payload and then its marker through the maintained
   `encode_admission_marker`.
5. `exchange.await_controller_admission()` runs unchanged.
6. `begin_component_journal` admits the genuine journal with the real
   admission bytes. An admission event is appended, and the driver prints
   `exchange.admission_ack_line`.
7. Functional mode only: `SyntheticDelivery.respond(exchange)` writes
   `response.zip` and then `response.ready.json`. Both come from the maintained
   `encode_response_bundle`/`encode_response_tar`.
8. `exchange.await_response()` runs, followed by the unchanged
   `parse_verified_worker_response` and `seal_dual_arm_result`.

Native mode never installs the supplier. It waits on the same boundaries for
the external private supervisor. No caller-supplied supplier callback exists.

The state order is section 12. Generation-1 incumbents and learned cells run
before generation-2 publication. Generation 2 is published in the same
cluster and the same PostgreSQL repository. Stale-g1 proof follows, and only
then is the generation-2 frame printed.

**Stale-g1 proof.** The proof comes from two actual observations. The first
is the actual `VerifiedPublicationPin.revalidate_current()` refusal of the g1
pin, with code `stale_publication_receipt`. The second is
`old_batch_status`, a no-vector read of the g1 v2 batch row against the
accepted-publication CTE. It returns `imported_non_current` or
`not_imported_non_current` and the sha256 of the raw psql output. It never
issues vector SQL under the stale pin, and it never hashes an expected state.

**Transition interval.** This is the monotonic time from the g1
`await_response` return to the g2 readiness emission. The functional driver
records it.

**Frame (`cloe-publictext-generation-gate-v1`, closed).** The fields are:
`schema, phase, allocation, study_identity, attempt_id, generation, nonce,
request_sha256, input_identity, publication_identity,
artifact_profile_identity, q_source_closure_identity,
worker_source_closure_identity, task_pins_identity,
selected_task_set_identity, census_identity, preparation_identity,
record_counts, estimate_gate_identity, functional_only, stale_g1_proof`.
There is no `transition_gate_identity`. The g1 frame has `stale_g1_proof:
null`. The g2 proof must bind the frame publication as its new publication.

The reader `read_actual_gate` reads the 0600 owned log once, after generic
readiness, with no wait. Its limits are an 8 MiB log and a 64 KiB frame. It
requires exact ordered unique frames and the actual nonce and request. A
growing log is accepted, but a truncated or replaced one is not.
`validate_native_gate` refuses `functional_only: true`.

**Host-only facts.** The host reserves the single study before it launches
the runner. The host binds the real functional-transition receipt digest in
the base `AdmissionContract.gate_references`. The one new
`worker-reservation` gate binds the actual frame SHA, nonce, request and study
identity. The private factory receives the bound readiness nonce as its
fourth argument. The parent marks the g1 terminal between the two
`run_component` calls. None of these facts enters a Q frame.

### 19.4 Cells: `file_grading` and exact counts

Every cell gains a mandatory, closed
`file_grading: {state, reason}`:

- `state` is one of `verified`, `not_applicable`, `gap` or `not_run`.
- `reason` is `null` iff `state` is `verified`. Otherwise it is a closed code
  matching `^[a-z0-9_.:-]{1,96}$`.
- `metrics` has the twelve finite file metrics iff `state` is `verified`.
  Otherwise it is `null`.
- A completed learned cell requires `verified`.
- A completed incumbent cell may be `verified`, `not_applicable` or `gap`.
  Those values come from the maintained correspondence file grading
  (`baseline_file_metrics_with_correspondence`). Original node metrics are
  never copied, zeroed or inferred.
- A cell that is not completed has `not_run` with reason
  `execution_not_completed`.

Execution state stays independent. A completed operation with a grading gap
stays `completed`, and a failed operation is never turned into a success.

`counts` adds `file_grading: {state: {"value": n}}`. The reader recomputes
both count families. Every report count and every per-arm count sealed into a
generation must be an exact `int`. A `bool` or `float` is refused even when it
compares equal, in both the canonical report and a resealed report.

### 19.5 Failure receipt (private)

`write_failure_receipt(root, receipt)` writes one closed,
canonical `cloe-public-text-study-failure-v1` file into the existing
private report export root, with exclusive create and a 64 KiB limit. Its
fields are:

- `schema, phase, functional_only`;
- `study_identity` and `q_source_closure_identity`, each or `null` when not
  yet known;
- `task_pins_identity`;
- `stop_state` (a section 12 state) and a closed `failure_code`;
- `planned_cells` (864), `observed_cells` and `unknown_cells`, where the last
  two sum to the planned count;
- `components[{generation, state: recorded|not_recorded, report_sha256|null}]`;
- `cleanup{status, reason}`.

It holds no message, text, vector, plan, path or private identifier. It is
never a partial calibration report, and it invents no g2 facts. When full
facts exist but an operation failed, the full report is written as well as
the receipt, and the canonical test fails. Cleanup runs once after
ownership, independently of the primary error. Foreign or replaced
identities drop nothing.

Raw journal artifacts are framed through the unchanged
`emit_attempt_artifacts` only after both generations. That keeps the 8 MiB
readiness and admission log scan safe. The public report is exported
separately under the existing report root.

### 19.6 Encoding follow-ups F1–F11 (disposition)

- **F1–F2.** Only external callback boundaries catch arbitrary `Exception`.
  Span and evidence iterators are consumed inside the closed read wrapper
  (`tuple(...)` within the wrapper). Fresh `DualArmInput` owners are
  rebuilt and checked inside the closed refresh validation. A malformed
  fresh pin or task set yields the whole-generation code.
  `KeyboardInterrupt` and `SystemExit` are never caught. The unit
  negatives cover a failing iterator and a malformed fresh owner.
- **F3.** The new study preparation and request `publication_identity` use
  ASCII canonical `digest_json`. The original v1 worker request uses its own
  UTF-8 `_digest`. Both are named separately. The request manifest carries
  the scheme label and the original v1 identity. A Unicode pin regression
  proves the two are never equated.
- **F4–F6.** Test fixtures that supply retained maps call
  `retained_task_sha256` explicitly. The `DualArmRecord.source_identity` of a
  query row is the retained digest, and the v1 query digest stays separately
  bound. A Unicode synthetic task proves that substituting the v1 UTF-8
  digest for a retained pin is refused through the actual parser.
- **F7–F9.** These are the ADR precedence sentence (a sanitizer overlap is a
  conservative shape exclusion, while a marker overlap is a privacy refusal),
  a unit shape/sanitizer overlap test with a sanitizer double, and the
  corrected section 15 aggregate-mutation wording.
- **F10.** The driver checks `selected.pins == registered_task_pins()`, all 24
  retained objects and digests, and the fixed generations and repetitions
  before any frame. Synthetic pin sets confer no authority.
- **F11.** The census is clarified as 25 new Python files: 17 foundation
  files plus 8 encoding additions. The 22 encoding-owned files are 9 tools, 9
  unit and 4 integration owners. Capture, its unit owner and the readback
  support lie outside the 22.

### 19.7 What would make this section wrong

- The real `/sandbox-scratch/test-scratch` exchange root is unavailable inside
  the canonical pgvector sandbox, so the functional exchange cannot run.
- `accepted_candidate_publication_sql` still yields a row for a superseded g1
  publication after g2 publication in the same repository.
- `baseline_file_metrics_with_correspondence` changes execution state, or
  returns metrics for a cell whose correspondence is unverified.
- The g1 interval plus 120 seconds exceeds 600 seconds on the real functional
  run. Native admission then refuses, and no extension follows.

## 20. Corrective evidence and failure contract

Written before the parent correction of the deferred final-driver checkpoint.
All earlier input, timing, allocation and acceptance limits remain unchanged.
Two additional source owners, each at most 400 lines with a matching unit
owner, complete the evidence boundary:

| Owner | Interface |
|---|---|
| `tools/retrieval_public_text_export.py` | `ExportRefusal`, `emit_study_evidence(extras, *, journal_decoded_bytes, functional_only, stream=None) -> str`, `decode_study_evidence(raw_log, *, journal_decoded_bytes, expected_functional_only) -> dict[str, bytes]` |
| `w5_public_text_evidence.py` | `private_generation_inputs(prepared, selected, gate_payload)`, `retain_raw_members(root, attempt_id, members)`, `write_observed_report(...)`, `write_transition_pair(root, observation, *, counts, evaluator_identity, selected)`, `emit_private_evidence(root, journal_dirs, *, functional_only)`, `write_private_file(path, raw)`, `read_private_file(path, limit=32 MiB)` |

The evaluator closure includes both owners. The generic worker, parser,
bridge, runner and runner argument vector remain unchanged. `--report-dir`
alone does not export an inner report under ordinary `--no-coverage` scoped
proof. Therefore the existing journal frames remain unchanged and one
phase-private sidecar is emitted after the generations or a failed terminal.
No report/coverage flag, D12 flag or runner-policy exception is introduced.

The prefix is `CLOE_PUBLICTEXT_PRIVATE_EVIDENCE_V1 `. A single canonical JSON
frame carries a sorted manifest (fixed names, strict integer lengths, SHA256),
its digest, and an uncompressed deterministic USTAR payload encoded as base64.
Closed header fields identify this phase and a strict `functional_only` flag;
they make no success, model-origin or admission assertion. The decoder
rejects duplicate fields/frames/names, unknown names, unsafe paths, links,
devices, noncanonical archives, trailing archive bytes and digest/size errors.
It returns bytes without extracting paths.

Allowed names are `public-text-calibration-report.json`,
`public-text-study-failure.json`, `functional-transition-observation.json`,
`functional-transition-gate.json`, and five raw members under each
`raw-components/w5-semantic-g1/` or `raw-components/w5-semantic-g2/`:
`declaration.json`, `report.json`, `source-manifest.json`, `sources.zip`,
`terminal.json`. A raw group is absent or complete. A report or failure receipt
is required. A functional report requires the transition pair; native evidence
contains no functional transition pair. Raw bytes retain their actual format.
The report limit is 32 MiB, other metadata 64 KiB, each raw group 32 MiB,
combined journal and sidecar contents 64 MiB, TAR 72 MiB and captured stdout
96 MiB. These are cumulative limits, not extra per-channel allowances.

Owned private directories are 0700 and files are exclusive, fsynced 0600
regular files under the declared root. Actual raw model members are retained
before parsing, so a failed parse can retain bytes without claiming verified
component origin. Genuine journals additionally contain the exact printed gate
payload, publication, task pins, selected task objects, preparation and census
as private inputs. Questions and golds are audit inputs, never selection
authority. Public reports contain no raw text or private paths.

The functional proof reloads genuine journals and raw members, verifies the
report through `ReportEvidence`, decodes both actual printed generation
frames with `read_actual_gate`, and independently joins source/task identities.
It writes, rereads and checks the actual measured transition pair, then checks
the sidecar decoded from actual captured stdout. A generation-2 stale proof
must name the actual generation-1 frame publication. FIFO log inputs are
refused before a blocking read. All six incumbent arms must demonstrate real
verified file grading on applicable tasks; unexpected grading errors propagate
to a failed study. Genuine maintained gaps and unavailable/refused execution
states remain distinct from failures.

An actual failed operation in generation 1 terminalizes `G1_OBSERVED` before
generation-2 publication, frame or request. Unknown cells stay unknown. A
generation-2 operation failure can retain the full report and failure receipt
when all facts exist. Cleanup is attempted once after ownership even for
unexpected ordinary exceptions and interrupts; `KeyboardInterrupt` and
`SystemExit` propagate after cleanup. Journals cover component/observation
execution through cleanup, not later report publication. The whole-study
outcome and terminal evidence also cover report/export errors. Failure-receipt
I/O errors remain independent diagnostic codes beside the primary failure;
they cannot escape as a replacement error or imply success.

### 20.1 Allocation terminal classification

Before the final private controller is implemented, the allocation helper
adds `failure_for(g1, g2, *, cleanup_clean=False)`. Its caller supplies the
actual cleanup verdict. With two clean completed workers and clean final
cleanup, a failed study uses `study_evidence_failed`; it cannot claim cleanup
failed merely because report or evidence verification failed. Other worker
progress classes remain unchanged. Both writing and reloading the terminal
enforce this distinction against its strict boolean `clean` field. This adds
no reservation, retry, execution authority or product interface. Matching unit
and CORE filesystem integration cases exercise both classifications and reject
the opposite code. The actual driver failure receipt remains the detailed
cause; the allocation terminal records coarse worker/finalization progress.

### 20.2 Final review corrections and composed host boundaries

The maintained correspondence grader catches only `ExperimentRefusal` and
its subclasses as genuine grading gaps. Unexpected errors propagate through
the public-text adapter. Regressions must invoke the actual deeper grader,
rather than replace that entire helper. Journal-finalization, journal-framing
and report errors remain independent diagnostics when a primary study failure
already exists. Interrupted studies attempt failure receipt/export after
cleanup and then propagate the original interrupt. An unsuccessful diagnostic
write does not release an allocation or authorize a retry.

The sidecar writer estimates its contribution from decoded journal bytes.
That estimate is not an exact aggregate stdout count. The decoder and host
readback enforce the unchanged 96 MiB cap over actual captured bytes before
verification; oversized output refuses even if it was emitted successfully.

`read_actual_gate` is a bounded data reader, not native authority. The private
host composes it with `validate_native_gate` on each actual generation before
reservation and raw-response verification. The generation-2 stale proof joins
the retained generation-1 publication. Its 8 MiB live-log bound applies while
workers are waiting for admission. The driver emits large journal and sidecar
frames only after both generations and cleanup; final verification reads the
bounded captured stdout and actual archived gate payloads directly.

PTX documents and admitted queries are subsets of their corresponding v1
inputs; the declared count comparisons preserve that paired-arm invariant.
Generation 1 still requires at least one admitted PTX query from the fixed
four-candidate set, and generation 2 still has none. Allocation receipts carry
digests and sequence state; they do not validate the underlying gate content
or prove native origin. The private host must bind those digests to actual
frames, requests, source/task closures, operator authority and raw outputs.

### 20.3 Exact final-driver source integration owners

These are scoped source-proof selectors, all run with `--no-coverage` through
the canonical containerized runner. They grant no model, native, scientific,
complete-suite or hosted-CI acceptance.

The CORE profile selects these eight whole-file owners (25 current cases):

```text
src/test/int/python/tools/retrieval_public_text_tasks.int.test.py
src/test/int/python/tools/retrieval_public_text_request.int.test.py
src/test/int/python/tools/retrieval_public_text_capture.int.test.py
src/test/int/python/tools/retrieval_public_text_census.int.test.py
src/test/int/python/tools/retrieval_public_text_journal.int.test.py
src/test/int/python/repomap_kg/retrieval/public_text_custody_regressions.int.test.py
src/test/int/python/repomap_kg/retrieval/lexical_capture_source_boundaries.int.test.py
src/test/int/python/repomap_kg/storage/lexical_query_scope_boundaries.int.test.py
```

The journal owner includes both allocation classifications from section 20.1
and the actual exclusive-write failure regression. The pgvector profile
selects these exact owners (four current cases), including the complete
functional lifecycle with synthetic raw delivery over the real boundaries:

```text
src/test/int/python/tools/retrieval_public_text_postgres.int.test.py
src/test/int/python/repomap_kg/storage/semantic_candidate_runtime_boundaries.int.test.py
src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py::test_public_text_functional_lifecycle
```

The learned selector from section 19.2 is excluded from source proof. The
refreshed functional run retained the genuine two-generation journals,
actual raw members, source/task joins and all 864 observed cells. Every
incumbent arm demonstrated verified file grading on applicable tasks.

### 20.4 Accepted bounded native observation

Native CAL5 completed both workers and the canonical study with clean terminals
on 2026-11-12. The parent strict raw-evidence replay matched its 864-cell report,
actual model members, source archives, fixed tasks and cleanup. Report identity:
`sha256:37461c6d4fba05e1952402249563592cd2e77bc2fc0fbd9eb2447da942858ea4`.
All scientific/release acceptance flags remain false. The original failed
attempts, document-only generation-2 rule and no-retry boundaries stand. See
[the outcome](cloe-public-text-calibration-outcome-v1.md) for exact proof scope.
