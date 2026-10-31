# CLOE retrieval and evaluation specification v1

## Scope and implementation status

Implemented in `REPOMAP-CLOE-RETRIEVAL1` under accepted [ADR0127](../adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md)
and recorded in [cloe-retrieval1-exit.md](../../tools/ci/cloe-retrieval1-exit.md)
(local scoped unit, containerized integration, and static gates verified; overall
phase status `NOT ACCEPTED` pending fresh hosted CI qualification). W2 delivers
an internal reference and evaluation instrument, not a production text index or
evidence of agent productivity. The accepted roadmap remains
[CLOE transition](cloe-roadmap-transition-v1.md).

## Current owners and facts

- server/sqlite_read_binding.py supplies SqliteInvestigationReadStore,
  SqliteCanonicalReadStore and SqliteSourceReadStore. SQLite navigation_search
  and node_locations are implemented. PostgreSQL's corresponding investigation
  adapter currently returns backend_unsupported for those two methods.
- Existing node/file/observation search and graph navigation read accepted stored
  metadata. Metadata can include short extracted text, but is not a full-text
  representation of source files. Email extraction redacts bodies and selected
  metadata; feed extraction has its own maintained redaction policy.
- artifacts/manifest.py has PortableSnapshotManifest.entries and bindings;
  snapshot_vector is a property. The manifest identifier uses snapmanifest1:.
- artifacts/bundle.py has PublicationBundle.bundle_id, candidate_id, graph_id,
  snapshot_manifest_id, snapshot_vector, generation fields and families. It has
  no provenance field and is candidate material, never acceptance authority.
- storage/publication.py has RunPublicationReceipt.attempt, generations and
  optional portable. The portable binding has publication_bundle_id, candidate_id,
  snapshot_manifest_id, snapshot_vector and extraction_receipt_id (receipt1:).
  The attempt has job_id and attempt; it is not a graph run identifier.
- ManifestArtifact has binding_id, source_relative_path, reference and executable.
  ArtifactReference carries content_digest, size_bytes, media_type, record_format
  and artifact privacy. Do not invent ArtifactKind, art1: identifiers or get_bytes.
  ArtifactStore has read/get/open_stream/verify with max_bytes bounds.
- Manifest and bundle do not have validate methods. Use their actual canonical
  parser/constructor and existing artifact/capture validators. Preserve original
  execution references when checking semantic canonical serialization.
- SQLite schema.accepted_identity reads the current accepted marker; PostgreSQL
  publication_readback reads maintained publication records. A supplied receipt
  is insufficient. Portable attempt retention is finite; missing retained bytes
  mean unavailable reference, not permission to reopen a current checkout.
- tools/source_navigation_consumer.py and tools/portable_handoff.py are separate
  caller-side helpers. Preserve their actual arguments, constants and outcomes;
  do not invent new behavior or a database check in either helper.

These paths are under src/main/python/common_lore_index unless prefixed tools/.
Inspect the actual signatures before implementation; the new types below are W2
types, not claims that additional fields already exist in those owners.

## Query contracts

Internal contract version: cloe-retrieval-query-v1.

| Mode | Meaning |
|---|---|
| exact_identity | Deterministic exact known-identity lookup with honest disambiguation. |
| current_literal_enumeration | Preserve documented literal metadata matching and ordering. |
| literal_captured_text | Punctuation-sensitive actual text matching in authorized captured material. |
| ranked_discovery | Candidate ranking; declare whether its surface is metadata, text or another representation. |
| graph_investigation | Accepted typed graph relationships; relevance alone is not a relationship. |
| semantic_discovery | Explicit optional capability, unavailable when not admitted or supported. |

Direct locator handoff is an auxiliary workflow. It may make zero graph calls
and delegates to the real caller-side helper; it does not alter the six modes.

A new internal envelope records version, requested/effective mode, match surface,
publication/source scope, actual ordering-policy version, capability state,
explicit fallback, omissions/completeness and provenance. Capability states
distinguish available, partial, refused, stale, unavailable, failed and not_run.
Backend unsupported is a reason for unavailable, not a successful empty result.
Existing CLI/MCP schemas and behavior do not acquire this envelope in W2.

