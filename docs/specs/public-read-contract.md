# Public Read Contract

## Scope

This contract defines the public result boundary for bounded canonical lists
and embedded canonical read collections. ARCH7A1 applies it to direct CLI and
MCP canonical node and edge reads. ARCH7A2 applies the same resource and
diagnostic vocabulary to neighborhood node/edge collections and explanation
evidence collections.

The storage query functions, SQL builders, canonical records, filters, and
graph model remain authoritative. This contract is a presentation envelope,
not a second graph-query model.

MS-FLAKE2 additively extends the existing `ops graph-files --json` record for
explicit-binding graphs. `source_binding` identifies the file's binding ID,
alias, role, and immutable snapshot; `candidate_id` identifies the accepted
candidate. Enumerating the candidate's records proves its participating
binding/snapshot set while each record reveals only its own binding. `path`
remains source-relative and never exposes a checkout root. Legacy graph-file
records retain their existing path and use null additive fields. Canonical edge metadata similarly
reports `resolution_outcome`, `resolution_evidence_class`, source/target
binding, `cross_binding`, and candidate identity when the bounded Nix resolver
produced the edge or evidence. Non-exact relations use opaque per-observation
targets so these scalar fields remain scalar rather than merging across
unrelated references. Configured multi-source CLI/MCP reads use the logical
`graph:<graph-id>` storage root. If any binding makes the graph non-public,
public-safe projections and MCP sanitization redact every binding root and
expanded root while retaining only authorized logical IDs, aliases, and roles.

## Version 1 Envelope

Configured graph search, project summary, graph neighborhood, and language summaries
select the current repository by stable graph identity, with a bounded
identity-NULL legacy-root fallback. Selection precedes content filtering; empty
current data does not enable fallback. Requested-root presentation and existing
privacy sanitization are preserved. See
[ADR 0068](../adr/2026/09/0068-configured-graph-readback-identity.md) for precedence
and compatibility details.

The same identity guarantee covers configured `project=<graph_id>` routing
for status, canonical tools, and all six ingested-source readers. Nested feed
metadata and references remain within the selected repository when keys collide.
Status reports the selected repository name while keeping the existing root
display marker. Explicit connections and legacy project configurations retain
root-only compatibility; public tool names and argument schemas are unchanged.

Canonical node and edge JSON results use this shape by default:

```json
{
  "schema_version": 1,
  "result_kind": "canonical_nodes",
  "items": [],
  "page": {
    "limit": 50,
    "offset": 0,
    "returned": 0,
    "truncated": false,
    "next_offset": null
  },
  "diagnostics": []
}
```

`result_kind` is `canonical_nodes` or `canonical_edges`. `items` retains the
accepted canonical record JSON shape. `returned` equals the number of exposed
items and never exceeds `limit`. `truncated` is true only when one lookahead
row proves that another page exists. In that case `next_offset` is `offset +
returned` and diagnostics contains:

```json
{
  "code": "result_truncated",
  "message": "additional results are available"
}
```

An exhausted page uses `truncated: false`, `next_offset: null`, and no
truncation diagnostic.

## Version 1 Embedded Envelope

Canonical neighborhood and edge-explanation JSON results use this shape by
default:

```json
{
  "schema_version": 1,
  "result_kind": "canonical_neighborhood",
  "result": {
    "center": null,
    "nodes": [],
    "edges": []
  },
  "collections": {
    "nodes": {
      "limit": 50,
      "offset": 0,
      "returned": 0,
      "truncated": false,
      "next_offset": null
    },
    "edges": {
      "limit": 50,
      "offset": 0,
      "returned": 0,
      "truncated": false,
      "next_offset": null
    }
  },
  "diagnostics": []
}
```

`result_kind` is `canonical_neighborhood` or
`canonical_edge_explanation`. The latter has the accepted `edge` and
`evidence` result members and one `evidence` collection descriptor. A
neighborhood retains the accepted `center`, `nodes`, and `edges` result
members and independent `nodes` and `edges` descriptors.

Each embedded collection follows the same limit, offset, returned,
truncation, continuation, and one-row-lookahead rules as a direct list. A
truncated embedded collection adds the collection name to its diagnostic:

