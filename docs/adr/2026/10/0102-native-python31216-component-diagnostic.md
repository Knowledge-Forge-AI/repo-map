# ADR 0102: Native Python 3.12.16 component diagnostic in the existing CI lane

## Status and authority

The operator selected A from the Trixie continuation packet on 2026-10-27.
Bounded phase authority is accepted. The parent accepted this concrete design
after independent review, with the binding conditions below, before implementation.

Phase: `REPOMAP-PRODUCT6-NAVIGATION47-AMDPROOF1`.

## Context

The local source checkpoint retains Python 3.12.16 and ADR 0101's finite glibc
acceptance. Its ARM payload observation cannot establish AMD imports. The
new AMD default remains unobserved and refused. The current native lane runs
one canonical E1/E4 integration owner. Its ordinary dependency-runtime
prerequisite encounters that held default before the raw base can be observed.
An extra canonical invocation would violate the lane's one-runner contract.

## Decision

Retain the existing native job, named owner, merge/source/environment binder,
report export, uploader, one canonical runner invocation and all gates. Add
one component observer inside E1 exploration immediately after native engine
facts and before trust/closure/builder work. It reads the pinned raw base and
never builds or materializes an image. The native job and its canonical source
fragment select the existing exact-ID raw-image override. Require that exact
AMD config once in the workflow command validator; do not accept arbitrary,
duplicate, missing or cross-platform overrides.

The approved Python index is
`sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e`.
The AMD manifest is
`sha256:6d2b0577e6d1632f077331de8e4780535f54839d163ded7abb4b7dd37b5d37ac`,
and its config is
`sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28`.
The frozen ARM hierarchy is included solely to verify the shared observer
natively on the local ARM environment. No ARM result supplies AMD evidence.
The exact public metadata envelope has SHA-256
`9781988ca058dcee40e7818be04843aedfdaec43fd5ab5fb1816fdb4a7fd2ce1`.

## Component contract

Before image execution, verify the real daemon is native for the requested
Linux platform. Verify the envelope hash; each raw index/manifest/config hash;
the one platform descriptor and config relationship; observed image config ID,
RepoDigest, image OS/architecture and exact rootfs diff IDs. Missing, wrong,
ambiguous, altered or foreign identities refuse before container creation.

Use one run-owned, network-less container on that exact config ID. Run the
current source payload contract under Python -I -B with assertions enabled.
Print and retain the actual raw no-exclusion observation before modification.
Only the already frozen native `_tkinter` path, size, ELF machine and SHA may
be removed. Derive the diagnostic explicit exclusion from that actual native
observation, never a historical or foreign import tuple. Pass this test-only
mapping explicitly to the payload contract; never edit its global/default map.

Require the expected raw refusal, exact sole removal, no surviving digest or
mode changes, complete retained imports, LD_BIND_NOW linkage, no unresolved
libraries, real shared-library ownership, Python version/banner and native
machine. Host validators independently check the returned raw/trimmed contract
and preservation facts. Reject incomplete, malformed, duplicate or conflicting
observations. Default AMD enrollment must remain absent throughout.

The mutable report slot `steps.python31216_component` is installed before
execution and retains partial/refused outcomes on failures. Return an observed
component only after ledger and Engine cleanup verification and zero operation
delta. Record actual before/after counts and omit raw container IDs/private
host paths from public data. Original execution errors and cleanup failures
remain failures; cleanup cannot promote a failed probe to success.

E1's existing exploration writer retains this slot in its bounded canonical
report even if subsequent legacy closure refuses the held AMD default. The
existing host sealer copies the exploration report without changing its
qualified/result rules. The parent validates the component record separately;
a workflow pass, refusal-path pass or legacy E4 status is never substituted.
Limits remain 1.5 MB per part and 5 MB total, including cleanup reserve.

## Execution and preserved boundaries

One staging publication and one automatic CI campaign are authorized. Existing
ADR 0092's unchanged per-job initial cold SDK setup remains at most one, with
its existing intent/identity accounting and zero retry. No SDK recipe change,
local SDK build/rebuild or additional hosted setup is introduced. Local checks
must reuse the verified cached ARM SDK and stop on a miss. The existing five
frozen harness acquisitions per canonical integration invocation are disclosed.
No dependency-runtime materialization is needed for the new component probe.

