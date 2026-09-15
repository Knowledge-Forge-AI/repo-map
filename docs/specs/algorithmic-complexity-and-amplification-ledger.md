# RepoMap Algorithmic Complexity And Amplification Ledger

## Status and purpose

This document records the source-derived algorithmic complexity, client and
PostgreSQL resource exposure, storage amplification, compatibility cost, and
remaining evidence boundary of the normalized RepoMap full-refresh pipeline at
ARCH-CLOSE.

The ledger is an architecture audit. It does not change source, schemas,
migrations, dependencies, public contracts, publication authority, graph
state, or protected inputs. It does not claim that the SCALE acceptance
campaign completed. It gives no protected repository identity, path, source
value, database value, backend identifier, connection value, raw SQL, or raw
telemetry.

The governing records are:

- [RepoMap architecture](architecture.md);
- [ADR 0039: synchronous and asynchronous architecture](../adr/2026/07/0039-synchronous-and-asynchronous-architecture.md);
- [ADR 0040: SCALE0 high-scale full-refresh ingestion](../adr/2026/07/0040-high-scale-full-refresh-ingestion.md);
- [SCALE epic log](../status/2026/07/14/00537-scale-epic-log.md); and
- [SCALE10 acceptance-campaign record](../status/2026/07/15/00567-scale10-argo-cd-acceptance-campaign.md).

All complexity statements are static upper bounds or source-derived accounting
unless a cited accepted record explicitly identifies a measurement. Percent
contributions are reported only when the accepted records isolate them.

## Overall judgment

**The normalized architecture is sound for resuming SCALE under a separately
approved plan.**

ARCH1 through ARCH8 remove both confirmed quadratic paths, retire legacy graph
amplification, establish closed family descriptors, bound representation and
spool lifetimes, attribute every accepted pipeline boundary, remove every
production import SCC and test-support dependency, bound public read surfaces,
separate run from publication authority, and deploy exact ownership,
backup-first upgrade/recovery, least privilege, privacy, readiness, and
packaged runtime boundaries. ARCH8 integrates the public-safe repository and
operational gates. Protected-scale throughput remains deliberately unclaimed;
that is the next campaign's evidence objective, not an unresolved architecture
defect.

## Variables and accounting rules

The ledger uses the following symbols.

| Symbol | Meaning |
| --- | --- |
| `C` | Total parsed configuration entries and fields across RepoMap configuration files. |
| `F` | Discovered file rows. |
| `B` | Total bytes read from candidate source files across one named pass. Repeated passes are counted separately. |
| `O` | Raw observations, including file observations and extractor diagnostics represented as observations. |
| `R` | Historical relationship rows used by pre-ARCH4C legacy-projection evidence. |
| `FN` | Historical file-derived legacy node proposals. |
| `LNP` | Legacy node staging proposals. `LNP = FN + 2R` under the current adapter. |
| `LVP` | Legacy evidence staging proposals. `LVP = F + R` under the current adapter. |
| `LEP` | Legacy edge staging proposals. `LEP = R` under the current adapter. |
| `LN` | Historical retained legacy node rows after proposal selection; `LN <= LNP`. |
| `LE` | Historical retained legacy edge rows after proposal selection; `LE <= LEP`. |
| `LV` | Historical retained legacy evidence rows after proposal selection; `LV <= LVP`. |
| `CN` | Canonical node rows. |
| `CE` | Canonical edge rows. |
| `CV` | Canonical evidence rows. |
| `CNL` | Canonical node-evidence link rows. |
| `CEL` | Canonical edge-evidence link rows. |
| `D` | Diagnostics retained outside `O` by a stage, when applicable. |
| `Q` | Rows selected by one readback request. |
| `K` | Saved baseline files for one graph and baseline kind. |
| `P` | HTML-to-stylesheet pairs considered by CSS/HTML cross-file matching. |
| `S` | CSS selectors considered for one HTML-to-stylesheet pair. |
| `H` | HTML elements retained for one matched document. |
| `M` | Distinct list-valued metadata items accumulated into one canonical edge. |

Rules for interpreting the ledger:

- `Theta` denotes a tight source-derived bound for the described operation.
- `O(...)` denotes an upper bound where extractor behavior or PostgreSQL plan
  selection prevents a tighter statement.
- A pass means a complete traversal of the named input representation.
- A sort is counted separately even when it is required for determinism.
- PostgreSQL memory exposure is not the same as client peak RSS.
- Durable staging, final tables, indexes, temporary files, and WAL are separate
  amplification surfaces.
- Family counts are not interchangeable. In particular, `O`, `CV`, `CNL`, and
  `CEL` may have materially different cardinalities.
- No percentage is inferred from elapsed bands, row counts, byte deltas, or
  aggregate counters unless the source record isolates the numerator and
  denominator for the same interval.

## Classification of costs

### Asymptotic defects

An asymptotic defect performs avoidable superlinear work as one logical input
dimension grows. The audit identified exactly two confirmed localized defects:

1. CSS descendant matching could take `Theta(P * S * H^2)` before ARCH6A; and
2. canonical edge metadata list accumulation could take `Theta(M^2)` before
   ARCH6B.

Both localized defects are resolved. Their historical bounds remain recorded
to preserve the evidence for the accepted structural corrections.

### Constant-factor and storage amplification

The following costs remain linear in the aggregate input or output but retain,
serialize, parse, hash, transfer, index, or log the same logical information
multiple times:

- content hashing followed by extractor reads;
- whole-repository observation materialization before observation spooling;
- legacy and canonical projection from the same observation sequence;
- ten simultaneously retained or spooled staging families;
- JSONL serialization and replay for observations and large row families;
- typed identity and payload serialization plus two SHA-256 computations per
  staged row for completeness evidence;
- one COPY operation per retained family;
- durable staging plus final-table writes and index maintenance;
- PostgreSQL temporary files for spill-prone sort, distinct, and join plans;
- WAL for durable staging, final mutation, stage state, and cleanup; and
- complete JSON aggregate materialization at readback boundaries.

These are not asymptotic defects merely because their constants can dominate a
large run.

### Necessary compatibility and correctness cost

The following costs are required by accepted contracts until a separate phase
changes those contracts with parity evidence:

- `files`, raw observations, and the five canonical graph/evidence families
  remain retained; legacy graph families are historical only;
- raw ordinals, payload hashes, stable keys, canonical keys, graph-key versions,
  evidence identities, and link identities remain exact;
- all seven current families participate in the stage manifest and
  completeness proof;
- duplicate proposals and missing references fail closed or select the accepted
  deterministic compatibility winner;
- source, configuration, extractor, and canonicalizer generations are fenced;
- the staged forced-full graph mutation and complete publication receipt share
  the sole authoritative transaction; no receiptless final mutation path
  remains;
- commit-unknown state is reconciled from durable receipt evidence;
- public/private presentation boundaries redact configured private markers;
  and
- deterministic output requires stable traversal or explicit ordering.

The existence of a correctness cost does not establish that its current
implementation has the lowest safe amplification.

### Hypotheses requiring measurement

The following are hypotheses, not confirmed defects:

- repeated full source-generation scans may be a material fraction of
  pre-storage elapsed time;
- one or a small subset of staging families may dominate COPY transfer,
  checksum work, stage bytes, index maintenance, or WAL;
- `ANALYZE stage_canonical_node_evidence` may be material for skewed stages;
- ordered array aggregation and correlated lateral aggregation in source
  readback may perform avoidable work at large result cardinalities;
- PostgreSQL parallel workers may multiply per-node memory and I/O exposure for
  validation or merge plans; and
- stage cleanup may create a material secondary WAL and dead-tuple cost.

The accepted public evidence does not provide safe percentages for these
hypotheses.

## End-to-end pipeline ledger

### 1. Configuration discovery, parsing, overlay, and validation

- **Source boundary:** `repomap_kg.ops.config.load_ops_config_home()`,
  `read_toml_payload()`, `merge_ops_config_payloads()`, and
  `build_ops_config_from_payload()`.
- **Input/output cardinality:** configuration files and `C` parsed entries become
  one `OpsConfig`, ordered graph/source lists, and bounded diagnostics.
- **Time:** `Theta(C)` after deterministic filename sorting; directory entry and
  selected-file sorting add `O(c log c)` for `c` configuration files.
- **Peak client memory:** `Theta(C)` because parsed file payloads and the merged
  payload coexist.
- **PostgreSQL memory exposure:** none during pure configuration load. Separate
  status checks issue bounded readback queries.
- **Disk/staging/WAL:** configuration reads only; no staging or WAL.
- **Passes/sorts/hashes/serialization:** one TOML parse per selected file; two
  deterministic filename orderings; one overlay pass; no content hash.
- **COPY/validation/merge/index needs:** none. Schema and field validation are
  client-side.
- **Cancellation/parallelism:** sequential and without a cancellation token.
- **Constants:** supported suffixes are `*.rp.toml` followed by `*.rpl.toml`;
  no source-derived global count or byte limit applies here.
- **Measured evidence:** no stage-isolated performance measurement is recorded.
- **Judgment:** **Sound for deterministic configuration semantics; structurally
  acceptable.** The absence of a cancellation token is not material for normal
  small configuration sets, but no public resource bound is established.

### 2. Configured authority resolution and generation snapshot

- **Source boundary:**
  `repomap_kg.coordinator.configured_refresh.ConfiguredRefreshResolver` and
  `repomap_kg.ops.source_generation.scan_source_generation()`.
