# ADR 0049: Qualification Evidence Authority, Verification Boundaries, And Reproducible Gates

## Title

Qualification Evidence Authority, Verification Boundaries, And Reproducible
Gates

## Status

Accepted. This is a docs-only architectural decision: it defines how RepoMap
establishes and preserves trustworthy qualification evidence. It implements
nothing, changes no source, test, tool, runner, or dependency byte, adds no
validator, and authorizes no successor phase.

Adversarial review was performed by Codex GPT-5.6 Sol High under the
`architecture-docs-review` profile as a non-veto reviewer. Gate 1 (pre-draft,
against the phase decision packet) returned `CORRECTION_REQUIRED` with zero
Critical, nine High, and two Medium findings, plus five fact-check
corrections. Gate 2 (final, against these drafted documents) also returned
`CORRECTION_REQUIRED`, with six High and four Medium findings, and its
corrections were applied before acceptance. Every material finding was
technically dispositioned by the primary author. Both gate verdicts and the
per-finding dispositions are recorded in
[status 00753](../../../status/2026/08/12/00753-repomap-adr0049-qualification-evidence-authority-exit.md),
which is the durable record for this decision.

## Date

2026-08-12

## Context

RepoMap's recent phases produced qualification evidence faster than it
produced rules about which evidence governs. A single phase could hold, at the
same moment: runtime observations captured by a parent process, frozen
expected contracts written before the run, redacted public projections of the
same values, phase-specific diagnostic gates invented for that phase only,
the canonical `unit`/`int`/`smoke` suites, and historical gate manifests whose
exact membership no longer existed anywhere.

These sources have genuinely different authority, and they disagreed. The
repository had no durable rule for which one governs, so each phase
re-litigated the question and several answered it wrongly:

- Assertions were written against a value the harness itself had programmed,
  making them tautological. Status
  [00751](../../../status/2026/08/11/00751-test-cov5k-r2-groupa-diag1-preparation-regression-exit.md)
  records both halves of that defect: evidence that "`ExecutorEvidence` carries
  them, but `verify_executor_evidence` does not enforce them", and a producer
  that "rewrites any real worker error to the catalog-programmed category", so
  that "assertions against the normalized failure source would therefore be
  tautological unless raw and injected outcomes are first separated."
- A generic consumer accepted specialized evidence without verifying the
  specialized contract, so integrity checks passed while semantics went
  unchecked.
- An exact selective gate was reported as `2152/2152 passed` in status
  [00752](../../../status/2026/08/12/00752-test-cov5k-r2-groupa-fix2-runtime-derived-evidence-exit.md),
  but the repository durably retains only that count. No selector, ordered node
  manifest, digest, command, or environment identity for that set exists in
  tracked history, so the claim cannot be reproduced or audited.
- Temporary qualification machinery was repeatedly confused with the ordinary
  commit gate, and phases argued about whether a red diagnostic node blocked
  work that had nothing to do with it.

Status 00752 settled the immediate question for its own phase — canonical
`unit`, `int`, and `smoke` results govern the commit, and temporary COV5K
diagnostics remain honestly recorded history — but settled it as a phase
decision, not as repository policy. This ADR makes the general rule durable.

Adjacent decisions already own parts of the problem and are not disturbed.
ADR [0044](../07/0044-bounded-startup-authority-decomposition.md) established,
for the preparation campaign, that a case is exercised, observed, compared
against a separate exact expectation, and that only the observed result is
serialized; it also holds that "worker terminal and cleanup fields are claims
until the parent observes an exit code, signal state, process-tree settlement,
and zero subordinate resources that exactly match." ADR
[0047](../07/0047-preparation-resource-sampling-deadline-policy.md) owns the
Runtime Qualification Identity Contract and the rule that any identity-field
change voids a timing receipt. ADR
[0048](0048-test-harness-resource-retention-reclamation-and-host-admission.md)
owns resource retention, reclamation, host admission, and the invariant that
APG report packets are transient reporting conveniences rather than durable
acceptance authority.

## Problem Statement

How should RepoMap establish and preserve trustworthy qualification evidence
when runtime observations, expected contracts, redacted projections,
phase-specific diagnostics, canonical test suites, and historical gate
manifests have different authority or disagree?