Never label metadata hits as body hits. Fallback is caller-selected and disclosed.
Ranked discovery does not imply body indexing: SQLite's current metadata ranking
is a real baseline, while unsupported PostgreSQL navigation stays unavailable.
Do not pool those backend populations. Ordinary graph readback remains useful
when projection, vectors or other enhancements are absent.

Normalize evaluation results to binding identity + source-relative path + optional
line span; retain canonical/evidence keys as additional provenance. Respect
source scope before matching. Mixed-scope requests disclose policy exclusions
without testing forbidden contents. Zero hits establish absence only for an
available, complete selected scope; partial or unavailable results cannot do so.

## Captured-input projection reference

Version: cloe-captured-text-reference-v1. New internal records may be decomposed
for readability; public serialization is explicitly versioned and closed.

ProjectionInputs contains the real bundle, publication receipt, manifest and
ArtifactStore plus a mandatory AcceptedPublicationReference and resolved policy.
The new AcceptedPublicationReference records graph/repository identity, backend,
actual run identity, publication_bundle_id, publication job/attempt and any
backend-specific generation. It is a trusted caller input, not self-authenticating
authority and never an untrusted CLI/MCP object. The benchmark constructs it from
actual accepted-store readback, verifies it against the captured inputs, and
checks for advancement before accepting a query result. W3 must supply a real
request-pinned store view before any production endpoint can use this reference.

Require a non-null receipt.portable. Match graph identities, job/attempt, bundle
identifier, candidate identifier, snapshot manifest/vector and available source/
config/extractor/canonicalizer generations across their actual typed owners.
Verify canonical identities using maintained validators and canonical parsers;
then verify every consumed artifact with the actual bounded store API. A matching
digest proves byte integrity under its framing, not acceptance, privacy or rights.
Missing, foreign, stale or unavailable inputs cannot produce an available result.
Do not read source roots, infer a host path from a locator or use live-file fallback.

Each output file/chunk preserves:

- Accepted-store reference and bundle/receipt/manifest identities.
- Source definition, binding/revision, snapshot and source-relative locator,
  derived from the actual manifest; opaque IDs use current constructors.
- Optional canonical/evidence links from the same bundle. Join evidence-role
  information through canonical_node_evidence; nullable spans are explicit.
  No matching symbol is required for valid searchable prose.
- Original content digest, representation digest/version, source format,
  chunk policy, raw and normalized extents and truncation/exclusion state.
- Artifact privacy classification and original/resolved graph/binding policy
  labels as separate domains. Output raw text keeps its artifact classification.

W2 reference authorization is deliberately narrow: explicit public-fixture code
and prose with resolved public-dev graph/binding policy, full-authorized retention
and a caller's explicit selected body scope. Unresolved inherit, private scopes,
metadata-only/ephemeral retention, email bodies, feed bodies and unsupported
formats are excluded before opening their blob for projection. This is not a
change to production capture/retention policy. Metadata remains usable. The
reference does not reinterpret public-dev as permission to publish raw text and
does not replace existing feed redaction with a weaker regex. W3 owns further
format/private-scope admission and an explicitly named indexed-text capability.

Per-binding/file policy exclusions do not depend on the query or whether hidden
content matches. Return bounded codes, not hidden text or content-dependent
secret findings. The benchmark scans results, envelopes, reports and logs for
private-body canaries. Source fixture inputs and permitted raw capture stores
are not mistaken for output disclosure.

Use strict UTF-8, reject NUL anywhere, and normalize CRLF/CR to LF under a named
representation. Defaults:80 lines and8192 UTF-8 bytes per chunk,262144 projected
UTF-8 bytes per file. An input-read bound of1MiB and aggregate8MiB protect this
fixture reference before opening artifacts. Oversized inputs are recorded as
excluded; projected prefixes are explicitly partial. Split long lines only at
valid UTF-8 boundaries. Preserve byte/line extents so normalization and partial
coverage cannot be confused with original-byte completeness.

