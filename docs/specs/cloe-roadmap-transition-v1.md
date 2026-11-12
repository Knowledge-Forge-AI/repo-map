# Common Lore Index transition and v0.1.0 delivery

## Accepted direction

The operator authorized advancing the reviewed remaining-roadmap proposal on
2026-10-29. The selected identity is Common Lore Index (CLOE), distribution
`common-lore-index`, preferred executable `cloe`, home selector `CLOE_HOME`,
default `~/.cloe`, and base/local configuration suffixes `.cloe.toml`
and `.local.cloe.toml`. These are target surfaces, not a claim that the full
rename has shipped. ADR0118 selects `common_lore_index` and installed ownership;
ADR0123 defines their coordinated source cutover and finite compatibility. Preserve the current license and
Samuel Leighton Lair <sam.lair@knowledge-forge.ai> as public commit identity.

## Starting point and working custody

Public main is v0.0.3 at `5ad00d162ad8a04430874275246a53227578c533`, qualified
by [CI87 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40779161422).
All nine jobs and the retained same-attempt system/staging contracts pass;
Python unit and integration coverage meet the two-point margin. Core
qualification does not establish optional pgvector usefulness/admission,
hosted ARM/Windows support or deployment acceptance. ADR 0105 retains the
informational treatment of inherited Debian issues.

The qualified public tree is the implementation baseline for compatibility
preparation. Preserve the private checkout's concurrent tracked/untracked work
and the three-way reconciliation map. This does not declare private-line
reintegration complete. Resolve those differences before a broad namespace
move; do not reset or mirror public content over protected private work.

## Dependency-ordered milestones

| Workstream | Outcome and acceptance |
|---|---|
| W0 | Reconcile release evidence, current docs and private/public implementation custody; preserve historical reports and private-only material. |
| W1 | CLOE rebrand and compatibility: config/home, packaging, commands, import/resource ownership and supported migration/recovery. |
| W2 | Query modes, privacy and publication-bound text projection, representative tasks, baselines and grading before tuning. |
| W3 | Useful measured PostgreSQL native FTS with identifier/phrase policy; evaluate optional trigram matching within extension admission. |
| W4 | Intent-aware navigation and compact context with valid serialized-byte bounds, provenance, omission accounting and advisory freshness. |
| W5 | Useful optional pgvector and measured fusion after the lexical baseline, plus the named-workload JSONB disposition. |
| W6 | Bounded Rust extraction and quality/performance pilot through retained Python semantics and parser-helper admission. |
| W7 | Measure and govern actual expensive work; qualify first useful Local/Server and mixed-material experiences. |
| W8 | Exact-candidate installed/release qualification and an evidence-backed v0.2.0 search-engine decision. |

W6's dependency-free prerequisite is assigned
`REPOMAP-CLOE-RUST-FOUNDATION1` under
[ADR0154](../adr/2026/11/0154-extractor-capability-receipt-foundation.md).
This reserves the specific `CLOE-RUST-FOUNDATION` family. Its implementation
does not select a parser or close W6; parser/runtime adoption remains a
separate decision. This prerequisite is accumulated into the next substantial
milestone before public CI.

The operator selected the bounded container-side Rust parser class on
2026-11-05. `REPOMAP-CLOE-RUST-PILOT1` reserves the specific `CLOE-RUST-PILOT`
family for the resulting ADR, isolated source helper, retained semantics and
native component evidence. This class selection is not dependency adoption
or W6/release acceptance. The reviewed foundation remains its prerequisite;
the next publication accumulates this work into a substantial milestone.

Its resulting design is accepted for implementation in
[ADR 0155](../adr/2026/11/0155-isolated-rust-source-parser-pilot.md) with the
[Rust parser pilot contract](cloe-rust-parser-pilot-v1.md). Source
implementation, ARM component execution and the AMD gating step remain pending
behind that contract's gates. Independent review corrections cover Rust
attribute association, the closed D12/Rust workflow contract, per-platform
scenarios and residue checks before publication; no native acceptance follows
from the design disposition.

W1 starts with [configuration compatibility](../ops/cloe-config-compatibility.md)
under [ADR 0109](../adr/2026/10/0109-cloe-configuration-compatibility.md).
Its usable new-format loader and inert filename planner are a preparatory
milestone; full rebranding and live migration remain subsequent work.

CI92 qualified the configuration compatibility/recovery milestone on staging
`bec838a210f3ffea84986ae85986e4081b2e8291`, with all nine jobs passing and
the retained same-attempt staging obligations verified. The next W1 milestone,
[ADR 0112](../adr/2026/10/0112-cloe-runtime-configuration-producer.md), enables
explicit CLOE runtime setup and existing-family detection, with guarded targets,
dry-run replay and connected configuration/mount readback. It retains legacy
empty-home defaults and is not the broad namespace/default-home/data migration.
CI93 attempt 1 qualified that runtime-setup candidate at
`433a2edf89284f71f10996d20c88bcf3e311c9de`, including all nine jobs and the
retained same-attempt staging/system obligations. That result does not qualify
the local successors described below.

[ADR 0114](../adr/2026/10/0114-cloe-config-migration-apply-recovery.md) adds
explicit, confirmed configuration filename apply, rollback and finalize for an
owned private home. It uses durable journaled backups, crash recovery and
drift refusal. It does not change the default home, namespaces or data. Its
hosted qualification is now established by CI95 attempt 1 on staging
`ed23f6fff49b7796ee70e50e29d6e4db4779d6fe`, together with the W0 runner recovery
and its CI94 corrections. All nine jobs passed. Retained same-attempt smoke/M/A
and system contracts validate against independently derived committed source;
unit coverage is 88.1/87.6 and measured integration coverage 90.1/82.1, exceeding
the hard floors by at least two percentage points. This does not qualify later
local successors or perform a main promotion.

[The W0 custody audit](cloe-development-custody-v1.md),
REPOMAP-CLOE-CUSTODY1, preserves private work and distinguishes public successor
fixes from meaningful unincorporated harness work. It restores command-contract
characterization, the nonempty ICU-version assertion and accurate current
Local/Server descriptions. The subsequent
[ADR 0115](../adr/2026/10/0115-bounded-runner-failure-diagnostics.md) source slice
integrates typed first-cause retention, safe discovery diagnostics and guarded
cleanup, closing that mandatory W0 follow-up with scoped proof and independent
review. Preserved private experiments retain their W2/W5 owners; blanket
private-line reintegration and hosted successor qualification are not implied.
[ADR0118](../adr/2026/10/0118-cloe-installed-ownership-and-safe-home-selection.md)
settles the coordinated W1 distribution/import/resource/command ownership direction.
Safe default-home selection and current resource-ownership preparation form the
milestone qualified by CI97 attempt 1 on staging
`b90fa8e9c8126be2eac73620001c3869b2cf8e33`, including its two eager-facade
compatibility corrections. All nine jobs and retained same-attempt smoke/M/A
and system contracts pass; unit coverage is 88.0/87.6 and integration90.1/82.2,
meeting both two-point margins. The canonical distribution/import/resource/entrypoint
cutover remained atomic and subsequent at that checkpoint. Current scoped proof
and hosted successor qualification remain distinct.

[ADR0121](../adr/2026/10/0121-installed-ownership-diagnostics-and-service-upgrade-compatibility.md)
adds the next two-part upgrade prerequisite: explicit categorical installed-owner
diagnostics and exact persisted-service module recognition/reinstallation recovery.
The ordinary identity payload stays stable; legacy definitions never become
healthy or reactivate during failed uninstall. This is source preparation for
the atomic move, not installed-package qualification. The
[consumer inventory](../ops/cloe-installed-upgrade-compatibility.md) preserves the
documented configuration-migration Python API and names the remaining facade,
module-path projection and disposable install-order obligations. No blanket
no-facade policy or historical-authority rewrite is accepted.

Keep SQLite Local useful without Server or enrichment dependencies. Search
projections are derived from accepted captured material with privacy and
publication identity; they are not another graph authority. Current MCP
readers remain source-blind. Any body-text query gets an explicit capability
contract; even locator-only matching can expose private information.

Compare competent native tools, existing graph behavior, native FTS and graph,
compact context, then vectors/fusion on the same selected material and tasks.
Include correctness and failed attempts in cost results. Define numeric
criteria from the baseline before held-out evaluation. No fixed savings claim
or superiority follows from another project's marketing or a working SQL query.

OpenSearch/Elasticsearch implementation, public corpus services, Cloud alpha,
GUI/federation, a broad language rewrite and unqualified Windows claims remain
outside required v0.1.0 delivery. Versions below v0.1.0 remain GitHub source
previews; package-manager publication starts no earlier than v0.1.0.

## Coordinated W1 namespace milestone

CI98 attempt1 qualified staging `6d818ad6d43d38d47c64b8c474c2b64b853f631a`,
including all nine jobs and retained same-attempt contracts. Unit coverage was
88.1/87.7 and measured integration coverage90.1/82.2, meeting both two-point margins.
That result qualifies the prerequisite, not the successor package cutover.

[ADR0123](../adr/2026/10/0123-coordinated-cloe-package-and-namespace-cutover.md)
coordinates canonical source, distribution, resources, commands, finite documented
compatibility and installed ownership proof. Its strict source/document projection
preserves every historical authority and numerical debt ceiling. Local preparation
and exact source-edge checkpoints are combined with current consumer work before
one larger public campaign. Hosted qualification of this successor remains pending.
Live home/service migration, package-manager publication, repository rename and
release promotion remain separate. W2 follows the accepted dependency order after
this W1 milestone is qualified; preserved private experiments are not automatically
accepted or overwritten.

## W2 retrieval contracts, projection reference, and calibration baseline

