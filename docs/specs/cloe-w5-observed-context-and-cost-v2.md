# W5 observed context and cost report V2

## Scope

[ADR0146](../adr/2026/11/0146-w5-observed-operation-and-paired-cost-disclosure.md)
adds evaluator operation evidence and an explicit opt-in paired report. Source
implementation and final proof are separate milestones. Scientific criteria,
held-out usefulness, broader representations and production acceptance remain
open. No new model, corpus, gold label or dependency is selected.

The existing paired report V1, strict experiment ResultV2 and six journal members
keep their contracts. Historical artifact bytes are immutable. Future writers
correct the unsupported reference-recall observation described below; that is a
forward evaluator correction, not historical rescoring.

Optional attempt 15 has now completed with exit code 0 and clean custody. Its
calibration source binding is
`21fa1ee4bcbbda78c41e3c29ec62f6d21a698396effe5ced3eed28e2d700bfee`; candidate
head `14f9d4e250e2cdcd0f0af89049dd36aeb048b728` and dirty-source state are
disclosed explicitly. Independent review 4 reported no blockers. The
pre-calibration scoped proof recorded 347 unit and 34 core integration cases
with static, hygiene and privacy findings at zero; this is not final metadata
qualification.

The run covered 12:32:19–12:40:37 UTC and recorded 621+27 = 648 cells and
216 comparisons. The 216 actual vector-operation records comprise 24 completed,
12 `not_run`, 162 unavailable and 18 refused states. Whole/supported/graded/
eligible denominators remain 648/339/285/264. Baseline evidence includes 36
safety-correct cases, 18 vector/fusion refusals and 12 HNSW
`not_run/index_not_selected` cases. Raw Generation 1 contains 80 documents,
4 queries and 84 embeddings; Generation 2 contains 80 documents, 0 queries and
80 embeddings, using public data and the same approved BGE profile. No completed
ANN, performance, scientific, held-out, full-W5 or production acceptance is
inferred.

The retained report is 3,703,442 bytes with SHA-256
`3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f`; no
private paths are present. No application or SDK build or model-wheel
acquisition occurred. One pgvector 0.8.7 materialization ran on native ARM.
Calibration proved the writer-to-journal-to-ResultV2-to-V2-reader composed
seam. The final artifact analysis rejected all six tampered report derivatives.
Optional 15 is spent and has no automatic attempt 16.

The optional-15 native HNSW provenance observation records 72 HNSW operation
records, including 24 actual per-binding `HnswProvenance` records. All 24 have
raw state `not_run`; EXPLAIN executed and cleanup was verified for all 24, with
at most 63 plan nodes and zero expected ANN-index-selected cases. This proves
the retained not-run provenance shape, not completed ANN or performance.

This bounded calibration does not activate the conditional CI115 attempt-1
binder prepared under
[ADR0147](../adr/2026/11/0147-w5-observed-operation-and-paired-cost-disclosure-staging-campaign.md)
with four grant owners. CI115 would consume native AMD start 28 after 27, but
has not been remotely triggered or spent. CI114 remains the latest green hosted
predecessor. Final public-candidate
scoped proof, publication review disposition and exact-commit report remain
pending; final counts belong in that phase commit and candidate report.
All complete local Python suites, coverage and application builds remain
intentionally unselected, and the soft 87%/82% target remains pending hosted
qualification.

## Entry point and custody

The tools-only entry point is `tools/retrieval_semantic_pair_v2_report.py`:

```sh
python3 tools/retrieval_semantic_pair_v2_report.py \
  --journal 1=/owned/evidence/w5-semantic-g1 \
  --journal 2=/owned/evidence/w5-semantic-g2 \
  --result 1=/owned/results/g1/result-v2.json \
  --result 2=/owned/results/g2/result-v2.json \
  --output /owned/analysis/paired-context-v2.json
```

`build_pair_report_v2` reads both original journal/result generations, checks
their terminal and member/result bindings, and reuses the existing identity
joins. `write_pair_report_v2` creates one new owned output. It refuses overwrite
and unsafe paths. `read_pair_report_v2` validates a derivative's structure and
internal relations; it does not reopen the original sources, authenticate a
live store, or authorize execution. Rebuild from the original artifacts when
checking source correspondence.

The output schema is `cloe-w5-semantic-paired-report-v2`. Every acceptance field
remains false. A record digest establishes consistency, not trusted origin,
publication permission, model execution or scientific acceptance.

## Distinct evidence families

| Family | Evidence and meaning |
| --- | --- |
| Declared/grade context | Literal values retained on the grade, including unknowns; no inferred execution. |
| Observed envelope | Closed public fields from the hash-bound actual query envelope. |
| Observed operation | Validated `cloe-w5-observed-operation-v1` journal extension from typed runtime inputs and returned results. |
| Recorded work | Distinct journal, ResultV2, correspondence and generation/component cost layers. |
| Comparison gaps | Missing or conflicting observations, separate from scientific comparability. |

Baseline modes, fallback, capability, surfaces and selection come from the
actual envelope and its hits. Public projection excludes raw hits, locators,
bodies, display text, vectors, SQL and principals. A declaration that differs
from the observed request is disclosed. Two observed claims of the same fact
that disagree are refused. Unknown, unrecorded, empty and zero remain distinct.

Vector APIs do not expose an effective shared QueryMode. Their effective mode
stays null; the actual operation descriptor supplies the separate SQL or fusion
context. An arm name, task mode, caller mapping or copied publication witness
cannot establish execution. Serialized operation records remain inert data.

## Capture boundary

`observed_operation` is a sibling field on `query_observed`. It never enters
`ExperimentCell`, `QueryEnvelope` or the strict ResultV2 cell. It binds generation,
task, arm and repetition and carries its own canonical digest. The terminal
journal digest also covers the entire observation stream.