A trustworthy answer has to survive adversarial use. The failure modes that
matter are laundering (an expectation, an intent, or a projection quietly
becoming an observation), circularity (a record proving itself), bypass
(evidence accepted without its semantic contract being checked), erosion (a
temporary rule silently becoming permanent policy, or a normative test
silently becoming a diagnostic), selection (choosing the candidate, cohort, or
observation window after seeing results), and evaporation (a durable claim
whose supporting evidence exists only in storage that is not durable).

### What would prove this ADR wrong

This decision is falsifiable. It is wrong if any of the following holds:

- A phase can satisfy every rule here and still publish a qualification claim
  that a later reader cannot audit or reproduce to the degree the claim
  asserts.
- The evidence-layer model cannot describe a qualification claim RepoMap
  actually makes — for example a canonical coverage result or an ADR 0047
  timing receipt — without distortion.
- The rules make ordinary development materially more expensive without
  removing a real failure mode, for instance by turning routine local reruns
  into mandatory durable evidence.
- Claim-scoped candidate identity lets a real regression retain qualification
  credit, or conflicts with ADR 0047's receipt-voiding rule.
- The retention rules require evidence that RepoMap's privacy boundaries or
  ADR 0048's retention classes forbid keeping.

## Definitions

**Qualification claim.** An assertion, recorded on a durable surface, that a
named candidate met a named standard under named conditions, stating the
identity of that candidate. "The canonical unit suite passed at 6356 tests with
89.8 percent line coverage on candidate X" is a qualification claim. A console
line nobody cites is not. An assertion that asserts qualification without
naming its candidate identity is not exempt from this ADR: it is an **invalid
qualification claim** and is nonconforming, not out of scope.

**Atomic observation claim.** A claim about one directly observed property at
one observation boundary. A **relational claim** asserts a relationship
between two or more independently observed properties.

**Evidence layer.** A set of facts sharing one producer, one observation
boundary, and one relation to reality: `raw` (directly observed at that
boundary), `derived` (computed from other layers), `projected` (redacted or
otherwise reduced from another layer), or `expected` (written before the run).

**Acceptance boundary.** The point where a consumer stops treating evidence as
an artifact to carry and starts relying on it — transforming, aggregating, or
authorizing on its basis.

**Candidate.** The exact thing a claim is about: repository content plus the
environment and runner identity the claim depends on.

**Canonical suites.** The `unit`, `int`, `all`, and `smoke` suites run through
`tools/run_tests.py`, whose current selection and thresholds are owned by
[`repo-map-testing-standards`](../../../contrib/skills/repo-map-testing-standards/SKILL.md).

**Temporary qualification evidence.** Gates, matrices, campaigns, and
collectors built to answer one phase's question.

## Scope and Non-Scope

This decision governs qualification claims and the evidence cited to support
them. It applies wherever RepoMap asserts that something was qualified,
verified, or gated.

It does not govern ordinary test authoring, ordinary local development
iteration, or test artifacts that are never cited as qualification. It does
not define graph, storage, extraction, ingestion, CLI, or MCP behavior.

It does not:

- implement anything, or authorize an implementation phase;
- create a Gate C selector, a node manifest format, or any selection tool;
- change Group-A evidence semantics, the failure-notice protocol, timing
  values, or retry values;
- change `tools/run_tests.py`, its suites, its thresholds, or its exit
  composition;
- add a Markdown, link, ADR, or status validator;
- change dependencies or lockfiles;
- supersede ADR 0042, 0044, 0045, 0046, 0047, or 0048; or
- restate the Group-A remediation chronology, which remains in the status
  archive.

## Evidence Hierarchy

The facts below were verified read-only against the repository state this
phase entered — the state accepted by status 00752 — and are the basis for the
decision. Where a general principle is broader than what the current
implementation demonstrates, this ADR says so rather than implying the code
already proves it.

- Evidence layering is real and already implemented for one family.
  `src/test/support/python/repomap_test_support/test_cov5k_r2_fix2_preparation.py`
  defines frozen, slotted `ScenarioIntentFact`, `ChildLocalExceptionFact`,
  `WireFailureNoticeFact`, `ParentObservedAttemptFact`, `PublicProjectionFact`,
  and `FrozenExpectedFact`, aggregated by `AttemptEvidenceLayers`.