- **Input/output cardinality:** one graph request and configured root produce one
  authority snapshot with four generation identifiers and connection routing.
- **Time:** configuration work plus `Theta(B + F log F)` for a successful source
  inventory and deterministic generation serialization.
- **Peak client memory:** source bytes are chunked, but `F` digest records are
  retained and serialized; peak is `Theta(F)` plus the encoded inventory.
- **PostgreSQL memory exposure:** none for generation discovery; publication
  read methods later issue bounded queries.
- **Disk/staging/WAL:** source reads only.
- **Passes/sorts/hashes/serialization:** one SHA-256 content digest per source
  entry, a deterministic record sort, JSON serialization of the full inventory,
  and one generation SHA-256. Request resolution and later authority resolution
  can each take a fresh snapshot before full extraction performs its own reads.
- **COPY/validation/merge/index needs:** none.
- **Cancellation/parallelism:** polling snapshots accept a cancellation event;
  ordinary request and authority resolution do not. Scanning is sequential.
- **Constants:** default scan bounds are 10,000 files, 16 MiB per file, 512 MiB
  total, 1 MiB chunks, two retries, 1,024 path characters, and 30 seconds.
- **Measured evidence:** SCALE10 reports the complete pre-storage partition only
  as an under-ten-minute band; generation scanning is not isolated within it.
- **Judgment:** **Correctly fenced but amplified.** Repeated full-source snapshot
  work requires structural review while generation equivalence remains exact.

### 3. Repository discovery, filtering, classification, and content hashing

- **Source boundary:** `repomap_kg.graph.discovery.discover_repository()` and
  `classify_path()`.
- **Input/output cardinality:** a repository tree produces `F` unique `FileInfo`
  records and `F` file observations later in extraction.
- **Time:** `Theta(B + F log F)` as a repository-level bound, plus per-directory
  filename and directory-name sorts.
- **Peak client memory:** `Theta(F)` for the file list and deduplication mapping.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** source reads only.
- **Passes/sorts/hashes/serialization:** deterministic `os.walk`, sorted child
  names, symlink containment checks, exclude matching, a content SHA-256 per
  admitted file, path-keyed deduplication, and one final path sort.
- **COPY/validation/merge/index needs:** none.
- **Cancellation/parallelism:** sequential; the normal refresh discovery path
  has no cancellation token.
- **Constants:** ignore and configured-exclude sets are finite source constants;
  the normal refresh path has no global `F` or `B` limit comparable to the
  polling source-generation scan.
- **Measured evidence:** SCALE10 includes discovery in the combined pre-storage
  band and does not isolate its percentage.
- **Judgment:** **Deterministic and privacy-conscious, but not independently
  resource-bounded for full refresh.** Repeated ordering is a modest constant;
  repeated file reads are the larger amplification.

### 4. Per-file extractor dispatch

- **Source boundary:** `repomap_kg.graph.discovery.discover_observations()` and
  the language/document extractor packages.
- **Input/output cardinality:** `F` files produce `O` observations and extractor
  diagnostics represented within `O`.
- **Time:** normally `O(B + O)` plus parser-specific work. This statement excludes
  the confirmed CSS/HTML cross-file defect below.
- **Peak client memory:** `Theta(F + O)` because the discovery list, repository
  path set, cross-file indexes, and observation list coexist.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** source reads only before observation spooling.
- **Passes/sorts/hashes/serialization:** dispatch is a fixed ordered chain of
  language predicates. Recognized files are read after discovery hashing.
  Markdown also participates in a repository anchor-index pass before its file
  extractor, making multiple byte passes source-visible.
- **COPY/validation/merge/index needs:** none.
- **Cancellation/parallelism:** per-file dispatch is sequential. Individual
  parser limits vary by extractor family.
- **Constants:** the number of dispatch predicates is a fixed source constant;
  there is no repository-wide observation bound on this path.
- **Measured evidence:** SCALE10 attributes no percentage to language dispatch.
  Earlier accepted records show that pre-storage can complete, but do not prove
  a general resource bound for every document shape.
- **Judgment:** **Semantically sound but structurally over-retentive.** Full-list
  materialization and heterogeneous extractor bounds require revision.

### 5. Go helper subprocess protocol

- **Source boundary:**
  `repomap_kg.extractors.languages.golang.extract_go_repository_observations()`,
  `repomap_kg.extractors.languages.go_protocol.iter_go_protocol_observations()`,
  and `src/main/go/`.
- **Input/output cardinality:** sorted unique Go paths and bytes `B_go` produce
  `O_go` observations/diagnostics.
- **Time:** `O(B_go + O_go)` under the per-file protocol limits.
- **Peak client memory:** the protocol queue is bounded, but the Python caller
  converts the yielded stream to a tuple and later appends companion
  observations, giving `Theta(O_go)` retained client memory.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** source reads and subprocess pipes only.
- **Passes/sorts/hashes/serialization:** path deduplication and sort; one JSON
  request/response stream; protocol validation for sequence, path, counts, and
  terminal `file_end`.
- **COPY/validation/merge/index needs:** none.
- **Cancellation/parallelism:** requests are sequential. Two daemon reader
  threads drain bounded stdout/stderr channels. Failure terminates the helper
  and joins readers within bounded cleanup waits.
- **Constants:** protocol version 1; 1 MiB maximum line; 64 KiB retained stderr;
  250,000 observations and 32 diagnostics per file; eight stdout queue lines;
  30-second response and two-second cleanup timeouts. Go path scope limits paths
  to 4,096 bytes and rejects symlink escapes.
- **Measured evidence:** Go unit tests cover deterministic output, malformed
  input, bounded diagnostics, protocol line limits, path containment, and
  sequential command behavior. No independent large-run throughput percentage
  is available.
- **Judgment:** **The helper protocol is sound and bounded; the Python tuple
  boundary is an avoidable retention point.**

### 6. Cross-file CSS/HTML selector matching

- **Source boundary:**
  `repomap_kg.extractors.documents.css_html_matching.extract_css_selector_match_observations()`,
  `_match_selector()`, and `_has_matching_ancestor()`.
- **Input/output cardinality:** `P` stylesheet pairs, `S` selectors per pair, and
  `H` elements per HTML document produce CSS match observations included in
  `O`.
- **Time:** **`O(H + P * S * H * D)` after ARCH6A**, where `D` is the bounded
  pointer depth walked for a candidate. One pointer lookup is built per matched
  HTML document and reused across linked stylesheets and selectors. The prior
  confirmed worst case was `Theta(P * S * H^2)` because every candidate rebuilt
  the full lookup.
- **Peak client memory:** persistent indexes are `O(O + H)` for the per-document
  element lookup; repeated transient `Theta(H)` maps are removed.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** none before downstream observation spooling.
- **Passes/sorts/hashes/serialization:** one observation-index construction,
  one element-map construction per matched document, then deterministic nested
  pair/selector/element scans.
- **COPY/validation/merge/index needs:** downstream match observations inherit
  normal raw/canonical staging costs.
- **Cancellation/parallelism:** sequential and without a cancellation point in
  the nested match loop.
- **Constants:** selectors with more than two descendant parts are rejected;
  this limits selector grammar, not `H` or the quadratic work.
- **Measured evidence:** the ARCH6A adversarial size series in
  `src/test/unit/python/repomap_kg/extractors/documents/css_html_matching.unit.test.py`
  produces 32, 64, and 128 matches with 51, 99, and 195 element traversals for
  16, 32, and 64 descendants. Successive traversal ratios are 1.94 and 1.97.
- **Exact evidence:** `extract_css_selector_match_observations()` owns the
  document lookup cache, `_match_selector()` receives that lookup, and
  `_has_matching_ancestor()` performs pointer lookups without rebuilding it.
- **Judgment:** **Algorithmically sound under the documented selector-grammar
  and pointer-depth bounds after ARCH6A.**

### 7. Observation materialization, generation, and spool

- **Source boundary:** `repomap_kg.ops.refresh.refresh_graph()`,
  `repomap_kg.ops.generations.source_generation()`, and
  `repomap_kg.observations.spool.ObservationSpool`.
- **Input/output cardinality:** the discovery list of `O` observations becomes a
  tuple, one source-generation digest, and, in staged mode, a replayable JSONL
  observation spool of `O` records.
- **Time:** `Theta(O + bytes(O))` for tuple creation, generation processing, and
  spool serialization.
- **Peak client memory:** before spooling, discovery's list and the new tuple can
  overlap. The spool is created before the tuple is released. Peak is therefore
  `Theta(O)` with an avoidable representation multiplier.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** private temporary JSONL of `Theta(bytes(O))`; no
  PostgreSQL staging or WAL yet.
- **Passes/sorts/hashes/serialization:** one list-to-tuple pass; generation hash
  work; one observation JSON serialization pass; every later spool traversal
  reparses JSONL.
- **COPY/validation/merge/index needs:** none at this stage.
- **Cancellation/parallelism:** sequential. The spool has explicit close and
  deletion paths; refresh cancellation is not polled during serialization.
- **Constants:** no spool-size ceiling is source-defined for full refresh.
- **Measured evidence:** accepted SCALE9A records establish that observation
  spooling reduced prior tuple retention but did not eliminate the completed
  preparation peak. SCALE10 does not isolate this stage's percentage.
- **Judgment:** **Correctness-preserving but unnecessarily amplified.** A bounded
  handoff must avoid simultaneously retaining the complete discovery and spool
  representations.