Following CI100 qualification of the W1 namespace cutover at `970d7dc9f6b895a210953e38bccb54cc839ccf75`,
`REPOMAP-CLOE-RETRIEVAL1` implements the W2 milestone under accepted
[ADR0127](../adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md),
[cloe-retrieval-evaluation-v1.md](cloe-retrieval-evaluation-v1.md), and
[cloe-retrieval1-exit.md](../../tools/ci/cloe-retrieval1-exit.md). It delivers
internal six-mode query envelopes (`cloe-retrieval-query-v1`), the bounded
in-memory captured-input text projection reference (`cloe-captured-text-reference-v1`),
the public-safe `mixed-v1` multi-source evaluation corpus across two generations
and 36 frozen tasks (24 calibration, 12 held-out), real native (`git grep --no-index`),
current-graph (SQLite Local and PostgreSQL), and reference adapters, and the
declared 24-task calibration baseline plus baseline-derived future criteria
proposal. The12-task held-out split remains unexecuted for W3. [CI101 attempt1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/41204249885)
qualifies exact staging `ae636963abcf3c952150bb738b122464cec9399f`: all nine jobs,
same-attempt staging M/A and system contracts pass. Unit88.1/87.4 and measured
integration90.1/81.9 meet the hard gates; the requested integration82% branch
target is11 covered branches short and stays a W3 regression-coverage objective.
W3 must carry actual query modes/fallbacks/surfaces into summaries before treating
metadata-intent scores as metadata retrieval. Existing attempts remain immutable.

## W3 native lexical, metadata parity and evaluation evidence milestone

[ADR0129](../adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md)
and [the lexical operator guide](../ops/lexical-search.md) deliver opt-in
PostgreSQL native lexical build/query/revoke, owner-fenced derived storage and
request-pinned public metadata navigation parity. The source also closes empty
resolved-scope misclassification and preserves actual modes, surfaces, fallback,
omissions and provenance in evaluation v2. Historical attempt7 has a separate
raw-journal-bound v2 reprojection; its original artifacts remain unchanged.

Corrected-source retained W3 calibration `w3-calibration-attempt-2` has24tasks ×6arms ×3repetitions:432query
observations,144graded slots and 1010journal records, bound to its pre-query
source/input archive. It records zero execution failures or divergent tasks;
refusal/unavailability and weak scores remain visible by cell. These observations
do not establish superiority or accept proposed future criteria. All12held-out
tasks remain unexecuted, behind a separate source/criteria acceptance gate.

[ADR0130](../adr/2026/10/0130-lexical-milestone-staging-campaign.md) binds one
review-ready staging publication and automatic CI102attempt1. See the
[phase exit](../../tools/ci/cloe-lexical1-exit.md) for resulting-state proof and
the W3 hosted qualification section below for the accepted CI104 result.
Optional trigram, vectors/fusion, W4 compact context, Rust and release/installed
qualification remain subsequent roadmap work. No live deployment is performed.

W3 retains its first successful observation at its original source and the
independent-review corrections at attempt2; neither is repinned. Before future
criteria acceptance, disposition the native comparator output above the proposed
65,536-byte ceiling and the incumbent PostgreSQL graph absent-answer discrepancy.
That W3 milestone qualifies lexical lock expressions, not all large-ID
publication. ADR0162's later W7 work separately addresses the staged publisher
with high-ID row exclusion and admission guards; low IDs retain namespace19042.

## W3 hosted qualification and W4 selection

Automatic CI102 and successor CI103 were classified `EXECUTED_FAIL` and repaired
under [ADR0131](../adr/2026/10/0131-ci102-compatibility-repair-and-twentieth-native-amd-attempt.md)
and [ADR0132](../adr/2026/11/0132-ci103-measured-child-repair-and-successor-qualification.md).
CI104 attempt 1 passed all nine jobs and retained same-attempt staging M/A and
system contracts on exact staging `7babd887cb6b46c2791a22d57baddcdc24914463`, and
the parent accepted that qualification: unit passed 14,947 tests at 88.0/87.1
statement/branch coverage, and the measured staging integration lane passed 1,961
tests at 89.8/81.4. Both hard coverage gates (85/85 unit, 80/80 integration) are
met; the 82.0% staging integration branch margin remains ~0.6 percentage points
short and carries forward as a W4 real-boundary coverage objective. CI104
qualifies that W3 candidate only: it does not accept proposed evaluation
criteria, execute the 12 held-out tasks, admit optional trigram indexing, deploy
live, promote staging to `main`, or qualify later commits.

With W3 qualified on staging, W4 (`REPOMAP-CLOE-CONTEXT1`) is selected as the
next milestone, with architecture and specification authored in design phase
`REPOMAP-CLOE-CONTEXT-DESIGN1` under proposed
[ADR0133](../adr/2026/11/0133-intent-aware-navigation-and-bounded-context.md)
and [cloe-intent-context-v1.md](cloe-intent-context-v1.md):

- **Epic A (intent-aware deterministic navigation):** explicit caller-declared
  `NavigationIntent` (`definition`, `implementation`, `tests`, `docs`,
  `messages`, `general`), six-tier lexicographic ranking (`cloe-intent-rank-v1`)
  with byte tie-break (`cloe-intent-tiebreak-v1`), versioned affinity and
  Python test-subject classification (`cloe-intent-tables-v1`) without a
  universal test penalty, isolated context direct-evidence roles
  (`CONTEXT_DIRECT_EVIDENCE_ROLE_V1`), ambiguity preservation, and complete-scan
  enforcement while keeping MCP `repomap_navigation_search` unchanged.
- **Epic B (bounded compact context):** `cloe-compact-context-v1` packets via
  `cloe ops context-pack` and `build_compact_context`, enforcing hard serialized
  UTF-8 byte budgets (`4,096..65,536`, default `16,384`) with skeleton echo
  compaction (`skeleton_compaction_v1`), strict rank-prefix admission
  (`seeds_then_neighbors_v1`), `_destination`-preserving location deduplication,
  stored `canonical_edges` relation support, explicit PostgreSQL neighborhood
  non-support (`expansion_backend_unsupported`), and separate storage-work and
  SQL-statement caps (`MAX_SCAN_UNITS = 8`, `MAX_SQL_STATEMENTS_SQLITE = 36`,
  `MAX_SQL_STATEMENTS_POSTGRES = 12`).
- **Epic C (reusable source selection and optional advisory freshness):**
  caller-held `cloe-source-selection-v1` records via `cloe ops context-select`
  (storing no filesystem roots and revalidated against live config and accepted
  publication state on every call) and opt-in bounded structural freshness
  observations (`cloe-advisory-freshness-v1`) with root-anchored no-follow
  descriptor traversal and structural-only file/span checks,
  leaving source excerpts deferred out of W4.

`REPOMAP-CLOE-CONTEXT1` ([exit report](../../tools/ci/cloe-context1-exit.md),
[operations guide](../ops/compact-context.md)) implements the accepted W4
architecture across SQLite Local and PostgreSQL Server Engine with 59 scoped
unit tests, 37 containerized integration tests, and the 20-task × 7-arm ×
3-repetition `context-v1` calibration observation (`w4-context-calibration-attempt-1`,
420 query observations, `held_out_queries_executed == 0`). Neither the 12
`mixed-v1` nor the 10 `context-v1` held-out tasks are executed or accepted, and
one later hosted qualification campaign remains gated on parent review
disposition and separate parent authority.

## W4 qualification and W5 design selection

[CI106 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/41382023561)
qualifies staging `a300dc82d317ecde5646e4e90717b5eaa4aee8db` after the CI105
import-cycle and lineage-regression corrections. All nine jobs and retained
same-attempt staging M/A/system contracts pass. Unit: 15,271 passed, 40 skipped,
59,851/68,080 statements and 19,378/22,346 branches. Integration: 2,004 passed,
12 skipped, 60,988/68,080 statements and 18,075/22,346 branches. Hard gates pass;
the desired 87%/82% branch margins remain 64 unit and 249 integration branches
short at that denominator and carry forward into W5. There is no main promotion.

Earlier W4 producer counts and calibration descriptions above are historical
checkpoints. Final local proof is 404 scoped unit and 71 containerized integration
cases with no project Python coverage. The retained actual functional journal
is `w4-context-functional-attempt-7`, 420 observations with zero held-out tasks,
at its own source binding. It is not repinned to the CI106 import correction,
and neither it nor green core CI accepts scientific criteria or optional vectors.

W5's model-independent foundation continues under accepted
[ADR0137](../adr/2026/11/0137-model-independent-w5-evaluation-foundations.md)
and [the foundation contract](cloe-w5-foundations-v1.md). The exact route-A
model-dependent path is separately accepted under
[ADR0136](../adr/2026/11/0136-w5-local-embedding-and-fusion-evidence.md);
neither record asserts W5 completion, learned usefulness, held-out results or
production qualification. The `REPOMAP-CLOE-SEMANTIC1` milestone retains its
verified local enrichment, vector/fusion comparison and named-workload JSONB
disposition boundaries. Existing synthetic/private proposals remain evidence
only, not accepted models, corpora, labels or thresholds.


### Model-independent W5 continuation

REPOMAP-CLOE-SEMANTIC-FOUNDATION1 proceeds under
[ADR0137](../adr/2026/11/0137-model-independent-w5-evaluation-foundations.md)
and [the foundation contract](cloe-w5-foundations-v1.md). The operator renewed
roadmap continuation on 2026-11-02. Dependency-free representation/provenance,
file-level fusion/grading and disposable named JSONB evidence remain within
this foundation. The separately accepted ADR0136 route does not make this
foundation a model result: learned usefulness, held-out criteria and full W5
completion remain separate. No public campaign is scheduled for a partial
foundation checkpoint.