Chunks cover a contiguous selected prefix without gaps/overlap; empty files have
an explicit complete empty record. A literal spanning adjacent chunks of the
same file must remain findable; never join different files. Optional evidence
links do not manufacture a canonical relationship. Define deterministic framed
SHA-256 identities over the policy, source/binding/publication and exact normalized
bytes. Missing/excluded/truncated/removed files and bindings remain accounted for.

This is an in-memory reference. There is no database index generation, production
ready flag, historical graph query or persistence promise. Old material is usable
only with a genuinely matching retained graph view; otherwise it is recovery-only
or unavailable. The previous artifact store may already have expired.

## Corpus and task instrument

Reuse maintained portable capture, extraction, publication and fixture helpers;
inspect ops/portable_refresh.py, ops/local_refresh.py and existing portable/semantic
test support. Do not hand-assemble a competing publisher or manually populate
canonical tables as the product baseline.

Create controlled source bindings core, companion, feeds and mailbox with two
generations, duplicate relative paths and declared roles/policies. Include Python,
shell/Nix cross-source material, a design document, a selected saved-message
document, standalone non-code notes, local RSS/Atom and email metadata fixtures.
No external acquisition or account connector. Target source code is never run.
Generate oversized/repetitive files deterministically rather than padding Git
history. Record exact fixture bytes, representation, policy and selection digests.

Freeze36 tasks,24 calibration and12 held-out, before the first baseline. All ten
families occur in both splits:

| Family | Total | Calibration | Held-out |
|---|---:|---:|---:|
| Exact symbol and partially remembered name |4|3|1|
| Full punctuation-sensitive phrase and distractors |4|3|1|
| Behavior described without its exact symbol |3|2|1|
| Shell/Python or Nix/script cross-source investigation |4|3|1|
| Relevant tests for a behavior |3|2|1|
| Code plus design or selected-message context |3|2|1|
| Independent document/email/feed retrieval |4|3|1|
| Duplicate paths, quotations, long/Unicode material |4|2|2|
| Absent, ambiguous, changed, deleted or stale material |5|3|2|
| Direct-location workflow with zero graph calls |2|1|1|

Each task stores ID, family/split, question and permitted query plan, graph/
generation/scope, intended match surface, comparator exposure, ordered gold
locators and integer relevance grades0..3, expected policy/capability constraints
and grading rule. Labels are authored and validated against fixtures before
adapters run; never derive gold from the implementation's returned hits.
Canonical keys are optional gold metadata, not a native-tool output requirement.
Document partial/ambiguous/no-answer rules. Schema validation of held-out tasks is
allowed; executing their real retrieval queries or tuning against them is not W2.

## Adapters and comparability

1. native_tools_baseline uses an actual already available search executable,
   preferably git grep --no-index in the existing sealed SDK, or actual rg when
   present. Record executable/version and arguments. Auxiliary ordinary document
   parsing/direct reads are allowed over a declared extracted-text view. A Python
   scanner or AST routine alone is not labeled the native comparison.
2. current_graph_baseline calls real maintained SQLite/PostgreSQL read stores
   over actual accepted fixture publications. Reuse caller-side source helpers
   where the task allows them. Unsupported body/navigation modes remain named
   gaps, not fake successes or silently substituted implementations.
3. captured_projection_reference uses the bounded validated artifact reference
   above. It is fixture/contract evidence, not measured production search utility,
   learned ranking or pgvector usefulness.

Every arm declares its input view, authorization, publication, source selection,
representation, backend and output budget. Metadata/body/graph-only tasks have
separate comparability strata. Do not pool scores across unsupported backends or
different exposure and call them an advantage. Native tools must not be deprived
of ordinary selected reads, search depth or safe query techniques to favor CLOE.
Privacy controls precede body matching; an approved extracted metadata view for
non-code is distinct from access to the raw body.

