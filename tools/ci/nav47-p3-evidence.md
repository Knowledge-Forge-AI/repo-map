# P3 evidence publication checkpoint

Phase: `REPOMAP-PRODUCT6-NAVIGATION47-P3PUBLIC1`.

## Scope and result

This docs-only milestone publishes the completed D12 P3 evidence investigation
and [proposed ADR 0099](../../docs/adr/2026/10/0099-d12-p3-artifact-evidence-and-remediation-hold.md).
The [evidence report](../../docs/specs/postgresql-d12-p3-artifact-evidence-v1.md)
and [machine record](../../docs/specs/postgresql-d12-p3-artifact-evidence-v1.json)
distinguish prospective-base bytes, source/version candidates and CI72's
existing diagnostic observations. The [roadmap](../../docs/specs/roadmap.md)
keeps D12/P3 and D15 incomplete. No product behavior or runtime pin changed.

The evidence originated in `REPOMAP-PRODUCT6-NAVIGATION47-P3BYTES1`.
All eight inspected Python 3.12.16 blobs match their retained identities and
diff_ids. One 45-case collector check and one whole-set inert audit passed.
The investigation made no image execution or new application build. Review
found the bounded evidence usable, with derived-report corrections; the published
record states the independent-review and parent-correction limits explicitly.

## Verification boundary

Local publication checks cover the exact changed documentation: relative
links/paths, JSON population/arithmetic and source bindings, public/private
reference boundaries, whitespace, staged scope, committed export and custody.
They do not supply new product qualification or coverage.

- Unit/int: not run; docs-only.
- Complete-suite override: absent; zero local complete executions.
- Smoke/staging/system/combined suites and coverage: not run; docs-only.
- Compileall and scoped source static profiles: not run; docs-only.
- Existing unit/integration/static proof and four application-start ceilings
  remain spent. No grant or ledger is reset.

## Hosted CI

State: `AVAILABLE`, retaining the operator's capacity disposition. The current
publication request authorizes one ordinary staging push. The existing open
draft staging-to-main PR supplies its automatic `synchronize` event for
`repomap-release-qualification`. No manual dispatch, rerun, cancellation,
PR-state change, main promotion, tag or history rewrite is part of this phase.

The source/export, pre-review static, unit, staging M/A, native D12 preflight,
system admission, CodeQL and SBOM jobs remain unchanged. Normal hosted setup
may run under its existing limits. The spent ordinal-72/attempt-1 system grant
must refuse a successor before system SDK or application work. Therefore
`main-system-gate` is expected to fail at `d12-system-hold`, making the overall
workflow red even if every other job passes. This is a source-based forecast.
P3/image/native
acceptance remains false; no fifth application start is authorized.

This record is committed before publication, so the successor hosted execution
is pending here. CI72 was `EXECUTED_FAIL` at its deliberate P3 acceptance hold;
its successful diagnostics do not make it a qualified image. Local docs checks
cannot replace any required hosted result. The new campaign's exact commit,
run identity and observed state are recorded by the publishing parent after
the remote event, without claiming a pass before workload execution.