- `validate_attempt_evidence_layers` requires a parent observation, validates
  it intrinsically, compares the wire layer to the parent only when the wire
  layer is `captured`, compares child to wire only when both are `captured`,
  compares the public projection to the parent unconditionally, and compares a
  supplied expectation to the parent. Every comparison raises; none assigns.
  An expectation can reject an observation and can never write one.
- Absence is represented by explicit state tokens rather than by `None`. The
  `not_observable()` and `sender_closed()` constructors store the states
  `not_observable_at_parent_attempt_boundary` and
  `observed_sender_closed_without_notice`. That vocabulary is not closed: the
  `status` field is an unrestricted `str`, and the validator branches only on
  `captured`, so an unrecognized status silently bypasses the captured-only
  comparisons. This is a gap, recorded in Deferred Work.
- Redaction in that family is an **ingress** boundary, not an inter-layer
  projection. `_public_raw` collapses any value outside the closed raw category
  and boundary vocabularies to the single token `unrecognized`, and it runs
  before both the parent fact and the public projection are constructed, so the
  two stored layers hold the same collapsed values. The forward-only,
  non-invertible rule below is therefore stated as policy; the current code
  demonstrates non-invertible redaction, not inter-layer loss.
- Consumer-side verification exists and is incomplete.
  `verify_executor_evidence` recomputes parameter digests, the registered-owner
  binding, and owner observations, dispatches `semantic_group` `A` and
  `PARENT_SETTLEMENT` to their contract verifiers, and recomputes the result
  digest. Any other declared group runs no specialized contract check and still
  passes digest verification. Producer-side verification also exists, so the
  design already relies on defense in depth rather than a single check.
- Digests bind bytes, not meaning.
  `src/test/unit/python/tools/scale28_preparation_settlement.unit.test.py`
  rebinds the result digest after each of eleven representative semantic
  mutations and still requires the contract verifier to reject them, while a
  complementary unrebound mutation is caught only by "result digest differs".
  Those eleven are mutation families chosen for coverage of independently owned
  invariants; the consumer enforces materially more predicates than eleven.
- The canonical runner's exit status is ambiguous by construction. Composition
  happens inside `run_pytest_suites`: a nonzero pytest status is returned
  unchanged, and a coverage-only failure independently returns `1`.
  `run_selected_suites` receives that composed status and may then run smoke.
  Because pytest's own tests-failed status is also `1` — an upstream pytest
  contract, not a fact this repository establishes — a bare exit `1` does not
  distinguish failing tests from a coverage shortfall.
- Exact selective gates evaporate unless something retains them. Status 00752
  records `Gate C: 2152/2152 passed`; whole-tree search finds no selector,
  ordered node manifest, digest, command, or environment identity for that set.
  The durable archive retains a count.
- Reruns were already understood to be non-laundering. Status
  [00702](../../../status/2026/08/01/00702-test-cov5k-r2-fix4-gate1-bounded-complete-gate-stop-exit.md)
  records the same unchanged node failing once and passing once under identical
  bytes and policy, and concludes that "the rerun earns no credit and does not
  overturn the failed pre-gate." Status 00752's Gate B figure of `10/10 passed`
  is meaningful only because reruns and replacements were counted and were
  zero.
- No repository-owned Markdown, link, ADR, or status validator exists under
  `tools/`. ADR 0042 deferred one; ADR 0048's docs-only verification was diff
  checks plus manual mechanical checks. This phase does not add one.

## Decision

RepoMap adopts eight principles, D1 through D8. Items marked **[invariant]**
hold unconditionally. Items marked **[default]** may be varied by a later
accepted decision that states the variance.

### D1. Layered observation authority

Every evidence set used for a qualification claim declares its layers. Each
layer declares its producer, its observation boundary, its relation (`raw`,
`derived`, `projected`, or `expected`), and its states for presence and
absence **[invariant]**.

- For an atomic observation claim, exactly one `raw` layer is authoritative
  **[invariant]**. For an explicitly relational claim, several `raw` layers may
  hold joint authority, each over its own property. A `derived` or `projected`
  layer may never be authority for its own inputs **[invariant]**.
- An `expected` layer may reject an observation. It may never become one, and
  no expected value may be written into an observed field **[invariant]**.
