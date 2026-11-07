# W5 admission and paired evidence v1

## Status and scope

This specification implements [ADR0144](../adr/2026/11/0144-w5-admission-scope-and-paired-evidence-closure.md)
inside the existing REPOMAP-CLOE-SEMANTIC1 evaluator milestone. The bounded
implementation has pre-review scoped proof: the initial proof has 255 unit
passes, while its containerized evidence contains 44 initial passes, one
retained failed exact node, and one corrected exact-node pass (45 distinct
passing cases overall). The completed grant cohort adds 5 unit and 4
integration passes, for 260 unit and 49 distinct integration cases across the
cohorts. The explicit immutable source bridge preserves prior source identity
evidence; it is not a same-census rerun. ADR0146 predecessor source proof has
historical checkpoints: the pre-correction frozen 5f66 census recorded 315 unit
and 26 core integration cases with full retention and scanner checks, while the
620c census recorded 328 unit and 29 core integration cases. The earlier
260-unit/49-integration scoped cohort accounting is historical as well; none of
these checkpoints qualifies the ADR0144 implementation. Reviews 2 and 3 are
closed with findings. Resulting cohort 9 census
`b589d41bf2fb3a77e8d23db46e9e11e9f1169f0f7ce8432e9e03624139c00d76` passed 342
unit and 31 core integration cases with static, hygiene and privacy findings at
zero. This is bounded evidence, not whole-candidate acceptance. Review 3's
narrow cross-reader and activation-proof corrections are closed. CI114 has
qualified the hosted ADR0144 candidate; independent review 4 reported no
blockers. The final public candidate's scoped proof and exact-commit report
remain pending, and the subsequent ADR0146 work remains separate from any full
W5 acceptance.

The product CLI, MCP, canonical graph vocabulary, model artifacts, corpus,
task catalog, gold labels and held-out population remain unchanged. Historical
journals and result-v2 artifacts retain their original bytes and interpretation.

## Admission evidence

The supported baseline runner reads publication pins independently before and
after execution. Its evaluator precheck validates the actual policy against
the token-issued pin, rather than accepting a structural lookalike or serialized
permission decision. The task must remain in the calibration split and match
the pin's generation before candidate access. A declared
private binding can be denied even when its content is absent from the public
publication: the pin-bound policy digest covers the declaration. An unknown
binding or missing public binding does not supply evidence of a privacy denial.

Admission also checks an object-bound factory seal over the pin's fields and
readback-adapter identity. Copying a dataclass or changing a digest does not
transfer issuance. The runner and arm context freeze per-backend policy digests
before execution. This seal does not add universal live-policy discovery to
generic publication adapters; supported readers retain their own authorization
checks. A published binding absent from the policy remains undeclared, rather
than inheriting an authorization-denial label.
The historical pin-level `denied_bindings` fallback may still record an
unresolved-policy code for such a binding. That raw provenance field does not
classify the current admission decision or authorize access.

Any authorization denial refuses the entire requested mixed scope before the
arm callback, native process or fusion can execute. Public subsets are not
silently substituted. The envelope records the requested selection, actual
backend, omissions and reason, together with `evaluator_precheck` and
`backend_policy_enforcement_observed=false`. A correct precheck refusal does
not demonstrate backend enforcement. Body restrictions apply to body requests;
public feed metadata retains its previous capability outcome.

Admission wall time is work, including when execution is blocked. It belongs
in observed elapsed time and is disclosed as a component of that elapsed time.
It must not be added a second time when reading a report. Database scan bytes
remain unknown. A blocked native invocation has no process stdout or file-read
work; its issued capture still binds the zero-work record to that execution.

Current file grading uses `cloe-w5-file-grading-v2`: an actual refusal is
considered before arm applicability. Explicit v1 evaluation preserves the
historical precedence. New journal grade events disclose their policy version;
an old event without that field is reported as not recorded, never inferred
to have used the current version.

Under this current policy version, cal-21/22's policy-declared mailbox denial is
therefore refused before applicability is considered. Cal-16/17 are public
feed metadata tasks and retain the existing non-body capability outcome. These
are evaluator-policy results; `backend_policy_enforcement_observed=false`
remains explicit and no backend enforcement or private-body access is claimed.

## Literal scope and matching

Evaluator prefixes admit canonical path segments or exactly one trailing `/`.
The trailing slash means descendants only. `shared/` excludes a file named
`shared`, the sibling `shared2`, and every case or Unicode variant. Percent,
underscore and backslash are literal characters rather than query operators.
Whitespace padding, traversal and repeated separators are refused.

The lexical product envelope can normalize `shared/` to `shared`. Strict
baseline correspondence permits that particular normalization only after
revalidating actual projection inputs, their policy and complete manifest
against the accepted publication. A selected file exactly named `shared`
disproves equivalence and leaves a visible correspondence refusal. A boolean,
matching string or deserialized witness cannot prove the scope.

Current-observation matching folds only ASCII A–Z, preserving other code
points. PostgreSQL uses fixed `translate`/`strpos` expressions with C collation
over the same four fields as the Python predicate. Metadata validation and
selected-binding/path filtering precede pagination. Every matching malformed
metadata row must remain visible to validation, including beyond the retained
page. Incomplete pages and traversal limits propagate omissions and partial
capability to graph envelopes; an unexpected out-of-scope locator fails closed.

