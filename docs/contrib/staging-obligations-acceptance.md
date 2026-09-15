# Staging obligations: report acceptance and trusted-consumer handoff

## Authority and claim

The operator approved Decisions A and B for PR26-STAGING-CONTRACT1. The
[ADR0067 amendment](../adr/2026/09/0067-runner-owned-portable-child-measurement.md)
requires ordinary measured integration M and intentional abrupt behavior A.
Both behavior obligations must execute and pass. Only M provides verified
measurement at 80/80 over the complete product-source denominator. A's child
measurement is unavailable/incomplete and no A data enters M. Unit remains
85/85. This is a changed completeness policy for the executed population.

This document authorizes neither a hosted attempt nor deployment. QUAL1–QUAL6
remain consumed historical attempts. A later exact-candidate request must
explicitly adopt this policy and disposition trusted-consumer compatibility.

## Trusted executor inspected separately

The reference staging base is
`78e99c4bf53b51b5e81df4b65f356fe992360f19`. Its
`.github/workflows/repomap-staging-gate.yml` preserves the trusted
`tools/ci/gate_contract.py`, verifies the approved merge parents, and invokes
the candidate's canonical command once:

```text
python3 tools/run_tests.py --suite staging --hygiene-profile exhaustive
  --declared-complete-gates 1 --operator-attest-exclusive
  --operator-attest-pressure-degradation --pg-container-port 55433
  --sandbox --report --report-dir <workspace>/ci-test-report
```

The workflow delegates ordering, coverage arithmetic and operation accounting
to that runner. It can therefore execute both new obligations through the same
command without a workflow change. Candidate workflow copies are not the
trusted executor of their own qualification.

This is invocation compatibility only. PR26-STAGING-CONTRACT1-FIX1 isolates the
collection-only seal in an invocation-owned child. Its imports cannot populate
M's module cache; M measures its own genuine collection and workload. Discovery
executes no test bodies and contributes no measurement data. Validate the exact
ordered raw/eligible/deferred population and request/source binding before M/A,
and require both actual legs to reconcile with that same immutable seal. Missing,
invalid, stale, cross-run or unsuccessful discovery must block execution with
owned cleanup and no retry.

Discovery uses the current interpreter with isolated startup, then copies the
caller's effective source/support/tools search paths into the child only. The
request binds cwd, pytest arguments, declarations, invocation/source identity and
test-owned environment, including Go helper and sandbox/PG container inputs.
Coverage bootstrap and Go coverage-output variables are excluded. Request and
receipt are invocation-owned regular files, each limited to 2 MiB; receipt hashes
bind the exact request and ordered collection. The collection bound is 120
seconds, followed by at most two five-second process-group settlement windows.
There is no inherited discovery deadline in the existing caller interface.
Output streams use the null device. For a failed child, require a validated
receipt digest, exception type and population counts in the refusal detail, or
an explicit unavailable/mismatched-receipt reason. Partial node lists and raw
collection tracebacks are not retained. A failure receipt never admits M/A.
Isolated startup ignores Python environment options, which are not forwarded.
The child's independent hash seed may expose hash-sensitive collection ordering
as a refusal; exact ordered equality remains required. Manager disposition of
that risk and the unmeasured 120-second bound precedes another staging attempt.
No retry, real-population execution or measured credit is inferred here.

Isolation supersedes 00886's deferred cached-import risk. Hermetic tests do not
quantify recovery in the live population or guarantee the unchanged 80/80 floors.
Neither adding seal hits nor lowering floors is approved; actual hosted M/A
qualification remains pending until separately authorized and executed.

The old trusted result derives its conclusion from `steps.staging.outcome`.
It has no staging policy revision or staging report digest binding. Existing
`system_report_sha256`/`system_binding_sha256` fields apply to main-system and
cannot be reinterpreted as staging evidence. A step exit alone does not validate
the richer report contract.

## Manager acceptance procedure

1. Verify the trusted gate request/result and exact tested candidate SHA/tree
   and approved base/head parent relation. Confirm the later authorization
   explicitly adopts the two-obligation policy and the consumer disposition.
2. Recover **both** `repomap-ci-gate-result-v1` and
   `repomap-staging-gate-report` from the same run and attempt. The latter uploads
   `ci-test-report` and is retained for **14 days**; the gate result is retained
   for **90 days**. Preserve the actual report bytes and member digests before
   expiry. The longer-lived result cannot replace an expired report.