Use safe argv, fixed-string option/terminator, explicit selected paths, one search
thread, no shell or target-code/textconv execution, bounded stdout/deadline, exact
owned-child cleanup and no hidden retry. Prove native output framing with real
component integration tests. No-match and command failure are different states.
Do not force native search to stop at the projection's chunk/per-file size cap.
Its internal file opens/input I/O are unobserved unless actually instrumented;
requested-file counts or file sizes are not measured I/O. Observe invocation,
wall duration and output bytes directly. Additional Python reference scans, if
useful, carry their own name.

## Grading and accounting

Separate execution (completed/failed/unavailable/refused/not_run) from grading
(correct/partial/incorrect/ungraded/not_applicable). Safety-refusal correctness is
separate from retrieval correctness and from completed agent-task correctness.
Preserve one record for every declared adapter/backend/task slot, including
failures and missing capability. Fixed split denominators cannot silently shrink.
Report ungraded and unavailable cases independently; never count them as correct.

Support Recall@k, MRR and nDCG at explicit cutoffs using frozen gold grades and
unique target identities; repeated quotations cannot create duplicate gain.
Define absent-answer handling separately from positive-relevance metrics.
Report supported/graded denominators alongside whole-split populations, not
only a favorable available subset. No scalar winner is required.

Record setup separately from per-query measurements. A fresh connection is not
a cold OS cache. Preserve raw timing samples/sample counts and medians; do not
claim meaningful per-task p95 from three repetitions. Byte counters name the
observed layer; output payload bytes are not source I/O or model tokens.

Model/token/agent completion cost is not observed by this deterministic harness.
Leave such fields unavailable, not zero. A generic accounting helper may accept
real externally supplied grades/telemetry: include failed-attempt spend, refuse
an apparently complete metric with unknown spend, and report null/zero-success
explicitly when no task is correct. Synthetic arithmetic tests are not telemetry.

Baseline observations can contain poor retrieval and failed attempts; record
them rather than imposing a zero-failure winner gate. Instrument failures,
identity drift, missing task records and privacy leaks block an acceptable run.
No predetermined expected scores, universal savings or fixed percentage target.

After calibration, freeze the actual baseline artifact and a parent-reviewed
numeric criterion declaration for the named future workload. Derive its values
from observed baseline deficits and intended behavior before later tuning and
any held-out comparison. Criteria carry baseline/corpus/task/policy digests and
separate invariant, quality and cost requirements. If evidence cannot justify a
numeric criterion, record that unresolved limitation instead of inventing one.

## Implementation owners and proof

Three internal units S1 contracts/projection, S2 corpus/tasks and S3 adapters/
grading/baseline share one canonical phase and one exit. No new subphase IDs.

- Product: `src/main/python/common_lore_index/retrieval/` (`__init__.py`,
  `query_contracts.py`, `publication_binding.py`, `projection_policy.py`,
  `projection_text.py`, `projection_chunks.py`, `projection_evidence.py`,
  `projection_build.py`, `projection_query.py`) for reusable contracts and
  projection only; each module is `<= 400` physical lines. Evaluation schema
  and grading are not shipped in the distribution.
- Test support: `repomap_test_support/retrieval_evaluation_canaries.py`,
  `retrieval_evaluation_fixture.py`, and `retrieval_evaluation_publication.py`.
- Developer tools: `tools/retrieval_evaluation_schema.py`,
  `retrieval_evaluation_accounting.py`, `retrieval_evaluation_grading.py`,
  `retrieval_evaluation_views.py`, `retrieval_evaluation_native.py`,
  `retrieval_evaluation_graph.py`, `retrieval_evaluation_reference.py`,
  `retrieval_evaluation_criteria.py`, `retrieval_evaluation_harness.py`, and
  `retrieval_evaluation.py`, `retrieval_evaluation_admission.py`,
  `retrieval_evaluation_attempts.py`, `retrieval_evaluation_execution.py` and
  `retrieval_evaluation_comparability.py`.
- Public fixture assets: `src/test/fixtures/retrieval_evaluation/mixed-v1/`,
  including `tasks/catalog-v1.json`, `freeze-v1.json`, and the declared
  24-task calibration baseline artifacts under `baseline/`
  (`attempt-declaration-7.json`, `calibration-attempt-7.json`,
  `retained-attempt-7-evidence.json`, `criteria-proposal-v1.json` and
  `attempt-history-v1.json`; held-out split unexecuted). Superseded draft and
  source-bound observations remain retained separately and never qualify a
  successor tree.
