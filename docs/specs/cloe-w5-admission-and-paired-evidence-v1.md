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
evidence; it is not a same-census rerun. Final independent review is a
publication prerequisite. Hosted CI114 qualification remains separate.

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

The pre-review scoped proof records the initial 255 unit and 45 distinct
integration cases plus the completed grant cohort's 5 unit and 4 integration
passes, for 260 unit and 49 distinct integration cases across cohorts.
Retained-Python static4, checks4 and scanner3 pass against source census
`9fcdad0d1cd3283f52586796a6b651fbf6835fa8182a490f78e560a70c4d85bb`. The
complete local unit, integration, smoke, staging, system and combined suites,
and local Python coverage, were intentionally unselected. CI114, final
independent source review and the activation predicates for ADR0145 are
publication prerequisites; no new model/optional attempt or runtime build is
implied. At publication, the introducing commit must record final review and fresh
proof after its traversal, pin-issuance, classification and compatibility fixes.