## Retained artifact report

The tools-only entry point is `tools/retrieval_semantic_pair_report.py`:

```sh
python3 tools/retrieval_semantic_pair_report.py \
  --journal 1=/owned/evidence/w5-semantic-g1 \
  --journal 2=/owned/evidence/w5-semantic-g2 \
  --result 1=/owned/results/g1/result-v2.json \
  --result 2=/owned/results/g2/result-v2.json \
  --output /owned/analysis/paired-report.json
```

Each journal directory contains its six original members. The reader checks
their exact lengths/digests against the V2 references, matching attempt,
generation, declared input and planned population. It joins cells by recorded
generation/task/arm/repetition identity. Array order is not identity. Duplicate,
foreign, malformed and tampered records refuse the report. Valid incomplete
evidence remains a gap instead of being discarded or relabeled as success.

Inputs retain the canonical V2 limits: 4 MiB per result and 8 MiB aggregate.
Journal members and generated report output have their own explicit bounds.
Files must be regular owned artifacts; symlinks and overwrite of existing
output are refused. No runtime, live graph, model, subprocess query or network
access is performed by the report builder.

The versioned output preserves:

- source member/result digests and generation-specific declared plans;
- whole, supported, graded and eligible populations with reason categories;
- recorded observations, grades, refusal/absence flags and unknown values;
- actual file/span metrics, exact-rational fusion records and byte-work layers;
- three fixed arm comparisons: FTS/exact, FTS/hybrid and exact/HNSW;
- each comparison's stored values and explicit missing/comparability gaps.

Planned `not_run` cells have their own reason category. Their per-cell
classification remains separate, including any earlier safety or absence rule;
the reason category does not relabel them as observed unsupported executions.

There are no deltas, win/tie/loss decisions, superiority aggregates or rescoring.
Safety and absence outcomes are not relevance measurements. ANN exact-reference
recall is a correctness measurement distinct from task relevance. Generation 2
remains document-only with zero vector queries; its whole population is not
removed from denominators. The native cal-07 retained 495,781-byte observation
and unaccepted 65,536-byte proposed criterion remain separate facts.

The retained pair13-analysis4 report code analyzes the old 648-cell,
216-comparison calibration source. Its report digest is
`90b2a2a82abe25b1e08a6c0e3737c70908a1d0293c54659511c4ab40c0de97fd`.
It does not rescore the current source or establish scientific acceptance.
Seven retained `not_run` cells now have their own reason category. Whole,
supported, graded and eligible populations remain unchanged.

Hashes establish consistency with the supplied artifacts. They do not establish
trusted origin, live publication authority, current-source calibration, scientific
acceptance or full W5 completion. Every acceptance field remains false.
`read_report` performs bounded structural validation; it does not rehash the
source artifacts or recompute denominators. Rebuild from the original journal
and result inputs when checking a derivative report against its sources.

## Verification boundary

Exact unit owners cover admission, grading precedence, literal matching/scope,
policy versioning and artifact-report refusal paths. Containerized integration
owners use disposable publisher-backed SQLite/PostgreSQL publications and
temporary artifact IO. Their commands and results belong in the milestone exit
record. Scoped `--no-coverage` proof does not quantify over the complete hosted
population or establish the 87%/82% coverage aims. Complete local suites,
optional model execution and builds require their separate current authority.

The pre-review scoped cohorts recorded the initial 255 unit and 45 distinct
integration cases plus the completed grant cohort's 5 unit and 4 integration
passes, for 260 unit and 49 distinct integration cases across those historical
cohorts. These are ADR0146 predecessor source-proof checkpoints, not proof of
the ADR0144 qualified implementation. Reviews 2 and 3 are closed with findings;
review 3's narrow cross-reader and activation-proof corrections are closed.
Resulting cohort 9 census
`b589d41bf2fb3a77e8d23db46e9e11e9f1169f0f7ce8432e9e03624139c00d76` passed 342
unit and 31 core integration cases with static, hygiene and privacy findings at
zero. This is bounded evidence, not whole-candidate acceptance. Independent
review 4 reported no blockers; the final public candidate's scoped proof and
exact-commit report remain pending. Retained-
Python static4, checks4 and scanner3 remain bound to the historical source census
`9fcdad0d1cd3283f52586796a6b651fbf6835fa8182a490f78e560a70c4d85bb`. The
complete local unit, integration, smoke, staging, system and combined suites,
and local Python coverage, were intentionally unselected. Independent review 4
reported no blockers for the calibration source; final publication review and
the ADR0147 activation predicates remain prerequisites. CI114 has already
qualified the hosted ADR0144 candidate.
Optional attempt 15 is complete with code 0 and clean custody, is spent, and
has no automatic attempt 16. A conditional CI115 attempt-1 binder under
[ADR0147](../adr/2026/11/0147-w5-observed-operation-and-paired-cost-disclosure-staging-campaign.md)
is prepared with four grant owners, but no remote trigger or application start
28 has occurred. No new model, body or input representation, dependency,
runtime build, new push or full-W5 acceptance is implied. At publication, the
introducing commit must record final review and fresh proof after its traversal,
pin-issuance, classification and compatibility fixes.