Exact-query descriptors are captured from the actual validated CandidateQuery
at the execution boundary. Publication, receipt, profile, rebuild and admitted
source scope are checked against a factory-issued pin and current readback.
The descriptor contains digests and bounded public identity/work fields, not
raw vector or SQL payload. SQL completion, overall cell outcome and later
cleanup outcome remain separate observations.

Hybrid fusion captures the existing FileFusionResult's policy, counts,
inspected work and incomplete/truncated/fallback states. It does not duplicate
hits or numerator/denominator fields. Exact-rational values remain on their
original cells. This preserves V1 rational interpretation while new journal
member hashes truthfully bind the added bytes.

Unadmitted vectors and a hybrid blocked by its upstream arm record no attempted
vector/fusion operation. A failed arm cannot gain credit through fallback.
Both unadmitted writer paths preserve their explicit state. HNSW creation,
plan, SQL result, provenance, reference comparison and cleanup are separately
retained; an empty plan and its old digest do not establish an observed plan.
Capture never bypasses a pin, scope or identity refusal to retain an operation.
Such a refusal stops trusted capture and may leave an incomplete cell journal;
the generation failure record cannot substitute for missing cell evidence.

## HNSW and reference recall

`EXPLAIN ANALYZE` executes SQL work. When the expected index is not selected,
the cell remains `not_run` for ANN and retains the actual plan/work. This gives
neither ANN execution nor a performance result. Missing plan evidence alone
does not prove that no SQL work occurred. The evaluator does not force a planner
choice or change frozen HNSW settings for calibration.
The bounded plan summary preserves up to 128 actual node labels and 16 index
names, including repetitions from nested plans. This accommodates the retained
63-node plan within the existing artifact byte limits; it adds no ANN credit.

The typed evaluator's exact-baseline recall and the outer writer's reference
recall remain distinct. Future writers omit the outer recall when the exact
reference did not complete or was empty. A valid empty reference is disclosed
as vacuous rather than measured recall. Old stored literals remain visible
with their evidence gap; the report does not rewrite them into new measurements.

## Counts, costs and limits

Component document/query/embedding/record counts are captured from the same
validated sealed worker response and remain bound to its component digests.
The report marks them recorded with `independently_revalidated=false`. A missing
count is not zero. The optional raw-model-bundle reader is deferred; independent
private raw-bundle verification remains a separate evidence claim.

Raw process stdout, selected text, serialized envelopes, artifacts/materialized
reads, correspondence work and returned-row counts are distinct layers. Unknown
database wire/internal I/O stays unknown. Tokenizer input counts are not billable
agent completion tokens or dollars.

Existing exact and HNSW elapsed values include validation, readback, EXPLAIN or
other work within their actual spans. The generation's query-loop timer also
includes capture, serialization and grading. These are composite observations,
not isolated SQL timings. Nested component timings are not summed again, and
new capture work is not retroactively attributed to old query observations.
Live pin revalidation performs readback inside that composite timer; its
separate work and duration are unmeasured and remain unknown.
Shared campaign cleanup remains charged once to the last retained generation.

The operation record has a bounded byte/cardinality budget within unchanged
journal limits. The 16 MiB observations member, 4 MiB individual ResultV2,
8 MiB aggregate encoded-result input and 32 MiB report output limits stay in
force. A cap conflict refuses rather than hiding observations or widening limits.

All declared cells, whole/supported/graded/eligible counts, reason categories,
stored grades and fixed comparisons remain. The retained native cal-07 output
of 495,781 bytes and unaccepted 65,536-byte proposal stay separate facts. No
deltas, pooling, win/tie/loss, superiority aggregate or threshold acceptance
is produced.

## Verification boundary

Exact unit owners cover type/identity/digest conflicts, provenance and binding
relations, no-execution states, reference recall, privacy and bounded outputs.
Canonical containerized integration uses real journal/ResultV2 writers and
SQLite/PostgreSQL readback. Disposable pgvector and learned calibration each
require their separately recorded current allocation; core proof does not
substitute for those boundaries.

Final commands and results belong in the phase exit and exact-commit report.
Complete local unit, integration, smoke, staging, system and combined suites,
local Python coverage and application/SDK builds remain intentionally unselected.
Hosted CI owns complete-population and native assembled-system qualification.

## Resulting-source review clarifications

No-execution and unsuccessful bindings retain their cells and nullable query
descriptors. A blocked hybrid has no attempted query/fusion evidence. The
orchestration-to-journal path requires scoped refusal and failure proof before
learned calibration, alongside completed and HNSW-plan outcomes.

Baseline context reports envelope evidence separately from vector-operation
capture. A baseline never gains an artificial missing-vector-operation gap.
Unavailable public-safe reason text is marked `withheld`; absence remains null.
Generation-2 disclosures agree with recorded sealed-response counts while
preserving their non-independent trust boundary. The cal-07 byte constant is a
historical reference, separate from current input observations. A second journal
read must match the first validated member identities before projection.

## Public provenance and timing clarifications

The public A4 projection may expose provenance identifiers for the binding,
snapshot, repository, attempt and operation index only after public-scope
verification. A selected-list count and digest are compact correspondence
support; neither is a privacy control. Private bodies, vectors, SQL, raw
payloads and principals remain prohibited from public output.

The A5 projection retains creation and ANN-cleanup durations when observed.
Generation-level aggregates use `index_ns` and `ann_cleanup_ns`. Operation
metrics are per binding and limited to observed `EXPLAIN` metrics. Separate
timings that were not recorded remain absent or unknown; they are never inferred
from a cell's elapsed time. Composite elapsed values therefore remain distinct
from generation aggregates and per-binding operation metrics.
