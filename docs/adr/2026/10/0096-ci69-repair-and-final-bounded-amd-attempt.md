# ADR 0096: CI69 repair and one final bounded AMD attempt

## Status

Accepted design before implementation. Operator Route A approved; independent
engineering design/ADR review and parent design acceptance completed on 2026-10-26. This record accepts no implementation, image, P3 finding,
platform, merge or deployment result.

## Date

2026-10-26

## Context

CI69 executed for public staging 51a3e055b3ea35dc4e9f0bba7966e4799881b159.
Its unit suite failed one stale literal forward-admission expectation while
coverage exceeded 87/87. Integration tests passed, but an unregistered isolated
Python child invalidated ordinary measurement; abrupt leg A remained blocked.
The assembled-system builder passed admission and same-daemon preflight, then
failed at the final release probe. It consumed the one-use AMD application
allowance despite failing to produce a final image. Terminal cleanup passed.

The final probe rejects every gcc-prefixed package, including the observed
gcc-14-base 14.2.0-19 amd64 base-support package. Debian's
[package record](https://packages.debian.org/trixie/gcc-14-base) and
[file list](https://packages.debian.org/trixie/amd64/gcc-14-base/filelist)
identify documentation rather than a compiler payload. This is a confirmed
probe defect. The build's first exception was lost behind a long repeated
BuildKit command in the final 2,000 stderr characters; it is not uniquely
attributed to that defect. Isolated stdlib child launches provide a strong
coverage mechanism hypothesis, not a uniquely proved child attribution.

ADR 0095 reserved unchanged release.py/local rendering and one AMD build with
no retries. The operator separately approved the bounded corrections and one
additional AMD attempt. This ADR supersedes only those narrow boundaries;
ADR 0095's historical body and every other hold remain unchanged.

## Decision

1. Correct the literal FORWARD_ADMISSIONS expectation for the committed
   D12SYSTEM1 admission. Preserve the executable lineage audit, every inherited
   authority record and ownership/selection join.
2. Isolate only the controlled D12 stdlib proof-writer and flock children from
   inherited Coverage startup state using the existing child-environment owner.
   Keep product-executing children measured/registered and the measured parent
   environment unchanged. Preserve real proof/mode/O_EXCL/LOCK_NB/cleanup and
   refusal assertions. A cohesive test-support child-lifecycle owner may provide
   headroom; no generic arbitrary unmeasured snippet interface is introduced.
3. Correct the shared final release probe under an explicit rendering exception.
   Only gcc-14-base at version 14.2.0-19 on amd64 can receive the base-support
   classification, after package/file observations establish the exact known
   documentation-only payload, no executable/header/ELF/symlink payload and no
   unclassified verification problem. Other old compiler/development-package
   refusals remain. No package, dependency, image pin or supplier substitution.
   Preserve every libpq owner/hash/version/ABI/dynamic C linkage, Python import,
   license and build-only-module assertion. None/empty product manifest defaults
   remain unresolved. This is no generic or ARM admission.
4. Create readable headroom by moving the complete embedded final-probe helper
   program from release.py into the existing Python/final-image payload owner
   python_payload.py, preserving its release facade and adding the narrow check
   there. No unrelated module or parser is introduced. Record the actual clean
   cohesive move without changing old decomposition records or debt ceilings.
5. Retain useful build failure context within the existing 2,000-character error
   envelope. Prioritize actual exception context over repeated command/source
   echoes, annotate omissions and retain stdout fallback. Keep SystemTestError,
   existing sidecar byte ceilings, iid/cleanup custody and canonical gate schemas.
   A bounded excerpt does not promise the complete build log or traceback.

## Additional AMD authority

The original human-authorized maximum remains two application starts total.
CI69 consumed the first AMD start. Exactly one additional native AMD start is
approved through the existing sole main-system builder, making AMD's narrowly
admitted cumulative maximum two. Starting it exhausts the total allowance,
including failure, timeout, cancellation and uncertain start. No further retry.

Preserve the original parent ledger fields, default one-per-platform rule and
CI69 reservation/consumption. Record this exact AMD-only operator exception
separately. Generic/ARM remain held. No fresh runner or nonce resets history.
Bind a new canonical reservation to the actual cumulative ledger and operator
approval, the changed frozen source/recipe/Dockerfile and unchanged SDK identity.

The one-use grant is limited to existing draft PR 13 synchronize from
51a3e055b3ea35dc4e9f0bba7966e4799881b159 against unchanged main
24d15650a2d4563d188acb8bbf34a0dabf8f3d65, workflow 70/attempt 1 and the actual
future merge/head/tree. Fresh remote drift refuses. Grant/proof v1 key sets stay
closed; use real fields and canonical SHA bindings, with no key/signing service.
Pin the approved decision SHA separately from the reservation digest and reject
the spent CI69 nonce/reservation explicitly with full-match hex validation.
Old 69, later ordinals, reruns, wrong parents/approval/ledger, stale source,
duplicates, racing/reused intents and unsupported platforms refuse.

Host admission remains before SDK work; actual inner-daemon native preflight
remains before intent. One fsynced exclusive intent, one managed builder/image
and one resource ledger apply. Compose cannot build or pull. Failure-safe exact
cleanup and truthful diagnostic reports remain mandatory.

## Verification and publication

Use the approved exact 40 unit paths and both existing container integration
owners with --no-coverage, plus the existing ten-check static profile and clean
affected-owner enforcement. Cumulative ceilings are unit 9/integration 7/static 11,
with RED 1/diagnostic 1 unchanged, preserving all prior attempts. Run one first;
repeat only after a finding, correcting source and independent disposition.
No unchanged passing rerun, complete local suite, local Python coverage or local
SDK/application build/pull is included. Existing canonical Go prerequisites are
distinct from a standalone campaign.

Tests exercise the actual embedded package predicate, child-observed environment
and real proof/lock/cleanup boundary, not copied predicates or a self-reported
computed environment. Actual GCC metadata/payload negatives and realistic
bounded BuildKit failures are required. Scoped evidence does not establish a
native assembled image or whole-population coverage.

Complete independent resulting-state review and fresh parent source/proof/custody
acceptance precede the exact public phase commit/report, committed export checks,
fresh remote binding, reservation and one ordinary staging fast-forward push.
Use the existing PR's automatic campaign only. No manual dispatch/rerun, PR-state,
main/tag/history mutation, infrastructure, emulation, new SDK, pgvector or live
runtime/graph deployment follows. Public main remains preview 0.0.3.

## Residuals and alternatives

P3 and the incumbent comparison, image/platform acceptance and merge authority
remain unresolved/false. System scenarios can collect diagnostic evidence on
the unaccepted candidate, but the aggregate cannot grant qualification success
while P3 is unaccepted. A different build failure may appear and still spend
the final allowance. Positive evidence never follows solely from retained files.

Keeping AMD held and publishing only unit/staging corrections was considered;
the operator selected the bounded additional diagnostic attempt instead.
Generic gcc-base exceptions, new dependencies, weakened measurement, historical
rewrites, automatic retries and fabricated security/qualification claims are
rejected. A later required scope or build exception returns to the operator.

The retained native runtime inventory establishes 142 package identities and no
closure additions, with gcc-14-base as the observed old-predicate offender.
Native dpkg-L output was not retained; the exact public Debian filelist informs
the narrow guard, whose actual native payload observation remains mandatory.
The local SDK can prove observed tooling refusal, not AMD-positive qualification.
The unchanged arch7f release-resource owner remains hosted-only under the closed
40-path scoped selection. Preserve its helper value, alias and child-call shape;
selected apt-custody/payload owners exercise the actual new code and renderer.
Test child instrumentation observes the scrubbed environment with a fixed
stdlib guard without changing production transfer code or measuring locally.