Use exact scoped unit/static checks and one native ARM integration owner for
the changed shared observer, all --no-coverage. The standalone integration
owner exercises the same observer; it adds no optional marker or deselection
policy. Preserve all debt and coverage ceilings. There is no local complete
suite, local AMD emulation, new dependency/lock, application build or retry.
Four historical application starts remain spent; the CI72 grant is untouched.

The combined workflow may remain red. Other P3 findings, final image evidence,
application build authority, image acceptance, D15, main promotion and tags
remain separate. Collect the single campaign's terminal records without
rerun/cancellation and stop for the resulting-state decision. Update existing
draft PR metadata for the actual source checkpoint when publishing; no new PR.

## Alternatives and rollback

Retaining the current prerequisite path cannot observe the held AMD payload.
Adding a second runner or job changes the one-owner/one-invocation policy and
is unnecessary. Automatically adopting observed AMD imports would conflate
diagnostic observation with reviewed source admission. Replacing Trixie or
accepting other P3 risks is outside the selection.

Rollback is a normal forward source correction removing this added diagnostic
hook and exact raw-base selection; preserve all published observations and
failure records. Do not rewrite a reported commit, rearm a spent grant or
convert diagnostic proof into image qualification.

## Binding design-review conditions

B1. Component outcomes have their own channel. Recoverable Docker, validation
and cleanup errors are retained as refused/partial component records; they
never append a new stage to E1's existing `refusals`, and the legacy chain
continues unchanged. The existing hosted parser accepts only the established
libpq/trust/closure/builder/final refusal prefixes. Never claim a successful
component after any probe or cleanup failure. Canonical process-control
exceptions remain cancellation/abort events: retain the partial record and
perform exact cleanup before propagating them, rather than swallowing them.
The canonical runner's final custody and failure semantics remain authoritative.

B2. The native CI command validator rejects every pre-separator option that
is not an exact full allowlisted option. Require one exact raw AMD config;
reject abbreviations, unknown flags, duplicate or conflicting values, missing
values and foreign inputs. Preserve variable-expansion, one-invocation,
no-loop, exact-node and all other existing command obligations. This changes
the named job's exact command contract, not argparse or general runner policy.

B3. The standalone integration owner is a local native ARM proof only. On
AMD it verifies the ARM refusal before image access and emits a distinct
non-qualification record. It adds no second AMD probe to the ordinary staging
population. The admitted E1 path is the sole AMD component observer in this
campaign. Ordinary ARM integration also retains the older ARM owner; these
overlapping observations are disclosed and not counted as independent image
qualification.

B4. The local shared-observer proof command is exactly scoped:
`python3 tools/run_tests.py --suite int --no-coverage --jobs 1
--pg-container-port 55433 --smoke-image-reference
sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3 --
src/test/int/python/repomap_kg/runtime/d12_native_python_proof.int.test.py::test_native_python31216_component`.
Reuse the verified cached ARM SDK. Any SDK build, dependency-runtime ensure/
materialization, application build or nonzero inner build/pull counter stops
acceptance; canonical setup pulls stay separately accounted.

A1-A3. Use a dedicated create/cleanup/verify sequence and actual run-boundary
counts/ledger readback, not E1's action-before-cleanup helper. Independently
verify observed image/config/RepoDigest/rootfs and selected exact override;
an environment variable alone is no identity proof. Test canonical indented
report size against the retained real ARM observation and the existing part,
total and cleanup-reserve limits. Bound component capture and retain a
refused/partial record on overflow instead of losing the exploration report.

A4-A7. The requested platform comes from admission, never inferred from the
daemon. Check the duplicated ARM manifest bytes against the older ARM helper.
When the legacy closure supplies a raw baseline, compare its entry count,
digest and imports against the independent component observation, retaining
any conflict in the component channel. Component strings contain no private
host paths; existing redaction/provenance refusals are preserved.
