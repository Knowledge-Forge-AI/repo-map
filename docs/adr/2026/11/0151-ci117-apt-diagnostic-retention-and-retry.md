# ADR 0151: CI117 APT diagnostic retention and fresh staging attempt

## Status

Accepted under the operator's explicit instruction to repair failed CI117 and
try again. This is a new operator-directed campaign, not automatic rearm of
ADR 0150.

## Context

CI117 passed unit, static, source/export, SBOM and CodeQL lanes. Its three
container lanes failed while preparing the same SDK recipe, before entering
the application builder or container test populations. Retained diagnostics
identify APT prerequisite refusal and package resolution, but discard the
canonical helper's already-redacted explanation. Output digests cannot recover
that explanation. No exact package conflict has been established.

The unchanged pinned base resolves the requested graph in a native ARM
simulation and in a native ARM solver using verified inert AMD package
metadata. Neither probe installs packages, builds an image, executes AMD code
or establishes native AMD qualification. The first ARM probe had invalid
capability restrictions, and an initial metadata probe had a fixture syntax
error; neither is evidence of the CI cause. Negative refresh fixtures already
fail closed, and an alternate snapshot endpoint refuses access. These results
do not justify speculative dependency, mirror, retry or resolver changes.

## Decision

Repair the confirmed loss of actionable failure evidence. Retain only the
canonical `apt prerequisites refused:` line, allowing the numeric BuildKit
progress prefix and removing terminal color escapes. Apply the existing
canonical redactor again before the existing size bound. Retain the source
line's byte count and SHA-256, alongside existing full-stream identities and
closed reason codes. Do not publish arbitrary surrounding build output,
arguments, environment values, private paths or URLs. Successful builds do
not report echoed failures. Preserve primary exit status and single-attempt
behavior. SDK recipe, helper, pinned base and dependencies remain unchanged.

After exact scoped unit and containerized integration proof, static/privacy
checks, independent `dynamic_default` review and an exact-commit report, permit
one ordinary staging synchronization for CI118 attempt 1. Keep public main
and draft PR state unchanged. No manual or duplicate workflow trigger.

CI117's native seal has null application counters because SDK preparation
failed. Those nulls remain unknown fields, not zero-valued native receipts.
The job's failed SDK step and skipped downstream steps, together with the
unchanged prepare-before-build control flow, establish that the campaign did
not enter the application builder. System likewise stopped at SDK setup.
Retain this distinct parent observation and its supporting artifacts. Actual
cumulative starts remain 28; the unspent 29th start may be reserved for CI118.
Keep cumulative caps 29/29 and all historical rows unchanged, reject CI117's
nonce/reservation, and bind fresh approval, nonce and reservation identities.
No CI119 rearm, application start 30 or automatic retry is authorized.

## Verification and boundaries

Use exact unit and containerized integration selectors with `--no-coverage`.
Cover both output channels, BuildKit formatting, redaction before bounds,
noncanonical context refusal, successful output refusal, and a real failed
subprocess retaining its cause without retry or a real image build. Retain
grant denial and cross-process admission proof with all debt ceilings intact.

Hosted CI owns complete populations, candidate coverage and actual SDK/system
qualification. Existing hard floors and 87/82 goals remain unchanged. The
specific CI117 SDK failure remains unresolved until fresh hosted evidence.

No new dependency, lockfile, test-runner policy, local SDK/application build,
complete local suite, candidate coverage, model/scientific acceptance,
production admission, main promotion, tag or history rewrite.