- Unit owners (14 new files + 2 existing boundary/projection owners):
  `src/test/unit/python/repomap_kg/retrieval/query_contracts.unit.test.py`,
  `projection_binding.unit.test.py`, `projection_policy.unit.test.py`,
  `projection_text.unit.test.py`, `projection_chunks.unit.test.py`,
  `projection_query.unit.test.py`, `corpus.unit.test.py`, and
  `src/test/unit/python/tools/retrieval_evaluation_schema.unit.test.py`,
  `retrieval_evaluation_catalog.unit.test.py`,
  `retrieval_evaluation_grading.unit.test.py`,
  `retrieval_evaluation_native.unit.test.py`,
  `retrieval_evaluation_harness.unit.test.py`,
  `retrieval_evaluation_criteria.unit.test.py` (plus
  `src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py`,
  `src/test/unit/python/repomap_kg/cli/sqlite_mcp_transport.unit.test.py`,
  and `src/test/unit/python/tools/ci/retained_python_projection.unit.test.py`).
- Real integration owners (5 files):
  `src/test/int/python/repomap_kg/retrieval/projection_publication.int.test.py`,
  `corpus_publication.int.test.py`, `native_search_process.int.test.py`,
  `evaluation_baselines.int.test.py`, and
  `src/test/int/python/repomap_kg/storage/sqlite_mcp_transport.int.test.py`.
- Current clean ownership/inventory/cohort admission under existing policy; no
  old authority or numerical allowance changes. Append an authority only when
  its real executable contract requires it. Never reset or absorb debt into a baseline.
- Update this spec, ADR status, current roadmap/as-built references and the
  public phase exit with truthful implementation/baseline and pending-CI status.

Canonical commands select exact paths after --:

    python3 tools/run_tests.py --suite unit --no-coverage -- <exact .unit.test.py owners>
    python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- <exact .int.test.py owners>

The phase assignment replaces those notation examples with actual selectors.
Use the existing container sandbox and cached images; no image build, external
pull, dependency/runner policy or lock change. Require real native search,
SQLite/PostgreSQL publication/readback, no-coverage scoped proof, clean static
enforcement, privacy/canary checks and independent source review. Complete local
suites and Python project coverage remain unselected; hosted CI owns them.

Adversarial proof covers mismatched/stale publication, missing/foreign/corrupt
blob, no-portable receipt, unknown policy/version, scope collision, privacy
refusal before blob reads, canary-free outputs, UTF-8/chunk/size/completeness,
duplicate/missing task records, ungraded/failed accounting, deterministic grades,
zero-success/unknown token costs, actual native no-match/failure/timeout and
cleanup. Do not reimplement a fake publisher or call a fake executor real
integration. Existing CLI/MCP and Local optional-driver isolation remain intact.

W2 stops at its reviewed implemented baseline milestone. W3 persistence,
generation lifecycle, native FTS and query exposure, W4 context policy, W5 vectors,
Rust, live migration/deployment and package publication do not start inside an
implementation dispatcher. The parent owns subsequent roadmap selection and
the separately frozen single staging campaign.


### Clean ownership admission amendment

ADR0127 permits exactly one guarded transition for the new retrieval package.
Update only its ownership digest and new clean retained/T1-future selection rows.
Preserve every predecessor row and all Ruff, mypy, migration, file-length, tool
and schema sections exactly. No new file-length ceiling is admitted. Append one
scope-transition record bound to ADR0127 and tools/ci/cloe-retrieval1-exit.md.
Retain generator comparison evidence and require complete static enforcement
after applying the checked candidate; generation alone is not acceptance.

## Durable experiment admission and developer operation

