# RepoMap Qualification Evidence Contract

## Authority and use

[ADR 0049](../adr/2026/08/0049-qualification-evidence-authority-verification-boundaries-and-reproducible-gates.md)
is the architectural authority. This document is procedure that implements
that authority. If this procedure conflicts with ADR 0049, ADR 0049 wins.

Use this contract when a phase will make a qualification claim. It does not
turn ordinary development, diagnostics, or private operational artifacts into
qualification evidence, and it does not restate all of ADR 0049.

## 1. Qualification and ordinary development

- A **qualification claim** is a durable assertion that an identified candidate
  met a named standard under named conditions.
- An **ordinary development result** is feedback from a run used to develop or
  diagnose work. It is not qualification evidence unless its qualification
  attempt was declared before execution.
- **Temporary or diagnostic evidence** answers a bounded phase question. It may
  inform a disposition, but it does not replace the canonical health boundary.
- A **durable acceptance record** is a tracked status, commit, or other
  repository-owned record of the claim and its support. It records a claim; it
  does not prove itself.
- An **operational artifact** is a private run product used for handoff or
  audit, such as a response, report, evidence file, or APG packet. It is not
  durable acceptance authority.

A development run cannot be promoted retroactively. Declare a new
qualification attempt and execute it. A later green run does not erase an
earlier qualification failure. A mixed record on an unchanged candidate is a
flakiness defect that blocks qualification; retain and disposition it, then
requalify before making a positive claim.

## 2. Candidate identity

Every qualification claim names three distinct identity components:

1. repository content;
2. environment; and
3. runner or profile.

For a clean candidate, repository-content identity is the exact commit. For a
dirty candidate it is the base commit plus every staged path and its bound
content, every unstaged path and its bound content, and every relevant untracked
path and its bound content.

ADR 0049 deliberately defers a canonical dirty-content serialization and
digest. A Git-diff digest, patch digest, tree hash, manifest JSON encoding, or
path-ordering algorithm may be recorded as an integrity helper, but none is the
universal dirty-candidate identity. Until a separately accepted decision
defines the canonical serialization, the durable claim must enumerate and bind
the actual dirty content. If it cannot, use conservative whole-candidate
identity.

Claim-scoped dependency sets are permitted only when the set is frozen before
execution, its transitive closure is justified, and the claim records the set.
The closure includes relevant source, tests, fixtures, runner, configuration,
generated inputs, and external identity. If closure cannot be established, use
whole-candidate identity.

## 3. Qualification attempt declaration

Before execution, bind all six ADR 0049 D5 fields:

```text
qualification attempt
attempt identity: <stable identity for this declared window>
candidate identity: <repository content + environment + runner/profile>
environment identity: <recorded runner environment, stated distinctly>
cohort or population: <named suite population or exact fixed set>
stopping rule: <when execution ends>
replacement policy: <none, or an explicit predeclared policy>
```

For a canonical whole-population suite claim, the named suite command,
candidate identity, and recorded runner environment may derive the fields ADR
0049 permits: the suite defines the population, the declaration is the attempt
identity, the stopping rule is one execution of the named command, and the
replacement policy is none. An exact node manifest is not a general ADR 0049
requirement. The accepted ADR0067 PR26-STAGING-CONTRACT1 amendment additionally
requires a sealed exact M/A partition for integration/staging because membership
now determines the applicable measurement obligation. This specialized evidence
does not change ADR 0049's general canonical-suite model.

For a fixed-cohort or exact-set claim, state all six fields explicitly. Record
every execution in the declared window, including failures.

## 4. Managed-run artifact bundle

This bundle is an orchestration-environment convention, not a new ADR 0049
requirement. Its retention lifecycle remains governed by
[ADR 0048](../adr/2026/08/0048-test-harness-resource-retention-reclamation-and-host-admission.md).

When an active orchestration environment supplies an artifact destination, a
managed RepoMap phase or subphase produces this bundle on every terminal
outcome: success, failure, refusal, partial result, hard stop, or
manager-disposition stop.

```text
<PHASE>.response.md
<PHASE>.report.md
<PHASE>.evidence.json
```

The response is the concise manager-facing checkpoint. The report holds
detailed human-readable evidence, reasoning, dispositions, and boundaries. The
JSON file holds structured observations and identities. Use the supplied
destination; repository policy does not prescribe a developer-specific path.

The files are private by default and use mode `0600` where the host and
filesystem support it. Terminal stdout prints each artifact location and its
SHA-256. Stdout is not a substitute for the files, and an APG report is
additional rather than a substitute.

These files are operational/private artifacts. Do not track them merely to
satisfy this convention, treat them as durable acceptance authority, or use
them as the sole support for a positive durable qualification claim. If the
requested bundle cannot be produced, state that reporting defect on whatever
durable surface remains available; terminal stdout does not silently become
equivalent evidence.

### 4.1 Hosted admission and no-execution attempts