### 8. Historical legacy file and relationship projection

This pre-ARCH4C boundary is retained only to explain the removed amplification
and the accepted seven-family delta. It is absent from the current pipeline.

- **Source boundary:** `repomap_kg.storage.legacy_rows` and
  `repomap_kg.storage.staged_rows.build_staged_rows()`.
- **Input/output cardinality:** `O` observations produce `F` file rows, `R`
  relationship rows, `LNP = FN + 2R` legacy-node proposals, `LVP = F + R`
  legacy-evidence proposals, and `LEP = R` legacy-edge proposals. The later
  merge reduces those proposals by stable key to retained `LN`, `LV`, and `LE`.
- **Time:** `O(O + F log F + R log R + LNP + LVP + LEP)` under deterministic
  row ordering and proposal construction.
- **Peak client memory:** `Theta(F + R + LNP + LVP + LEP)` while the proposal
  families are materialized or spooled; file and relationship source sequences
  remain live while canonicalization also runs.
- **PostgreSQL memory exposure:** none until COPY.
- **Disk/staging/WAL:** row families over the threshold become temporary JSONL;
  smaller families remain tuples.
- **Passes/sorts/hashes/serialization:** observations are traversed for file rows
  and again for relationship rows. Stable keys and metadata payloads are built
  for every proposal. Deterministic ordering is compatibility-significant.
- **COPY/validation/merge/index needs:** four retained stage/final families need
  stage ownership/ordinal indexes, stable-identity lookups, and legacy endpoint
  validation. SCALE3 owns eight fixed legacy/raw validation and merge
  statements.
- **Cancellation/parallelism:** sequential client preparation and family
  adaptation. PostgreSQL plan parallelism is a later stage concern.
- **Constants:** legacy families remain required by SCALE1; no family may be
  removed as a performance shortcut.
- **Measured evidence:** SCALE0's row-wise statement model includes these writes
  in `3F + 4R`; `FN`, `LNP`, `LVP`, `LEP`, and retained `LN`, `LV`, and `LE`
  have no independent row-wise statement terms. SCALE10 does not isolate their
  staging contribution.
- **Judgment:** **A necessary compatibility boundary whose current simultaneous
  retention and generic treatment require revision, not silent removal.**

### 9. Canonicalization and deterministic graph construction

- **Source boundary:**
  `repomap_kg.canonicalization.main.canonicalize_observations()`, canonical
  family handlers, and `canonicalization_result_from_state()`.
- **Input/output cardinality:** `O` observations produce `CN`, `CE`, `CV`, `CNL`,
  `CEL`, and `D` diagnostics.
- **Time:** normally
  `O(O + CN + CE + CV + CNL + CEL + D)`. Deterministic presentation adds
  `O(CN log CN + CE log CE + CV log CV + CNL log CNL + CEL log CEL + D log D)`.
  The edge metadata defect below adds a localized `Theta(M^2)` term.
- **Peak client memory:**
  `Theta(CN + CE + CV + CNL + CEL + D)` for canonical state. `to_dict()` creates
  sorted lists and dictionaries, adding another output-sized representation at
  presentation boundaries.
- **PostgreSQL memory exposure:** none until stage COPY/validation.
- **Disk/staging/WAL:** canonical row families may later be spooled; no
  PostgreSQL cost in pure canonicalization.
- **Passes/sorts/hashes/serialization:** a Go-context prepass, one fixed ordered
  family-dispatch pass, Go finalization, canonical identity hashes, and explicit
  output sorts for serialization.
- **COPY/validation/merge/index needs:** five canonical families require typed
  proposal, raw-reference, endpoint/evidence-reference, identity, and final
  uniqueness checks. SCALE4 owns eleven fixed canonical validation and merge
  statements.
- **Cancellation/parallelism:** sequential and without a cancellation token in
  the main dispatch loop.
- **Constants:** dispatch branch count is fixed by accepted source; output
  cardinalities are not globally bounded.
- **Measured evidence:** accepted records show canonicalization can complete on
  large inputs, but SCALE10 reports no stage-isolated percentage or peak for the
  accepted commit.
- **Judgment:** **The graph model and deterministic dispatch are sound; resource
  and cancellation structure require revision, and the metadata defect must be
  removed.**

### 10. Canonical edge metadata accumulation

- **Source boundary:** `repomap_kg.canonicalization.core._upsert_edge()`,
  `_merge_summary_metadata()`, and `_append_distinct_json_values()`.
- **Input/output cardinality:** repeated proposals for one edge accumulate `M`
  distinct values in list-valued summary fields.
- **Time:** **expected `O(J)` after ARCH6B**, where `J` is the total traversed
  JSON-compatible structure across retained and incoming values, under standard
  Python dictionary performance. The historical implementation was confirmed
  `Theta(M^2)` because every merge copied and linearly searched the existing
  list.
- **Peak client memory:** `Theta(M)` retained metadata plus `Theta(M)` equality
  keys and bucket references. Repeated transient full-list copies are removed.
- **PostgreSQL memory exposure:** none in canonicalization; the enlarged payload
  later increases stage/final row size, COPY bytes, checksum bytes, WAL, and
  readback serialization.
- **Disk/staging/WAL:** downstream amplification is linear in the final metadata
  bytes; the quadratic defect is client CPU/allocation work.
- **Passes/sorts/hashes/serialization:** the first merge indexes existing values
  once; each later incoming value is recursively keyed once and checked only
  against its collision bucket before later JSON and checksum serialization.
- **COPY/validation/merge/index needs:** no special index requirement; identity
  and payload equivalence must remain unchanged.
- **Cancellation/parallelism:** sequential and without an inner-loop
  cancellation point.
- **Constants:** no bound on `M` is enforced.
- **Measured evidence:** the ARCH6B adversarial fan-in size series in
  `src/test/unit/python/repomap_kg/canonicalization/canonical_edge_metadata_accumulation.unit.test.py`
  records 192, 384, and 768 equality/hash work units for 16, 32, and 64
  proposals. Both doubling ratios are 2.00. The red baseline recorded 480,
  1,984, and 8,064 work units with ratios 4.13 and 4.06.
- **Exact evidence:** `_DistinctJsonValues` retains first-seen list order and a
  private equality-key index; `_json_value_key()` covers mappings, lists,
  tuples, scalars, and a conservative unhashable fallback; collision buckets
  confirm exact equality before append. A pinned whole-result digest and edge
  key prove serialized graph and identity parity.
- **Judgment:** **Algorithmically sound under standard dictionary-performance
  assumptions and the documented JSON-compatible metadata contract after
  ARCH6B.**

### 11. Seven-family staging adaptation and row spooling

- **Source boundary:** `repomap_kg.storage.staged_rows.build_staged_rows()`,
  `_family_rows()`, `_materialize_or_spool()`, and
  `repomap_kg.storage.row_spool.RowSpool`.
- **Input/output cardinality:** observations and current file/raw/canonical
  projections become exactly seven family iterables with aggregate cardinality
  `F + O + CN + CE + CV + CNL + CEL`. ARCH5 removed the three legacy families.
- **Time:** linear in aggregate family rows and serialized bytes, excluding the
  previously identified defects and deterministic sorts.
- **Peak client memory:** file rows, relationship rows, and the complete
  canonical graph coexist during preparation. Each family retains up to 4,096
  rows in memory or writes a spool after buffering 4,097 rows. Small families
  can all remain materialized simultaneously.
- **PostgreSQL memory exposure:** none before connection work begins.
- **Disk/staging/WAL:** every large family becomes a private JSONL spool. All seven
  family handles are retained until the complete staged operation exits.
- **Passes/sorts/hashes/serialization:** at least three observation traversals
  occur for file rows, relationship rows, and canonicalization. Large rows are
  JSON-serialized to spools and reparsed on every checksum or COPY traversal.
- **COPY/validation/merge/index needs:** the closed family catalog drives later
  COPY and count validation. Family-specific semantics cannot be inferred from
  the generic loop alone.
- **Cancellation/parallelism:** family preparation is sequential and does not
  poll cancellation. Explicit close paths remove spools on normal and error
  exits.
- **Constants:** exactly seven families; row-spool threshold 4,096.
- **Measured evidence:** ARCH6C uses public-safe 32, 512, and 4,200 observation
  fixtures. Each preparation performs four complete observation-sequence
  iterations, retains seven family containers, and emits five prepared rows per
  observation. Normalized bytes are 104,311, 1,676,802, and 13,810,869. The
  full fixture retains five spools totaling 8,131,599 bytes.
- **Exact evidence:** the full fixture performs five pre-COPY spool replay
  passes and decodes all 21,000 spooled rows solely for checksum calculation.
  Small and medium fixtures remain below the spool threshold. Checksum-manifest
  digests are pinned for every size and remain stable across equal-length stage
  identifiers.
- **Correction evidence:** ARCH6D preserves the same 160, 2,560, and 21,000
  prepared rows; normalized bytes; 8,131,599 full-fixture spool bytes; and all
  three checksum-manifest digests. Checksum-only spool replay falls from five
  passes and 21,000 decoded rows to zero. The independent COPY replay remains.
- **Lifetime evidence:** ARCH6E records all five full-fixture spools and all
  8,131,599 bytes live before each of seven family COPY boundaries and still
  live after the loop. The five replay passes and 21,000 replayed rows are
  exactly the intended COPY consumption. Later boundaries use only aggregate
  counts, checksums, classifications, and file count.
