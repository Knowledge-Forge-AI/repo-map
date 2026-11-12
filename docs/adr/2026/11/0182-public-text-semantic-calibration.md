# ADR 0182: Public-text semantic calibration

Status: selected input class and source implementation accepted for this bounded
calibration checkpoint; native CAL5 passed on 2026-11-12. Scientific usefulness,
held-out evaluation, full W5 and release acceptance remain open. The original
CAL1 allocation and CAL2–CAL4 failures remain historical; later operator grants
authorized the named successors and the host-only receipt policy in ADR0183.
Phase: `REPOMAP-CLOE-PUBLIC-TEXT1`. Date: 2026-11-11; outcome: 2026-11-12.
CAL5 ran against the frozen evaluator before the final typing corrections.
CI140 contains the corrected evaluator, with fresh scoped and synthetic
functional proof; no new native model execution is inferred for that source.
Declaration 2 and its authority history are in
[the implementation design](../../../specs/cloe-public-text-calibration-implementation-v1.md).
The accepted foundation interfaces are in
[the foundation contract](../../../specs/cloe-public-text-foundation-v1.md).
The remaining study/report technical contract is owned canonically by
[the study contract](../../../specs/cloe-public-text-study-v1.md).

## Context

CI139 qualifies the bounded installed-experience prerequisite in ADR0181.
W5 remains a release prerequisite. Its optional readback, publication fencing,
explicit unavailable outcomes, stored-seed MCP, evaluator, paired evidence and
component dossier already exist. They must not be rebuilt as new milestones.

The learned input remains `canonical-node-v1`: canonical key, kind and display
name. ADR0136 explicitly limited its first implementation to accepted node
metadata and left a captured-text representation for a later decision. Its
retained calibration has 80 document records per generation, four query
embeddings in generation 1 and zero in generation 2. Those are historical
metadata-representation results, not a body-text comparison. Optional15 is
spent and its bytes/source bindings remain immutable.

The public fixture already contains captured public code and documents, and
retained projection policy distinguishes them from denied or metadata-only
bindings. A separately versioned public-text experiment can answer whether
that admitted material gives the existing model a useful comparison surface.
It does not justify a new corpus, model, private-content route or service.

The original design checkpoint permitted design work. It does not silently supersede
ADR0136's input boundary or the operator-owned scientific/held-out decisions
in the W5 semantic-evidence contract.

## Selected input class and bounded program

Select one evaluator-only, public-fixture milestone of three connected epics
under [the proposed protocol](../../../specs/cloe-public-text-semantic-calibration-v1.md).

1. **Publication-bound public-text representations.** Add
   `canonical-node-public-text-v2`, retaining one representation per admitted
   canonical-node/binding pair. Combine the existing metadata with one bounded,
   deterministically selected excerpt from already captured public material.
   Verify the accepted publication, effective body policy, source snapshot,
   artifact digest and observed evidence before reading bytes. Independently
   reconstruct the exact model input from those owners; caller claims and
   inference output never establish provenance.
2. **Disposable learned comparison.** Keep v1 intact as a separate arm. Use
   an evaluator-owned typed v2 profile and temporary vector storage in the
   existing pgvector 0.8.7 disposable path. Do not broaden the production
   `EmbeddingProfile` allowlist, production SQL/schema, public CLI/MCP or
   production extension admission. Run the unchanged approved calibration
   population, with public-text applicability frozen before any query. Compute
   both metadata and public-text document/query vectors afresh inside the same
   bounded generation worker; import no historical vectors or scores. Reuse
   the exact operator-selected BGE/ONNX artifacts and isolated native-ARM boundary.
3. **Inspectable comparison and decision evidence.** Reuse compatible component,
   provenance, journal and strict-cell validators through a bounded new adapter;
   preserve the historical fixed-generation dossier factory. Add a distinct
   public-text calibration report linking original component bytes to v1/v2,
   native/graph/lexical, exact-vector, observed ANN and fusion observations.
   Preserve failure, missing, unsupported, truncated and unknown states. Use
   the result to prepare a later scientific/held-out decision; do not declare
   numerical usefulness, superiority or full W5 from calibration.