## W5 evaluator milestone

The bounded evaluator/generator/fusion and named JSONB milestone has retained
two-generation public calibration within its declared capabilities. See the
[operational exit](../../tools/ci/cloe-semantic1-exit.md) and ADR0138 for the
separate one-use staging campaign. Generation2 has document-only inference and
an explicit unsupported metadata-vector query. Relational JSONB behavior stays
in place. CI109 attempt 1 qualified the bounded evaluator milestone at staging
`e012f0180b7e2b85112e46a361fc4cd7fcd66472`, with all nine jobs and retained
same-attempt staging/system contracts passing. Unit coverage is 87.9/86.7 and
measured integration coverage is 89.6/80.9: hard gates pass; the 87%/82% branch
headroom aim remains open. The next connected W5 batch under ADR0141
addresses baseline publication correspondence, current-generation PostgreSQL
comparison and related provenance/privacy proof. Held-out criteria, broader
utility and production model/pgvector/schema/index admission remain open; W5 is
not complete. No successor source or public-main promotion is qualified here.


The ADR0141 correspondence continuation retained a fresh 648-cell calibration,
backend-specific publication witnesses and current-run raw-observation comparison.
Its original journals and supplementary V2 results remain separately bound.
Absent-mailbox safety expectations and three normalized-FTS-prefix correspondence
records remain explicit measured limits; no scientific aggregate is accepted.
[ADR0142](../adr/2026/11/0142-w5-correspondence-milestone-staging-campaign.md)
bounds the one-use CI110 staging campaign for this connected milestone.
At that historical checkpoint, hosted qualification of the successor and full
W5 remained pending.

[ADR0143](../adr/2026/11/0143-unpublished-staging-campaign-ordinal-reconciliation.md)
transfers the unused ADR0142 allocation to CI113 after three unrelated Dependabot
promotion-policy refusals advanced the workflow counter. No candidate was pushed
for CI110 and no application start was added. The implementation commit and all
calibration/formatting evidence remain intact; only forward campaign metadata
and its owning tests change.

## W5 correspondence qualification and evidence closure

[CI113 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/41726594941)
qualified staging `228716d8bfa2858d0d1c31cf39af0636fa7e855d` with all nine jobs
and verified same-attempt measured/abrupt, native and five-scenario system
contracts. Its single application start brings the actual cumulative count to 26.
The 87%/82% branch-margin aim remains 12 unit and 233 integration branches short
at 22,346 branches. No rounded display, scoped proof or calibration closes it.

The connected technical batch under
[ADR0144](../adr/2026/11/0144-w5-admission-scope-and-paired-evidence-closure.md)
addressed admission and refusal/applicability ordering, literal path/matching/page
correspondence and added traceable paired-artifact reporting. It preserves the
frozen tasks, golds, old journals and source bindings. New scientific criteria,
held-out evaluation, broader model/input choices, production admission and full
W5 remain separate. At that selection checkpoint, this direction did not qualify
successor code or promote public main.

## W5 admission, scope and paired-evidence implementation

The evaluator-only continuation selected by ADR0144 is now implemented in the
public candidate tree. Admission recomputes from a token-issued publication pin
and its matching frozen policy, requires the calibration split and exact
publication generation, and refuses a denied mixed scope before candidate or
other-arm access. Policy-declared denials, observed denials, undeclared
selections and declared-public-but-absent bindings remain distinct; no privacy
or safety result is inferred from a task, gold, alias or caller-supplied
decision. Current policy-v2 grading evaluates the actual cal-21/22 refusal
before arm applicability, while cal-16/17 remain public feed metadata with
their existing non-body capability outcome.

The ADR0146 predecessor source proof includes historical checkpoints: the
pre-correction frozen 5f66 census recorded 315 unit and 26 core integration
cases with full retention and scanner checks, while the 620c census recorded
328 unit and 29 core integration cases. The earlier 260-unit/49-integration
scoped cohort accounting is historical as well; none of these checkpoints
qualifies the ADR0144 implementation. Reviews 2 and 3 are closed with findings.
Resulting cohort 9 census
`b589d41bf2fb3a77e8d23db46e9e11e9f1169f0f7ce8432e9e03624139c00d76` passed 342
unit and 31 core integration cases with static, hygiene and privacy findings at
zero. This is bounded evidence, not whole-candidate acceptance. Review 3's
narrow cross-reader and activation-proof corrections are closed. The immutable
source bridge preserves prior source identity evidence; independent review 4
reported no blockers, while final public-candidate scoped proof and the exact
commit report remain pending. Retained-Python
static4, checks4 and scanner3 remain bound to the historical source census
`9fcdad0d1cd3283f52586796a6b651fbf6835fa8182a490f78e560a70c4d85bb`, with no
threshold, denominator or debt change.

The retained pair13-analysis4 report code analyzes the old 648-cell,
216-comparison calibration source. Its report digest is
`90b2a2a82abe25b1e08a6c0e3737c70908a1d0293c54659511c4ab40c0de97fd`.
This is descriptive analysis of immutable historical evidence, not rescoring,
current-source science acceptance, or full W5 acceptance.

At publication, the introducing commit must record final review and fresh proof
after the traversal, pin-issuance, classification and compatibility corrections.
CI114 has qualified the hosted ADR0144 candidate. Independent review 4 reported
no blockers, while the final public candidate's scoped proof, exact-commit
report and publication disposition remain open. The ADR0145 grant is spent.
Optional attempt 15 is now complete with code 0 and clean custody; it is spent
and has no automatic attempt 16. A conditional CI115 attempt-1 binder under
[ADR0147](../adr/2026/11/0147-w5-observed-operation-and-paired-cost-disclosure-staging-campaign.md)
is prepared with four grant owners, but no remote trigger or application start
28 has occurred. The resulting calibration is bounded evidence, not publication
or full W5 acceptance. No new model, runtime/application build, complete local
suite or local coverage follows from this scoped proof.
Complete local unit, integration, smoke, staging, system and combined
populations remain intentionally unselected, and public-main promotion remains
separate.


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
Its implementation evidence is bounded and is not accepted as final public W5
evidence by CI114. Old grade-only unknowns remain unchanged. Broader
input/body representation, scientific criteria, held-out evaluation, production
admission and main/release promotion remain separate. Review 3's narrow
cross-reader and activation-proof corrections are closed; independent review 4
reported no blockers. Optional attempt 15 is complete and spent, with no
automatic attempt 16. The conditional CI115 attempt-1 binder is prepared under
ADR0147 but has not been remotely triggered or spent; no start 28, new push or
new public campaign has occurred.

## Optional-15 observed-context calibration and CI115 preparation

The optional-15 calibration completed with exit code 0 and clean custody. Its
calibration source binding is
`21fa1ee4bcbbda78c41e3c29ec62f6d21a698396effe5ced3eed28e2d700bfee`; the
candidate head is `14f9d4e250e2cdcd0f0af89049dd36aeb048b728`, with dirty-source
state disclosed explicitly. The pre-calibration scoped proof recorded 347 unit
and 34 core integration cases with static, hygiene and privacy findings at
zero; it is not final metadata qualification.

The run covered 12:32:19–12:40:37 UTC and recorded 621+27 = 648 cells and
216 comparisons. Its 216 actual vector-operation records were completed 24,
`not_run` 12, unavailable 162 and refused 18. The unchanged denominators are
648/339/285/264; baseline evidence includes 36 safety-correct cases, 18
vector/fusion refusals and 12 HNSW `not_run/index_not_selected` cases. Raw
Generation 1 contains 80 documents, 4 queries and 84 embeddings; Generation 2
contains 80 documents, 0 queries and 80 embeddings, using public data and the
same approved BGE profile. No completed ANN, performance, scientific, held-out,
full-W5 or production acceptance is inferred.

The retained report is 3,703,442 bytes with SHA-256
`3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f`; no
private paths are present. No application or SDK build and no model-wheel
acquisition occurred. One pgvector 0.8.7 materialization ran on native ARM.
Calibration proved the writer-to-journal-to-ResultV2-to-V2-reader composed
seam. The final artifact analysis rejected all six tampered report derivatives.
These are bounded source and report-integrity facts, not scientific or
production acceptance.

The optional-15 native HNSW provenance observation records 72 HNSW operation
records, including 24 actual per-binding `HnswProvenance` records. All 24 have
raw state `not_run`; EXPLAIN executed and cleanup was verified for all 24, with
at most 63 plan nodes and zero expected ANN-index-selected cases. This closes
the not-run provenance-shape observation without claiming completed ANN or
performance.

Historical pre-CI115 preparation: the CI115 binder was a conditional ADR0147 preparation only: attempt 1 would be
the native AMD start 28 after 27, but it is not triggered or spent. CI114 was then
the latest green hosted predecessor. Final scope combines W5 with the grant and
refusal owners; final public-candidate
scoped proof, publication disposition and exact-commit report remain pending.
Exact final counts belong in the phase commit and candidate report. All complete
local Python suites, coverage and
application builds remain intentionally unselected, and the soft 87%/82% target
remains pending hosted qualification.

## CI115 qualification and component correspondence milestone

CI115 qualified staging 1275b49 with nine successful hosted jobs, native AMD
evidence and all five system scenarios. It authenticated cumulative application
start 28. Hard coverage floors passed. The exact 87/82 branch-goal gaps were
6 unit and 235 integration branches; rounded percentages do not close them.