- Stimulus is not observation. A programmed intent, injected fault, or
  configured scenario category may not be re-emitted as the observed category
  **[invariant]**. This is the rule that makes assertions non-tautological.
- Projections are forward-only. Verification projects the authoritative layer
  and compares; it never inverts a projection to recover a redacted value
  **[invariant]**. Where redaction happens at ingress rather than between
  layers, the same rule applies to the ingress boundary.
- Digests prove binding and integrity. They never prove semantics
  **[invariant]**.
- Absence is an explicit state at its own layer and is never filled in from
  another layer **[invariant]**. Presence and absence states are drawn from a
  closed vocabulary, and each state defines which cross-layer comparisons apply
  to it **[invariant]**. An unrecognized state is an error, not a silent
  skip.
- Independently observed layers are consistency-checked conditionally on their
  declared states. They are never normalized into agreement **[default]**.

**Counter-rule against runtime laundering.** Observation authority is authority
over what happened, not over what should have happened **[invariant]**. When an
observation and an expectation disagree, that is a finding. It is dispositioned
explicitly as either a stale assertion or a regression, and recorded. It is
never resolved silently in either direction — neither by rewriting the
expectation to match the run, nor by rewriting the observation to match the
contract.

This generalizes ADR 0044's campaign-scoped rule to qualification evidence
generally. ADR 0044 continues to govern the preparation campaign concretely.

### D2. Verification at every acceptance boundary

Semantic verification is owed at each acceptance boundary, and an acceptance
boundary exists per consumer and per claim, not once per pipeline
**[invariant]**. Every consumer that transforms, aggregates, or authorizes on
the basis of evidence must verify the contract it actually relies on.

- Defense in depth is retained. Producer-side checks localize failures early
  and are valuable, but they cannot discharge a downstream consumer's duty,
  because the consumer is what binds the claim **[invariant]**.
- A generic consumer must not silently accept specialized evidence. It either
  dispatches a declared semantic class to that class's contract verifier, or
  refuses evidence whose declared class it cannot verify **[invariant]**.
  Unknown and falsely declared specialized classes fail closed. A class that
  legitimately has only the base contract declares that explicitly.
- Digest verification is necessary and not sufficient. Passing an integrity
  check while skipping the semantic contract is the specific bypass this rule
  forbids **[invariant]**.
- Mutation testing against rebound digests is warranted where evidence is cited
  at an acceptance boundary, is mutable between production and acceptance, and
  uses a digest as an integrity claim **[default]**. Coverage is proportional to
  independently owned semantic invariants and to tampering risk — not one case
  per enforced predicate, which would misdescribe existing suites and force
  brittle churn whenever checks are regrouped.

This generalizes ADR 0044's parent-observation rule, under which worker
terminal and cleanup fields remain claims until the parent independently
observes matching facts.

### D3. Canonical-first health, explicit temporary evidence

The canonical suites are RepoMap's ordinary health boundary, and commit
verification is selected by change class, as owned by
`repo-map-testing-standards`
**[invariant]**. This ADR does not restate or duplicate the current gate
commands, thresholds, or suite composition; that skill remains authoritative,
and a docs-only change legitimately runs only the diff checks.

- **Collection determines debt.** A test still collected by a canonical suite is
  canonical debt while it is red, regardless of what a phase calls it
  **[invariant]**. Naming does not change collection.
- Truthful exits from canonical red are: fix it, or retire it from canonical
  collection. Retirement requires evidence that the protected behavior is
  genuinely obsolete **and** authority from the owner of that contract
  **[invariant]**. Relocating, renaming, or relabelling a red normative test as
  a diagnostic is not retirement.
- Phase-private diagnostics live outside canonical collection. They may remain
  historically red after an honest disposition without blocking unrelated later
  work **[default]**. They are still subject to ADR 0048's admission and
  retention rules; "temporary" grants no resource exemption.
- Temporary qualification evidence never replaces the canonical suites
  **[invariant]**. The commit-message contract in
  [`repomap-phase-hygiene`](../../../contrib/skills/repomap-phase-hygiene/SKILL.md)
  mechanically requires the canonical lines, which is why substitution is
  visible rather than merely discouraged.
- **Promotion follows ownership** **[invariant]**. A temporary rule binds only
  its own phase until it is promoted by the authority that owns what it
  constrains: architectural or publicly visible behavior requires an ADR or
  existing accepted authority; tests implement accepted authority rather than
  creating it; runner and skill changes own only their procedural domains.
  Landing a test or editing a routed skill does not create architectural policy.