### Input and privacy boundaries

- Only existing approved `mixed-v1` calibration material and queries are in
  scope. No catalog, query, gold, split, corpus or fixture body is edited.
- An eligible body must already be captured, belong to the exact accepted
  publication and be permitted by the effective body-projection policy.
  Public source availability alone is insufficient. Document admission applies
  body-mode policy per binding, including email/feed and retention bans:
  metadata-only, denied, withheld or unverifiable pairs are explicitly excluded
  before their body access or inference. Existing global binding denials still
  refuse the whole query before any arm. Supplemental body-mode denial refuses
  only the public-text arm and any fusion depending on it; v1 and incumbent arms
  retain their existing mode-derived decision. Excluding one
  document pair does not silently discard its requested query task.
- Query admission for the public-text arm always uses body-mode policy for all
  selected bindings, including metadata-mode tasks. Any resulting difference
  from v1 is a visible applicability/refusal outcome, never an empty scored miss.
- No live target filesystem, private graph/home, connector, upstream corpus or
  user document is an input. MCP stays read-only and source-blind. Similarity
  creates no canonical edge.
- Missing/invalid body evidence excludes v2 explicitly. It never substitutes
  metadata bytes under the v2 name. The independently labelled v1 arm remains.

### Runtime and execution boundaries

The model revision, all twenty dependency pins and artifact profile from
ADR0136 remain exact. This selects no runtime dependency, package metadata,
lockfile, image, model, inference backend or platform change. Restore an
existing approved artifact bank only after its retained hashes verify. Any
missing/unverifiable bank, incompatible cached SDK or new upstream acquisition
requirement is a stop gate; do not substitute artifacts or rebuild the SDK.

Before substantive implementation, first perform a model-free task-side
applicability check against the frozen public calibration metadata and body-mode
binding policy. Generation 2 has only one calibration task and was ineligible
for metadata inference; it may also be ineligible here. Under declaration 1,
if either generation had no applicable non-denied public-text query, the
proposal stopped before building the epics or reserving a learned slot; that
happened (below). Do not alter the catalog to rescue this proposal. No body,
model or held-out content is read by that task-side check.

Declaration 1 (historical) deliberately exceeded the earlier document-only
generation-2 diagnostic by requiring query observations in both generations.
Its census stopped it before implementation: all 24 calibration digests
matched; generation 1 has at most four ranked-discovery queries; generation 2
has only cal-23 (`current_literal_enumeration`), which the existing seam
refuses. No body, model, held-out content or learned slot was used. That stop
stands and is not reinterpreted as a pass.

Declaration 2 is the operator-amended predeclared study. On 2026-11-11 the
operator explicitly permitted document-only generation 2, resolving B-AUTH.
Generation 1 supplies its four fixed ranked queries subject to fresh body
policy and document admission. Generation 2 supplies fresh document vectors,
import, publication-fencing and cleanup observations, with zero model query
inference. Every original incumbent baseline operation and unavailable/refused
learned-query cell remains visible; no task is relabelled. No learned query
metric or cross-generation learned-query claim is made for generation 2.

The task-side body-policy census has passed for all four generation-1 ranked
tasks. Before reservation generation 1 still needs an admitted public-text
query and document, and generation 2 an admitted public-text document. Missing
data remains a stop. Input class, fixed population and allocation are unchanged.

These remain execution-efficiency floors, not scientific acceptance. The
selected allocation is `PUBLICTEXT-CAL1`: one predeclared calibration attempt with
at most two isolated generator-worker invocations, one per existing fixture
generation, and one study-owned pgvector materialization. Each worker computes
fresh v1 and public-text vectors within one combined bounded request; the
500-record and every other limit apply to that combined request, not per arm.
This does not re-arm Optional15 or grant Optional16. Record the conditional
artifact-bank restoration and all component starts in its distinct ledger.
Separate scoped functional tests use the
existing test profile with exact, individually recorded invocations. There is
no automatic learned retry or sweep. Every current artifact/request/result,
transport, record and byte ceiling is preserved. The 500-record ceiling and
512-token model limit remain. A cap conflict stops the attempt.