ADR0148 delivers three connected technical work items: original component-byte
verification through the maintained parsers, a separate two-generation
correspondence dossier/CLI, and one-generation real SQL provenance with an
explicit synthetic384D supplier. The learned optional15 paired report remains
3,703,442 bytes, SHA256
3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f.
Its dossier is5,729 bytes, SHA256
ab2cbbdba639a7228460f94b61fce9b86fc42081077db76cc8502535f63d105d.
No original artifact was rewritten, rescored, repinned or executed.

The first functional diagnostic failed on its sixth index-selection check;
its strict failed ResultV2 is retained and missing raw-journal bytes disclosed
in ADR0148. The separately reviewed corrected diagnostic completed all three
repetitions: six actual expected-index observations, six verified index
cleanups and 6/6 confined EXPLAIN/candidate calls. Complete raw journal members decoded from verified stdout frames and strict
ResultV2 agree. Canonical --report was refused before tests because coverage is
excluded; no report policy was changed. Only exact registered ANN payloads
receive enable_seqscan=off and enable_sort=off; exact-reference and other
routes retain their original options. Separate default reader sessions keep
both settings on. This is functional SQL provenance, with no learned-worker,
calibration quality, performance, held-out or production acceptance.

Scoped feature proof recorded 224 unit and 12 core integration cases, plus the
single corrected optional case, without coverage or application/SDK builds.
Final campaign/grant proof selectors and observed counts belong in the exact
phase commit and report. All complete local suites remain intentionally
unselected. Runtime/library dependencies, debt ceilings and V1/V2 formats stay
unchanged. The pure scalar grant-helper extraction preserves policy and aliases.

Historical CI116 preparation: ADR0149 conditionally bound one normal staging synchronization for CI116
attempt1 and native AMD start 29 after28. CI115's spent grant stays rejected.
No automatic retry, start 30, manual/duplicate trigger, main promotion, tag or
history rewrite follows. Hosted CI remains AVAILABLE under the operator's
standing authorization; CI116 is untriggered at this local preparation.
All CI116 complete-population, coverage and assembled-system gates are pending.
Full W5/scientific criteria and production remain reserved decisions.

### CI116 remediation checkpoint

CI116 published the component milestone but failed qualification: all 2,067
selected staging tests passed before an unregistered dossier CLI coverage shard
was rejected; the system sandbox SDK build separately failed before application
work. The native SDK lane passed with the same pinned recipe. The actual CLI
repair preserves isolated execution and measurement while explicitly invoking
the maintained registration bootstrap through the observed launch family.
Synthetic registration fixtures and real dossier build/check subprocesses prove
receipt closure. Strict rejection of unknown shards remains unchanged.

The SDK failure's underlying reason is not established from the retained
generic diagnostic. Closed failure-category evidence is improved without a
speculative base/dependency change or automatic retry. ADR 0150 authorizes one
fresh CI117 attempt under the operator's repair request, with a new grant and
CI116 replay rejection. Actual application starts remain 28 and the cumulative
cap remains 29. Hosted coverage/system qualification and all scientific,
held-out, production and full W5 decisions remain open.

### CI117 SDK preparation and fresh CI118 checkpoint

CI117 passed unit/static/source/security lanes but its three container lanes
failed at APT prerequisite resolution during SDK setup, before container tests
or application work. The canonical helper explanation was lost by the outer
diagnostic. ADR 0151 repairs that specific reporting defect with redaction
before bounds, exact-line identity and scoped subprocess regression proof.
Unchanged ARM and inert AMD package graphs currently resolve; the exact hosted
failure remains unconfirmed, so no dependency or mirror change is inferred.

The native failed seal's application counters remain null. The separate parent
control-flow/job-step observation establishes no application entry and preserves
those null fields. CI118 receives fresh campaign identities, denies CI117 replay
and retains actual starts 28/cap 29. One operator-directed staging synchronization
is permitted after final proof and independent review. Complete qualification,
coverage goals and all scientific/full-W5/production decisions remain pending.

### CI118 recovery-probe isolation and CI119 preparation

CI118 passed all SDK/native/system scenarios and the source/unit/static/security
lanes. Its one integration failure was a nested missing-selector recovery probe
refused by the disk guard before discovery. ADR 0152 gives that discovery-only
fixture controlled HostSignals while retaining real admission, discovery,
managed cleanup and failure-report code. Positive and zero-capacity cases
must preserve missing-node evidence and real admission refusal, and workload
execution is forbidden. Ordinary runner policy and outer admission are unchanged.

CI118's same-attempt system artifact authenticates one application start, making
29 cumulative. The new operator retry request authorizes CI119 attempt 1 and
one additional start 30, under fresh identities and caps 30/30. No automatic
retry, CI120 or start31 is authorized. Hosted qualification and scientific,
full-W5, held-out and production decisions remain pending. Hard coverage floors
passed CI118; exact remaining 87/82 branch-goal gaps are 6 unit and 236 integration.

### CI119 containerd capacity binding and fresh CI120 checkpoint

CI119 passed the native/system and source/unit/static/security lanes. Staging
failed before collection at outer capacity binding on its Ubuntu 26.04/Docker
29.4.2 runner. The exact rejected path was not retained. ADR 0153 repairs the
independently reproduced rejection of Docker's supported default system
containerd overlayfs snapshot layout without weakening capacity or ownership
checks. Scoped unit refusals and containerized process/filesystem protocol
integration cover the new exact path and the retained managed layout. Controlled
Engine/mount inputs do not establish native daemon qualification.

The authenticated CI119 system intent/report and native seal establish one
application start, making 30 cumulative. This operator retry request permits
CI120 attempt 1 and one additional start 31, caps 31/31, with fresh identities
and CI119 replay denial. No automatic retry, CI121 or start32 is authorized.
CI119 integration coverage is unavailable; the CI118 integration measurement is
historical. The 87/82 goals and scientific/full-W5/production decisions stay open.

### CI120 outcome and W6 dependency-free foundation

CI120 attempt 1 is `EXECUTED_FAIL`: eight jobs succeeded and the sole
independent failure was an HTTP 504 during native AMD SDK APT preparation.
Native preflight was not entered, seal cleanup/parity is not accepted and the
native application counters are null. Staging passed with hard coverage floors;
the exact 87/82 branch goals remain 6 unit and 235 integration branches short.
Actual application starts are 31. No CI121 grant or start 32 exists; hosted
capacity stays AVAILABLE and no remote action belongs to this checkpoint. See
the [semantic exit](../../tools/ci/cloe-semantic1-exit.md) for the evidence header.

Under the operator's direction to proceed, `REPOMAP-CLOE-RUST-FOUNDATION1`
implements ADR 0154's
[dependency-free capability foundation](cloe-extractor-capability-foundation-v1.md):
closed vocabularies, the legacy registry, strict receipts, bounded storage, a
witness contract with no positive path and canonical refusal of raw capability
claims. Its [exit](../../tools/ci/cloe-rust-foundation1-exit.md) records scoped
diagnostic proof and pending gates. Parser selection, native execution, Rust
graph vocabulary and the remaining 10k–100k meaningful-LOC W6 milestone stay
separate; this prerequisite is not published alone, and W6 and v0.1.0 are not
complete.

### W6 bounded Rust pilot source checkpoint

The operator approved the bounded container-only Tree-sitter pilot in
[ADR 0155](../adr/2026/11/0155-isolated-rust-source-parser-pilot.md), sharing one
allocation across duplicate approval replies. The opt-in implementation adds
confined per-file runtime construction, live parent-witnessed Rust semantics,
offline/worker refusal, exact qualification manifests and one additional gate
in the existing native AMD job. The default legacy `.rs` classification stays
unchanged. The original fixture/gold window is frozen before native execution.

The [pilot source exit](../../tools/ci/cloe-rust-pilot1-exit.md) records 616
passing scoped unit cases, 22 passing containerized integration cases and a
passing retained-code gate. Independent resulting-source review and native ARM
qualification remain pending. No application build or public campaign is
allocated by this checkpoint; actual application starts remain 31. This source
proof is not native or hosted qualification. Container-free Local Rust, measured
comparison against credible alternative parsers, full W6 and v0.1.0 stay open.

### CI121 outcome and contract-repair checkpoint

CI121 passed native AMD D12/Rust qualification and all five assembled-product
scenarios. Its bounded Rust component evidence records 13 fixture comparisons,
420 claims and15 containment probes; this is component evidence for the tested
source, not full W6 acceptance. Nine unit assertions failed. All2,108 staging
behavioral tests passed before branch coverage failed at 18,786/23,552.
Actual application starts are 32. Hard 85/85 and 80/80 gates stay unchanged;
the 87/82 branch-margin goals remain open.

[ADR 0158](../adr/2026/11/0158-ci121-contract-and-coverage-repair.md) repairs
facade/census drift, redundant raw traversal, report-depth portability and stale
historical assertions. Its [repair exit](../../tools/ci/cloe-ci121-repair1-exit.md)
records225 scoped unit cases, a later five-case overlapping facade proof,
55 product integration cases and three grant/manifest integration cases, with
no local Python coverage, build or native parser execution. Connected receipt,
protocol, static discovery and publication regressions add useful coverage.

Fresh conditional CI122 bindings permit one normal staging synchronization,
application start 33 after 32 and the separately recorded necessary AMD component
command/two exact wheel transfers. Spent CI121 authority is rejected. Existing
native reports stay immutable; the repaired source has pending hosted evidence.
No automatic retry, main promotion, Local Rust or full W6/scientific acceptance
follows. Coverage-only deficits accrue with the next substantive milestone.

### CI122 outcome and W7 resource-experience design

CI122 passed all nine hosted jobs on the CI121 repair candidate, public staging
`4c61936725ed711cc0fe655eec143d90ea5f6143`. The parent's independent
same-source obligations validator qualifies that result. Public main remains
`5ad00d162ad8a04430874275246a53227578c533`; there is no main or tag
promotion.