## CI114 qualification and observed-context continuation

[CI114 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/41774180008)
qualified staging `14f9d4e250e2cdcd0f0af89049dd36aeb048b728`, tree
`730e1368310b5466ddae3992b49add06d720875f`. All nine jobs and independently
validated same-attempt measured/abrupt, native AMD and five-scenario system
evidence pass. CI114 consumed one actual application start, bringing cumulative
actual consumption to 27; ADR0145 is spent. Unit coverage is 59,918/68,081
statements and 19,430/22,346 branches; measured integration is
61,000/68,081 statements and 18,086/22,346 branches. Hard gates pass. Exact
branch counts remain 12 unit and 238 integration below 87%/82%.

The separately predeclared same-model current-source calibration 14 completed
648 cells and 216 descriptive comparisons, with whole/supported/graded/eligible
counts of 648/339/285/264. Generation 1 produced 80 document and 4 query
embeddings; Generation 2 produced 80 documents and observed zero-query
inference. These counts were independently verified from retained raw model
bundles; paired-evidence V1 does not record the query count. All 36 baseline
safety refusals are correct. Eighteen vector/fusion refusals remain ungraded,
and 12 HNSW observations retain `not_run/index_not_selected`. No ANN selection,
scientific utility, held-out acceptance or full W5 closure is inferred. No new
model, body or input representation, dependency, scientific criterion or main
promotion is claimed. Optional calibration 14 is spent and immutable; its
original journals/source pins remain immutable. The descriptive paired-report
digest is
`449d466006fdb97191ab81e4bfd74fab1315cca98316fb38833fefa4c5421410`.

[ADR0146](../adr/2026/11/0146-w5-observed-operation-and-paired-cost-disclosure.md)
advances actual operation/work capture, opt-in paired-report V2 context/cost
disclosure and adjacent identity/state proof as one connected technical batch.
Its implementation evidence is bounded and is not final public W5 acceptance by
CI114. Old grade-only unknowns remain unchanged. Broader input/body
representation, scientific criteria, held-out evaluation, production admission
and main/release promotion remain separate. Review 3's narrow cross-reader and
activation-proof corrections are closed; independent review 4 reported no
blockers. Optional attempt 15 is complete and spent, with no automatic attempt
16. The conditional CI115 attempt-1 binder is prepared under ADR0147 but has
not been remotely triggered or spent; no start 28, new push or new public
campaign has occurred.

## Optional-15 observed-context calibration and CI115 preparation

Optional attempt 15 completed with exit code 0 and clean custody. Its calibration
source binding is
`21fa1ee4bcbbda78c41e3c29ec62f6d21a698396effe5ced3eed28e2d700bfee`; candidate
head `14f9d4e250e2cdcd0f0af89049dd36aeb048b728` and dirty-source state are
disclosed explicitly. The pre-calibration scoped proof recorded 347 unit and 34
core integration cases with static, hygiene and privacy findings at zero; this
is not final metadata qualification.

The run covered 12:32:19–12:40:37 UTC and recorded 621+27 = 648 cells and
216 comparisons. Of 216 actual vector-operation records, 24 completed, 12 were
`not_run`, 162 unavailable and 18 refused. Denominators remain 648/339/285/264;
baseline evidence includes 36 safety-correct cases, 18 vector/fusion refusals
and 12 HNSW `not_run/index_not_selected` cases. Raw Generation 1 contains 80
documents, 4 queries and 84 embeddings; Generation 2 contains 80 documents,
0 queries and 80 embeddings, using public data and the same approved BGE
profile. No completed ANN, performance, scientific, held-out, full-W5 or
production acceptance is inferred.

The retained report is 3,703,442 bytes with SHA-256
`3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f`; it has no
private paths. No application or SDK build or model-wheel acquisition occurred.
One pgvector 0.8.7 materialization ran on native ARM. Calibration proved the
writer-to-journal-to-ResultV2-to-V2-reader composed seam. The final artifact
analysis rejected all six tampered report derivatives. This is bounded
source/report-integrity evidence only.

The optional-15 native HNSW provenance observation records 72 HNSW operation
records, including 24 actual per-binding `HnswProvenance` records. All 24 have
raw state `not_run`; EXPLAIN executed and cleanup was verified for all 24, with
at most 63 plan nodes and zero expected ANN-index-selected cases. This closes
the not-run provenance-shape observation without claiming completed ANN or
performance.

The CI115 binder is conditional ADR0147 preparation: attempt 1 would be native
AMD start 28 after 27, but it is not triggered or spent. CI114 remains the
latest green hosted predecessor. Final scope combines W5 with the grant and
refusal owners; final public-candidate
scoped proof, publication disposition and exact-commit report remain pending.
Exact final counts belong in the phase commit and candidate report. All complete
local Python suites, coverage and
application builds remain intentionally unselected, and the soft 87%/82% target
remains pending hosted qualification.
