# ADR 0101: Retain Trixie with an explicit glibc risk disposition

## Status

Accepted for the enumerated glibc findings in the D12 staging candidate.
The operator stated on 2026-10-27: "Stick with Debian Trixie and accept the glibc
risk." This is the written ADR 0087 P3 disposition. It supersedes the proposed
Alpine route, including its self-imposed November 1 campaign cutoff. No
distribution or linking-model migration is selected.

## Date

2026-10-27

## Context

The Python 3.12.16 source correction under ADR 0100 and its scoped component
proofs are retained. The separate glibc finding CVE-2026-19499 had blocked
P3 while Trixie supplied 2.41-12+deb13u4. The retained catalogue also enumerates
twenty other findings against that same glibc source/version, including
severity conflicts and disputed legacy records. Package/version candidates
do not establish exploitable paths. Their scores and applicability claims
remain visible; Debian urgency labels never lower them.

## Decision

Keep the exact approved PostgreSQL 16.15 and Python 3.12.16 Trixie indexes.
Retain Psycopg/psycopg-c 3.3.6 and the approved dynamic linking model.
The dependency-only diagnostic observed libpq 17.11; the application candidate
uses PGDG libpq 18.6 (package 18.6-1.pgdg13+2). These are separate inventories;
this decision changes neither input.
Record each of the 21 retained glibc findings as accepted unresolved under
Samuel Leighton Lair. The operator's component-level disposition is expanded
into this finite per-finding record, not a wildcard for future advisories.

The public record is `tools/ci/d12_glibc_risk_disposition.json` at SHA256
`5ed32d84313cadab05514c0372b53c0e9e3081de9d2df072cde4bf989e2b0231`. Its retained source catalogue hash is
`b7be264228c3ab778074c27171cd0e7da7a7ae25adf7e2056e1e14e297feee6d`. The executable assessor
must verify the exact approved record, image indexes, platform and observed
glibc package/source version before returning accepted_unresolved. Missing,
duplicate, altered, extra, foreign-component or unobserved records refuse.
Accepted findings stay affected/unknown as recorded; never relabel them fixed,
outside_affected_range or image-qualified. Future findings or a changed libc
version need their own disposition.

## Implementation and evidence

Add a small stdlib-only assessor and integrate its retained result into D12
post-build evidence. Test the actual decision boundary with exact scoped unit
and canonical containerized integration owners using --no-coverage. The
integration owner observes the already pinned native Trixie component,
including config identity, actual libc package/version, ownership and byte
hashes, using only exact run-owned resources. It does not assemble a product
image. Independent source review precedes execution and parent acceptance.

The current CI-remediation objective continues. No old allocation is rearmed
or rewritten. Ordinary focused verification for this new accepted behavior
uses a separately recorded parent execution envelope, conditional repeats
only after a finding and correction. There is no complete local suite or
coverage override, new dependency, SDK rebuild, fifth application-build grant,
remote rerun, main promotion or live deployment in this risk disposition.
Any later application start must have fresh applicable authority and an exact
event/candidate grant; the four historical application starts stay spent.

## Preserved P3 boundaries

This closes the written disposition for these exact glibc findings only.
Other components and unknown runtime findings retain their existing rules.
The previously named incumbent-inventory comparison gap is not reinterpreted.
Missing final candidate bytes, licences/provenance, ABI, ownership or cleanup
evidence remains a refusal that risk acceptance cannot waive. Native AMD
qualification remains pending; ARM evidence is never substituted. No constant
P3/image accepted flag or unconditional stop removal is permitted.

## Consequences and rollback

The enumerated glibc risk remains unresolved and owned. New supplier fixes
should become a separately reviewed exact-input remediation. A future operator
can withdraw the acceptance by changing the reviewed finite record and its
assessor; do not rewrite this historical decision. No production admission or
post-staging promotion follows from this ADR.