The registered CI122 qualification input, as read and attested by the
independent design review, records these results:

- run 42164983397, attempt 1, classified `EXECUTED_PASS`;
- 33 cumulative application starts;
- native AMD component command count 2 and transfer count 8;
- unit branch coverage of 86.86%, which is 34 branches short of 87;
- integration branch coverage of 80.04%, which is 463 branches short of 82.

The hard gates are unchanged, and the desired 87/82 margins remain open. CI122
qualifies the CI121 repair candidate only. It does not establish full W6, Local
Rust, release or installed acceptance, or learned or scientific acceptance.

Under the operator's roadmap-continuation instruction,
`REPOMAP-CLOE-RESOURCE-EXPERIENCE1` is the next W7 milestone. Its bounded source implementation is assigned
under accepted
[ADR 0159](../adr/2026/11/0159-resource-view-and-first-use-workflows.md) and
the [resource experience specification](cloe-resource-experience-v1.md) (design
checkpoint 3), in two epics:

- a report-only, internal, call-owned `cloe-resource-view-v1` observer over
  SQLite Local and PostgreSQL refresh, the existing lexical build and bounded
  compact context. It reports descriptive, non-additive values that are
  already in memory, and it attributes existing controls truthfully. It adds
  no limit, refusal, CLI flag, CLI or MCP field, staging tier, or SQL. Staging
  resource values are projected only from events that a caller independently
  selected;
- reproducible source-level first-use workflows for Local, Server and mixed
  material over the public `mixed-v1` fixture, through the existing commands.
  Local stays free of Psycopg, Docker, parsers and enrichment. Each workflow
  asserts only its stated delta over the existing Local operator and lexical
  round-trip owners.

The observer's hooks never sit where an owner handler could relabel a
committed publication as failed or cancelled.

The source checkpoint implements both epics and passes 141 scoped unit cases,
57 containerized integration cases and retained-code enforcement with zero new
debt. Real-boundary proof includes clock degradation, post-commit interrupt
custody and observed Local/Server concurrency. Its
[source exit](../../tools/ci/cloe-resource-experience1-exit.md) binds the exact
selectors and source hashes. Final acceptance requires independent
resulting-state review, with its disposition recorded in the phase commit.
Several items remain separate:

- public exposure of the view, numeric governance and worker-side attribution;
- the lexical query, vector and Rust views;
- the missing sealing I/O cap (manifest caps are checked only after capture);
- the W7-owned staged-publisher BIGINT gap, addressed by the later ADR0162 phase;
- held-out tasks;
- publication.

Publication waits for final independent review and the fresh candidate binding
in [ADR0160](../adr/2026/11/0160-resource-experience-staging-campaign.md).
That conditional CI123 campaign permits one application start34 after33,
native AMD Rust command3 and two exact wheel transfers for cumulative10;
it is not execution or rearm of CI122. W7, W6 and v0.1.0 are not complete.

### W7 resource governance continuation

CI124 attempt 1 passed all nine jobs for the repaired resource-experience
candidate. Retained M/A, system, native and Rust artifacts were reconciled
against its exact source. Application starts are 35; native AMD Rust commands
are 4 and exact wheel transfers 12. Unit branches are 20,674/23,826 (86.77%);
integration branches are 19,113/23,826 (80.22%). Hard floors pass; the desired
87/82 margins still require 55/425 branches at this denominator. These counts
do not qualify a successor candidate.

The operator's continuation selects `REPOMAP-CLOE-RESOURCE-GOVERNANCE1`,
under [ADR 0162](../adr/2026/11/0162-early-sealing-admission-and-bigint-publication.md):
early admission against existing manifest policy and descriptor-streamed
sealing, followed by BIGINT staged-publication exclusion with matching
admission guards. The writer-conflict inventory is resolved in ADR 0162;
real competing-connection proof remains required. Both epics form one
batched milestone; no intermediate
design-only publication is planned. Existing numeric limits and debt ceilings
remain unchanged. Whole-I/O governance, installed qualification and full W7
completion remain open.

Both resource-governance epics pass 223 scoped unit and 36 containerized
integration cases, including actual maximum-BIGINT publication under the
standard refresh role, cross-mode contention, admission, lexical lifecycle
and first-use compatibility. Retained enforcement preserves all 2,805 debt
comparisons and admits the new owners cleanly. The
[phase exit](../../tools/ci/cloe-resource-governance1-exit.md) records exact
selectors and limitations. Conditional
[ADR0163](../adr/2026/11/0163-resource-governance-staging-campaign.md) selects
one fresh reviewed CI125 attempt1 (application cap36 after actual35, native
AMD Rust command5 and cumulative wheel transfers14). Independent final review
and exact-candidate binding precede publication. No successor has executed.

### CI125 forward repair

CI125 attempt 1 executed and failed two tests: an old positional run-INSERT
assertion and connected startup recovery's classification of sanitized
admission contention. The other seven jobs passed, including the five system
scenarios, native D12 and Rust checks. Retained artifacts authenticate actual
application starts 36, native AMD Rust commands 5 and wheel transfers 14.
Unit branches are 20,713/23,886 (86.72%); measured integration branches
are 19,148/23,886 (80.16%). Both hard floors pass; desired 87/82 margins remain
open (68/439 branches at this denominator).

`REPOMAP-CLOE-CI125REPAIR1` repairs those regressions under
[ADR0164](../adr/2026/11/0164-publication-contention-recovery-and-ci126.md).
Busy refusals retain storage-error compatibility and become expected durable
recovery contention; unrelated schema failures remain unexpected. Receipt
assertions select the actual run INSERT while retaining field/value checks.
Scoped proof and independent review precede one fresh CI126 attempt 1; the
[repair exit](../../tools/ci/cloe-ci125repair1-exit.md) records the exact
selectors, limitations and pending hosted boundary. Full W7 remains open.


### CI126 qualification and W7 operator reports

CI126 run42352930739 attempt1 passed all nine jobs at staging08956ee9.
Retained exact-source M/A, native, Rust and five system artifacts qualify that
candidate. Actual application/native-Rust/wheel consumption is37/6/16. Unit
branches20716/23886 and integration19149/23886 pass hard floors; desired87/82
margins remain65/438 branches short. No successor is qualified by those counts.

The operator's continuation selects `REPOMAP-CLOE-RESOURCE-REPORT1` under
[ADR0165](../adr/2026/11/0165-bounded-operator-resource-reports.md) and the
[report contract](cloe-resource-reports-v1.md). Three epics form one milestone:
bounded report files/offline inspection, explicit single-operation CLI attachment,
and lexical query/revoke views with connected custody proof. The
[source exit](../../tools/ci/cloe-resource-report1-exit.md) owns actual evidence.
No intermediate design-only publication is planned. Full W7, numeric governance,
worker attribution, installed/release acceptance and scientific work stay open.

### CI127 explicit admission-census repair

CI127 attempt 1 failed one unit assertion; its other eight jobs passed. The
resource-report admission itself passed static lineage validation. The unit
test's independently enumerated forward-admission list omitted that new phase.
`REPOMAP-CLOE-CI127REPAIR1` appends only the reviewed phase and preserves every
proof/continuity/namespace/source check. Its projection owner reproduced red
and then passed all 49 scoped cases. [ADR0167](../adr/2026/11/0167-projection-admission-census-and-ci128.md)
and the [repair exit](../../tools/ci/cloe-ci127repair1-exit.md) bind one fresh
reviewed CI128 attempt 1 at application/native-Rust/wheel caps 39/8/20, after
actual 38/7/18. No successor qualification or full W7 completion is implied.

### CI128 qualification and W7 Server parity design

CI128 run 42414664976 attempt 1 passed all nine hosted jobs (`EXECUTED_PASS`) on
staging `5ce48979661a13cd017bca48fea7f61ac6ec23b8` (merge
`a8575b4f759303c3d0f7f5a228c60db85bbe3aeb`, tree
`997fdaa1491693ff0ac6c8f927bae767b4492ed5`, source SHA-256
`d49cd86397359feaa607b28b091beae6b50f30f1d26154cb034873f511e2f9f3`) against
public main `5ad00d162ad8a04430874275246a53227578c533`. Retained same-attempt
staging M/A, native AMD (`D12_qualified=true`, `Rust_component_qualified=true`,
420 claims, 13 comparisons, 15 containment probes) and five-scenario system
(`intent_sha256=0ffdbb4108022215b87d5ef6177a50750e18e6c37a85b5e89d168b5888fd2fcb`,
`report_sha256=aca5583983f5002957de9318537f5229f5d7937685415fd265b3d8e628f6ee88`,
`cleanup_verified=true`) obligations pass. Authenticated cumulative counters
reach 39 application starts (`new_application_builds=0`), 8 native AMD Rust
commands and 20 parser wheel transfers (`same_exact_wheel_transfers=2`). Unit
passed 17,140 (40 skipped, 0 failed; 68,635/74,100 lines, 20,939/24,140 branches
at 86.74%, raw log `c79740387ebab54ad55042a42ab86e085f9edeb9858eecf76e070f7b1af4c965`)
and integration passed 2,277 (12 skipped, 0 failed; 66,013/74,100 lines,
19,341/24,140 branches at 80.12%). Hard coverage floors pass; the desired 87%/82%
branch margins remain 63 unit and 454 integration branches short at 24,140
branches. CI128 qualifies `5ce48979661a13cd017bca48fea7f61ac6ec23b8` only;
release and full W6/W7 acceptance remain false.

