# ADR 0165: Bounded operator resource reports

## Status and date

Accepted parent W7 phase decision, 2026-11-07, under the operator's instruction
to continue the roadmap after passing CI126. Independent design review found
no blockers; the parent sealed its thirteen implementation clarifications in
the [report specification](../../../specs/cloe-resource-reports-v1.md).

Canonical phase: `REPOMAP-CLOE-RESOURCE-REPORT1`. The accepted roadmap reserves
this specific namespace. Public source companion records live under tools/ci;
private historical status material is not copied into the public tree.

## Context and decision

ADR0159's internal resource view has no operator delivery or offline inspection.
W7 owns this follow-up public selection. Reuse its bounded identity-free payload
with a strict domain reader and new-only private file delivery; attach only by
explicit option at six existing single-operation CLI seams. Extend the internal
view to lexical query/revoke without changing subject defaults or transactions.
Keep context projections Local-safe and correct the identified sealing FD
ownership gap. The specification defines exact custody, privacy and refusal
semantics before implementation.

Report delivery follows the business outcome and never enters publication
handlers. Metadata-only output safety checks are explicit opt-in IO; reports
cannot be placed under configured sources or managed runtime namespaces.
Format validity is not authenticity or evidence of an executed measurement.
Future public vocabulary growth requires a schema bump.

## Alternatives and limits

Stdout augmentation would break existing machine consumers. Unbounded result
dumps expose private identities. Overwrite/rename delivery risks existing files.
Writing before capture perturbs source identity. Implicit discovery exclusions
change ingestion policy. All are rejected. No dependency is needed beyond the
existing standard-library and product facilities.

No numeric governance/SLO, schema/MCP/worker, native parser/model, installed
package, live runtime, complete local suite or image acceptance is authorized.
Full W7 remains open. Hosted publication needs separate final candidate binding;
this ADR grants no application build or automatic retry.

## Verification and rollback

Use the specification's exact scoped unit/connected integration plan and
independent resulting-state review. No-option behavior must remain compatible.
Disable the opt-in path or correct forward on regression; never rewrite
reported history or delete operator files. Hard coverage and debt policy stay
unchanged; desired margins are measured only in hosted CI.