- A superseded temporary gate is retired explicitly in the phase exit record,
  including what it no longer proves **[default]**.

### D4. Reproducibility proportional to the claim

Retention obligations scale with what the claim quantifies over **[invariant]**.

- A whole-population claim ("the canonical unit suite passed") is reproduced by
  its suite command, candidate identity, and results. Exact membership is not
  load-bearing, because the population is defined by the suite.
- An **exact-set claim** ("these specific nodes passed") makes selection
  load-bearing. It requires the selector rule and its version, the exact ordered
  node identifiers, the manifest bytes and their digest, candidate identity,
  environment identity, runner flags, coverage mode, skip and xfail policy, and
  the result and failure identifiers **[invariant]**. A count is not a
  reproducible exact-set claim.
- When exact historical authority no longer exists, a newly constructed gate is
  **new authority** and must say so **[invariant]**. It carries its own
  construction candidate, states that the historical set was not recovered, and
  states what the historical record does retain. For Gate C, the historical
  record retains a count.
- No permanent selector tool is mandated **[default]**. A one-shot deterministic
  rule plus a retained manifest satisfies an exact-set claim. A tool is
  justified only when the same selection must be reproduced across phases, and
  this ADR does not create one.

### D5. Qualification campaigns, retries, and no-redraw

The discriminator is what the claim quantifies over, not whether a command was
run twice **[invariant]**.

- **Deterministic construction** — collection, manifest building, selector
  evaluation — is a pure function of candidate and rule. Retrying it is
  evidence-neutral while zero test bodies execute and the candidate is
  unchanged **[invariant]**.
- **Execution** is where laundering is possible. A qualification attempt
  declares, before it runs, six fields: an attempt identity, the candidate
  identity, the environment identity, the cohort or population, the stopping
  rule, and the replacement policy **[invariant]**. Every execution inside that
  declared window is recorded, including failures.
- All six fields are always required; what varies with the claim is how much
  must be written down explicitly rather than derived **[default]**. For a
  whole-population claim, naming the suite command and the candidate derives
  the rest: the attempt identity is that declaration, the environment identity
  is the recorded runner environment, the cohort is the suite's own collected
  population, the stopping rule is "one execution of the named command", and
  the replacement policy is "none". A claim that quantifies over a fixed cohort
  or an exact node set derives none of them and states all six explicitly.
- Ordinary development reruns are not qualification evidence and do not have to
  be recorded **[invariant]**. Because predeclaration is what makes a window
  auditable, a development run that was never predeclared cannot later be
  promoted into qualification credit: citing it does not retroactively create a
  window **[invariant]**. To qualify, declare an attempt and run it. This is a
  duty to declare before claiming, not a ban on rerunning.
- A mixed record on an unchanged candidate means the node is flaky. Flakiness is
  a defect and blocks qualification until it is explicitly dispositioned and
  requalified. It is never resolved by taking the green run **[invariant]**.
  Status 00702 is the worked precedent.
- **No-redraw** semantics apply only where sampling cardinality is itself part
  of an explicit experimental contract. There the cohort is fixed in advance and
  replacements are prohibited or counted, which is what made Gate B's "zero
  reruns or replacements" a meaningful figure **[default]**.
- Domain-specific predecessor rules continue to govern where they are stricter.
  ADR 0047's no-resample and freshness rules are not relaxed by this ADR
  **[invariant]**.

### D6. Claim-scoped candidate identity

A qualification claim states the identity of the candidate it was produced
against. An assertion that omits it is an invalid qualification claim and is
nonconforming **[invariant]**.

- Candidate identity has three components: repository content, environment, and
  runner or profile **[invariant]**. All three are named; none is implied by
  another.
- The repository-content component is the commit identity when the worktree is
  clean. When it is not clean, it is the base commit plus a dirty-content
  identity that enumerates every staged, unstaged, and relevant untracked path
  and binds their content **[invariant]**. This ADR does not fix a canonical
  serialization or digest algorithm for that enumeration; defining one is
  deferred. Until it is defined, a dirty candidate is identified by explicitly
  listing those paths in the record, and a claim that cannot do so falls back to
  the conservative whole-candidate rule below.