The operator's current manual continuation selects
`REPOMAP-CLOE-SERVER-PARITY1` as a partial W7 batch. The parent accepted the
first two components under
[ADR 0168](../adr/2026/11/0168-bounded-server-context-and-refresh-outcomes.md)
and [the parity contract](cloe-server-parity-v1.md), then separately accepted
[ADR 0169](../adr/2026/11/0169-positive-server-retained-attempt-recovery.md)
and [explicit retained-attempt recovery](cloe-server-retained-attempt-recovery-v1.md).
Implementation and scoped proof are in progress; no successor is qualified.

1. **Bounded PostgreSQL depth-1 context parity.** The selected contract uses
   one repository- and accepted-identity-pinned expansion statement. It reads
   directional seed windows, applies the SQLite greedy admission order, and
   projects locations only for admitted neighbors. Both backends use the
   existing four-part canonical relation identity: production relations with
   identical empty metadata hashes must survive, while self-loops deduplicate.
   Unsupported ports keep explicit refusal/fallback. Existing logical, SQL,
   seed, edge, node and evidence limits remain unchanged; returned-window
   bounds do not imply bounded physical query work or a shared snapshot.
2. **Truthful Server refresh outcomes.** A private per-call phase witness
   distinguishes pre-publication, confirmed rollback and possible publication
   using the existing public vocabulary. Cleanup after publisher return must
   never mark the attempt failed. Primary BaseExceptions survive secondary
   settlement and close faults. Resource reports prioritize commit uncertainty
   over cancellation. Existing coordinator receipt reconciliation is unchanged.
3. **Explicit positive-only retained-attempt recovery.** Inspect or settle one
   named Server attempt after validating its retained artifacts and exact
   graph/operation-bound historical PostgreSQL publication. Inspect performs
   no filesystem writes. Settle changes only retained bookkeeping, with a
   private backup, cooperating namespace lock and compare-and-replace. Missing
   or conflicting proof remains held; no capture, publication retry, failure
   inference, automatic scan or artifact deletion is introduced. SQLite Local
   retains its separate existing recovery. Optional receipt materialization is
   bounded at 16 MiB, without changing the general artifact/publication limit.

The proposed startup-option timeout was rejected because it can override a
stricter effective server, database or role default. It remains held; no such
compatibility change or server-side request deadline is introduced. A future
safe control/query alternative must charge both statements honestly under the
unchanged cap. The current deadline remains cooperative between statements.

This batch adds no dependency, DDL, role, runtime image or test-runner policy.
The original 3.5k–4.4k design forecast covered the first design, not the later
recovery selection or an observed delta. The parent aims for substantial
related work without padding. Local Rust, model/held-out work, complete local
suites, local Python coverage and full W6/W7 completion remain unselected.
Application start 40, native AMD command 9 and wheel transfers 21–22 require a
fresh final-candidate campaign binding after proof and independent review;
they are not spent or qualified by this design record.


### CI131 qualification and next resource-governance batch

CI131 run 42489743980 attempt 1 qualified staging
`52c60169303458905d11c1f307504ec9ff3ebe4b` against public main
`5ad00d162ad8a04430874275246a53227578c533`. All nine jobs passed
(`EXECUTED_PASS`). Retained same-attempt staging M/A, five-scenario system,
D12 native AMD and Rust component obligations validate against source, merge
`66554d9928ad644878a80e1f7165a1c774be0c69` and tree
`43002184513e95b003a09477aa5ab15ae30fa424`. Unit passed 17,274 cases
(40 skipped), with 69,696/75,336 lines and 21,271/24,570 branches (86.57%).
Measured integration passed 2,344 cases (12 skipped), with
67,076/75,336 lines and 19,673/24,570 branches (80.07%); the report also
contains three passing smoke checks. Hard coverage floors pass; desired
87%/82% branch margins remain 105/475 branches short. Authenticated cumulative
consumption is 42 application starts, 11 native AMD Rust commands and 26 wheel
transfers. This qualifies only the named staging candidate, including the
bounded Server parity and positive retained-attempt recovery batch. It does
not close W6/W7, installed qualification or release acceptance.

The current roadmap continuation assigns
`REPOMAP-CLOE-RESOURCE-GOVERNANCE2` to the next connected W7 batch: actual
sealing-I/O accounting and call-owned governance, honest worker resource
attribution, and compatible resource-plan/report delivery. These are ordinary
W7 design choices under the current continuation; the parent must accept an
ADR and concrete contract after independent design review before product
implementation. The accepted first resource-governance phase remains
immutable, and this phase continues its namespace rather than allocating a
near-duplicate family.

The design must inventory real reads, traversal/retry work and child-process
ownership before choosing limits or attributing measurements. It must label
self-process versus descendant/whole-operation cost, measured versus estimated
values and unavailable observations honestly. Existing public v1 report
contracts cannot gain vocabulary in place; compatibility and any separate
versioned surface require an explicit design disposition. Numeric policies
need a stated basis and refusal/cleanup proof. No blanket hard-RSS, physical
PostgreSQL work, efficiency or full-W7 claim follows.

The rejected startup-option timeout remains held. New dependencies, images,
DDL, role grants, native parser/model work, installed/live-state mutation,
complete local suites and local coverage are outside this selection. Scoped
unit and real containerized integration proof, strict new-owner quality
enrollment, full resulting-source review and parent acceptance precede any
substantial milestone publication. Aim for a useful 10k–100k line batch without
padding. No intermediate design-only public CI is planned. A future single
campaign requires its own final-source binding; the consumed CI131 grant is
not reusable. Main and release boundaries remain unchanged.

Implementation status (feature proof, not qualification): ADR 0173 and its
contract were accepted after two independent design reviews, and the three
epics are implemented in source with scoped unit and containerized integration
proof through the canonical runner, strict new-owner enrollment and the exit
record `tools/ci/cloe-resource-governance2-exit.md`. Independent work review,
parent verification, campaign binding, commit and publication remain open;
CI131 does not qualify this successor.

### CI134 outcome and W7 lifetime/efficiency continuation

CI134 attempt 1 executed on staging
`efdb5286b8a0bc40e242cdfc89a37b99dec89e18`. All 17,632 unit cases and
2,450 measured integration cases passed, as did five abrupt cases and five
system scenarios. Unit branches were 21,743/25,030. Measured integration
branches were 20,023/25,030: one branch below the hard 80% floor despite
display rounding to 80.0%. The desired 87%/82% branch margins remain 34/502
branches short. Static-tool bootstrap and Syft acquisition separately failed
with HTTP 504 responses; their missing checks are not qualified. The campaign
is `EXECUTED_FAIL`, and no whole-candidate acceptance follows. Authenticated
application/native-Rust/wheel consumption is 44/14/32.

The operator's roadmap continuation, together with the earlier direction to
carry coverage work into substantial milestones and proceed past 504-only
failures, selects `REPOMAP-CLOE-RESOURCE-GOVERNANCE3`. This continues the
existing resource-governance namespace with two connected design objectives:

1. **Worker lifetime custody:** extend interruption cleanup to default and
   ticketed launches with exact child/group ownership, one reaper, durable
   ticket/fencing reconciliation and primary-exception preservation.
2. **Sealing read efficiency:** remove only proven redundant body reads while
   preserving ordinary discovery hashes, content identity, retry and race/error
   semantics, alias/collision handling and truthful meter/plan/report values.

Both objectives were explicitly left open for later ordinary W7 design by
ADR0173. An independent source-backed design review and parent acceptance of
ADR0177 and a concrete contract must precede implementation. Real connected
Local/Server first-use and refusal/cleanup proof belong in this batch; they
must add new assertions rather than duplicate existing first-use owners.
The scope does not introduce a speculative whole-operation planner or grow
the public v1/v2 report vocabulary in place.

Aim for a useful 10k–100k line batch without padding. Coverage remediation
must exercise useful real boundaries over the unchanged denominator and
floors. No intermediate design-only publication is planned. New dependencies,
base/SDK-image admission, DDL/roles, runner-policy classes, native-platform
expansion, live/installed
mutation, complete local suites and local coverage remain outside this
selection. The PostgreSQL startup timeout and unsupported hard-RSS or
whole-operation guarantees remain held. Final proof, independent work review,
fresh campaign binding and one separately qualified staging attempt remain
required; full W6/W7, installed/release and main acceptance stay open.

Implementation status: ADR0177 and the two concrete contracts were accepted
for source implementation. The two connected epics and strengthened first-use
owners now have passing scoped unit/containerized integration proof; the public
transition receipt is `tools/ci/cloe-resource-governance3-exit.md`. Final static
enforcement, independent resulting-source review, fresh campaign binding and
hosted qualification remain separate. This does not close W6/W7 or qualify the
successor through CI134.

### CI136 outcome and W7 first-use workload continuation

CI136 attempt 1
([run 42647736470](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/42647736470))
executed on staging `cc6c91e1e4170d2775540945e5996d734bc0800e` over public
base `5ad00d162ad8a04430874275246a53227578c533`. The candidate merge was
`0927d7deca02be215238cc992f2133398a9d45d9`, the tree
`7d152cc656253ca0a3314213276ab86ebdfac758` and the source SHA-256
`6dc33cc1cb3c0fa5665f9615536d01097c08887b89d3bf4a917be94165d92492`.
The result is `EXECUTED_PASS`. All nine jobs executed and passed, and the
same-attempt M, A and system evidence was validated together.

