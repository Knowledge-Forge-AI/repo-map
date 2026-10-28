# ADR 0105: Debian stable slim maintenance and CI responsibility

## Status

Accepted before implementation on 2026-10-28 by the maintainer's explicit
instruction: Debian vulnerabilities and other upstream Debian issues must not
fail RepoMap's pipeline; RepoMap must keep up with the latest Debian slim stable.
The preceding acceptance of the three observed libxml2/Kerberos findings as
unresolved for D12 staging remains a historical disposition. It does not imply
that any finding was fixed.

## Date

2026-10-28

## Context

The D12 diagnostic route deliberately failed even after successful application
construction and all five scenarios. ADR 0104 authorized conditional acceptance
and one further native AMD attempt, but its closed vulnerability catalogue and
per-finding dispositions made inherited distribution issues release blockers.
The maintainer has now changed that responsibility boundary. Debian 13 Trixie
is stable. Official PostgreSQL Trixie and Python slim Trixie derive from
`debian:trixie-slim`.

## Decision

Inherited, unmodified Debian packages, their upstream vulnerabilities, and
upstream slim-image omissions are informational evidence. They do not require
per-CVE acceptance, a complete vulnerability catalogue, a fixed package version,
or a vulnerability-free Debian image to pass RepoMap CI. Do not turn affected or
unknown findings into fixed/clean claims. Retain findings and supplier identity
where collected. RepoMap does not patch Debian, replace it with Alpine, or set
an operator deadline to repair upstream Debian.

Maintain official Debian stable slim and its official runtime derivatives.
Resolve current stable and relevant official derivative tags before publication,
retain the observed date and immutable manifest/config identities, and update
stale pins together with their generated manifests, compatibility evidence and
tests. Keep digest-pinned build inputs. An upstream tag moving after that frozen
observation does not invalidate an in-progress campaign. Refresh observations
for the next publication. Document the check/update procedure; never label a
stale observation as a live freshness check. A future Debian major upgrade needs
the normal compatibility work rather than a silent mutable-tag build.

Debian ownership is established by the pinned supplier image and package/source
provenance, not by a path prefix. Inherited missing files and checksum diagnostics
are retained, including slim exclusions; they alone do not fail the gate.
RepoMap-introduced missing runtime files, unresolved dynamic libraries, invalid
payload provenance, unsupported assembly changes, licence/notice omissions from
our payload, broken Psycopg dynamic linkage or ABI, build-tool residue, product
failures and resource leaks remain blocking. A base-image issue that actually
prevents RepoMap from working still causes the corresponding functional test to
fail; the gate does not suppress test failures based on upstream ownership.

This supersedes ADR 0087 P3 and ADRs 0091/0101/0104 only where they require
Debian vulnerability classification, fixed versions or finite risk acceptance as
prerequisites for the new qualification route. Preserve those historical records
and diagnostic v1 validators. The missing incumbent inventory remains recorded
unresolved under ADR 0091; no additional comparison build is required. Other
source/dependency security and licence obligations remain in scope.

For the new route, replace the deliberate unconditional failure with actual
conditional qualification: admitted immutable candidate, same-daemon native
preflight, valid assembly/runtime evidence, unchanged five system scenarios and
archive round trip, verified export, and successful inner/outer cleanup. Emit a
versioned qualification supplement linked through the existing report/binding;
preserve the hosted success/merge-authorized semantics. The outer verifier must
use retained host admission evidence, not only values chosen by the inner report.
The existing admission proof already binds the complete Git candidate SHA/tree.
Use that retained proof plus independently hash-checked committed policy/assessor
blobs and a host-retained export manifest as the trust root for the new supplement; a new admission-proof version
is unnecessary after removing the closed Debian catalogue. This supersedes
ADR0104's proposed proof-v2 transport requirement. Write the supplement before
the SystemReport and reference its digest through coordinator_evidence, avoiding
a hash cycle. Before export, the outer host hashes the actual stopped-container
archive's required files into an exclusive receipt beside its admission proof.
The sandbox cannot write that host path. Exported files must match this retained
receipt; rehashing inner records cannot substitute another baseline or payload.
The artifact upload retains both host proof and receipt for postflight. Verify
all tracked candidate source, including transitive assessor imports, against the
committed Git candidate. Main-system GateResult success always requires the host
proof and receipt; report-selected markers cannot disable this obligation.
The current frozen Debian closure is empty; refuse a changed closure before any
build until its exact delta-provenance support is implemented and proved. No change to generic GateRequest/GateResult schemas or workflow topology.

ADR 0104's single fifth native AMD start, CI85 attempt 1, one ordinary reviewed
staging publication, scoped testing, no local image builds/pulls, sequential Muse
assistance and protected checkout boundaries remain. Required Debian runtime
pin refreshes are authorized by this decision; unrelated dependencies and new
infrastructure are not. No sixth application start, retry, main promotion,
deployment, pgvector admission or D15 work is granted.

## Verification and rollback

Add positive tests showing inherited affected/unknown Debian findings and slim
omissions do not block a valid candidate. Negative tests must still reject
foreign/missing identity, broken or unattributed product payload, missing runtime
libraries, failed scenarios, tampered/export-missing evidence and cleanup failure.
Use exact scoped unit and containerized integration selectors with
`--no-coverage`; complete local suites and local Python coverage remain excluded.
Record current official baseline metadata and resulting source verification.
Hosted CI qualifies the actual final image; metadata alone does not.

Rollback is a reviewed forward change restoring the stricter route. It preserves
historical evidence and every consumed build/reservation. It never reuses spent
authority or rewrites public commits.

## Sources

- <https://www.debian.org/releases/stable/>
- <https://github.com/docker-library/official-images/blob/master/library/debian>
- <https://github.com/docker-library/python/blob/master/3.12/slim-trixie/Dockerfile>
- <https://github.com/docker-library/postgres/blob/master/16/trixie/Dockerfile>