All model execution remains inside the already qualified native-ARM SDK,
network-disabled, without a host home, private mount or Docker socket. No model
runs in the privileged canonical sandbox. No native AMD model, attended macOS,
Windows or service qualification is inferred.

## Alternatives

**Keep the metadata representation only.** This needs no representation
expansion and preserves a useful compatibility arm. It leaves the recorded
body-stratum mismatch and limited learned-query population unresolved. It is
the default if the operator does not select this proposal.

**Admit held-outs now.** Rejected for this milestone. The future protocol and
numeric criteria are an operator decision. Held-out tasks/golds remain opaque
to selection, inference and grading; only existing source-integrity hashing is
permitted. Public-text calibration should inform that later proposal.

**Use another model or new public corpus.** Not selected. It expands artifact,
license, input and annotation authority before testing the admitted material.

**Add text-to-vector product search or enable production pgvector.** Not
selected. Public capability design, enrichment-principal authority and the
complete ADR0051 D15 record remain separate.

## Authority and acceptance

The operator explicitly selected this public-text input representation and
bounded calibration path ("proceed", route A, 2026-11-11). Ordinary roadmap
continuation and green core CI did not supply that choice. The selection is
conditional implementation authority, not evidence of model compatibility or
usefulness.

Before implementation, the parent must accept the resulting technical design
and dispose independent findings. Scope-preserving technical refinements do
not authorize a new input/runtime class. If the proposed temporary adapter
cannot preserve the production v1 contract, stop rather than broaden it. The
technical design keeps production `EmbeddingProfile`, schema, readers, the
generic worker and its source closure unchanged; v2 uses evaluator-typed
profiles and invocation-owned study tables created by the existing disposable
owner under its already granted rights. The production sealer cannot accept a
combined dual-arm response. Calibration v1 vectors therefore go only to a study
`canonical-node-v1` batch in the invocation-owned study relations, and
production-reader parity is proven in integration with synthetic vectors. Span lines come from the new companion
`w5_public_text_readback.py` support owner, bound to both unchanged existing
SQLite/PostgreSQL v1 evidence readers and their exact accepted row sets.

Source acceptance requires exact scoped unit and containerized integration
owners with `--no-coverage`, unchanged quality/debt/coverage policy, independent
source review, recorded calibration admission/outcomes, and an exit record.
Missing or failed calibration may be retained but cannot close the milestone.

Batch the three epics for one substantial reviewed publication, aiming at the
operator's 10k–100k meaningful-line preference without padding. The preliminary
planning range is roughly 8k–15k changed lines across source, paired tests and
docs; it is uncertain until technical design and existing-code reuse are mapped.
Reuse takes precedence over a line target. Add meaningful tests for the existing
admission, publication, SQL and evidence failure branches alongside the new
behavior, aiming to recover the recorded 22/502 branch deficits. Hosted CI alone
measures the resulting 87/82 margins. No intermediate design-only CI is planned.
One later normal staging campaign requires a fresh exact-source binding after
the implementation exists. CI139's 49/19/42 cumulative application/native-Rust/
wheel consumption is spent; this proposal neither re-arms it nor mints a next
build, trigger, retry, main promotion, tag or release.

## Rollback and residuals

Remove only phase-owned temporary data and disable the evaluator-only v2 path.
Keep historical v1/V2 reports, profiles, source identities and failed attempts.
No accepted graph, live database, installed package or service is migrated.

The sample remains small, English-oriented and capped. Public-text input is
not anonymous. Independent component evidence and exact SQL order do not
establish learned relevance. HNSW may remain unselected at this scale; record
that state and claim no ANN acceleration. Held-out/scientific acceptance,
production D15, full W5/W6/W7/W8 and v0.1.0 release remain open.

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


### Evaluator privacy closure (2026-11-11 source review)