- **Lifetime correction:** ARCH6F releases each spool after its successful COPY.
  Full-fixture live spool count before successive family boundaries becomes
  5, 4, 3, 2, 2, 1, 0 and final live spool bytes become zero. COPY still
  performs exactly five passes over 21,000 rows. Failed and unconsumed spools
  remain owned by final idempotent cleanup.
- **Pass attribution:** ARCH6G records exactly one file-projection pass, one
  Go-context-filter pass, one canonical-dispatch pass, and one raw-projection
  pass at 32, 512, and 4,200 observations. Each pass visits exactly `N` items;
  there are no unattributed visits. The file-only Go pass produces zero claims,
  but establishes the absence of Go inputs for the canonical forward-resolution
  context. No accepted layer already owns a reusable kind index.
- **Judgment:** **The closed family contract is correct, but preparing every
  family before the first COPY retains required completeness evidence. Keeping
  consumed spools after their successful COPY was unnecessary lifetime
  amplification and is corrected by ARCH6F. The remaining four fixed-count
  passes are intentional bounded linear architecture.**

### 12. Typed family completeness checksums

- **Source boundary:** `repomap_kg.storage.staging_checksums.checksum_family()`.
- **Input/output cardinality:** each family row produces contributions to one
  `FamilyChecksum`: row count, normalized byte count, stable-key digest, and
  payload digest.
- **Time:** `Theta(total typed serialized family bytes)` with two SHA-256 inputs
  and modular 256-bit accumulation per row. Nested mappings are key-sorted.
- **Peak client memory:** bounded per row plus the decoded spool row, but the
  family source remains retained for the later COPY pass.
- **PostgreSQL memory exposure:** none.
- **Disk/staging/WAL:** no new durable data; reading a family spool causes a full
  disk pass.
- **Passes/sorts/hashes/serialization:** one complete family pass; typed identity
  serialization; typed payload serialization that embeds identity again; two
  SHA-256 operations per row; final stream digests. A later COPY requires
  another complete pass.
- **COPY/validation/merge/index needs:** checksums are stage-header completeness
  evidence; they do not replace typed PostgreSQL conflict/reference validation.
- **Cancellation/parallelism:** sequential and without a cancellation token.
- **Measured evidence:** ARCH6C records zero checksum spool replays below the
  4,096-row threshold and five replay passes covering 21,000 rows for the
  4,200-observation fixture.
- **Correction evidence:** ARCH6D feeds the existing order-independent
  checksum-v2 accumulator immediately before each private spool write. The
  full fixture records one bounded checksum event per family but no checksum
  spool iteration. `checksum_family()` remains the materialized-family path and
  iterable parity oracle, not a spool fallback.
- **Judgment:** **Corrected for spooled families. Checksum work is fused with
  spool creation, and only COPY replays the private spool.**
- **Constants:** checksum protocol v2; SHA-256; order-independent addition modulo
  `2^256`.
- **Measured evidence:** the controlled deterministic observer aggregates the
  checksum duration separately without per-row events. The repeated fixture's
  diagnostic host probe changed from 1.07 to 1.04 seconds real time and from
  59,179,008 to 59,654,144 bytes maximum resident set size. These small changes
  are not accepted as deterministic performance thresholds; the exact accepted
  result is removal of 21,000 spool decodes.
- **Judgment:** **Necessary correctness evidence with significant serialization
  amplification.** Its cost must be measured independently before changing the
  typed contract.

### 13. Stage ownership, header creation, and durable preparation setup

- **Source boundary:** `repomap_kg.storage.staged_ingestion.run_staged_full_refresh()`,
  `StageHeader`, `StageOwner`, and the SCALE1 migration.
- **Input/output cardinality:** one authority, repository, run, and prepared
  family manifest create one durable attempt-scoped stage header.
- **Time:** fixed client work plus bounded indexed database reads/writes; no row
  family transfer occurs in the header itself.
- **Peak client memory:** the complete `PreparedStageRows` remains live while
  connection, repository, run, and stage state are established.
- **PostgreSQL memory exposure:** bounded catalog/identity lookups and row writes.
- **Disk/staging/WAL:** durable WAL-logged repository/run/stage rows are committed
  before family COPY. The 24-hour expiry and state indexes support recovery and
  cleanup classification.
- **Passes/sorts/hashes/serialization:** manifest counts, byte counts, and
  checksum payloads are serialized into the stage header.
- **COPY/validation/merge/index needs:** owner, operation, state, expiry,
  repository/run, and publication-reconciliation indexes are correctness and
  recovery requirements.
- **Cancellation/parallelism:** one owned connection; replay and commit-unknown
  paths are classified before new work. Client-side preparation has already
  completed before signal handlers can cancel PostgreSQL.
- **Constants:** default stage TTL 24 hours; safe connection cancellation timeout
  one second.
- **Measured evidence:** SCALE10 established coherent zero state and one owned
  direct attempt. Setup is not isolated as a percentage.
- **Judgment:** **Sound ownership and recovery model, but connection setup occurs
  too late to provide PostgreSQL cancellation during client preparation.**

### 14. Current seven-family COPY transfer and historical ten-family evidence

- **Source boundary:** `repomap_kg.storage.staged_ingestion._copy_families()` and
  `repomap_kg.storage.staging_copy.copy_stage_rows()`.
- **Input/output cardinality:** the seven family iterables transfer
  `F + O + CN + CE + CV + CNL + CEL` rows into seven regular stage tables.
- **Time:** `Theta(total adapted row bytes + stage index maintenance)` with one
  fixed COPY operation per family.
- **Peak client memory:** bounded per adapted row and Psycopg transfer buffers,
  while all prepared family sources remain retained.
- **PostgreSQL memory exposure:** COPY input conversion, constraints, relation
  buffers, and index maintenance. Exact per-backend and shared memory are not
  available in public evidence.
- **Disk/staging/WAL:** one durable stage row plus stage indexes per input row;
  WAL grows with logged stage writes. Failed COPY can leave reclaimable physical
  space even when rows are not visible after failure.
- **Passes/sorts/hashes/serialization:** each family spool is parsed again;
  mappings are adapted in fixed column order; JSONB uses explicit typed
  adaptation; COPY transmits through the client connection.
- **COPY/validation/merge/index needs:** exactly seven sequential COPY calls. Raw
  staging has `(stage_id, source_ordinal)` ownership; the other six stage
  tables use `(stage_id, family_ordinal)`. Families also have their specific
  identity/reference indexes from the SCALE1 migration.
- **Cancellation/parallelism:** application COPY is sequential by family. Signal
  handling requests safe connection cancellation. PostgreSQL may perform its
  own internal I/O work, but no application-level parallel COPY is present.
- **Constants:** seven COPY calls; family catalog is closed and identifiers are
  repository-owned.
- **Measured evidence:** ARCH4C reduced the generated public-safe data plane
  from 29 historical operations to 22 current operations by removing three
  legacy COPY streams and four legacy validation/merge operations. ARCH8
  accepts descriptor, observability, cleanup, and representation-lifetime
  coverage across the integrated public-safe ladder.
- **Judgment:** **Sound.** The typed descriptor-owned COPY boundary has closed
  family ownership, bounded spool lifetimes, cancellation, cleanup, and
  public-safe attribution.

### 15. Stage statistics and completeness validation

- **Source boundary:**
  `repomap_kg.storage.staged_ingestion._refresh_canonical_node_evidence_statistics()`,
  `mark_validating()`, `validate_stage()`, and `mark_validated()`.
- **Input/output cardinality:** seven active stage families produce seven
  observed counts, one pass/fail completeness decision, and stage-state
  updates. Historical pre-ARCH4C measurements include three additional legacy
  families.
- **Time:** one `ANALYZE stage_canonical_node_evidence` plus seven indexed or
  stage-filtered `count(*)` queries. The source-derived bound is linear in the
  rows scanned by the selected plans; exact plan cost is unavailable.
- **Peak client memory:** bounded scalar results.
- **PostgreSQL memory exposure:** statistics collection, scans, and aggregation.
  Hash/sort exposure depends on selected plans and configuration.
- **Disk/staging/WAL:** `ANALYZE` reads stage pages and writes statistics;
  stage-state changes generate WAL. Count queries are read-only but may perform
  physical I/O.
- **Passes/sorts/hashes/serialization:** one statistics refresh and one count
  validation per family. Typed conflict and reference guards occur in the final
  statement builders, not in `validate_stage()`.
- **COPY/validation/merge/index needs:** stage-id-leading indexes are needed to
  constrain family scans. Statistics are refreshed for the empirically
  sensitive canonical node-evidence table only.
- **Cancellation/parallelism:** sequential client statements. PostgreSQL may
  select parallel plans; each worker is a separate resource consumer.
- **Constants:** one explicit `ANALYZE`; seven count queries.
- **Measured evidence:** SCALE10 combines this work with staging and COPY. It
  records that final statement 1 had not begun, so final merge statements do
  not explain the elapsed partition. COPY, checksum, statistics, and count
  percentages are **unavailable**.
- **Judgment:** **Correct but inadequately observable.** The generic count loop
  proves completeness, not resource safety or semantic conflict/reference
  validity.

### 16. Set-based conflict/reference validation and final merge

- **Source boundary:** the file/raw merge builder with four fixed statements,
  `build_canonical_merge_statements()` with eleven fixed
  statements, and `execute_final_transaction()`.