Follow the classification and recovery procedure in the
[agent hosted-CI stewardship policy](ci-agent-policy.md). Hosted capacity and
runner admission are a separate evidence layer from candidate execution:

- a no-step run can support neither a pass nor a fail of repository workload;
- local evidence cannot replace a required hosted claim;
- preserve the hosted attempt identity and exact candidate identity even when
  workload never starts;
- preserve a no-execution admission record after a later attempt executes;
- classify quota, budget, runner, workflow, or other exact cause only when the
  available evidence supports it; and
- after capacity is restored, require a fresh trigger or an explicitly
  authorized rerun of the declared current attempt.

A later executed attempt may qualify its exact candidate, but it does not erase
the earlier admission observation or turn that observation into a candidate
defect.

## 5. Durable acceptance record

A positive qualification claim in a tracked status or commit must make these
facts identifiable from durable material:

- the claim made;
- candidate identity;
- evidence producer;
- acceptance boundary and verification performed;
- result; and
- a reproducibility payload proportional to the claim.

A tracked record may cite private artifact or APG digests as audit pointers,
but neither private artifacts nor APG packets may be the sole support. A digest
binds bytes once found; it does not preserve or locate missing bytes. If
load-bearing evidence is not durably preserved, narrow the durable claim to
what survives.

Use an explicit non-acceptance disposition for preserved checkpoints:

```text
maintenance proof / diagnostic proof: retained
final qualification: incomplete
candidate accepted: false
```

## 6. Whole-population canonical suite claims

For a canonical `unit`, `int`, `smoke`, `staging`, or `system` qualification
claim, record at minimum:

- exact suite command;
- candidate identity;
- environment and runner identity;
- suite result; and
- whether coverage was enabled or disabled.

Where coverage applies, keep these facts distinct: pytest status, runner
composed status, line coverage, branch coverage, threshold, the policy or
selector that chose the threshold, explicit threshold decision, and measured
root set. Never attribute a bare exit `1` to test failure or coverage without
corroborating evidence. Smoke is not coverage-tracked; do not invent coverage
data for it.

### Integration and staging: two required obligations

The current [ADR0067 amendment](../adr/2026/09/0067-runner-owned-portable-child-measurement.md#pr26-staging-contract1-amendment--two-required-evidence-obligations)
changes completeness for the whole executed population. Ordinary measured
integration M and predeclared intentional abrupt behavior A must both execute
and pass, with a disjoint exhaustive partition sealed before bodies execute.
Keep exact ordered IDs, parameter cases, declared child roles, actual per-test
records and separate skip/build-deselection records. Missing records, duplicate
execution, stale IDs and teardown failure cannot become successful reconciliation.

Only M contributes coverage, over the unchanged complete product-source
denominator at independent 80/80 floors. A records authentic expected-versus-
observed launch, startup/checkpoint, termination and cleanup evidence; its abrupt
child measurement is unavailable/incomplete. No A parent, child or sibling data
can improve M. Every ordinary child registered for measurement stays subject to
strict start, terminal, readable-shard and content validation. Unit floors remain
85/85. Scoped and no-coverage runs cannot establish this full qualification.

The manager must validate the same-attempt structured obligations report with
the candidate's report validator, as well as the trusted gate's candidate/parent
binding. Both required legs, M measurement/floors, population reconciliation and
cleanup must pass. A step exit code or old `merge_authorized` field alone is
insufficient. See the [trusted-consumer handoff](staging-obligations-acceptance.md)
for artifact custody and the unactivated deployment proposal.

## 7. Exact-set and fixed-cohort claims

For a claim that "these exact nodes or cases passed", retain the ADR 0049 D4
payload:

- selector rule and version;
- exact ordered identifiers;
- manifest bytes and digest;
- candidate identity and environment identity;
- runner flags and coverage mode;
- skip policy and xfail policy; and
- result and failure identifiers.

A count alone is not an exact-set qualification claim. If historical exact
membership is lost, do not reconstruct it as historical authority. A
reconstruction is new authority under a new candidate and construction record,
and must state that the historical set was not recovered.

## 8. Evidence layers and acceptance boundaries

Apply ADR 0049 D1 and D2 at each consumer and claim boundary:

- an expected layer may reject raw observation but can never become raw;
- stimulus is not observation;
- projected or derived evidence cannot become authority for its inputs;
- digests prove integrity, not semantics;
- unknown presence or absence states fail rather than silently skipping a
  comparison; and
- a generic consumer verifies the declared specialized semantic class or
  refuses it, while a legitimate base-contract class is declared explicitly.

The last two bullets are architectural requirements, not descriptions of full
current-source conformance. Current `main` still has the known COV5K gaps: open
presence/absence status strings and an unknown-`semantic_group` path that can
reach digest acceptance without specialized verification. They require a
separately authorized source implementation phase; this procedural document
does not fix them.
