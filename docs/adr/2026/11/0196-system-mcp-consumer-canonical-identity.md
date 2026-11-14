# ADR 0196: Complete v0.0.4 qualification-consumer rebranding

## Status and authority

Selected before implementation for CLOE-CI145REPAIR1 under the current operator
CI-remediation and rebrand request. ADR 0195 makes initialize serverInfo.name
common-lore-index for canonical and finite legacy launches. This repairs stale
qualification consumers and owning expectations. It introduces no new product
identity or accepted-name fallback, resource allocation or hosted campaign.

## Evidence

CI145 attempt 1 built the candidate and passed system scenarios 1 through 4.
Scenario 5 refused its real common-lore-index/0.0.4 initialize result because the
system client still required repomap-kg. Its positive unit fixture masked the
mismatch. Cleanup completed. Eight unit failures concerned stale version,
recipe, workflow, policy, catalog or captured-response expectations. A scoped
PostgreSQL integration run also reproduced a separate stale catalog pin.

## Decision

Use DISTRIBUTION_NAME in the system consumer's exact single-name predicate.
Keep response-ID, JSON-RPC, notification and tool-error refusals, graph/status/
search checks, semantic projection and two-session determinism. Unit cases admit
the hard-coded canonical name and refuse legacy, arbitrary and missing names.
A containerized integration case bridges the existing injected transport to real
guarded MCP stdio processes over a disposable populated SQLite graph. It checks
two recreated processes, an empty WAL, byte-exact durable graph/configuration
state and forbidden-event absence. SQLite may create its transient WAL-index
cache. This proves the identity/readback contract, not an assembled image.

Advance exact public version and packaging-transform expectations to 0.0.4.
Update the one renamed workflow display-name mapping and the conservative
security-policy wording owner; retain filenames, triggers, jobs, all other
assertions and support commitments.

Refresh the maintained smoke consumer and PostgreSQL integration catalog pins
for only ADR 0195's six description substitutions. Keep all 31 names, schemas
and read-only restrictions. Reversing only those descriptions must reproduce
the former catalog digest; reversing the earlier two W3 descriptions must still
reproduce the older digest. No operator-native runtime or private graph is used.

Retain the older release-recipe digest and reproduce the formerly current D12
digest by restoring only the amd64 linux-libc-dev 6.12.116-1 builder package row
in a disposable manifest copy. Pin the independently derived current 117-1
recipe digest. No renderer, package pin or runtime supplier changes here.

The captured navigation fixture permits only 54 payload.version and four
locations[].extractor_version changes from 0.0.3 to 0.0.4, their 26 corresponding
publication-bundle IDs and two raw-payload hashes. A dedicated version proof
derives both exact old/current bundle IDs by changing only the Markdown extractor
version, requires every other canonical family value and raw-record field to
remain exact, and checks the one changed raw-hash pair. The original equality
owner pins all 67 cases and compares every actual response/error byte exactly.
All other fixture bytes remain unchanged. Difference-path diagnostics do not
normalize or relax equality. Imports for the derivative proof stay inside that
test, preserving collection of the basic version check independently.

Legacy payload fields such as server=repomap-kg, tool names, persisted identities
and finite launch aliases intentionally retain ADR 0195's compatibility contract.
They are distinct from the newly canonical initialize serverInfo.name. No other
public vocabulary, schema, storage or service-ownership migration is selected.

## Amendment: remaining CI145 integration repairs

Selected on 2026-11-13 as the same-attempt integration report completed. This
extends the original consumer repair decision within the conditional CI146 scope.

The completed CI145 report also found stale installed-candidate expectations.
Advance only the candidate pins and wrapper expectations to 0.0.4. Read the
immutable incumbent archive's own metadata for migration expectations, retaining
its exact commit, distribution and 0.0.3 version. Offline wheel fixtures remain
within ADR 0181's existing unmeasured launch classes; no image build is involved.

One hosted cancellation case returned success after a signalled test blocker.
The original signal landing point was not retained. A deterministic fault at
Python Condition.wait's lock-release/try boundary reproduces KeyboardInterrupt
being replaced by RuntimeError; the product's ordinary telemetry-failure path
then continues. Replace only the test child's Event.wait delay with time.sleep,
which needs no condition-lock cleanup. Prove interruption propagation in both
the default proxy and the actual test-child adapter. Preserve the child-origin
post-ACK readiness byte, one direct SIGINT, all four cancellation points, strict
lifecycle validation, rollback, backend absence and source-preservation checks.
Fault injection is restricted to a test-owned Event and module-local clock
substitutes; unrelated runner threads retain their real primitives.
Add bounded failure diagnostics without changing product handlers or telemetry
failure policy. This closes a reproduced test-control defect without claiming
the original hosted instruction pointer is known.

## Limits and follow-up

No dependency, runner-policy class, timeout, coverage floor, image, native parser
class, live service migration or operator-host proof changes. Complete local
suites and local coverage remain unselected. The pre-existing exception type
for malformed non-object initialize result fields is deferred; strict name and
protocol acceptance is not broadened.

A successor campaign requires fresh resource disposition after scoped tests,
static/privacy checks and independent review. The existing v0.0.4 ancestry-
preserving promotion choice carries forward, with main/tag/release held until
the exact current hosted candidate passes the required audits.
