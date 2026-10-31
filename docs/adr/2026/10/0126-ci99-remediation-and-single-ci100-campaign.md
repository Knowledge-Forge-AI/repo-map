# ADR 0126: CI99 remediation and one CI100 campaign

## Status

Accepted for the bounded repair and publication described below. This is the
parent's interpretation of the operator's current retry request, not a numerical
operator reply or a standing retry allocation. Install this ADR only after the
source-repair dispatcher has closed and its checkpoint has been reviewed.

## Date

2026-10-30

## Context

CI99 attempt 1 executed on public staging `3c326f2`, test merge `fc464cf`.
Source/export policy, static enforcement, both CodeQL jobs, vulnerability scanning,
native AMD preflight and the assembled-system job passed. Unit reported 27 failures
and 29 setup errors; measured integration reported seven failures. Remaining
cutover consumers expected old CLI/distribution/resource values, one static-input
test namespace had been changed incorrectly, and the observer freeze still pinned
the predecessor tool bytes. The source repair is substantive and separately
reviewed under ADR 0125; documentation alone cannot remediate these failures.

Observed unit coverage was 88.1% line and 87.7% branch; measured integration was
90.1% line and 82.2% branch. Those values exceed the existing gates by at least
two points. They do not qualify a successor or erase failing assertions.

The retained system intent and qualification artifact establish one actual
sixteenth native AMD application build, exact candidate binding and terminal
cleanup. Every earlier spent start and reservation remains spent. ADR 0124
forbids an automatic seventeenth start. The operator has now explicitly requested
another repair/publication attempt and requested the dogfood dispatcher in
`dynamic_default` mode.

## Decision

The current request authorizes one reviewed source correction and one ordinary
staging synchronize push through existing draft PR 23. This creates CI100 attempt
1 with a fresh nonce, reservation, before/head/base and frozen build context.

Permit at most one additional native `linux/amd64` application start: cumulative
total and platform ceilings increase from 16 to 17. All sixteen observed starts
remain spent. The new allocation cannot be released, reused or automatically
rearmed. No eighteenth start, attempt 2, second push, duplicate trigger or automatic
retry follows from this ADR. A new failure requires disposition under a new request.
The unchanged hosted SDK may materialize once under its existing identity and
cleanup rules. No local application/SDK image build or external pull is admitted.

Keep the existing system builder, native-host/event/two-parent proof, complete
source/context hashes, exclusive reservation consumption, secure I/O, terminal
cleanup, closed schemas and every historical refusal. Add the CI99 nonce and
reservation to both spent-identifier refusal paths and preserve all older cases.
Reject CI99's allocation, future ordinals, and ceilings above or below this exact
campaign. Historical namespace, scope and export authorities are unchanged.

## Verification and boundaries

Use exact scoped unit and authenticated containerized integration owners with
`--no-coverage`, followed by retained static enforcement and independent review of
the frozen resulting source and grant. Complete local suites and Python project
coverage remain unselected. Hosted CI owns the complete populations and fresh
coverage. Preserve the hard gates and the two-point target.

The dispatcher uses `dynamic_default` and returns a local checkpoint. The parent
owns the final grant binding, commit, exact-commit report and single publication.
No active dispatch is interrupted. Keep the protected checkout's HEAD, index,
staged entries and pre-existing files unchanged. Public commits use
Samuel Leighton Lair <sam.lair@knowledge-forge.ai>.

No dependency, backend, supplier pin, SDK recipe, graph/storage/MCP contract,
live home/service/client, repository rename, main promotion, tag, deployment or
package-manager publication is authorized. The accepted finite compatibility
boundary and sealed namespace ancestry remain intact.