- **Input/output cardinality:** seven validated stage families become retained
  final `F`, `O`, `CN`, `CE`, `CV`, `CNL`, and `CEL` rows or an
  all-or-nothing failure.
- **Time:** statement count is fixed, but server work is data-dependent. With
  suitable indexes, most identity and reference work should be linear or
  `O(X log Y)`; PostgreSQL can choose hash, sort, nested-loop, or parallel plans.
- **Peak client memory:** bounded statement/result handling while all prepared
  family sources remain retained until operation exit.
- **PostgreSQL memory exposure:** potentially several sort/hash/join nodes per
  statement, multiplied by concurrent nodes and parallel workers. `work_mem` is
  a base per-operation limit, and hash operations can use
  `work_mem * hash_mem_multiplier`.
- **Disk/staging/WAL:** temporary files can grow when sort/hash operations spill.
  Final table and final index writes generate WAL while durable stage rows still
  exist. Rollback preserves publication atomicity but does not make server work
  free.
- **Passes/sorts/hashes/serialization:** typed duplicate selection, raw payload
  checks, endpoint/evidence reference checks, set-based upserts, and deterministic
  family-ordinal compatibility selection.
- **COPY/validation/merge/index needs:** stage identity/reference indexes and
  final unique/foreign-key indexes are correctness and plan-shape prerequisites.
  Query plans must be examined with generated public-safe data before claiming
  scale safety.
- **Cancellation/parallelism:** client executes statements sequentially;
  PostgreSQL may use parallel workers. Failure before commit rolls back and marks
  the attempt failed. Commit ambiguity enters receipt-first reconciliation.
- **Constants:** four file/raw statements and eleven canonical statements.
  The current core data-plane count is 22 when combined with seven COPY calls.
- **Measured evidence:** SCALE9 accepted records demonstrate that semantically
  equivalent validation shapes can differ by orders of magnitude in temporary
  storage and elapsed time. SCALE10 did not reach final statement 1, so it adds
  no final-merge measurement.
- **Judgment:** **Semantically sound and correctly atomic, but plan-sensitive and
  not generally resource-bounded by statement count alone.**

### 17. Publication, commit-unknown reconciliation, and cleanup eligibility

- **Source boundary:** `repomap_kg.storage.staged_publication`, publication
  fencing, receipts, staging state transitions, and cleanup eligibility.
- **Input/output cardinality:** one validated attempt becomes one complete
  publication receipt and graph-authority update, or one failed,
  commit-unknown, cancelled, abandoned, or quarantined disposition.
- **Time:** fixed control work plus receipt and owner lookups; cleanup time is
  linear in stage-owned rows deleted when cleanup is authorized.
- **Peak client memory:** bounded control records.
- **PostgreSQL memory exposure:** row locks, transaction state, receipt lookups,
  and deletion/index maintenance during later cleanup.
- **Disk/staging/WAL:** the final transaction writes receipt/run/authority/stage
  state. Cleanup deletion generates additional WAL and dead tuples. Exact
  cleanup amplification is unavailable.
- **Passes/sorts/hashes/serialization:** owner/fence/generation revalidation;
  complete receipt write; receipt-first reconciliation after ambiguous commit.
- **COPY/validation/merge/index needs:** publication receipt, owner, fence,
  stage-state, and expiry indexes are necessary. Cleanup must remain
  stage-scoped and blocked for live, conflicting, commit-unknown, or quarantined
  attempts.
- **Cancellation/parallelism:** cancellation before final transaction can be
  classified normally. Commit ambiguity must not be rewritten as known failure
  from process exit. One mutating graph lease remains authoritative.
- **Constants:** one final authoritative transaction; stage TTL defaults to 24
  hours, but expiry does not override reconciliation safety.
- **Measured evidence:** SCALE10 reconciled one failed run, no complete receipt,
  no active or commit-unknown stage, and zero retained-family rows. It did not
  publish, run repeat parity, save an accepted baseline, establish drift parity,
  close SCALE, or issue a GO24 recommendation.
- **Judgment:** **Sound.** Receipt-first publication and fail-closed reconciliation
  are necessary correctness costs and must not be weakened for throughput.

### 17a. Historical receiptless row-wise mutation

ARCH0 measured this removed linear path because it duplicated transformation,
final mutation, and latest-run authority without staging, fencing, validation,
replacement deletion, a receipt, or commit-unknown recovery. ARCH4A migrated
complete callers to staged publication, ARCH4B made partial acquisition
non-publishing and retired incompatible public surfaces, and ARCH4C removed the
programmatic primitives and row-wise implementation. The historical formulas
and measurements later in this ledger remain attribution evidence only; they
are not current pipeline costs or supported API contracts.

### 18. Storage readback, CLI JSON/table output, connectors, and MCP

- **Source boundary:** `repomap_kg.storage.canonical`, SQL readback builders,
  `repomap_kg.storage.readback_driver`, storage CLI dispatch, and MCP canonical
  tools.
- **Input/output cardinality:** one request selects `Q` rows or one object whose
  embedded node/edge/evidence arrays can themselves contain `Q` rows.
- **Time:** PostgreSQL query/ordering/aggregation plus `Theta(serialized output
  bytes)`. Public list and embedded-collection endpoints are `O(Q log Q)` at
  worst for explicit ordering within their accepted bounded windows.
- **Peak client memory:** both psql and Psycopg paths materialize the complete
  JSON object/array and then construct Python record tuples/dictionaries.
- **PostgreSQL memory exposure:** JSON aggregation, ordering, joins, and source
  summary lateral subqueries. Ordered `ARRAY_AGG(...)[1]` constructs complete
  arrays to select one latest value in current source-summary SQL; its material
  impact is a hypothesis pending `EXPLAIN (ANALYZE, BUFFERS)` on generated data.
- **Disk/staging/WAL:** read-only queries generate no application writes; sort or
  hash nodes can spill to PostgreSQL temporary files.
- **Passes/sorts/hashes/serialization:** SQL JSON construction, psql text parse or
  Psycopg typed return, shape validation, record conversion, deterministic
  client JSON serialization, and private-marker sanitization.
- **COPY/validation/merge/index needs:** no COPY or merge. Canonical identity,
  kind/source/target, path, evidence-link, and source-summary indexes are
  necessary for bounded read plans.
- **Cancellation/parallelism:** one query per command/tool call; PostgreSQL may
  choose parallel plans. Connector errors are bounded and sanitized.
- **Constants:** public CLI and MCP canonical lists default to 50, accept
  non-negative offsets, and reject limits above 200. Neighborhood node/edge
  and explanation-evidence collections have independent windows with the same
  defaults and maxima. Canonical neighborhood depth remains fixed at one.
- **Measured evidence:** connector parity tests cover psql/Psycopg shape and
  record equivalence. SCALE10 used bounded status/summary/baseline/storage-state
  readbacks after quiescence; graph/file and MCP smoke were not applicable
  without publication.
- **Judgment:** **Sound.** Connector parity, privacy projection, deterministic
  ordering, versioned envelopes, and public list/embedded-collection bounds are
  explicit and tested.

### 19. Baseline and drift readback

- **Source boundary:** `repomap_kg.ops.baseline_operations` and
  `repomap_kg.ops.baselines`.
- **Input/output cardinality:** one stored summary and optional preflight summary
  are normalized against one baseline; pruning considers `K` saved baseline
  files per kind.
- **Time:** fixed-field stored-summary comparison; preflight inherits
  `Theta(B + F log F)` source work; pruning is `O(K log K)` for deterministic
  retention ordering.
- **Peak client memory:** bounded stored summaries; `Theta(F)` source inventory
  for preflight; `Theta(K)` baseline-path inventory during pruning.
- **PostgreSQL memory exposure:** stored-summary aggregates and status readback;
  no graph mutation.
- **Disk/staging/WAL:** atomic baseline-file publication and bounded path-scoped
  pruning; no stage or final-table write.
- **Passes/sorts/hashes/serialization:** normalization, deterministic JSON,
  stored/preflight comparison, and timestamp/path ordering.
- **COPY/validation/merge/index needs:** no COPY or merge; stored summary indexes
  and source-generation semantics remain compatibility obligations.
- **Cancellation/parallelism:** preflight uses bounded source scan behavior;
  baseline file operations are sequential.
- **Constants:** pruning requires `keep >= 1`; display output is bounded by the
  baseline helper's fixed display limit.
- **Measured evidence:** SCALE10 saved no accepted stored or preflight baseline
  and makes no drift claim because no graph published.
- **Judgment:** **Sound and appropriately fail-closed.** Baseline meaning must not
  be changed as an incidental performance optimization.

## Generic staging-family contract audit

The descriptor-owned staging layer closes the current catalog at seven
families and preserves each family's exact identity, row type, serializer,
checksum, COPY, validation, merge, observability, and cleanup behavior. Generic
iteration does not make their row widths, cardinalities, reference fan-out,
index costs, or final retention interchangeable.