3. Use the candidate's structured obligations validator, also used by the
   producer, to validate policy, candidate/source, invocation and population
   identities. Compare these identities with the trusted result and the actual
   published candidate, not merely another report's self-description.
4. Require the sealed exact S/M/A partition to reconcile with actual records,
   including parameter cases and separate skips/build deselections. Require
   smoke and both required behavior legs to complete and pass; preserve setup,
   call and teardown failures without duplicate counts.
5. Require M's valid same-invocation measurement over the complete denominator
   above both 80% floors. Refuse unavailable ordinary measurement. Verify each
   A role's actual launch/start/checkpoint, expected-versus-observed deliberate
   termination and cleanup, with unavailable/incomplete child measurement.
   No A parent or sibling hits may contribute to M.
6. Require all supervisor, resource, security and export obligations to pass.
   Missing legs, missing fields, identity drift, blocked execution, inconclusive
   cleanup or absent report bytes refuse acceptance. Preserve the failed
   evidence; never obtain a preferred result by an unapproved repeat.

A report validator establishes the declared contract, not independence from
candidate code. Candidate/parent custody and the manager's source review remain
necessary. A green old `merge_authorized` field cannot bypass this procedure.

The same CLI validator used by local controls is:

```text
python3 tools/staging_report_contract.py
  --report ci-test-report/staging/latest/staging_contract_report.json
  --commit <trusted-tested-candidate>
  --source-sha256 <independently-derived-source-digest>
  --invocation-id <same-attempt-invocation>
```

Default success requires qualification; `--validate-only` checks the schema and
must not be substituted for acceptance. The report schema is
`repomap-staging-obligations-v1`, policy
`ADR0067-PR26-STAGING-CONTRACT1-v1`. `summary.json` embeds the obligations and
HTML displays M/A with a link to the authoritative same-invocation JSON.
An incomplete collection/refusal report is intentionally persisted even though
it cannot pass schema/acceptance validation.

In particular, smoke refusal records failed smoke and blocked M/A with no sealed
population. The validator reports a schema refusal for this incomplete artifact;
it is preserved failure evidence, not a successfully validated negative report.
The staging `smoke: passed` field currently depends on the canonical caller's
observed zero smoke exit and early return on failure. Direct invocation of the
lower-level paired execution helper is not independent smoke evidence.

Covered `int`/`staging` also requires a nonempty passing Go statement summary from
M at its existing 80% floor. `evaluate_go_integration_gate` returns no summary only
for ineligible suites or `--no-coverage`; missing setup/data is already a failing
summary. This condition does not add a new canonical Go floor. Requested HTML
rendering failure fails the aggregate while retaining substantive JSON records.

`runner_integration_execution.candidate_identity` defines the source digest:
ordered Git-listed tracked and nonignored candidate files under `src/main`,
`src/test`, `tools`, and `pyproject.toml`, binding each relative filename and its
SHA-256 bytes. The manager derives it from the actual tested checkout. The
partition digest binds ordered collected/required/M/A/deferred lists; separate
measurement session identities bind ordinary child receipts to their leg.
No inherited historical population total is used as completeness proof.
Full covered `int` executes M/A without smoke and reports `not_required` for
smoke. Its successful integration outcome does not claim a staging gate passed;
the staging acceptance predicate additionally requires smoke success. Scoped
selectors and `--no-coverage` can succeed as diagnostics but cannot qualify.

## Separate minimal deployment proposal — not activated

If automated trusted consumption is required, separately review and deploy only
the following closure on the trusted executor:

| Owner | Proposed change |
| --- | --- |
| `.github/workflows/repomap-staging-gate.yml` | Preserve the approved staging validator before candidate checkout; pass the exported same-attempt report and binding to trusted result recording; refuse missing reports. |
| `tools/ci/gate_contract.py` and its extracted result/CLI owners | Add an explicitly versioned staging policy/report binding, analogous to the main-system digest relation; compare trusted candidate/parents and require validated paired success before authorization. |
| Trusted gate contract unit owners | Prove missing, foreign-attempt, mismatched-policy/source, missing-leg and incomplete-measurement refusals alongside positive bound-report acceptance. |

Do not silently add fields to the old closed schema or deploy a candidate-only
bypass. A separate approval must identify the exact trusted closure, compatible
request/result versions, rollback to the prior executor, and manager handling of
old reports. No workflow, gate-contract, dispatch-ref, runner, permission, secret
or base-branch change is made by this implementation phase.
