# ADR 0099: D12 P3 artifact evidence and remediation hold

## Status

Proposed remediation design; evidence recorded for public review. Publication
of this proposal does not accept a runtime finding, image, native platform,
merge or deployment, or authorize implementation or another application build.
Existing accepted ADR 0087 and ADRs 0088–0098 remain in force, including
ADR 0088's conditional-preflight boundary.

## Date

2026-10-27

## Context

CI72 built and passed its five diagnostic system phases, then correctly failed
the unaccepted P3 hold. Subsequent bounded inert inspection of the prospective
Python 3.12.16 AMD/ARM base reduced package/file/payload uncertainty without
executing an image. The [evidence checkpoint](../../../specs/postgresql-d12-p3-artifact-evidence-v1.md)
and [machine record](../../../specs/postgresql-d12-p3-artifact-evidence-v1.json)
state exact identities, source/byte distinctions, review limits and residuals.
No new base is admitted. Four native AMD application starts remain spent.

## Proposed decision

Retain the D12/P3 hold. The inspected base still contains glibc
2.41-12+deb13u4. These are Python build-stage observations: the final image
uses the PostgreSQL base and takes its Python payload from `/usr/local` in
the Python stage.
Its glibc and CA store require separate PostgreSQL-base evidence; changing the
Python base cannot by itself clear final-userland findings. Python 3.12.16 addresses the named upstream SSL advisory but
does not clear all Python, libc, vendor, CA-trust, license or provenance gaps.
Source-package/version and vendored-subset candidates are not automatically
confirmed final-image findings. Numerical conflicts and unknowns remain;
each residual needs supported classification/remediation or its own written
operator disposition under [ADR 0087](0087-d12-image-evidence-and-core-security-prerequisite.md).

Before later implementation, bind available supported fixed inputs and exact
OCI identities, update all affected frozen recipe/payload/allowlist/grant
owners, review compatibility/license/support/lifecycle and rollback evidence,
and obtain exact scoped proof/acquisition/build/publication authority. Keep the
complete release probe and spent/stale/wrong-event grant refusals. Prefer exact
supported replacement bases over an in-image essential-libc upgrade that would
violate the existing frozen-baseline refusals.

Future actual platform execution remains native public-CI work. Inert archive
inspection is neither emulation nor native ABI/import qualification. Preserve
the deferred ARM acceptance boundary and the incumbent comparison's existing
owner in [ADR 0091](0091-d12-tls-p3-disposition-and-trixie-remediation.md).

## Scope and non-scope

This phase publishes diagnostic evidence, a proposal and roadmap status only.
It changes no product/test/tool source, dependency or lock, image/SDK pin,
workflow, coverage/debt threshold, package version or runtime. Dynamic C
Psycopg 3.3.6 with distribution-owned shared libpq remains required; static or
private bundled libpq is not introduced. The current recipe's removal of
build-only pip/vendor payload remains mandatory and needs proof with any new
pin; removal alone does not dispose builder-stage or Debian CA-trust risks.

The existing four-start application ledger is not changed. There is no new
grant, fifth start, retry/reset, local complete suite or source-proof allocation.
The ordinary public workflow is expected to refuse a successor application
build using its spent ordinal-72/attempt-1 grant before system SDK/application
work. That is an admission forecast, not a hosted pass. Publishing documentation
does not convert diagnostics into image acceptance or authorize main promotion.

## Required future owners and evidence

The exact decision must cover runtime release/payload and candidate-manifest
owners, native hosted admission/proof owners, and their connected unit and
containerized integration tests. New OCI identities require updated bindings
even where `_tkinter` bytes happen to match the old exclusion. Preserve strict
module/ELF/shared-library/package/license checks, unchanged archive restore
semantics, spent-grant refusal, exact resource cleanup and original debt caps.
No new selectors or execution counts are granted by this proposal.

## Alternatives and rollback

- Wait for supported fixed inputs and retain all current holds (recommended).
- Seek separately specified per-finding operator dispositions; this proposal
  supplies none and cannot waive missing provenance/license/ABI evidence.
- Select a different distribution or custom patch only through a separate
  supported design and exact authority; neither is selected here.

This documentation changes no data or runtime. A later rejected source change
must be reversed forward without rewriting public history or rearming a spent
grant. No affected predecessor is automatically accepted as a rollback target.
