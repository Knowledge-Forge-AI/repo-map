# Proposed public-text semantic calibration contract

Status: operator-selected public-text input class with the explicit
document-only generation-2 amendment dated 2026-11-11. The original failed
preflight remains history; declaration 2 retains all 24 tasks and the same
unspent two-worker/one-study/no-retry allocation. Foundation source is accepted;
comparison, report and driver source now have scoped executable proof and
independent review. Final composed source/private-host acceptance and native
qualification remain pending. See
[the implementation design](cloe-public-text-calibration-implementation-v1.md).

## 1. Question and result

Can the exact approved model produce inspectable learned comparisons over
already captured public text, where `canonical-node-v1` currently supplies only
key/kind/name? The result is a bounded calibration dossier and a later decision
proposal. It is not held-out usefulness, production enablement or an engine
replacement decision.

Preserve ADR0136's exact model/runtime class, the existing fixture and query
bytes, the two publication generations, current projection policy and the
500-record import ceiling. Do not reinterpret historical v1 results as v2.

## 2. Three epics and owned seams

| Epic | New responsibility | Existing seams to reuse |
|---|---|---|
| Representation | Evaluator-owned public-text descriptor, deterministic encoder, admission and independent recomputation | `tools/retrieval_semantic_representation.py`, `retrieval_semantic_provenance.py`, `retrieval_semantic_record_validation.py`, accepted capture/artifact readers and body-projection policy |
| Comparison | Typed v2 experimental profile, isolated request/receipt adapter and publication-fenced disposable exact/ANN reads | Existing fixed generator controller/kernel, `retrieval_semantic_bridge_admission.py`, `retrieval_evaluation_admission_w5.py`, optional pgvector support and frozen evaluator arm contracts |
| Evidence | Strict new report linking original bytes, arm correspondence, applicability, work/cost and decisions | Existing paired V1/V2 and component-dossier validators, journal/cell codecs and first-cause/cleanup records |

New modules belong under `tools/` and corresponding existing unit/integration
roots, with test-owned support only where required. Product modules import
neither tools nor test support. Enroll new owners under the existing quality
roots with no new debt, exemptions, dependency, runner class or ceiling change.
The detailed file list is frozen after operator selection and technical review;
these responsibility boundaries are not permission for a broad refactor.

## 3. Representation v2

Identity remains the accepted `(canonical_key, source_binding_id)` pair.
`canonical-node-public-text-v2` is distinct from `canonical-node-v1` in every
profile, request, input digest, response, import, journal and report.

The typed descriptor binds:

- repository and accepted publication/receipt identity;
- binding, source revision and snapshot identity;
- canonical key, observed evidence key, accepted source-relative path and span;
- captured artifact identity/content digest, selected excerpt byte interval and
  excerpt digest;
- representation/policy version, complete encoded-input digest, byte count and
  truncation/partial-coverage facts.

No absolute path, home, arbitrary filename, executable/module name, gold or
caller assertion can select source bytes. The trusted phase controller chooses
the maintained encoder and runtime factory. Serialized records select data
only, never code or commands.

### 3.1 Admission precedes reads

Revalidate the accepted publication and effective body policy before reading
any candidate body. Reuse v1's observed-evidence and mixed-provenance rules.
For document construction, apply the body-mode admission rules per binding,
including retention and the email/feed body bans, even if a query would use
metadata. Explicitly exclude metadata-only, denied or forbidden pairs before
their body reads or inference; record their reasons. This does not refuse all
otherwise eligible documents. Existing global binding denials still refuse the
entire query before any arm, exactly as today. Supplemental body-mode denial
refuses only the public-text arm and any fusion depending on it; v1 and incumbent
arms retain their existing mode-derived decision. Keep that query
visible in the report; document exclusion does not authorize task removal.

The public-text arm re-evaluates every query's selected bindings with body-mode
policy, even for a metadata-mode task. Email/feed, non-retained, withheld or
other body-denied bindings therefore refuse that arm's whole query. Keep v1's
own admission unchanged and report per-arm admission differences explicitly;
never score a refused/inapplicable public-text arm as an empty-result miss.

Use an evaluator-owned wrapper after the unchanged `admit_w5_task` decision,
requiring every selected binding to exist in the verified policy before calling
the maintained `_policy_denial(policy, binding_id, body=True)` helper. Missing
policy/binding or unverifiable correspondence refuses; the helper's `None`
for a missing binding is not authority. Do not relabel task mode, stratum or
match surface. Differential tests must preserve v1's serialized decisions and
global denial behavior byte-for-byte while proving supplemental per-arm refusal.