| Current family | Cardinality | Completeness identity | Required semantic/index work | Audit result |
| --- | ---: | --- | --- | --- |
| `files` | `F` | `path` | Stage path identity, final repository/path identity, and deterministic replacement | Required first-class file/source index family; descriptor and resource attribution are explicit. |
| `raw_observations` | `O` | `source_ordinal` | Exact ordinal, payload-hash conflict guard, and run-scoped final identity | Required source-evidence family; row width and JSON payload remain independently attributed. |
| `canonical_nodes` | `CN` | graph-key version plus canonical key | Typed duplicate guard and canonical identity index | Required canonical graph family. |
| `canonical_edges` | `CE` | graph-key version, source, kind, target, and identity-metadata hash | Source/target reference guard and wide identity index | Required canonical graph family; endpoint-plan shape remains visible. |
| `canonical_evidence` | `CV` | graph-key version plus evidence key | Raw-reference guard, evidence identity index, and explicit statistics consumer through link validation | Required run-scoped canonical evidence family. |
| `canonical_node_evidence` | `CNL` | graph-key version, canonical key, evidence key, and link kind | Node/evidence reference guard, lookup index, and targeted stage statistics | Required canonical link family with explicit plan-sensitive attribution. |
| `canonical_edge_evidence` | `CEL` | canonical edge identity plus evidence key and link kind | Edge/evidence reference guard and composite lookup | Required canonical link family with explicit wide-identity attribution. |

For historical comparison only, the accepted pre-ARCH4C SCALE0 symbolic
row-wise statement model, expressed with this ledger's archived symbols, was:

```text
6 + 3F + 4R + 2O + CN + CE + CV + CNL + CEL
```

The fixed six represent repository/run setup, completion, commit, and summary
operations. `FN`, `LNP`, `LVP`, `LEP`, and retained `LN`, `LV`, and `LE` have
no independent terms because the row-wise adapters emit their writes inside
file-derived and relationship-derived groups. This formula is source
attribution, not a throughput prediction.

The current staged core data-plane shape is:

```text
7 family COPY operations
+ 4 file/raw validation and merge statements
+ 11 canonical validation and merge statements
= 22 operations
```

The historical pre-ARCH4C shape was 29 operations across ten families. It is
retained only in the archived SCALE7 and ARCH4C comparison evidence.

Production orchestration additionally performs repository/run/stage setup,
stage state transitions, one explicit `ANALYZE`, seven completeness counts,
publication fencing, receipt completion, commit, reconciliation branches, and
later cleanup. A single exact production statement total is branch-dependent
and is not represented by the 22-operation data-plane bound.

### Generic-contract revision requirements

Any structural revision must:

1. preserve the closed seven-family catalog and exact identity fields;
2. preserve typed order-independent completeness evidence or replace it only
   with an equivalently collision-resistant accepted contract;
3. report count, normalized bytes, preparation elapsed, checksum elapsed, COPY
   elapsed, validation elapsed, merge elapsed, temporary bytes, and WAL by
   public-safe family or statement category;
4. avoid requiring all seven complete row families to remain live before the
   first COPY when transaction and replay semantics permit narrower lifetimes;
5. retain deterministic family order and deterministic proposal selection;
6. retain explicit close and failure cleanup for every private spool;
7. retain publication and commit-unknown semantics; and
8. stop if a proposed lifetime reduction would change parity, baseline meaning,
   retained history, or public readback.

## Package and import-direction audit

The repository-owned static AST guard resolves imports at every lexical scope
without importing or executing RepoMap. At ARCH-CLOSE the production graph is
a DAG: the SCC allowlist and production-to-test-support exception allowlist are
both empty. The table below preserves the six ARCH0 components as historical
decision evidence; ARCH1D through ARCH1J removed each component and the
production-owned synthetic-worker fixture boundary.

| Historical component | ARCH0 representative cycle | ARCH0 directional problem | Resolution |
| --- | --- | --- | --- |
| Extractor configuration | `extractors.config.generic` imported implementations that imported generic helpers or observation contracts | Registry and shared contracts were owned in both directions | Resolved by ARCH1I lower contract owners |
| Operations/runtime | `ops.config -> ops.readback -> ops.report_records -> ops.config`, expanded through runtime modules | Configuration records, presentation, and execution depended in both directions | Resolved by ARCH1H lower configuration/report owners |
| CLI/server | `cli.dispatch -> server.mcp -> server.mcp_core -> cli.main -> cli.dispatch` | Server implementation depended on CLI entrypoint code | Resolved by ARCH1G neutral presentation contracts |
| Coordinator | `_refresh_execution`, `_worker_launch`, `protocol`, and `refresh_adapter` | Protocol and launch/execution adapters depended cyclically | Resolved by ARCH1F neutral protocol/process contracts |
| Discovery | `graph.discovery <-> graph.discovery_extractors` | Traversal and extractor registry depended on one another | Resolved by ARCH1E neutral discovery records |
| Storage telemetry | `backend_connection_telemetry <-> backend_telemetry_events` | Event records and connection adapter depended in both directions | Resolved by ARCH1D neutral telemetry contracts |

At ARCH0, function-local imports hid some reverse edges and production launched
one synthetic worker from test support. ARCH1J moved the fixture target, support
path, mode allowlist, and fixture-selecting factory into test support. Current
compatibility facades are guarded as same- or lower-layer re-exports and do not
hide reverse dependencies.

**Package-structure judgment:** **Sound.** The six historical cycles are gone,
compatibility facades sit over acyclic lower-layer owners, and production has
no test-support dependency.

## Public API boundedness audit

The complete public/quasi-public command, argument-owner, JSON/table, exit,
MCP-tool, protocol, service, configuration, baseline/drift, and identity-version
registry is in `docs/specs/as-built-architecture.md` under "Public and
quasi-public contract inventory." This ledger adds the resource and authority
judgment for surfaces whose cost or bound is material.

| Surface | Current bound | Amplification exposure | Judgment |
| --- | --- | --- | --- |
| MCP canonical node/edge lists | Default 50, maximum 200, offset accepted | Bounded SQL rows and JSON array, subject to row width | **Sound.** |
| General MCP list validation | Maximum 500 | Bounded rows, subject to tool-specific schemas | **Sound when every list tool uses the validator.** |
| MCP canonical neighborhood | Depth fixed at 1; node and edge collections each default to 50 and cap at 200 with independent offsets | One request returns only its bounded deterministic windows plus continuation metadata | **Sound.** |
| MCP canonical edge explanation | Evidence collection defaults to 50 and caps at 200 with an offset | One request returns only its bounded deterministic evidence window plus continuation metadata | **Sound.** |
| Direct storage canonical node/edge CLI | Lists default to 50 and cap at 200 with offsets | JSON/table output is bounded to the accepted page | **Sound.** |
| Psql/Psycopg JSON connectors | Expected object/array shape validated | Complete query JSON is materialized in PostgreSQL and client | **Shape parity is sound; resource bound depends on query cardinality.** |
| Private MCP presentation | Configured private markers sanitized | Additional output traversal proportional to payload bytes | **Necessary and sound privacy cost.** |
| Historical row-wise mutation commands | No supported receiptless final mutation remains; complete input publishes through staging and partial acquisition is non-publishing | Historical output-linear row-wise cost is absent from the current graph pipeline | **Resolved.** |
| HTTP liveness, health, readiness, and status | Graph probes cap at 200, diagnostics cap at 100, and serialized responses cap at 8 KiB | Fixed allowlisted fields expose no graph, repository, database, root, credential, or raw diagnostic identifiers | **Sound.** |
| Local database lifecycle | Exact graph/control ownership, streamed private backup artifacts, checksummed complete sets, stable maintenance exclusion, applied-version ledgers, and explicit UTF-8/C provisioning | Server IO remains necessarily linear in dump bytes while client memory is bounded by chunks; rollback and failure cleanup are deterministic | **Sound for the accepted release-cluster contract.** |
| Generated cluster readiness and roles | PostgreSQL health and exact-current one-shot initialization/upgrade gate long-running units; readers, publishers, coordinator control, and lifecycle administration use distinct credentials | Readiness is bounded and long-running processes receive no lifecycle-administrator capability | **Sound.** |

ARCH7A completed the required revision: every public list and embedded
collection defines a default limit, maximum limit, deterministic ordering,
continuation/offset semantics, and bounded errors.

## SCALE0 and SCALE10 public-safe attribution

### SCALE0 synthetic evidence

SCALE0 was accepted on 2026-07-14. Its disposable public-safe probe used 20,010
synthetic input rows and compared four storage shapes. The accepted record
reports:

| Variant | Logical SQL statements | Text-equivalent payload | Elapsed | Client CPU | PostgreSQL peak RSS | WAL delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Row-wise upsert | 60,032 | 8,624,370 bytes | 1.32 s | 0.74 s | 22.5 MiB | 15,612,376 bytes |
| Multi-row INSERT | 125 | 2,054,569 bytes | 0.34 s | 0.16 s | 24.8 MiB | 15,612,376 bytes |
| Prepared/pipelined row-wise | 60,032 | unavailable | 0.37 s | 0.37 s | 22.5 MiB | 15,612,352 bytes |
| COPY plus set-based merge | 7 | 1,249,580 bytes | 0.25 s | 0.04 s | 31.3 MiB | 20,609,232 bytes |

These controls show that fewer row-shaped statements and less client text
reduce synthetic elapsed/client work, while durable bulk loading can increase
WAL. They do not predict a large repository, the historical ten-family path,
the current seven-family publication path, parity, or cancellation cost.

### Required public-safe fixture metric accounting

The required amplification metrics are accounted for below. Formulas use the
ledger symbols defined above. Schema-object counts are derived statically from
the current migrations. `Unavailable` means that no accepted public-safe
fixture records the required numerator and denominator for the same bounded
interval; ARCH0 does not substitute SCALE10 private counters or infer a value
from elapsed bands.