Source review identified that the inherited textual redactor's escaped regular
expressions miss ordinary credential assignments and credentialed HTTP URLs.
The new public-text input path must reject those shapes through a small local
stdlib predicate before encoding; it must not redact and admit them. Existing
product/v1 redaction behavior stays outside this evaluator-only phase. No new
dependency or runtime class is selected. A broader product correction remains
a separately tracked follow-up. The guard is frozen before learned corpus
body inspection or inference, independent of any calibration outcome.

Public-text metadata must also meet the descriptor's exact printable/length
bounds before body reads, otherwise exclude the pair with the closed metadata
privacy reason. This preserves v1's decisions and gives U+0080-U+009F metadata
a named refusal rather than an unclosed descriptor error; admitted excerpt
controls still use the specified JSON escaping. Revalidate each direct raw
excerpt read individually. A SQL-span link mismatch excludes its selected pair
before raw excerpt reread; any changed descriptor/exclusion set on the later
recomputation refuses the entire generation.

The follow-up findings of the second foundation source review (F1–F5) are
disposed by
[study contract section 14](../../../specs/cloe-public-text-study-v1.md#14-foundation-follow-up-delta-disposes-source-review-2-f1f5).
That disposition must happen before any learned corpus inspection. It covers:
- structured metadata ids without the body-assignment heuristic, while
  retaining the control-character, marker and credential-URI checks;
- non-HTTP userinfo, key compounds and PEM private-key headers;
- conservative body credential-shape exclusions, disclosed as coverage
  exclusions rather than claimed secrets;
- an evidence-key guard before any body read;
- closed refusals for descriptor-construction failures;
- direct stale-publication and per-read race proof;
- a numbered admission gate order.

No new dependency, parser or runtime class is selected.

## Encoding source compatibility disposition

The retained calibration manifest hashes canonical task JSON with ASCII
escaping. The unchanged learned-v1 query decision hashes UTF-8 JSON without
ASCII escaping. These differ for the existing Unicode task cal-20. Both
identities remain valid in their respective schemes. Every registered task
pin and every original task/question/gold/mode/generation byte stays unchanged.

The selected loader and task-set identity verify the retained ASCII digest.
The census carries both `retained_task_sha256` and its existing `task_sha256`
(the original v1 query digest). Request correspondence checks each against
its own scheme and binds both maps with named schemes. No pin is re-registered,
no old query decision is rewritten, and no digest check is relaxed.

Before sealing, the expected request is rebuilt from its actual owners and
compared for exact manifest, layout and record equality; the refreshed
request must also match layout and records. Native study entry additionally
requires the exact registered pin set before any reservation; synthetic
source fixtures confer no native authority. Unexpected exceptions are
closed only around external readback/refresh calls and refuse the whole
preparation/generation, never a favorable row exclusion.

Excerpt classification precedence is private marker, credential shape, then
the maintained sanitizer. All three refuse admission. When a credential shape
and the maintained sanitizer both match, the result is the conservative shape
exclusion. When a private marker also matches, the marker still wins and the
pair is a privacy refusal. A shape match is never evidence that a real secret
exists. Prior independent
source findings require fresh corrected-source review and paired proof.

The report owns the raw component's validated `elapsed_seconds` join; the
unchanged `SemanticCost` retains only its three timing fields. The new private
controller must bind per-generation worker reservations to actual frozen
requests before admission; old Optional15 allocation helpers are not current
authority. A narrowly adapted request-bound admission factory may do that
without changing Q's generic worker or any deadline, count or retry rule.

This is a technical compatibility correction within the approved public-text
class. All 24 tasks, three repetitions, two workers, one study, no retry and
all build/publication exclusions remain unchanged.

## Retrieval repair 2 disposition (2026-11-11)

The resulting-source review of the retrieval/report source (F1–F9) and the
parent's preliminary checks are disposed in
[study contract section 18](../../../specs/cloe-public-text-study-v1.md#18-retrieval-repair-2-resulting-source-review-f1f9-and-parent-checks).
That section is the exact API and owner record. In summary:

- The study SQL refuses a NULL public-text descriptor.
- Batch capability binds to the actual sealed arm. Query-only truncation is a
  legitimate `token_partial` batch.
- A new catalog owner fences the complete recorded child-object inventory of
  both study relations. That covers constraint and owned indexes, triggers,
  rules, policies and RLS. Every use and cleanup is fenced, and cleanup checks
  before any drop. Absence is reported per object.
- Owned indexes register only through an immutable typed catalog. ANN without
  a registered index never completes. The positive pgvector ANN case must
  assert a selected owned index and row correspondence, separate from the
  genuine unavailable case.
- Public-text fusion derives selected bindings from the actual task. It
  accepts only a validated typed projection. The v1 arm is called on real
  study rows.
- Two report helper owners close every nested report shape and join census,
  preparation, request, seal, component, imports, indexes, fences, cells and
  cleanup.
- The reader is structural by default and says so. Raw-evidence verification
  needs the actual journal, model members and selected task objects.

The prospective report gains a mandatory strict top-level
`functional_only: boolean` and a matching closed per-generation fence
`execution_kind`. This is a bounded clarification of the already required
synthetic/native distinction. It is not a new worker protocol, runtime
behaviour, scientific input or execution authority. The future complete
functional driver marks all of its study evidence `functional_only: true`,
without an allocation root or native reservation. The
learned selector marks `functional_only: false`. That flag alone never proves
model origin or native acceptance, and every acceptance flag stays `False` in
both modes.

A new test-support owner, `w5_public_text_artifacts.py`, writes synthetic raw
seven-member protocol artifacts. Only the unchanged parser turns them into a
response. It runs no model, database or network operation and makes no
model-origin claim.

No historical report, old V1/V2 factory, generic worker, parser, protocol,
fixture, task, gold, dependency, runner, threshold or allocation changes.

## Parent closure of retrieval repair 2 findings

The remaining query/task join, disclosure, strict-generation and projection
issuance findings are corrected before positive study closeout. Query seal
source identities join the retained task digest, and verified reads also
compare actual embedded query bytes with the unchanged task question. The
positive synthetic report uses the registered task objects over a pure,
artifact-backed fixture with matching public bindings. The dedicated test
support owner is `w5_public_text_registered_fixture.py`; original fixtures,
catalog, tasks and golds remain unchanged.

Builder and default reader are structural; raw verification requires actual
evidence context. Generation fields reject booleans. Public-text projections
are factory-issued in-process objects; copying the private token with
`dataclasses.replace` does not issue a new validated projection. Publication
fences record the state at observation time; later g2 staleness is separate
evidence and never retroactively erases g1 observations. A refused creation
readback leaves unknown objects untouched and reports failed cleanup before
the disposable cluster is removed. No native allocation or adoption follows.

## Final driver source window (2026-11-11)

This section names the final-driver owners, selectors and seams before any of
their source is written. The exact interfaces are in
[study contract section 19](../../../specs/cloe-public-text-study-v1.md#19-final-driver-source-contract).
It grants no native reservation, model run, study materialization, build,
acquisition, retry or publication. Two model workers and one study stay
unreserved.

**Twelve new source owners, each at most 400 physical lines, stdlib or
existing repository modules only.** Each has a matching unit owner under
`src/test/unit/python/tools/` named `retrieval_public_text_<suffix>.unit.test.py`.

| Owner | Responsibility |
|---|---|
| `tools/retrieval_public_text_allocation_io.py` | canonical finite receipt bytes, digest/seal, 0700 root and 0600 file custody, no-follow lock, bounded read, exclusive fsynced write; a torn write stays spent |
| `tools/retrieval_public_text_allocation.py` | closed receipt schemas, cross-links, one-study/two-worker order and the explicit terminal API |
| `tools/retrieval_public_text_native_gate.py` | the closed generation-frame codec, stale-g1 proof object and the one-shot bounded log reader |
| `tools/retrieval_public_text_native_inputs.py` | native path custody, exact 17-file worker-view copy, fixed learned argv and the scoped child environment |
| `tools/retrieval_public_text_preflight.py` | frozen timing basis, actual-count estimate and source-bound transition observation |
| `tools/retrieval_public_text_sources.py` | evaluator closure assembly and the separately named flat 17-file worker closure |
| `src/test/support/python/repomap_test_support/w5_public_text_generation.py` | actual Local/PostgreSQL fixture publication per generation and PostgreSQL-only input preparation |
| `src/test/support/python/repomap_test_support/w5_public_text_baselines.py` | the six original incumbent operations and their original grades |
| `src/test/support/python/repomap_test_support/w5_public_text_journal.py` | genuine component journals and the private failure receipt |
| `src/test/support/python/repomap_test_support/w5_public_text_functional.py` | synthetic raw delivery over the real exchange boundaries |
| `src/test/support/python/repomap_test_support/w5_public_text_learned.py` | the six learned arm operations and cell adaptation |
| `src/test/support/python/repomap_test_support/w5_public_text_study.py` | the one stateful driver: states, publication order, exchange order, cleanup and report |

**Selectors.** There is one name for each role. The source-proof pgvector
selector list excludes the learned owner explicitly.
- Functional full driver:
  `src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py::test_public_text_functional_lifecycle`.
- Single learned owner:
  `src/test/int/python/tools/retrieval_public_text_study.int.test.py::test_public_text_semantic_study`.
- Core journal integration:
  `src/test/int/python/tools/retrieval_public_text_journal.int.test.py`.
These supersede earlier notes that used the study owner for the functional
proof or a new `repomap_kg/retrieval` learned owner.

**Seam.** The functional and native modes run one driver with one exchange
order. The order is: publish the request, print the generation frame, emit
readiness, await controller admission, admit the genuine journal and print
the ACK, await the response, then the unchanged parser and study seal. Only
raw delivery differs. The functional mode installs a concrete synthetic
supplier, and the native mode waits for the external private supervisor. The
host reserves the one study before it launches the canonical runner. The
inner driver computes its own study identity, and its frame carries only
facts it observed. The frame omits any transition-gate field. The private
factory binds the real functional-transition receipt and the one new
worker-reservation gate. A `functional_only: true` frame, root or report is
refused by the native controller.

**Corrections required in this window.**
- Report counts and the per-arm counts sealed into each generation accept
  only exact `int`, so a `bool` or `float` is refused even when it compares
  equal.
- Cells gain a mandatory, closed `file_grading` object. It is independent of
  execution state.
- An early failure writes a bounded private failure receipt. It never writes
  a partial report.
- Encoding follow-ups F1–F11 are disposed in study section 19.
- The private-marker digest is not a capability. A caller can recompute an
  unkeyed digest. The bindings that count are the fresh owner and the scope
  object identity, and caller markers confer no native authority.
- `w5_public_text_registered_fixture.py` stays a unit helper. Its
  `SyntheticStudy` caller replaces the accepted reference run and
  generation, so it is not a real refreshed generation. The functional
  driver uses genuine publications instead.

**What remains held.** This window produces source-tested and synthetic
functional evidence only. It does not produce native, model, scientific,
roadmap or manager acceptance. The private controller, its bridge copies and
native admission remain parent-owned and need independent review.

## Parent correction of final-driver evidence and failure boundaries

Before correcting the deferred driver checkpoint, the parent selects two
cohesive evidence owners, each with a matching unit owner and a 400-line
ceiling: `tools/retrieval_public_text_export.py` for the bounded private stdout
sidecar, and `w5_public_text_evidence.py` for actual private inputs, raw-member
custody, report assembly and terminal evidence. Their exact interfaces and
limits are recorded in study section 20. This adds no dependency, generic
worker protocol, test-runner policy, model execution or allocation.

The ordinary scoped runner does not export a report tree merely because
`--report-dir` is present. Its existing journal stdout frames remain unchanged.
One phase-private sidecar retains the actual report or failure receipt,
functional transition pair when applicable, and five raw members per started
model response. Its labels confer no authority. The host verifies the bytes
and joins them to genuine journals and original tasks before native admission.

Unexpected correspondence errors fail the study instead of silently becoming
grading gaps. Actual generation-1 failed operations stop before generation-2
publication. Cleanup runs once even on unexpected exceptions; interrupts
propagate after cleanup. Journals describe component and observation execution
through cleanup, while the study outcome and terminal evidence additionally
cover later report publication. A report or diagnostic-write failure cannot
become a passing study or replace the primary failure.

The allocation terminal likewise separates failed final evidence from failed
cleanup: two clean completed workers plus clean study cleanup use
`study_evidence_failed` when final evidence is refused. Study section 20.1
defines this internal classification before its source correction. No native
slot or retry is added.

## Final driver review corrections

The independent driver review found an older catch-all beneath the new
baseline adapter. Narrow that helper to the maintained `ExperimentRefusal`
family: genuine correspondence refusals remain grading gaps; programming and
unexpected I/O errors propagate. Exercise the actual helper in the regression.

Keep later journal-finalization, journal-framing and report errors alongside
an existing primary failure in the driver's diagnostic list. On an interrupt,
attempt the same failure receipt and private evidence export after cleanup,
then propagate the original interrupt. An evidence-write failure does not
authorize retry, suppress the primary error or assert clean native completion.

The sidecar emitter's size estimate is not an exact aggregate stdout count.
The fixed 96 MiB aggregate cap is enforced on actual captured bytes by the
decoder and host readback before verification. Oversize output refuses; it
does not qualify. This clarifies the existing fail-closed bound without
changing any cap or granting another model/study attempt.

## CAL5 native outcome and conditional CI140

The operator authorized ADR0183's bounded host ownership receipt, one attribution
diagnostic, one conditional CAL5 successor study and one conditional CI140
campaign. The diagnostic passed before the study: one exact pgvector boundary,
575 ownership samples, no observation errors, exact container removal and
conserved host resources. Its runtime modules were adopted byte for byte.
Independent APGR source checkpoints and physical-line read audits were accepted;
an incomplete earlier read audit remains rejected rather than relabelled.

CAL5 then ran once in the existing native ARM boundary. Both generation workers
completed with clean terminals, the canonical runner exited zero, and final
cleanup passed. The parent replayed the actual stdout sidecars, original model
members, evaluator/worker source archives, generation gates and fixed task joins
through the strict report reader: 864 cells, six distinct incumbent arms with
verified file grading on applicable tasks, no failed operation cells, and a
non-functional-only report. Generation 2 remained document-only. The actual
report identity is
`sha256:37461c6d4fba05e1952402249563592cd2e77bc2fc0fbd9eb2447da942858ea4`.
All report acceptance flags remain false. Calibration is decision evidence,
not a numerical superiority, scientific, production or release verdict.

Five cumulative studies and two total model workers are spent. CAL4's failed
ownership observation and unproven strict closure remain unchanged. The fresh
CAL5 proof covers its verified receipt, sampled identities, known runner and
owned containers; it does not claim exhaustive discovery of every process.
There was no new image, application/SDK build, acquisition, local complete suite
or Python coverage run. Public schema, profiles, CLI/MCP and dependencies remain
unchanged. Exact proof selectors and residual boundaries are recorded in
[the outcome](../../../specs/cloe-public-text-calibration-outcome-v1.md).

Actual native PASS releases the approved conditional CI140 attempt-1 preparation,
subject to final candidate/grant proof and independent review. Its cumulative
limits are application 50, native Rust AMD 20 and wheel transfers 43. CI139's
49/19/42 is spent. Exactly one normal staging push may trigger the existing
campaign; no automatic retry, CI141, main promotion, tag or release is granted.


### CI140 wheel-counter correction

The operator approved the exact cumulative wheel-transfer correction from 43
to 44 after CAL5 passed. CI139 spent 42 transfers; the unchanged Rust qualifier
requires two pinned wheels. The final conditional CI140 attempt-1 limits are
application 50, native Rust AMD 20 and wheel transfers 44. Earlier cap43 records
remain historical. This correction permits no extra campaign, local build or
acquisition, study/model worker, automatic retry, CI141 or main/tag/release
action. The one staging push still requires final grant proof and independent
review; hosted qualification remains pending.
