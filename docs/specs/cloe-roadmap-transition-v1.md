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
observations,144graded slots and1010journal records, bound to its pre-query
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
The separate namespace19042 staged-publisher int32-ID limit remains W7-owned;
this milestone qualifies lexical lock expressions, not all large-ID publication.

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
in place. Hosted qualification, held-out criteria, broader utility and production
model/pgvector/schema/index admission remain open; W5 is not complete.