- Identity is scoped to the claim's **dependency set** rather than to the whole
  worktree **[default]**. A change outside the dependency set does not
  invalidate the claim. This makes the familiar docs-only carve-out an instance
  of a general rule instead of a special exception.
- The dependency set is frozen **before** execution and covers transitive
  sources, tests, fixtures, the runner, configuration, generated inputs, and
  relevant external identity **[invariant]**. It is never narrowed after results
  are seen. Where closure cannot be established, the conservative
  whole-candidate identity is used **[invariant]**. Changing the definition of a
  dependency set produces a new identity rather than preserving old credit.
- Older results remain historical evidence. Qualification credit applies only to
  the identity the result was produced against **[invariant]**.
- Timing qualification remains governed by ADR 0047. No dependency-set scoping
  in this ADR preserves timing credit across an ADR 0047 identity-field change;
  that receipt is voided as ADR 0047 specifies **[invariant]**.

### D7. Coverage and runner provenance

Exit-code arithmetic is not provenance **[invariant]**. Six things stay
distinct: pytest's own status, the runner's composed exit status, measured line
coverage, measured branch coverage, the threshold in force, and the explicit
threshold decision.

- A bare runner exit `1` is ambiguous by construction and may not be attributed
  to coverage, or to test failure, without corroborating evidence
  **[invariant]**.
- Attributing a nonzero exit to coverage is admissible only when the record
  cites the measured line and branch figures, the threshold in force, the suite
  or policy that selected that threshold, and the explicit pass or fail decision
  **[invariant]**.
- A coverage percentage is meaningless without the measured root set, which the
  record must state **[invariant]**. Which roots a suite measures is the
  runner's business and is described by `repo-map-testing-standards`; the
  durable obligation is that the claim names them.
- A qualification record states whether coverage was enabled at all
  **[invariant]**.

### D8. Retention surfaces and evidentiary sufficiency

Durable surfaces **record** claims and the independently produced evidence
summary that supports them. They do not **prove** their own assertions
**[invariant]**. A status document that asserts qualification and cites only
itself or its enclosing commit has proved nothing. ADR 0048 already models the
correct shape by requiring an external private post-commit close receipt rather
than letting the record vouch for itself.

Accordingly, a qualification claim recorded on a durable surface carries enough
to be audited: the evidence producer, the candidate identity, the result, and
the verification performed **[invariant]**.

Surfaces and their roles:

| Surface | Role | Authority |
|---|---|---|
| ADR | durable decisions, invariants, alternatives, falsification conditions | architectural authority |
| Terminal status record | outcome, gate identities, counts, digests, dispositions, boundaries, next authorization | phase acceptance record |
| Commit | the repository-content component of a clean candidate, plus its message contract | partial candidate identity only; environment and runner identity must be recorded separately |
| Phase-private retained evidence | exact manifests, raw captures, private identities | audit material, not durable authority |
| APG report packets | transient reporting convenience | never durable acceptance authority (ADR 0048) |

- No decision may depend on APG packet internals. A property obtainable only
  from a packet belongs in a repository-owned surface instead **[invariant]**.
- A digest authenticates bytes once they are found. It neither locates nor
  preserves them **[invariant]**. Citing a private artifact by digest therefore
  does not make a claim reproducible if that artifact is the only copy of
  load-bearing bytes.
- Where cross-phase reproduction is genuinely required, the minimum public-safe
  reproducibility payload is retained in a repository-owned surface
  **[default]**. Otherwise the claim is narrowed to what durably survives, and
  the record states that exact reproduction expires with the private artifact.
  This phase creates no such surface.
- Retention lifecycle — TTL, GC, pinning, quotas, deletion — is owned entirely
  by ADR 0048 and is not redefined here **[invariant]**. This ADR constrains
  only evidentiary sufficiency.
- Private and packet surfaces may be referenced by digest but may not be the
  sole support for a durable claim **[invariant]**.

## Worked Applications

The model has to describe more than the family it came from.

**Layered attempt evidence.** Six declared layers, one authoritative `raw`
parent observation per atomic claim, an `expected` layer that can only reject,
an ingress redaction boundary that is non-invertible, typed absence, and a
consumer that dispatches by declared semantic class. D1 and D2 describe this
directly. The current gaps — an open status vocabulary and a dispatch that does
not fail closed on an unknown class — are exactly the places D1 and D2 identify
as underspecified, which is the intended diagnostic value.