Declare inside the actual execution runtime. Run the developer tool with the
existing product, tools and test-support module paths configured. The public
installed CLI/MCP surface is unchanged. The PostgreSQL target must be an owned
disposable fixture database; this tool does not select a developer's live home.

    python3 tools/retrieval_evaluation.py declare-attempt --attempt-id calibration-example-1 --output experiment/declaration.json
    python3 tools/retrieval_evaluation.py run-calibration --declaration experiment/declaration.json --attempt-root experiment/attempts --output experiment/report.json

The persistent experiment root atomically reserves the identifier independently
of the output filename. An admitted or partially failed start cannot be reused.
Admission validates all calibration IDs, arm order, source bytes and actual Git,
Python, platform, predecessor and PostgreSQL-port identity before any query.
It durably saves the declaration, input/source archive and manifest first.
There is no cross-experiment global ID registry or resume of a partial attempt.

Every repetition has a flushed start and observation record. Failures, known
spend and partial traces remain; unknown counters stay null. Divergence fails the
task and attempt while retaining all repetitions. Terminal hashes bind the
declaration, journal, report, source manifest and archive. These files have a
single owner; they are not a concurrent or reconstructible transaction service.
Disk failure may leave only a partial reserved directory, which still blocks reuse.

Ordinary integration runs use unique functional IDs and temporary roots. They
verify serialization, lifecycle and refusal invariants without fixed quality
scores or promotion into retained evidence. Criteria reject functional or failed
reports by default. A test-only functional derivation remains explicitly labeled.

Projection-build artifact reads are setup observations. In-memory reference
queries read zero artifact bytes. Per-query summaries take each layer's maximum
over repetitions, with null if any sample is unknown; raw repetition spend is
retained. Native stdout, read-store responses and serialized projection envelopes
are distinct layers. The proposed envelope ceiling uses only projection-envelope
observations. Externally supplied task costs reject mixed identified/anonymous
denominators and label all-anonymous success counts as successful attempts.

The closed wire parser preserves input types, rejects coerced consent/ranks and
identities, and permits only finite scores. High-offset literal queries retain
only the requested page, count all matches and order files before page selection.

### Publisher and comparability correction

Every projection requires all three retained references and an owned spool path.
Manifest bytes must match their supplied object; streaming validation must return
the matching bundle/receipt/manifest identities. Missing inputs and invalid
digest-valid publication streams refuse. There is no trusted-caller validation
bypass. Real unit fixtures now pass the streaming validator, and container tests
exercise a tampered retained bundle and actual source/evidence links.

Canonical node-evidence uses `canonical_key`; canonical evidence uses `raw_kind`
and the maintained metadata `binding_id`/`source_relative_path` provenance keys.
The projection no longer depends on invented fixture-only row names.

Reports expose task populations grouped by comparator exposure inside each arm,
and proposed body floors remain per arm/exposure. Seed-heavy graph tasks retain
their observed scores but justify no general traversal-quality floor. Traversal
is bounded and uses canonical edges, with no edge-type filter. W3 must establish
an appropriate workload before choosing that quality gate. Projection setup
counts measured body-input bytes only; total validator/store I/O is unobserved.
Developer freeze and criteria outputs are exclusive, preserving earlier files.

## Requested mode and metadata surface correction

The captured-reference evaluation adapter preserves each task's requested mode.
When that mode differs from the executed literal-text scan, it records an explicit
caller-selected fallback with both modes and the reason. Ranked navigation-search
hits declare a stored-metadata surface. Unit regressions and the real calibration
integration journal enforce those disclosures. Attempts5/6 remain retained at their
actual source; attempt7 binds the corrected execution bytes without repinning them.
The underlying query accepts an explicit fallback to literal_captured_text, keeps
its original requested mode, and rejects unsupported fallback targets before
execution. Backend tests and unit regressions cover that same direct contract.

The benchmark supplies current accepted-publication readback on every query.
The internal direct projection API's optional omitted readback establishes no
advancement check; callers must supply it for that guarantee. Correspondence
verifies top-level references and stored manifest bytes. Individual projected
body blobs are verified by bounded store reads; missing blobs are explicit
partial/excluded outcomes, not a claim that every manifest entry was preverified.