| Required metric | Derived or measured result | Evidence limitation |
| --- | --- | --- |
| Rows emitted per raw observation | For `O > 0`, current staged-family rows per raw observation are `(F + O + CN + CE + CV + CNL + CEL) / O`. ARCH4C measured `49 / 8 = 6.125` for the accepted size-4 fixture. | This is one deterministic seven-family proposal vector, not a universal extractor ratio. Historical SCALE7 ten-family vectors remain archived below. |
| Staging bytes per raw observation | Pure staged-family bytes use `sum(normalized_byte_counts[family]) / O`. ARCH4D reproduced 2,756 normalized bytes for eight observations, or `344.5` normalized bytes per observation, and a 30,434-byte encoded transfer/merge proxy. | The normalized-byte ratio is fixture-specific; the encoded proxy also includes merge text and is not on-disk relation bytes, index bytes, or WAL. |
| Final rows per raw observation | For a successful complete publication and `O > 0`, `(F + O + CN + CE + CV + CNL + CEL) / O`, excluding run, receipt, and authority metadata. ARCH4C measured 98 inserted staging-plus-final rows for 49 staged family rows. | The fixture proves one complete seven-family vector and exact replacement, not a universal retained-row ratio. |
| Indexes maintained | Seven stage-family primary keys plus their accepted family-specific secondary indexes; current final file/raw/canonical indexes are migration-owned and checked by schema/catalog tests. | Schema-object counts are not index-entry or WAL counts. A row touches only its family indexes; conflict/update behavior and metadata/publication indexes require separate counters. |
| Validation scans | Seven family completeness counts plus one explicit `ANALYZE`; conflict/reference validation is descriptor-owned in the 15 current file/raw/canonical blocks. | Physical scans remain planner-dependent; public-safe counters separate operation categories but not every heap/index scan. |
| Merge statements | The current data plane executes four file/raw plus eleven canonical validation/merge blocks, in addition to seven COPY calls for 22 operations. | Production setup, completeness counts, statistics, fencing, receipts, reconciliation, and cleanup are branch-dependent and excluded from the 22-operation core. |
| WAL contribution | ARCH4C measured 64,317 staged data-plane WAL bytes for eight raw observations, or `8,039.625` bytes per observation; ARCH4D reproduced the value. | The ratio covers one generated family mix and excludes orchestration outside its timed data plane. WAL by family, index, statement, or protected workload remains unavailable. |
| Baseline dimensions | Stored baselines define four scalar count dimensions and four keyed count-map dimensions. Preflight baselines define 14 scalar dimensions, one boolean dimension, and five keyed count-map dimensions. | These are contract-field families from `ops/reports.py`; map cardinality depends on observed languages, kinds, roles, categories, and exclude keys. They are not ingestion-work percentages. |
| Drift dimensions | Stored drift compares the same eight stored field families. Preflight drift compares the same 20 preflight field families plus nine safety booleans, including `private_root_redacted`. | Dynamic changed-key cardinality is fixture-dependent. The dimensions measure graph/preflight change, not per-family storage cost. |

SCALE7 later recorded 29 staged data-plane operations for the ten-family
generated workload and small public-safe size sweeps. That evidence validates
the operation shape, not a constant-time server cost: PostgreSQL work, stage
bytes, indexes, WAL, locks, and transaction duration still grow with family
rows and row widths.

ARCH4C re-ran the size-4 generated workload against the published ARCH4B
ten-family implementation and the seven-family writer. Deterministic family
rows fell from 73 to 49, encoded transfer/merge bytes from 40,834 to 30,434,
client data-plane statements from 29 to 22, server statements from 67 to 54,
and inserted rows from 146 to 98. Observed WAL bytes fell from 92,361 to
64,317. The one-run elapsed, CPU, and RSS differences are local observations,
not acceptance thresholds. Historical ten-family formulas and measurements
above remain labeled evidence for the pre-ARCH4C implementation.

ARCH4D repeated the size-4 seven-family measurement and reproduced every
deterministic value: 49 family rows, 30,434 encoded bytes, 2,756 normalized
bytes, 22 client and 54 server statements, 98 inserted rows, 64,317 WAL bytes,
467 WAL records, zero temporary bytes/files, two commits, and zero rollbacks.
This accepts the writer-transition shape without converting local elapsed,
CPU, or RSS samples into performance thresholds.

### SCALE10 bounded non-acceptance

SCALE10 closed on 2026-07-15/16 with a bounded non-acceptance result:

- one exact-scope direct staged attempt ran;
- pre-storage completed in the under-ten-minute band;
- the combined staging/COPY/validation partition remained active when the
  90-minute total limit fired;
- final statement 1, the final transaction, receipt finalization, and commit had
  not begun;
- direct-client and attributable PostgreSQL RSS stayed below their limits;
- free space stayed above its floor;
- final temporary-byte and WAL counters exceeded their limits;
- the private evaluator had already selected the elapsed stop and did not
  reclassify the resource verdict when final counters became available;
- the child quiesced after one direct signal;
- reconciliation found a failed run, no complete receipt, no active or
  commit-unknown stage, and zero retained rows in all ten families; and
- no repeat, parity result, accepted baseline, drift result, SCALE closure, or
  GO24 recommendation followed.

The only supported product-category attribution is therefore:

```text
staging_copy_validation_throughput
```

The record does not identify whether COPY, family checksum replay, stage index
maintenance, the explicit statistics refresh, completeness counts, connection
waiting, WAL pressure, temporary-file pressure, or another sub-boundary
dominated.

### SCALE11 normalized seven-family characterization

SCALE11 adds public-safe structural and elapsed characterization for the
current seven-family pipeline. The measured synthetic bands are 128, 512,
2,048, and 8,192 work items, with three repetitions for each of six data-shape
profiles. The complete matrix retains every repetition and produces three
`superlinear_suspect` and three `measurement_unstable` profile-level elapsed
classifications. These labels are not asymptotic proof.

At the largest bands, family preparation, checksum, and COPY timings account
for only part of total elapsed. A targeted mixed profile attributes most of the
remaining time to aggregate merge and semantic-guard events. Unchanged repeats
preserve seven-family counts and structural digests but move slow cost among
ordered guard and merge occurrences. The current event schema therefore does
not establish one stable statement-level complexity owner.

One 8,192-item targeted publication completed in 485.4 seconds. Its
300-second elapsed limit was observed only in the terminal sample, so the
crossing is not a pre-cancellation cause. This is a measurement-control defect:
the harness cannot enforce the elapsed bound while publication is active.
SCALE11 stops without query-plan or further performance evidence and does not
accept protected-retry thresholds.

### SCALE12 live operation attribution

SCALE12 corrects the terminal-only measurement defect with a supervised direct
child, live 250-millisecond deadline polling, one-second resource sampling,
and a closed registry of source-owned logical operations. The publication's
normal 28-operation sequence is stable across unchanged completed repeats.
Every interval within statistics, validation, semantic guard, merge, and
receipt is attributed to an active operation; lifecycle validation prevents a
completed operation from receiving later active time.

The targeted mixed profile completed three 2,048-item publications between
4.1 and 10.7 seconds and three 8,192-item publications between 45.5 and 54.5
seconds. No operation exceeded 22 seconds, no live threshold crossed, and no
operation owned more than half of elapsed in two unchanged repetitions. These
bounded measurements do not establish an asymptotic class and do not isolate a
reproducible product complexity owner. PostgreSQL plan inspection was not
triggered.

Instrumented and uninstrumented medium repetitions retained equal semantics
with measured median overhead within the 20 percent limit. Self-host and
public full-repository static and publication repeats retained equal counts,
structural digests, receipts, cleanup, final state, and operation sequence.
The evidence supports measurement-control acceptance and a separately
authorized fresh-cluster protected retry, not a production optimization.

### SCALE18 structural-digest lifetime correction

SCALE18 diagnoses the protected prelaunch stop as a representation-lifetime
amplification defect. Prepared families were already independently spooled,
but the previous digest construction replayed them into a second complete
semantic graph, serialized that graph into one complete JSON string, and
encoded the string into one complete UTF-8 byte object before hashing. The
peak therefore included prepared families plus aggregate rows plus JSON text
plus encoded bytes. The digest itself remained linear in semantic byte count,
but its simultaneous ownership multiplied the live representation size.

The corrected path retains the exact digest contract while changing the
ownership bound:

- one family is projected at a time;
- ordering uses a 4 MiB encoded-row payload target per initial run, four
  bounded run levels, and a maximum 32-way merge fan-in;
- a single oversized row remains an unavoidable row-local bound;
- JSON text is fed through 16,384-character encoder chunks;
- only one server cursor is active during terminal readback; and
- iterators, cursors, runs, and spools close on success, error, cancellation,
  or retry.

For `R` semantic rows, `B` normalized semantic bytes, `K` ordering-key bytes,
and `F = 7` fixed families, digest work is `O(B + R log R)` when prepared rows
require ordering. In-memory ordering payload is targeted at 4 MiB plus Python
row/list/string/key overhead and one possibly oversized row-local encoding.
Open merge state is bounded by 32 runs per pass and four leveled carry slots.
Disk growth is `O(B)` and multipass merge I/O is `O(B log_32 runs)`. Terminal
readback remains `O(B)` client processing with one bounded cursor; PostgreSQL
owns the unchanged ordered-query cost.