For each admitted pair, require observed evidence and a captured artifact
whose binding/snapshot/path/span correspond to that exact publication. A stale,
foreign, inferred-only, malformed, withheld or unverifiable source excludes
the pair with a closed reason. Do not follow a live root, alias, symlink or
inference-produced location to fill the gap.

The accepted artifact reader must verify content identity and closure; it must
not pretend a prefix read verifies the entire object. Record actual verification
and excerpt-read work separately where observed. Unknown device or database
work remains unknown.

Technical design must name the existing captured-artifact reader and prove its
full-content verification and binding/snapshot/path closure. If that maintained
reader cannot provide this contract, stop before implementation; this proposal
does not imply a new broad reader, live-filesystem fallback or content backend.

### 3.2 Deterministic excerpt

Among fully admitted observed evidence, select the first tuple of
`(path_utf8_bytes, evidence_key_utf8_bytes, start_line, end_line)`, with the last
two fields compared as integers. Stored spans are positive, one-based line
numbers with an inclusive end, not byte offsets. Missing, reversed or out-of-file
spans exclude the pair. Any node kind without such observed source evidence,
including source/binding-only records, is ineligible; do not invent a span.
Multiple valid spans do not establish a unique definition.

The span owners are `public.canonical_evidence.start_line` and `end_line` on
the exact accepted observed-evidence row; their existing expansion is visible
in `storage/semantic_candidate_sql.py`. The v1 verified-representation object
does not carry those spans and cannot invent them. Technical design must map
the accepted reader to these fields; missing or unbound spans stop at gate 2.

`path_utf8_bytes` comes from the accepted evidence metadata's
`source_relative_path`, with the existing binding-aware correspondence checks.
Withheld or conflicting `evidence.path` is not an alternative input selector;
exclude unverifiable correspondence. Lexicographic selection is a fixed,
non-semantic rule and makes no claim about which definition is most relevant.

