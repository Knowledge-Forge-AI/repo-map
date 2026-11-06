# ADR 0161: CI123 repair and a fresh staging campaign

## Status

Phase: `REPOMAP-CLOE-CI123-REPAIR1`.

Accepted under the operator's new instruction, “Ci failed try again,” after
CI123. This authorizes one corrected, reviewed successor campaign. It does not
automatically retry the spent CI123 allocation.

## Date

2026-11-06

## Context

CI123 attempt 1 tested public staging
`e84143cf3390416890249bed279d83029589349b` through merge candidate
`b639b95c5b57569f2d8d26ab48f77a59ec228865`. Source/export policy,
native D12/Rust qualification, all five system scenarios, vulnerability
scanning and both CodeQL jobs passed. Three gates failed:

- Static suppression policy found two new type-ignore directives in the
  resource-view payload-detachment test.
- One unit assertion omitted the resource-experience admission from its exact
  historical-lineage fixture. The authority audit itself succeeded.
- All 2,180 measured integration cases passed, but branch coverage was
  19,044/23,826 (79.9295%), 17 branches below the hard 80% floor.

Unit coverage passed its hard gates: 67,551/72,939 statements and
20,655/23,826 branches. At that denominator, the desired 87/82 branch margins
need 74 unit and 494 integration branches. These are goals for meaningful
contract proof, not permission to manufacture tests or change a denominator.

Authenticated system evidence records one application start, bringing actual
starts to 34. Native AMD Rust commands total 3; exact wheel transfers total 10.
CI123's allocation is spent even though the overall campaign failed.

## Decision

Repair the confirmed test defects while preserving every historical authority,
strict replay check and quality ceiling. Payload mutation tests use explicit
JSON shape checks instead of suppressions. The exact lineage fixture includes
the independently recorded resource-experience admission.

Expand source-level proof for the existing ADR0159 resource-view and first-use
contracts: observer misuse and degradation, real lexical refusal/recovery,
caller-selected measurement failure, and real SQLite admission and delivered
packet accounting. Correct the unsupported observer-begin route under the
existing misuse guarantee; compact context continues through its pure
projector. Existing filesystem capture may receive source-level boundary proof
without adopting a new production route.

Pre-commit suppression verification must include new untracked candidate files
through the unchanged scanner's path inventory and baseline comparison. The
earlier tracked-only invocation did not inspect the then-untracked test file.
The public scanner and its baseline remain unchanged.

After final scoped proof and independent resulting-state review, prepare one
CI124 attempt 1 through an ordinary synchronization of existing draft PR #23:

- before staging: `e84143cf3390416890249bed279d83029589349b`;
- unchanged main: `5ad00d162ad8a04430874275246a53227578c533`;
- one native AMD system-builder application start 35 after 34 observed starts,
  with cumulative caps 35/35;
- one native AMD Rust component command, cumulative 4, and two transfers of the
  same exact pinned wheels, cumulative 12;
- existing bounded pipeline SDK preparation and qualification owners.

Use a fresh approval, nonce and reservation. Reject spent CI123 and every
earlier spent or superseded binding. Append the observed consumption,
allocation, reservation and source-pin lineage while preserving every prior
root, list prefix and native report. Bind the actual D12 context to both JSON
records. Refresh only changed existing host-source digests in the Rust closure;
the 264 paths, guest, fixtures/golds, wheels, SDK and scenarios stay unchanged.
Old native evidence retains its tested source; CI124 qualifies its own source.

## Boundaries

Local tests remain exact scoped canonical unit/integration selections with
`--no-coverage`. Complete local suites, Python coverage, local application/SDK
builds, native parser execution and new dependencies are excluded. Coverage
thresholds, source inventory, branch mode, exclusions, timeouts and all inherited
debt ceilings are unchanged. Newly created test owners join existing clean
profiles without adding product ownership or debt.

The user's normal `dynamic_default` dispatcher mode applies. Existing active
dispatchers are never disrupted. Expanded task-owned failure diagnostics retain
only safe exported metadata; unknown Muse terminal causes remain unknown.

At most one descriptive refresh of draft PR #23 may accompany publication.
No manual duplicate, automatic CI125/start36, main/tag promotion, package
release or image/production acceptance follows. Full W6/W7, installed and
scientific acceptance remain separate.

## Consequences

The new user request provides fresh successor authority after a failed
campaign. Reservation is not execution. Local proof establishes only its
declared source boundaries; hosted qualification and measured 87/82 margins
remain pending until the exact successor runs.