Seven public-safe family-skew profiles ran at 32, 128, 512, 2,048, 4,096, and
8,192 work items. Total sampled maximum RSS by band was approximately 41, 45,
61, 87, 118, and 191 MiB. Conservative digest increment was approximately 0.4,
1.1, 3.4, 21.3, 45.7, and 137.5 MiB. Combined temporary growth was 0, 0, 1.8,
48.5, 98.0, and 202.8 MiB; the largest case included 64.4 MiB of live external-
sort runs. All seven top-band doubling pairs pass either the direct 25 percent
total-RSS target or its stable fixed-baseline exception. This is consistent
with fixed process overhead plus approximately linear source/family/artifact
growth; it is not a protected-scale asymptotic proof.

The resource-control correction distinguishes a sampled maximum from an exact
operating-system peak. It retains the first causal crossing and all later valid
maxima through process exit, including post-signal samples, without converting
reader disappearance to zero. A continuous 50-millisecond digest sampler and
the 100-millisecond parent monitor contribute their greater maximum to the
acceptance authority. The SCALE17 stop remains causal and unchanged.

### Unavailable percentage attribution

| Requested attribution | Public-safe result |
| --- | --- |
| Configuration and authority resolution percentage | **Unavailable.** |
| Discovery percentage | **Unavailable.** |
| Extraction percentage | **Unavailable.** |
| Observation spool percentage | **Unavailable.** |
| Legacy versus canonical preparation percentage | **Unavailable.** |
| Per-family preparation percentage | **Unavailable.** |
| Checksum percentage | **Unavailable.** |
| Per-family COPY percentage | **Unavailable.** |
| Explicit `ANALYZE` percentage | **Unavailable.** |
| Ten completeness counts percentage | **Unavailable.** |
| PostgreSQL temporary bytes by statement/family | **Unavailable.** |
| WAL bytes by statement/family | **Unavailable.** |
| PostgreSQL CPU by statement/family | **Unavailable.** |
| Client CPU by stage | **Unavailable.** |
| Final validation/merge percentage in SCALE10 | **Not applicable; final statement 1 did not begin.** |

No family percentage, statement percentage, or private counter is inferred in
this ledger.

## PostgreSQL resource interpretation

The links in this section were checked on 2026-07-16. On that date,
`/docs/current/` resolved to PostgreSQL 18; PostgreSQL 19 was a development
version. These references establish PostgreSQL semantics, not the exact version
or configuration of any RepoMap runtime. Public evidence does not provide
values for `work_mem`, `hash_mem_multiplier`, `shared_buffers`, parallel-worker
limits, checkpoint settings, or WAL configuration; those values are
**unavailable** here.

- [COPY](https://www.postgresql.org/docs/current/sql-copy.html) documents that
  `COPY FROM STDIN` transfers data through the client connection, checks
  constraints, updates destination relations, and can leave physical space to
  reclaim after a failed large COPY.
- [INSERT](https://www.postgresql.org/docs/current/sql-insert.html) defines
  `ON CONFLICT` behavior and the requirement that a deterministic statement not
  affect the same existing row more than once.
- [Resource consumption](https://www.postgresql.org/docs/current/runtime-config-resource.html)
  documents that `work_mem` applies per sort/hash operation, that a complex
  query can have several such operations, that hash memory is multiplied by
  `hash_mem_multiplier`, and that parallel workers can multiply total resource
  exposure.
- [Cumulative statistics](https://www.postgresql.org/docs/current/monitoring-stats.html)
  defines database temporary-file/byte counters and cluster WAL byte counters.
  Aggregate counter deltas require ownership and interval controls before they
  can be attributed to RepoMap.
- [ANALYZE](https://www.postgresql.org/docs/current/sql-analyze.html) defines the
  statistics refresh used for `stage_canonical_node_evidence`.
- [Indexes](https://www.postgresql.org/docs/current/indexes.html) describes the
  read-speed/write-maintenance tradeoff relevant to every staging identity and
  final uniqueness index.
- [Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
  is the required basis for validating generated query plans, estimates,
  buffers, and actual rows before accepting a query-shape revision.
- [Parallel query](https://www.postgresql.org/docs/current/parallel-query.html)
  explains planner-selected worker execution. Application statement
  sequentiality does not imply single-process PostgreSQL execution.

## Required structural revision sequence

The following sequence separates behavior-preserving architecture work from
compatibility and performance proof:

1. **Import-direction revision:** define an allowed package-layer matrix and
   remove the six strongly connected components without behavior changes.
2. **CSS matching revision:** completed by ARCH6A; document lookup state is
   built once per matched HTML document, and deterministic traversal growth
   evidence rejects quadratic reconstruction.
3. **Canonical metadata revision:** completed by ARCH6B; first-seen output and
   exact duplicate behavior are preserved while deterministic fan-in evidence
   grows linearly.
4. **Preparation lifetime revision:** narrow complete-observation and
   complete-family coexistence while preserving replay, checksums, parity, and
   failure cleanup.
5. **Family attribution revision:** emit public-safe per-family counts, bytes,
   elapsed categories, checksum categories, COPY categories, and server counter
   categories without source or connection disclosure.
6. **Validation-plan revision:** characterize every guard and merge statement on
   generated skewed families with plans, actual rows, buffers, temporary bytes,
   WAL, cancellation, and rollback evidence.
7. **Public boundedness revision:** add explicit bounds and continuation
   semantics to direct lists, neighborhoods, and explanation evidence.
8. **Mutation-authority revision:** split latest recorded run from latest
   receipt-bearing publication, census every row-wise caller, and migrate
   immediate final mutation to acquisition-only input plus complete staged
   refresh or an announced retirement. Do not add partial publication.
9. **HTTP privacy revision:** add explicit graph-count/byte limits, make
   health/status a path-free configuration projection, and test successful/error
   diagnostics for private identifiers; do not represent it as PostgreSQL
   status.
10. **Identity and lifecycle revision:** reject duplicate effective graph
    databases, define relocation-stable repository identity, and derive exact
    graph/control ownership; then establish version-tracked backup-first upgrade
    and deterministic partial-target recovery before migrating path-keyed rows;
    expand
    backup/restore to every owned database with bounded streaming and explicit
    private modes, pin/test the PostgreSQL client/server/Psycopg matrix,
    declare compatible encoding/collation or explicit byte-stable protocol
    ordering, provision role/grant state declaratively, separate database roles,
    hold maintenance exclusion through backup/verify/drop with a stable
    coordinated recovery point, and gate readiness on PostgreSQL plus schema
    state.
11. **Compatibility-facade revision:** inventory consumers and decommission only
   through separately accepted parity phases; do not combine facade removal
   with preparation or storage changes.
12. **Acceptance evidence revision:** repeat the complete public-safe gates before
   any separately authorized acceptance campaign. Do not infer protected
   completion from synthetic controls.

Each phase must issue one subsystem judgment, preserve the preceding phase's
non-goals, and stop when evidence reveals a new issue class.

## Exit criteria for architectural soundness

The overall judgment can change only when all of the following are true:

- both confirmed quadratic defects have behavior-preserving regression and
  growth evidence;
- no non-trivial internal import cycle remains;
- configuration through publication has explicit cancellation ownership;
- observation and family lifetimes have bounded peak client memory evidence;
- every staging family has independent public-safe row/byte/time attribution;
- COPY, statistics, completeness validation, every final guard/merge category,
  temporary bytes, WAL, and cleanup are independently attributable;
- PostgreSQL plans and index use are demonstrated on generated skewed inputs;
- direct CLI and MCP embedded collections have deterministic public bounds;
- latest recorded run and latest receipt-bearing publication are distinct, and
  no supported receiptless row-wise path mutates final graph state;
- HTTP health/status is path-free, identifier-safe, and correctly documented as
  configuration-only;
- dedicated graph databases, stable repository identity, exact destructive
  ownership, versioned upgrades, complete owned-database backup/recovery,
  bounded streaming/private artifacts, a compatible pinned client/server
  matrix, cross-locale deterministic ordering, declarative role/grant
  restoration, maintenance-fenced stable recovery points, least-privilege roles,
  and storage/schema readiness are executable and proved;
- psql/Psycopg parity, publication receipt, rollback, commit-unknown,
  baseline/drift, privacy, and deterministic output remain intact; and
- a separately authorized acceptance phase completes publication, unchanged
  repeat parity, accepted baselines, drift, bounded smoke, and resource gates.

ARCH8 satisfies the public-safe acceptance criterion with deterministic small,
mixed, self-host, and public full-repository rungs. The integrated measurement
contract retains family rows, normalized and spool bytes, per-stage timing,
WAL, temporary-byte, client-memory, PostgreSQL-memory availability, total
lifetime, receipt, and cleanup attribution. The 32/128/512 synthetic size
series remained monotonic, required no temporary spill, and stayed below 70 MB
peak client memory at its largest rung. Repeated public full-repository
publication completed with equal file and observation counts below 92 MB peak
client memory. Real two-graph/control backup and restore streamed through fixed
packaged clients, and an abrupt full-service restart recovered within the
existing bounded readiness window. These are public-safe architectural bounds,
not protected-scale throughput evidence.

ARCH-CLOSE confirms that every criterion above is satisfied by committed
source, migrations, tests, and public-safe operational evidence. The remaining
privacy-helper duplication is accepted maintainability debt behind proved-safe
boundaries. The current technical judgment is:

**The specified structural revisions and public-safe acceptance gates are
complete, and SCALE may resume only under a separately approved plan.**