```json
{
  "code": "result_truncated",
  "collection": "evidence",
  "message": "additional results are available"
}
```

Collection windows are independent. Continuing neighborhood nodes does not
advance neighborhood edges, and continuing explanation evidence does not
change the selected canonical edge.

## Bounds And Ordering

- The default page limit is 50.
- The accepted limit range is 1 through 200 inclusive.
- Offset is a non-negative integer and defaults to zero.
- The query fetches at most `limit + 1` records; the lookahead record is never
  exposed on the current page.
- Canonical nodes retain ascending `canonical_key` order.
- Canonical edges retain ascending source key, edge kind, target key, and
  identity-metadata-hash order.
- Neighborhood nodes retain ascending canonical-key order. Neighborhood edges
  retain the canonical edge order above.
- Explanation evidence retains ascending run ID, raw-observation ordinal,
  evidence key, and link-kind order.
- Continuation assumes the selected graph does not mutate between page reads.
  The contract does not claim snapshot isolation across separate requests.

The internal storage-query default remains unbounded during the compatibility
interval because non-presentation callers use the same query functions for
complete internal scans. CLI and MCP presentations must always pass a bounded
window.

## CLI Contract

`storage nodes` and `storage edges` accept `--limit` and `--offset`.
`storage neighborhood` and `storage file-neighborhood` accept independent
`--node-limit`, `--node-offset`, `--edge-limit`, and `--edge-offset` windows.
`storage explain-canonical-edge` accepts `--evidence-limit` and
`--evidence-offset`. JSON uses the applicable version 1 envelope by default.
Table output contains exactly the same exposed items and ends with one footer
per collection, for example:

```text
page: offset=0 returned=0 limit=50 next_offset=none truncated=false
nodes page: offset=0 returned=0 limit=50 next_offset=none truncated=false
edges page: offset=0 returned=0 limit=50 next_offset=none truncated=false
evidence page: offset=0 returned=0 limit=50 next_offset=none truncated=false
```

An available next page is a successful bounded result, so the exit status is
zero. Invalid limits or offsets and storage failures retain exit status one.

The `--legacy-json-array` compatibility alias emits only the bounded `items`
array when combined with `--json`. It does not restore unbounded reads.
Embedded commands use `--legacy-json-object` to emit the bounded pre-envelope
result object. It does not restore unbounded embedded collections.

## MCP Contract

`repomap_canonical_nodes` and `repomap_canonical_edges` use the same default,
maximum, lookahead, ordering, envelope, and diagnostic rules as the CLI.
`result_schema_version=0` is the compatibility alias for the bounded legacy
array. Version 1 is the announced default. Other versions are rejected before
storage query execution.

`repomap_canonical_neighborhood` accepts independent node and edge windows.
`repomap_explain_canonical_edge` accepts an evidence window. Both use the
embedded version 1 envelope by default and accept `result_schema_version=0`
for the bounded legacy result object. Other schema versions and invalid
collection windows are rejected before storage query execution.

Private-graph redaction runs over the complete selected result after envelope
construction. Pagination metadata contains no root, graph, repository,
database, credential, or raw diagnostic value.

## Compatibility Interval

ARCH7A1 changes the canonical-list default JSON shape from an array to the
version 1 envelope. ARCH7A2 changes neighborhood and explanation default JSON
from direct result objects to the embedded version 1 envelope. Explicit
schema-zero aliases preserve the old outer shapes with the new bounds.
Removing an alias or changing version 1 fields requires a separately accepted
public-contract phase.

## STR-PUB5 Publication Projection

`ops refresh-status --json` may add a nullable `publication` object for the newest
accepted portable publication. It contains only execution route, protocol version,
snapshot-manifest, extraction-receipt, bundle and candidate identities, source-binding
count, and seven-family counts. It never contains artifact locators, object keys,
source roots or inventory, snapshot contents, credentials, physical stage identity,
private diagnostics, or fence values. Existing fields, table output, CLI behavior,
MCP read-only behavior, bounds, and private-graph redaction remain compatible.
