# ADR 0083: Opt-in bounded configured SQLite neighborhood

## Status

Amended candidate through REPOMAP-PRODUCT6-NAVIGATION24-SQLITE-SCALE1;
scoped functionality and SQL scaling accepted by the revisor following the
dispatcher-owned independent work review. Runtime integration remains on hold.

## Date

2026-10-17

## Context

The configured `repomap_neighborhood` route returns an unbounded one-hop
neighborhood. Large responses can exceed an optional consumer's capture budget.
The canonical tool's existing windows do not supply completeness probes for
this configured tool. Response size alone establishes no efficiency benefit.

## Decision

Add optional `node_limit` and `edge_limit`, each an integer from 1 through 100.
Explicit nulls, booleans, fractional numbers and values outside this range
refuse. With both arguments omitted, preserve the existing response and call
semantics. A supplied limit bounds only its own dimension; the other dimension
remains unbounded when omitted. Depth remains one and direction remains
`in`, `out` or `both`.

Only the configured SQLite read supports the opt-in branch. PostgreSQL refuses
bounded requests before its read; its default route remains unchanged. No new
tool, offset, cursor, schema migration or graph vocabulary is introduced.

SQLite reads the center and independent node and edge windows in one existing
read-only transaction. Nodes exclude the center and sort by canonical key;
edges sort by source key, kind, target key and identity metadata hash. A limited
dimension fetches at most limit plus one records; the extra record grounds
`has_more`. The opt-in branch uses incident-selective queries in the canonical
query owner; omitted-limit calls retain their original SQL. Separate outgoing
and incoming selections use the v1 unique source-prefix index and named target
index respectively. Incoming selections explicitly use the target index so
canonical ordering cannot induce a graph-version source-index scan. Their
edge-ID union deduplicates overlap and self-loops without losing parallel edge
identities; primary-key lookups then fetch and order only those edge candidates.
The opposite-endpoint key union feeds indexed node-key membership and excludes
the center. Each selection binds the graph version and center as parameters.
No schema, index, migration or checksum changes are needed.

SQLite may materialize and sort incident candidates; work may grow with local
degree and B-tree depth. SQL engine work is not bounded by the returned record
limit. The fixed-degree regression fixture establishes resistance to unrelated
edge amplification on the measured SQLite version, without promising constant
CPU, bounded bytes or universal performance. Omitted dimensions read their
entire requested one-hop scope independently.

Each opt-in result adds `bounds.nodes` and `bounds.edges`, containing
`requested_limit` (null for omitted), `returned_count`, `has_more` and
`completeness` (`complete` or `truncated`) for the stored directional scope.
Completeness concerns membership, not unredacted content, source freshness,
subsequent locator snapshots or complete dependency/impact analysis.

## Privacy and scope

All values use the existing sanitizer. Endpoint preservation retains the exact
NAVIGATION12 public-dev admission and spelling/version rules and sees only the
center and returned nodes. The probe record and excluded nodes cannot authorize
endpoint disclosure. Edges remain independent; unseen endpoints stay withheld.
No source acquisition, target execution, refresh, auto-pagination or retry is
added. No relationship is upgraded into an import-call or coverage claim.

## Verification and consequences

Focused tests cover extraction through disposable publication and public calls,
independent windows, directional completeness, SQL candidate bounds and privacy.
Dense and sparse synthetic SQL-seam cases use the actual published product
schema without extra indexes, with query plans and fetched-row counts recorded
separately from observed SQLite VM instructions. Exact before/after default
responses and catalog differences are retained in the stage packet.
NAVIGATION24 compares final queries against authenticated predecessor SQL with
two incident edges and 0, 100, 2,000 and 20,000 unrelated edges. The ceiling is
three times the zero-unrelated VM instruction count plus 200 instructions,
allowing modest B-tree/version variation while rejecting proportional scans.
A separate deliberately scanning query must fail that ceiling. Dense local
degree, parallel edges, cycles, self-loops and independent omitted dimensions
receive separate tests. Latency is context, not an acceptance threshold.

Both canonical containerized integration owners remain
`HOLD_RUNTIME_PREREQUISITE`: read-only Docker availability fails; this phase
does not authorize daemon permission changes, privileged startup or image
pulls. Host pytest cannot replace the harness. Complete suites and hosted
qualification are unselected. The dispatcher's independent final-byte SQL and
plan review found no blockers; production SQL bytes remain unchanged in revision.
The revisor's test and documentation amendments receive local verification with
no second independent review. Full product qualification still requires actual
integration evidence.

## Alternatives and rollback

Post-presentation clipping cannot establish a bounded store read. An implicit
limit on the other dimension changes the requested semantics. A new tool or
cursor is unnecessary for this slice. Reverting this candidate removes only
the opt-in contract and restores the previous catalog pin.