**Canonical suite and coverage evidence.** The layers are thin but real: the
`raw` layer is the runner's recorded results and measured coverage, the
`derived` layer is the composed exit status, and the `expected` layer is the
threshold in force. D7 forbids collapsing them. The claim is a whole-population
claim, so under D4 its reproducibility payload is the suite command, candidate
identity, measured roots, figures, threshold, and decision — no manifest
required. Under D5 the predeclaration obligation is discharged by naming the
suite and candidate. Under D8 the status record states figures and decision
rather than an exit code.

**ADR 0047 timing receipts.** The receipt is a `raw` observation bound to an
explicit runtime identity, and ADR 0047 owns both its identity fields and its
voiding rule. D6 defers to it: dependency-set scoping never rescues a timing
receipt whose identity field changed. D5's no-redraw discussion likewise does
not loosen ADR 0047's no-resample rule. This ADR contributes only the general
vocabulary; the domain rule stays stricter and stays where it is.

## Ownership And Adjacent Decisions

| Area | Owner | This ADR's relationship |
|---|---|---|
| Preparation-campaign observed authority; parent observation of worker claims | ADR 0044 | references and generalizes; does not supersede |
| Timing qualification identity, receipt voiding, no-resample, freshness | ADR 0047 | explicitly subordinate |
| APG packet non-authority; retention classes, TTL, GC, pinning, admission | ADR 0048 | references; constrains evidentiary sufficiency only |
| ADR and status archive placement, numbering, exit convention | ADR 0042 | referenced only where archive governance is discussed |
| Final-release observer authority reconciliation | ADR 0045 | no relationship; its observer authority rules are untouched |
| Bounded observer cancellation containment | ADR 0046 | no relationship; its cancellation rules are untouched |
| Current gate selection, suites, thresholds, commit-message contract | `repo-map-testing-standards`, `repomap-phase-hygiene` | delegates; does not duplicate procedure |

## Alternatives Considered

Nine alternatives were analysed. Seven were rejected and two were adopted; the
adopted ones are separated below so the section is not read as uniformly
negative.

### Rejected

**1. Frozen expectation as primary authority.** Treat the written contract as
truth and the run as a deviation report. Rejected: it inverts the failure mode
the repository actually suffered. It makes stale assertions authoritative,
licenses editing observations toward the contract, and cannot express "the
contract was wrong", which is a real and frequent disposition.

**2. Observation-layer primacy without a counter-rule.** Let the run define
correctness. Rejected: taken alone this is runtime laundering. If observation
always wins, an expectation can never fail, regressions redefine the contract,
and the suite degenerates into a change detector. D1 keeps observational
authority strictly bounded to what happened.

**3. Producer-only verification.** Verify at the point of production and let
consumers trust the artifact. Rejected: the consumer is what binds the claim,
so trust placed upstream is unverifiable downstream. Status 00751 records the
concrete result — evidence carried but not enforced.

**4. Consumer-only verification.** Drop producer checks as redundant. Rejected:
it discards early, local failure attribution for no gain, and the existing
design already benefits from checking in both places. D2 keeps defense in depth
while assigning the binding duty unambiguously.

**5. Temporary gates as permanent debt by default.** Every gate a phase invents
becomes a standing obligation. Rejected: it makes honest diagnostics expensive,
so phases stop writing them or quietly stop collecting them, and it lets any
phase create repository-wide policy without the owning authority's decision.

**7. Literal manifest preservation only.** Reproducibility means keeping the
bytes, always. Rejected as a universal rule: it is disproportionate for
whole-population claims, and it does not survive contact with reality, since
Gate C's bytes are already gone. D4 scales the obligation to the claim and D8
requires that unreproducible claims be narrowed rather than overstated.

**9. Manual reconstruction of lost authority.** Rebuild the missing set by hand
and treat the reconstruction as the original. Rejected as a restoration
mechanism, and preserved as a labelling rule: reconstruction is legitimate
work, but it produces **new** authority under a new candidate. Presenting it as
the historical set would silently repair a record that should stay honestly
incomplete.

### Accepted