| Area | Accepted result |
|---|---|
| Unit | 17,710 passed, 40 skipped, 0 failed. Lines 71,749/77,415; branches 21,858/25,152 (86.90%). Hard 85/85 met. The desired 87% branch margin is 25 branches short |
| Measured integration (M) | 2,468 passed, 12 skipped, coverage valid. Lines 68,967/77,415; branches 20,124/25,152 (80.01%), above the hard 80% floor. The desired 82% margin is 501 branches short |
| Abrupt integration (A) | 5 passed. Cleanup passed. Measurement unavailable by role |
| System, native D12 and Rust | `EXECUTED_PASS`; system cleanup proven |
| Retained artifacts (SHA-256) | native `2e72ce9f05741b02b5ea5b38c2889e2bf7c3c100e689b9bd717b409fdde09a48`; rust `510b3d8d5c3368df54004ec2b52f26672beffcf0d92ca8a7563e5f2075f2f533`; staging `f0fb7325dda3ae07f9cc5ddc6f2accab15fac4f6f2dfc2eeceba71a020ee869f`; system `aa64eb4cb8a8cac488033cf5fc9db00d2881409ff7ae635d40d2733c037b59e2` |
| Consumption | This attempt: 1 application start, 1 native Rust AMD qualifier invocation and 2 wheel transfers. Cumulative: 46/16/36. The slot is spent and there is no automatic re-arm |

This accepts `cc6c91e` as a qualified staging source candidate only. It does
not promote main, does not accept installed, release or image delivery, W6
or W7, and qualifies no later source. The selected retained-member digests
stay with the accepted evidence and are not repeated here.

The user's instruction to carry on with the roadmap after CI136 selects
`REPOMAP-CLOE-FIRST-USE-WORKLOAD1`. It reserves the specific
`CLOE-FIRST-USE-WORKLOAD` family and is ordinary W7 design within current
authority; it does not reopen the roadmap. Accepted
[ADR0180](../adr/2026/11/0180-reproducible-first-use-workloads-and-evidence.md)
and its [contract](cloe-first-use-workload-v1.md) define three connected
epics:

1. **Reproducible workload and evidence harness.** A committed census
   freezes the public `mixed-v1` generation inventories. A code-owned recipe
   fixes the ordered Local, Server and mixed steps, manual expected
   locations and explicit opt-in budgets. The intent binds the recipe,
   census, a product-source digest and the complete canonical candidate census, with
   no future commit SHA required.
2. **Real execution and readback.** New integration owners run cold and
   repeat refresh, generation change, replay, navigation, context and
   lexical readback, privacy and scope, sealing plans and v2 reports,
   refusal before worker launch with accepted-pin preservation, failure and
   cleanup. They run in the canonical sandbox over disposable homes, SQLite
   and temporary PostgreSQL. `4S+C+m+m_c+r` and `4S+1` come from fixture
   and store witnesses.
3. **Reconciliation and inspectable evidence.** A checkout-only pure
   reconciler refuses stale, partial, cross-attempt, cross-backend,
   cross-candidate, tampered, unbounded and unsafe evidence. It keeps
   expected refusals, failures and skips distinct. Bundles leave the
   sandbox only through the existing `--report` export, including
   CI137's hosted staging artifact, and `tools/first_use_workload.py check`
   re-validates them.

Deferred custody hardening, native Windows, installed or runtime delivery,
and optional parser or model work are not prerequisites.

The milestone adds:

- no product or installed command, runner flag or admission class;
- no change to the resource-report v1/v2 or sealing-plan schemas;
- no dependency, lock, packaging, image, DDL or role change;
- no native parser or model acquisition, live or private target,
  default-home migration, MCP change, retry or sweeping cleanup.

Quality roots, ceilings, measured and abrupt roles, suppression policy, the
complete product denominator and the hard 85/85 unit and 80/80 integration
gates are preserved. Frozen tasks, golds, the held-out split and old trials
stay unread and unchanged.

Status: accepted design implemented as a source candidate with scoped
unit/integration diagnostics. Corrective source review, final-source binding,
one ordinary staging publication and CI137 attempt 1 remain; hosted acceptance
is pending.
That campaign's inferred minimum cumulative consumption is 47 application
starts, 17 native Rust AMD invocations and 38 wheel transfers. This comes
from the normal roadmap campaign, not a separate numeric operator selection,
and binds only once final source exists.

There is no design-only CI, automatic CI138, 48th start, retry or second
push. Bounded first-use acceptance means the recipe reconciles on the
resulting source candidate. W8 installed acceptance, held-out evaluation, full
W6/W7, physical PostgreSQL and hard-RSS governance, and ADR0177's deferred
custody scenarios remain open.

The parent accepted ADR0180 and its bounded workload contract after independent
design review and the explicit returned/CLI/raised refusal-classification
correction. Implementation, scoped execution, final source review and the
CI137 candidate binding remain separate and pending. No design-only campaign
or full-W7/installed acceptance follows.

Local report admission refused `--report --no-coverage` before Python tests.
The first-use design now keeps local proof scoped and coverage-free, with
in-sandbox bundle validation. The normal hosted CI137 report supplies all
three exported bundles; their host check remains a required pending milestone
acceptance gate. No runner-policy change, local coverage or gate waiver is
introduced. Terminal cleanup is unconditional and observed after its callbacks.
The exact-commit private report binds final owner SHA-256 values and physical
line counts for the census, inventory, ADR, workload spec and roadmap append;
the private report may hash the exit, which never embeds its own hash.
Host checks of hosted evidence must use the same-attempt `candidate_identity.source_sha256`
and recorded merge commit/tree. A staging head is eligible only when its
complete candidate census equals that reported executed tree; otherwise obtain
the exact tree. Never repin an artifact or weaken the check; unavailable exact
tree evidence keeps hosted acceptance pending.

The three-epic first-use workload implementation now has scoped unit and real
Local/Server/mixed integration diagnostics, independent call-return/pin
witnesses, refusal checks and bounded inspectable evidence. The phase exit
records that source-tested boundary. Final review and campaign binding precede
one CI137 publication; exact-source hosted bundle export and host checks still
block bounded first-use acceptance. Full W7, installed qualification and
held-out scientific evaluation remain open.

### CI137 outcome and W8 installed-experience prerequisite

CI137 attempt 1
([run 42717271564](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/42717271564))
executed on staging `5997d06b7bf08b774e479968b518c6d167f556c6` over public
base `5ad00d162ad8a04430874275246a53227578c533`. The candidate merge was
`e9b94d883392d9c6fd5e41f6505d2c19292d3c5c`, the tree
`948de9c7d769153ba0a1ee853eaa523207990991` and the source SHA-256
`16ea54c3d1c8df45dba079926271e77a628394a1fca73433bc0460df80ec9e34`.
The result is `EXECUTED_PASS`. All nine jobs executed and passed, and the
same-attempt M, A and system evidence was validated together.

| Area | Accepted result |
|---|---|
| Unit | 17,901 passed, 40 skipped, 0 failed. Lines 71,752/77,415; branches 21,860/25,152 (86.91%). Hard 85/85 met. The desired 87% branch margin is 23 branches short |
| Measured integration (M) | 2,471 passed, 12 skipped, coverage valid. Lines 68,967/77,415; branches 20,124/25,152 (80.01%), above the hard 80% floor. The desired 82% margin is 501 branches short |
| Abrupt integration (A) | 5 passed. Cleanup passed. Measurement unavailable by role |
| System, native D12 and Rust | `EXECUTED_PASS`; system cleanup proven |
| First-use export | The host check of the exact-source exported bundles passed (check record SHA-256 `cc291481185f8df81496fbb1f6e5323f630d8e2c6776ecce132fa0bbb7980034`). Bounded first-use workload accepted |
| Retained artifacts (SHA-256) | native `bc556aea1fcbc8bf7c2737be144e963cead70029fa952b861abada7166907fb2`; rust `2af0405fca7c298b03c991ebfe14fbb3829d4db4a3f9541f9da23552dbbb21f6`; staging `e9ad8eb5945c54fbfe1f320eb4020eb399868564f6c93b9a5393ec030d2ef7c5`; system `3d41a77645c61684230c202f8bbc835660280d725c2e044603aca5f7b627feed` |
| Consumption | This attempt: 1 application start, 1 native Rust AMD qualifier invocation and 2 wheel transfers. Cumulative: 47/17/38. The slot is spent and there is no automatic re-arm |

This accepts `5997d06` as a qualified staging source candidate and accepts
the bounded first-use workload (ADR0180). It does not promote main, does not
accept installed, release or image delivery, W6 or full W7, and qualifies no
later source. The selected retained-member digests stay with the accepted
evidence and are not repeated here.

The user's instruction to continue the roadmap selects
`REPOMAP-CLOE-INSTALLED-EXPERIENCE1`, an independent W8 prerequisite. It does
not claim that every earlier workstream is accepted. Proposed
[ADR0181](../adr/2026/11/0181-exact-installed-experience-and-evidence.md)
and its [contract](cloe-installed-experience-v1.md) define three connected
epics:

1. **Exact offline installed environments.** The shared builder assembles
   the current wheel once per proof process and checks its inventory against
   the current owners. A pure-Local venv (`system_site_packages=False`) holds
   only the wheel and a verified projection of the SDK's installed
   `typing-extensions` 4.16.0, checked against its installed `RECORD`.
   Witnesses check closure, origin, distribution set and driver absence.
2. **Real installed workflows.** Installed wrappers run Local configure,
   init, refresh, a predeclared useful question, navigation and context,
   backup, restore and source-blind readback. Canonical and finite legacy
   stdio MCP run too. Configuration migration apply, rollback and finalize
   run over homes whose paths contain spaces, with the incumbent command
   where supported. A provisioned-Server environment, explicitly labelled,
   uses the SDK's existing dynamic Psycopg and a temporary PostgreSQL.
3. **Inspectable exact-candidate evidence.** A frozen recipe and an intent
   bind the wheel bytes, candidate inputs, provenance and expected facts. A
   checkout-only reconciler and `tools/installed_experience.py check`
   compare them with independently witnessed observations.

The milestone adds:

- no product or installed command, runner flag, launch family or admission
  class;
- no dependency, lock, version, license, packaging, image, DDL or role change;
- no native, macOS, Windows or service activation, live or default home, or
  network.

The `arch7f_pip` and `arch7f_probe` children stay unmeasured, so the
installed proof is diagnostic and not M coverage. The hard 85/85 unit and
80/80 integration gates, the 87/82 desired margins, quality roots and
ceilings are preserved. The W1 cutover and its unsupported overlap matrix
are not reopened. W5 and W6 decisions and ADR0177's deferred custody items
are not prerequisites. Named stop gates cover four cases: an unverifiable
projection (image decision), an unreachable installed-Server harness,
export that would need a runner change, and a packaging-metadata finding.

Historical status before CI138/CI139 (the bounded installed acceptance and
spent counts are superseded by the CI139 section below): design reviewed and
parent accepted; implementation and scoped diagnostics
present with scoped unit and containerized integration diagnostics, without
Python coverage. Corrective source review/proof governs final publication. One ordinary staging campaign and exact-source host
acceptance remain pending; independent final-source review and binding are
required before publication. The next normal roadmap publication
binds a fresh final-source CI138 attempt 1. Its inferred minimum cumulative
consumption is 48 application starts, 18 native Rust AMD invocations and 40
wheel transfers. This comes from the normal campaign, not a separate
numeric operator selection, and binds only once final source exists. There
is no design-only CI, automatic CI139, 49th start, retry or second push.
Bounded installed-experience acceptance needs that publication's host
`check` of the exported bundles. W8 release acceptance, full W5, W6 and W7,
held-out evaluation and native AMD or attended macOS proof remain open.

### CI139 qualification of the installed-experience prerequisite

CI138 attempt 1 executed but failed one stale fixture-census assertion. The
forward correction changes the expected count from 30 to 32, pins both added
fixtures as inert data, and preserves the manifest and fixture bytes. CI139
attempt 1 ([run 42829792591](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/42829792591))
qualified staging `c31fdfbc6bd7c65df75b1e473be2a3f0134233be` over public
base `5ad00d162ad8a04430874275246a53227578c533`. Its executed merge is
`40002d10be08e536440676c1dc4efef9b84d86ee`, tree
`3ee76046c2e3b20067674afaff751c9dde9e433b`, and runner-equivalent source
SHA-256 `86ddefd62d835361f392ea8b1eb37797f6dd0b25832d8e5c50eb29000dfbad80`.
All nine jobs executed and passed. Same-attempt smoke, M, A, system, native D12
and Rust evidence, merge parents/tree, archive digests and the complete source
census were independently reconciled. Classification: `EXECUTED_PASS`.

| Area | Accepted result |
|---|---|
| Unit | 18,051 passed, 40 skipped, zero failed; lines 71,752/77,415 and branches 21,861/25,152. Hard 85/85 met; desired 87% branch margin remains 22 arcs short |
| Measured integration M | 2,476 passed, 12 skipped; valid measured coverage, lines 68,965/77,415 and branches 20,123/25,152 (80.0056%). Hard 80/80 met; desired 82% branch margin remains 502 arcs short |
| Abrupt integration A | Five passed, exact cleanup passed; measurement unavailable by its declared role |
| First-use evidence | All three exact-source Local, Server and mixed exported bundles passed the host consistency checker |
| Installed evidence | Exactly one bundle for each of environment, Local, MCP, migration and provisioned Server passed the bounded reader and host checker; 56,000 actual aggregate bytes within 655,360 bytes |
| Consumption | One application start, one logical native Rust AMD qualifier invocation and two wheel transfers; cumulative 49/19/42. This slot is spent; no automatic re-arm |

The five installed owners share the independently verified candidate census and
NOTICE-inclusive wheel-input identity. Independent owner attempt nonces and
wheel ZIP digests are not required to match. The host check record SHA-256 is
`818378c820d31bab2cb337441808e2341f9e2a15a3d739bd7fcf11eae06f4e47`. These observations accept ADR0181's bounded
installed-experience prerequisite on this source, including wheel-only Local
and explicitly dependency-provisioned Server behavior. They do not establish a
fresh Server dependency install, release-image delivery, package-manager or
host-native support, attended macOS/Windows qualification, full W5/W6/W7/W8,
held-out scientific acceptance, main promotion or qualification of later source.
The desired coverage cushions remain open and accompany the next substantial
behavior-bearing milestone; no threshold or denominator is weakened.

### Proposed next W5 decision after CI139 (historical checkpoint)

This subsection records the initial design checkpoint. Its operator wait and
pre-implementation stop were superseded by the amendment and source progress
recorded in the following subsection.

[Proposed ADR0182](../adr/2026/11/0182-public-text-semantic-calibration.md) and
[its protocol](cloe-public-text-semantic-calibration-v1.md) propose three
connected public-text calibration epics: publication-bound representations,
disposable learned comparisons, and inspectable evidence. ADR0136 reserved
captured text separately from its metadata-only first slice. On 2026-11-11 the
operator selected this input class and its conditional `PUBLICTEXT-CAL1`
allocation ("proceed"). Declaration 1 then stopped at its model-free task
census: generation 2's only calibration task (cal-23) requests a mode the
learned seam refuses, so its per-generation query floor could not pass. No
body, model, held-out content or learned slot was used.

[The technical design](cloe-public-text-calibration-implementation-v1.md)
proposes declaration 2: generation-1 fixed ranked-discovery comparisons only
and a document-only generation 2, with the same population, input class and
wholly unspent allocation. Independent review found no new reserved class,
dependency or budget, and the design was revised for its technical findings.
Review returned one actual blocker, B-AUTH, to the operator: did "proceed"
bind declaration 1's per-generation query floor? Declaration 2 waits for that
answer and then for parent acceptance. If the floor was bound, declaration 2 is
withdrawn and the declaration-1 stop is final. No implementation is scheduled
or accepted.

The preliminary meaningful-line planning range is about 8k–15k, uncertain until
technical design, with reuse taking precedence over size. Pair the new behavior
with regression coverage of existing admission, publication, SQL and evidence
failure branches, aiming to recover the 22/502 arc deficits without artificial
test padding. No design-only public CI is planned. The proposal admits neither
held-outs nor production vector search and does not close full W5.

### Public-text floor amendment and source preparation (historical)

The operator selected the public-text input class, then explicitly approved
document-only generation 2 after the model-free preflight. All 24 frozen tasks,
queries, labels, golds and repetitions remain; generation 1 admits queries from
four fixed ranked candidates, requiring at least one public-text query under
declared policy, while generation 2 has zero model query
inference with original incumbent outcomes preserved. B-AUTH is resolved.
The same two-worker/one-study/no-retry allocation is unreserved and unspent.

The first APGR technical-design checkpoint produced a proposal and useful
advisory corrections but did not read every required source owner or obey all
read-tool limits. It is not a conforming acceptance checkpoint. Parent
corrections and conforming bounded checkpoints subsequently established
foundation source acceptance (142 unit and four integration cases), then
comparison/report source acceptance. The actual final driver now has scoped
proof: 758 unit, 25 CORE integration and four pgvector cases, including its
real two-generation functional lifecycle with 864 cells and synthetic raw
delivery. Independent final source review is being composed with exact byte
audits; private-host review and native qualification remain separate gates.

The [technical design](cloe-public-text-calibration-implementation-v1.md)
keeps production profiles and all original artifact/runtime/quality gates.
The [study contract's final selector record](cloe-public-text-study-v1.md#203-exact-final-driver-source-integration-owners)
names the source integration scope. These checks establish neither complete
suite coverage nor model-origin, scientific or hosted-CI acceptance. The two
native workers and one study remain unreserved. No new public CI has run for
this milestone.

### Public-text native milestone and CI140 preparation

The three connected public-text epics now have reviewed source, scoped proof,
the actual two-generation functional driver and native CAL5 PASS. The parent
verified all 864 actual report cells against original component artifacts,
source/task pins and cleanup evidence. Both model workers completed cleanly;
generation 2 has fresh documents and zero model query inference. The 24 fixed
tasks, original v1 arm and every unavailable/refused incumbent cell remain.
CAL5 is bound to its frozen evaluator before the final typing corrections.
CI140's corrected evaluator has fresh scoped and synthetic functional proof;
the earlier native run is not reclassified as execution of this new source.
See [the exact outcome and proof scope](cloe-public-text-calibration-outcome-v1.md).

CAL1–CAL4 history remains immutable, including CAL4's unproven strict closure.
The five-study allocation and both model workers are spent. Native PASS does
not close full W5, scientific usefulness, held-outs, production vector admission,
W6/W7/W8, release-image delivery or platform support. The next decision uses the
calibration evidence and hosted milestone results rather than repeating models.

One approved CI140 attempt 1 is being prepared after actual native PASS, with
fresh grant/source binding and independent review. Its cumulative application,
Rust and wheel limits are 50/20/43. Complete hosted qualification of this new
source remains pending; prior CI139 success is historical. Desired 87% unit and
82% integration coverage cushions remain targets above unchanged hard gates.
There is no local complete-suite/coverage substitution or automatic CI141.


### CI140 wheel-counter correction

The operator approved the exact cumulative wheel-transfer correction from 43
to 44 after CAL5 passed. CI139 spent 42 transfers; the unchanged Rust qualifier
requires two pinned wheels. The final conditional CI140 attempt-1 limits are
application 50, native Rust AMD 20 and wheel transfers 44. Earlier cap43 records
remain historical. This correction permits no extra campaign, local build or
acquisition, study/model worker, automatic retry, CI141 or main/tag/release
action. The one staging push still requires final grant proof and independent
review; hosted qualification remains pending.