Derive byte offsets from the exact captured artifact using LF boundaries.
CRLF remains two original bytes, a line's terminating LF belongs to that line,
and a final line without LF retains all its bytes. A terminal LF does not create
an extra observed line. A file whose line numbering depends on convention
(a lone CR, or another character Python's `str.splitlines` treats as a break)
excludes the pair; see technical design section 6.3. The excerpt begins at the
start line's first byte and
ends at the inclusive end line's byte boundary or 4,096 UTF-8 bytes, whichever
comes first. Never include bytes outside that interval. Drop only an incomplete
UTF-8 code point caused by the byte cap; malformed selected text excludes the
pair. Record exact original offsets, line-ending facts and whether the span was
cut. Freeze LF/CRLF/final-newline/multibyte test vectors before implementation.
Do not tune the window or select another span after observing query/gold results.

Separate the model-text bytes from the provenance envelope. Only version-tagged
metadata and admitted excerpt text go to the tokenizer; source digests remain
in the envelope and its independently verified identity, not in the model text.
Freeze exact field order, framing, UTF-8 encoding and independent digest test
vectors in the technical design. Never reuse a v1 digest for different bytes.

Keep the model's existing instruction, CLS pooling, normalization, 512-token
limit and disclosed truncation behavior. Record excerpt bytes, model-text
bytes and post-truncation token count separately; 4,096 bytes is not a claim
that the entire excerpt fits the tokenizer budget. Do not change the tokenizer or make a
new model/runtime compatibility claim. The representation/controller/source
profile must receive a fresh identity wherever the old identity binds v1.
Unchanged binary/model bytes do not make the old whole-profile or admission
digest valid for different inputs. Missing body input never falls back to v1 under the
v2 label; v1 remains a separate comparison arm.

### 3.3 Before and after inference

Independently reconstruct descriptors and input digests from accepted owners
before accepting a generator result. Revalidate publication and effective
policy after inference and before import/query. A publication or source change
invalidates the dependent result; preserve the failed attempt rather than
repairing its identity. Bind every generated vector to the admitted input,
model/runtime/source closure and terminal component receipt.

## 4. Temporary SQL boundary

The production `EmbeddingProfile.validate()` currently supports only v1. Do
not broaden its allowlist or mislabel v2 as v1 to get through that guard.

The v2 profile/query adapter is evaluator-owned and separately typed. Its
temporary table and any HNSW index live only in the invocation-owned disposable
database/session. Reuse admitted vector 0.8.7 and the maintained SQL literal and
identifier escaping conventions; never insert caller-selected SQL fragments.
Do not add an extension version, production table/migration, role grant or
public reader. Preserve canonical publication, repository, binding, snapshot,
profile and representation-digest fences on insert and read.

Limit each rebuild to the existing 500 node/binding records, deterministic
ordering and explicit partial/truncation reporting. Derive eligible rows from
the accepted publication; do not multiply the corpus or synthesize useful
labels. Temporary-object ownership and exact cleanup must be proved before a
success result. Do not remove a foreign object to satisfy cleanup.

Use actual exact cosine order as the ANN correctness reference. Preserve
current distance, tie-break, result/evidence bounds and independent oracle
rules. HNSW requires actual expected-index EXPLAIN provenance. An unselected
index remains `unavailable/index_not_selected`; a sequential scan is not ANN.
No forced planner setting, index tuning sweep or performance adoption is
selected by this proposal.

Technical design must list helpers imported unchanged versus bounded query
logic adapted for the temporary profile. Include a differential integration
control: equivalent v1 inputs through the study adapter and production v1
reader must agree on exact order, ties, evidence expansion and refusal fences.
This compatibility control cannot enable a public-text production profile.

Technical design must identify the existing disposable-profile principal that
owns temporary objects and show its already granted TEMP/CREATE rights. No
production principal or new privilege is implied. Missing rights stop at gate 3
rather than causing an opportunistic role grant or harness policy change.
The technical design (section 8) names `repomap_w5_hnsw_owner` and its
already granted `CREATE` on `repomap_enrichment`; it uses invocation-owned
regular study tables in the disposable database, not PostgreSQL `TEMP`
objects, because each support call is a separate `psql` session.

If these requirements cannot be implemented without broadening production
contracts or schema, stop at the technical design gate. This proposal does not
make a production v2 profile acceptable merely because a disposable query works.

## 5. Frozen calibration population

Use only the unchanged approved `mixed-v1` calibration tasks and source
generations. Freeze source/input/fixture/catalog identities, representation
rule, eligible selection, query policy, complete arm list, bounds, repetitions,
grading and output contracts before any query.

The new profile may change applicability where public body input is now
available. That applicability must be derived from the frozen task mode,
match-surface and admitted representation before execution, never from golds
or successful answers. Keep every requested task visible, including denials,
unsupported strata and empty generations. Report old v1 and new v2 counts
separately; historical generation-2 zero inference remains unchanged history.

Compute fresh v1 and public-text document/query vectors under the same current
source closure. Each generation worker handles both independently identified
arms in one request; shared model initialization is counted once, and all
input/record/result caps apply to the combined request. Never import historical
Optional15 vectors or scores. If the controller cannot support this within the
two-worker ceiling, stop at technical design; there is no implied third/fourth
invocation, hidden partition or enlarged request.

Compute query embeddings separately for each applicable representation arm,
even if query text happens to match. Count both in the combined request and
runtime estimate. No cross-arm query-vector reuse is assumed; declared reuse
across the existing comparison repetitions remains separate.

Retain the existing three comparison repetitions. Reusing one admitted query
embedding across repetitions is declared reuse, not three inference events.
Re-run matched native/graph/lexical controls on the same current material and
publication. Do not splice historical scores into a new comparison.

File-level relevance keeps the declared per-file maximum-gain projection and
source-qualified identity; node metrics remain separate. Body-text v2 and
metadata-only v1 are not automatically comparable across every task stratum.
Do not pool unlike populations or convert inapplicability into a negative hit.

All held-out task/gold contents remain inaccessible to selection, model input,
execution and grading. No upstream corpus, annotation effort or scientific
threshold is selected. Hashing the existing source census remains opaque
integrity work and gives no held-out-use permission.

## 6. Selected bounded native allocation

The first technical-design action, before substantive implementation, is a
task-side model-free census using only the already admitted public calibration
metadata and the proposed body-mode binding rules. Generation 2 has exactly
one calibration task, previously ineligible for metadata inference. It may also
be ineligible for public text. The check reads no body, model or held-out
contents. Missing admitted metadata is a preflight stop, not permission to open
an opaque held-out catalog. Never change tasks or golds to pass a floor.

**Declaration 1 (historical, stopped).** It required at least one applicable
non-denied public-text query in each generation and called that risk part of
the operator's selection. Its census found 24/24 matching calibration digests,
at most four ranked-discovery queries in generation 1 and none in generation 2
(cal-23 requests `current_literal_enumeration`). It stopped before substantive
implementation with no body, model, held-out or learned-slot use. Its text
remains the record of that study; it was not relaxed after execution.

**Declaration 2 (operator-amended).** The operator explicitly permitted
document-only generation 2 on 2026-11-11. B-AUTH is resolved. Freeze the
[technical design](cloe-public-text-calibration-implementation-v1.md) before
implementation of each owned epic. Generation 1 supplies only the four fixed
ranked queries whose declared core/companion body policy passed preflight,
subject to fresh runtime admission. Generation 2 has fresh document vectors,
import, publication-fencing and cleanup observations, zero model query inference,
and every original incumbent baseline operation plus unavailable/refused learned
cell retained. No task mode, query, label or gold is changed.

The task-side generation-1 floor has passed. Before learned reservation,
generation 1 still requires an admitted public-text query and document and
generation 2 an admitted public-text document. Missing data stops without a
slot. These are the explicitly amended efficiency floors, not scientific
criteria; there is no automatic further relaxation or retry.

After code, scoped proof and independent source review pass, reserve the new,
separately named `PUBLICTEXT-CAL1` calibration attempt. This neither re-arms
Optional15 nor grants the historical Optional16. Permit at most two isolated generator-worker
invocations, one per existing source generation, and one study-owned pgvector
materialization. Record every component, including refusal, failure and setup.
Record archive-bank restoration and actual worker/database starts under this
new allocation, with original artifact-admission references. No automatic retry,
replacement model or parameter sweep follows.

The old exact twenty-wheel/model bank may be restored from its private archive
only after byte hashes and the original artifact/license/admission chain verify.
Perform the current conditional checks before installation/execution. No new
upstream artifact acquisition or version substitution is permitted. The existing
verified native-ARM SDK must remain compatible and available; absence is not
permission for an SDK/application build or new image.

Preserve every existing input/archive/request/response/report/transport bound,
including 500 imported records and 512 model tokens. Preflight complete
requests before inference. If the v2 input or additional evidence cannot fit,
retain the bounded refusal and stop; do not increase caps or drop unfavorable
rows. Keep model execution outside the privileged test sandbox under the
existing network-disabled, no-host-home/no-private-mount/no-socket boundary.

Scoped synthetic/disposable functional tests are distinct from this learned
allocation and are declared through the existing canonical test profile.
They do not prove learned usefulness or consume a hidden model retry.

## 7. Evidence and interpretation

Before spending the learned slot, estimate combined v1/public-text work against
the unchanged worker and study time limits using frozen counts and retained
runtime observations. Record assumptions and uncertainty. Predictable timeout,
missing usable timing evidence or cap conflict stops at gate 5; no longer timeout,
hidden worker split or exploratory learned warm-up is granted.

The frozen timing basis must identify retained observed token lengths,
record counts, sequential inference work and a disclosed conservative scaling
assumption up to 512 tokens, with headroom under the existing deadline. Short
metadata timing alone is not proof of a full-length fit. If no defensible basis
is available, stop rather than claiming an estimate is a measured upper bound.
Freeze the exact calculation at technical design; no new timing run is implied.

Original component bundles containing captured excerpts inherit their source
privacy/retention class. Keep them in phase-owned private evidence and the
approved archive, outside Git and diagnostic logs. Public reports reference
excerpt digests, offsets and counts rather than copying body text. Historical
public fixture bytes remain unchanged.

Keep original component input/output bytes, source closure, current artifact
admission, publication snapshots and terminal receipts. Reuse compatible
component-dossier validation primitives through a bounded evaluator adapter;
do not assume the fixed two-generation paired-report factory accepts a new
representation. Technical design must identify the exact composition point
and any new strict codec. Preserve the historical factory, schemas and CLI
defaults; do not duplicate the dossier framework or fill observed counts from
plan fields. A missing original bundle is unknown, not zero.

Preserve historical V1/V2 schemas, CLI defaults and raw reports. A new strict
`cloe-public-text-calibration-v1` report references them and original component
members without changing their interpretation. Its reader recomputes hashes,
scope/applicability, counts, arm correspondence and semantic verdicts.

Names distinguish the public-text representation `canonical-node-public-text-v2`,
the historical paired-report V2 and the new public-text-calibration report V1.
Neither report name is a representation identity. New public-text components
must use the new strict codec where the historical schema cannot represent
them; existing paired reports remain byte-identical historical inputs.

Disclose correctness, relevance, recall, empty/absent behavior, selected-index
state, response/materialized bytes, observed work, inference/import/index/setup,
cleanup, latency and footprint in their actual layers. Count shared work once
under a frozen attribution rule; include failed attempts. Unknown wire/internal
work stays unknown. Do not combine unlike cost units into a savings figure.

The milestone can accept source correctness, component compatibility and a
bounded public-text calibration observation. It cannot accept scientific
criteria, held-out superiority, generalization, production vector/HNSW adoption,
full W5, a new search engine or release readiness. Its next decision packet
must expose insufficient applicability and negative findings as valid outcomes.

## 8. Proof and publication

New unit owners must prove deterministic bytes/digests, safe span/UTF-8 bounds,
mixed/denied/stale provenance, no metadata fallback, typed v1/v2 separation,
strict report unknown/failure states and no core import of evaluator code.

Exact canonical containerized integration owners must exercise real accepted
capture/artifact readback, denial before body reads, changed publication between
stages, v1 preservation, temporary SQL identity/refusal/order/cleanup, and actual
writer-to-reader report composition. Synthetic vectors prove SQL only. The
separate admitted native observation proves actual model input/output only.

Before implementation, freeze exact selectors and source ownership after
technical design review. Use `tools/run_tests.py` with exact selectors and
`--no-coverage`; no complete local unit/int/smoke/staging/system/combined suite
or project coverage is authorized. Preserve all quality roots, debt ceilings,
suppression policy and hard 85/85 and 80/80 gates. The desired 87/82 margins
remain open and are measured by hosted CI. The technical design must identify
existing untested admission, publication, SQL and evidence branches from the
CI139 measurements, add meaningful regression owners alongside the new paths,
and record its plan to recover the 22 unit / 502 integration arc shortfalls.
No implementation-mirroring or coverage-only assertion padding is selected.

One final independent source review and fresh exact-source binding precede a
substantial staging publication. No design-only push, duplicate/manual trigger,
main/tag/release, service activation or automatic retry is planned. A later
campaign's allocations must be derived from the then-current authenticated
ledger and workflow ordinal, not copied from a stale proposed packet.

## 9. Named stop gates

1. **Authority:** operator representation selection absent; no implementation.
2. **Privacy/source:** body authority or captured-source correspondence cannot
   be established; retain explicit exclusion/refusal, with no body/model read.
3. **Core boundary:** v2 would require production schema/profile/reader changes;
   return an amended design rather than treating this scope as adoption.
4. **Artifact/runtime:** exact bank or cached SDK fails conditional admission;
   no alternate artifact, image build or platform is inferred.
5. **Bounds:** any existing component/result/transport ceiling would need to
   grow; no hidden partition, selection or cap increase.
6. **Scientific:** any held-out content, new label/task, changed gold, threshold
   acceptance, claimed general superiority or production D15 becomes necessary;
   stop for its separately reserved decision.

7. **Task/census:** admitted metadata is missing, or a declaration-2 floor
   fails (generation-1 body-policy query census before implementation; the
   generation-1 query/document and generation-2 document floors before
   reservation); stop at the respective check. Declaration 1 stopped here.
   Do not alter the corpus or tasks to pass.
8. **Artifact reader/spans:** the maintained reader cannot prove complete
   captured-content closure or accepted line-span correspondence; stop under
   privacy/source gate 2, with no new backend or live fallback.
9. **Temporary privilege:** the existing disposable principal lacks the
   required already-granted TEMP/CREATE rights; stop under core-boundary gate 3.
10. **Time/work:** the frozen combined two-arm work estimate has no defensible
    timing basis or cannot fit unchanged deadlines; stop under bounds gate 5,
    without a learned warm-up, longer timeout or additional worker.

## Operator floor amendment and publication lifecycle

The operator explicitly selected "Permit document-only generation 2" after
the task-side preflight established four possible generation-1 ranked queries
and zero generation-2 ranked queries. All four generation-1 queries also pass
the unchanged core/companion body-policy declarations. The earlier query floor
and its B-AUTH wait are historical, superseded only by this explicit amendment.
Generation 2 retains every original incumbent baseline operation and its
unavailable/refused learned-query cells; it is not assigned a new query mode.

The learned path uses one disposable PostgreSQL study/cluster from the first
accepted publication. Each generation's descriptors, worker and vector reads
bind to that same PostgreSQL publication. No cross-backend eleven-field
equality or vector rebinding is attempted. The existing v1 production sealer,
profile allowlist, public interfaces and historical artifacts stay unchanged.