**6. Canonical-first plus explicit temporary evidence.** Adopted as D3.
Collection determines debt; retirement needs obsolescence evidence and owner
authority; promotion follows ownership. It preserves honest diagnostics without
letting them become either permanent tax or unowned policy.

**8. Deterministic selector plus retained manifest.** Adopted for exact-set
claims as D4, with the tool left optional. A deterministic rule plus a retained
manifest reproduces a selection without committing the repository to maintain a
selector tool that one phase needed once.

## Consequences

Positive:

- Which evidence governs is decided once, in the open, instead of per phase.
- Tautological assertions are identifiable by construction: any assertion whose
  observed value traces back to a programmed stimulus violates D1.
- Evidence bypass is visible: a consumer that accepts a declared specialized
  class without a contract verifier violates D2.
- Claims stop overstating themselves. A count is honestly a count.
- Ordinary development is unchanged. Docs-only work still runs diff checks, and
  routine local reruns are not durable evidence.

Costs and risks:

- Qualification records get longer, because identity and provenance fields are
  now required.
- Exact-set claims become genuinely more expensive to make. That is intended
  and will discourage them where a whole-population claim would do.
- Dependency sets are argued rather than computed today, so D6's conservative
  default carries real weight and will sometimes force whole-candidate identity.
- Two known implementation gaps are now formally out of contract — an open
  absence vocabulary and a dispatch that does not fail closed — and remain
  unfixed until a separately authorized phase addresses them.

## Verification Strategy

This is a docs-only change, so verification is the docs-only gate from
`repo-map-testing-standards` — `git diff --check` and `git diff --cached --check` —
plus mechanical checks performed by hand, matching how ADR 0048 was verified.
No source, test, or tool byte changes, and no validator is added.

The cached check only inspects content that is in the index, so both new
documents are staged before it runs; run against an index that does not contain
them it would inspect nothing and report success vacuously. `git show --check`
after the commit covers the same content once it is recorded.

Mechanical checks for this change: 0049 is the next unassigned ADR number and
appears exactly once; the filename, the H1, and the Title section agree; every
adjacent ADR, status, and skill link resolves; the status document uses the next
unassigned number 00753 and has an H1 containing `Exit`; and the ADR README
correction leaves the append-only policy intact. Directory placement is asserted
against the intended local commit date and can only be confirmed against the
committer timestamp after the commit exists, so it is checked post-commit rather
than claimed in advance.

Future conformance is assessed by review, not by tooling. A qualification claim
conforms when a reader can name, from the durable record alone, the
authoritative layer, the acceptance boundary that verified it, the candidate
identity, and the reproducibility payload the claim's scope requires.

## Refresh/Revisit Conditions

Revisit this decision when any of the following occurs:

- a qualification claim satisfies D1 through D8 and still cannot be audited;
- a real RepoMap claim cannot be expressed in the layer vocabulary;
- exact-set claims become frequent enough that a repository-owned selector or
  manifest surface is justified, which D4 and D8 currently decline to create;
- mechanical dependency-set derivation becomes available, which would let D6
  replace an argued set with a computed one; or
- ADR 0047 or ADR 0048 changes an identity, receipt, or retention rule this ADR
  defers to.

## Deferred Work

The following are identified, not authorized, by this decision:

- `verify_executor_evidence` does not fail closed on an unknown
  `semantic_group`; it skips specialized verification and still passes digest
  checks. D2 requires refusal. Fixing this is a source change outside this
  phase.
- Absence and presence state vocabularies in the attempt-evidence layers are
  not closed, so an unrecognized status silently bypasses conditional
  comparisons. D1 requires closure.
- Dependency sets are argued rather than computed. Whether mechanical derivation
  is worth building is left open.
- No archive or link validator is added; ADR 0042's deferral stands.

## Explicit Authorizations And Prohibitions

Authorized by this decision: nothing beyond recording it. Acceptance does not
start an implementation phase, does not authorize the deferred fixes above, and
does not authorize any successor.

Prohibited without a separate accepted decision: implementing these principles
in source or tests; creating a selector, manifest, or validator tool; changing
canonical suite composition, thresholds, or runner exit semantics; changing
Group-A semantics, the failure-notice protocol, timing values, or retry values;
and altering ADR 0048's retention lifecycle or ADR 0047's timing identity rules.
