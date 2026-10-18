# Scoped source-document navigation search

`repomap_navigation_search` is an optional SQLite Local view. Existing
`repomap_search_nodes`, file/observation search and locator defaults retain
their original contracts. Literal matching does not infer a task or backend.

## Callable and discovery

The tool is advertised by the existing MCP server through `tools/list` and
uses the configured investigation read store. Its arguments are:

| Argument | Default and supported values |
| --- | --- |
| `graph_id`, `query` | Required visible graph and existing trimmed literal query (1–200 characters) |
| `scope` | `all`; also `code`, `docs` |
| `grouping` | `none`; also `source_document` |
| `kind` | Optional exact persisted kind, intersected with scope |
| `source_binding_id` | Optional exact stored source binding identity |
| `source_path_prefix` | Optional source-relative subtree; requires binding |
| `limit`, `offset` | 20 and 0; strict integers, 1–50 and 0–10000 |
| `member_limit` | 5; strict integer 1–20 |

For an implementation task, first obtain the intended binding from existing
source/locator readback, then use an explicit subtree:

```json
{
  "graph_id": "example",
  "query": "persist",
  "scope": "code",
  "source_binding_id": "<stored binding identity>",
  "source_path_prefix": "src/storage/",
  "limit": 5
}
```

For documentation, use `scope="docs", grouping="source_document"`. The
response identifies `schema="repomap.navigation_search", schema_version=1`,
the graph/repository, query/scope, accepted publication and scan completeness.
`count_unit` is `nodes` when ungrouped and `groups` when grouped. `result_count`
is the returned page length; `page_end` is offset plus that length, never an
exact global cardinality. There is no navigation `total` field.

## Scope and literal paths

`code` currently supports exactly `python.module`, `python.class`,
`python.function`, `python.method`. `docs` supports exactly `doc.page`,
`doc.section`, `doc.adr`, `doc.skill`. These correspond to the direct subject
roles maintained by the source locator. Other language, file, configuration
and unknown kinds are accessible in `all` and raw search. Mixed corpora use
these exact sets; a symbol's spelling does not change its family. Test-only
selection is not inferred: use `scope="code"`, a supported exact kind if
needed, and an explicit binding/subtree that stores those Python subjects.

Membership is the existing SQLite escaped `LIKE` over canonical key, kind and
display name, including ASCII case folding and existing non-ASCII behavior.
Percent, underscore and backslash in a query are literals, not patterns.
Bindings and path subtrees use exact case-sensitive Unicode comparisons.
`pkg/` and `pkg` both admit `pkg` and `pkg/...`, excluding `pkg_extra`. A
trailing slash is ignored; percent encodings are not decoded. Percent and
underscore in paths are literals. Backslash is not a separator or escape;
locator-unsafe stored paths (including backslash paths) remain unavailable,
so such a prefix cannot qualify them. No host paths or source roots are
guessed. Absolute, dot-component and colon prefixes are refused.

`scope="code"` selects those supported node kinds; it does not search all code
text. For an assignment, comment, string, error message or syntax construct,
use bounded native literal-text search in the caller-selected workspace/subtree,
then inspect the source. Such text need not correspond to a canonical node.
Intent comes from the caller's question, never punctuation or a special token list;
the same spelling can legitimately name an indexed symbol elsewhere.

A complete empty result means no match in the indexed fields and selected
population/scope. It does not establish that source text, behavior, exports,
tests or implementation is absent. Incomplete, unavailable and error responses
support narrower claims still. Do not broaden an empty scope or retry to obtain
a hit. Raw node search matches the same identity fields without the navigation
family/source selectors; file and observation searches have their own contracts
in the [readback guidance](skills/repomap-mcp-readback/SKILL.md#query-workflow).

Only direct subject evidence with a usable public path and vector-verified
binding/revision/snapshot can satisfy a binding/path restriction. Referring
files, incoming links, containment and metadata-only `doc_path` do not qualify
a subject. A subject with several direct alternatives qualifies if any
satisfies the explicit restriction; its other alternatives remain visible
within the separate hint bound. Ambiguity still prevents document grouping.
Missing/withheld/unbound paths cannot qualify. Empty scope never widens.

## Identity and historical evidence

The query reuses the locator's direct role SQL and evidence projection.
Markdown document/heading/ADR/skill producers attach observed evidence to
their subjects; Python definitions do likewise. Inferred-from-edge evidence
is reference context. The producer contracts live in
`canonicalization/document_markdown_family.py`, `canonicalization/language_family.py`
and `graph/multi_source_routing.py` under the product package.

For each node, choose the accepted run if it has any linked evidence; otherwise
choose its latest linked historical run, before filtering direct roles. An
accepted references-only node does not borrow an old direct path. Nodes without
direct linkage remain separate unresolved singletons with canonical run hints.
Older evidence is available through the existing locator's historical window.

A proven documentation destination requires every selected direct alternative
to agree on binding, binding revision, snapshot, source-relative path, graph
path, run and accepted/historical relation. The binding/revision/snapshot must
agree with exactly one entry in that run's stored source vector. Grouping is
local to the selected graph/repository and run. Titles, basenames, content
hashes and decoded module names never establish identity. Same paths under
different bindings or revisions remain separate. Conflicting, unknown,
withheld or missing identity remains an explicit singleton. A moved document
can appear as a historical destination and a current destination; neither is
labeled source-current or source-verified. Freshness remains unverified.

Each group has `basis`, `unresolved_reason`, optional `destination`, exact
matching `members`, `matched_member_count`, `member_has_more` and empty
`context`. The empty `context` list is reserved in v1: this view never emits
context parents. No unmatched parent is inserted as a representative or match.
Members carry exact available canonical keys, kinds, run hints and bounded
`source_hints`, each retaining direct role, path/range status, source identity,
namespace, raw status/ordinal/kind and run/publication relation. Hints omit
evidence keys, raw hashes/source IDs, extractor details and publication objects;
use the selected member's existing locator route for those details.
Withheld canonical identities have `unresolved_reason="canonical_identity_withheld"`
and cannot provide an expansion key. No hidden group identifier
is exposed. Group membership examines all scanned direct alternatives even
when only three hints per member are displayed; `source_hint_count` and
`source_hints_has_more` disclose the separate bound.

## Pagination, scan and expansion bounds

SQL first applies literal query, exact kind and family. For explicit source
bindings, selected-run direct public evidence admits subjects relationally
before retrieving at most 2001 node headers. The accepted run is selected from
any linked evidence before role/source selection. A connection-local predicate
reuses the locator projection, vector corroboration and public scope predicate,
with exactly the configured graph's private markers. No SQLite JSON SQL
extension is required. Without a source restriction the original node scan
population and bounds apply.

The second bounded query fetches at most 10001 selected-run direct evidence
rows belonging to admitted subjects. It retains ALL their alternatives,
including outside-scope, other-binding and withheld alternatives. Rejected
subjects do not spend this evidence budget. Group identity examines every
alternative before the three displayed hints are selected. At most 2000 nodes
and 10000 evidence rows are processed for grouping, before output pagination.
Both reads and the accepted-marker read share one existing bound transaction;
there are no per-node backend queries, raw payload reads or source-tree reads.

Scoped `scan.nodes` counts admitted headers, capped at 2000; `scan.evidence`
counts all their direct alternatives, capped at 10000. A sentinel row detects
overflow. `scan.complete` means admission and both selected-row bounds completed;
it does not assert source freshness. Global exclusions are not counted:
`scope_excluded_count=null` and, on complete scoped results,
`scope_excluded_count_basis="not_counted_before_admission"`. Unscoped diagnostics
retain their original meaning. Complete scoped pages additionally report
`post_admission_scope_excluded_count`: subjects rejected by the definitive
public predicate after SQL admission. It is expected to be zero for this exact
prefilter; it never supplies a global exclusion count.

Scoped `scan.admission` separately reports predicate `checks` and
`decoded_bytes` (UTF-8 metadata bytes per evaluation plus vector bytes once per
distinct selected run), with
`check_limit=100000`, `byte_limit=33554432`, and `budget_exhausted`. These are
identity decoding budgets, including rejected alternatives. The request-local
vector cache is bounded by that byte budget and discarded after the read.
`vector_decodes` and `vector_bytes` report its distinct-run entries and input
bytes. `input_bytes` counts all metadata/vector bytes crossing the callback,
including repeated cached vectors and the terminating evaluation on exhaustion;
it can exceed the decoding budget. These inputs are distinct from transferred
full evidence records. No node/evidence corpus is accumulated in Python.
The shared locator projection consumes the cached decoded vector during both
admission and selected-evidence projection; normal
locator reads retain their default decoding path. Multiple decoder passes over
metadata are not counted as additional bytes. The callback stops SQL on budget
exhaustion. Evaluations may stop once the node sentinel is found; they are
not a global exclusion census. SQLite may still scan/sort more rows internally;
neither these budgets nor selected-row caps promise constant latency.
Non-budget callback failures preserve their original Python exception outside
SQLite; registration is removed on every exit. Malformed JSON therefore keeps
the existing bounded invalid-argument route instead of becoming a generic
database-availability error.

The default page contains at most 20 nodes/groups with five members per group
and three hints per member; maxima are 50 groups, 20 members and three hints.
These are row bounds, not a fixed serialized-byte ceiling: long sanitized
identities and many distinct alternatives can still produce large responses.
Start with a small limit/member_limit and expand selected members through the
locator. Fixture byte measurements are recorded in the phase exit; no production
size or latency target is qualified.

A cap breach returns `status="incomplete"`, an explicit node/evidence reason
or `admission_work_limit`,
`scan.complete=false`, no result page and `has_more=true`. Remaining group
identity/cardinality is unknown. This is not ordinary offset continuation: narrow
query/scope/kind or use existing raw/native navigation; no fetch-cap retry loop
is prescribed. A narrow bound subtree can complete despite unrelated global
overflow, including a complete empty set once emptiness is established. A
genuinely oversized admitted set or admission workload remains incomplete.
Missing publication and unsupported backend return explicit unavailable reasons.

On a complete scan, order groups by their smallest matching canonical key and
members by canonical key. For `source_document`, limit/offset/has_more count
groups; for `none`, they count individual matching nodes. `member_has_more` is
independent of group continuation. Stable offset pagination applies within one
fixed publication. Separate calls are independent reads and may observe a
newer accepted publication; no shared cross-call snapshot is promised.

For one selected exact member, call `repomap_node_locations` with the same
graph/key, `evidence_role="direct", detail="compact"`; increase its documented
limit or request full detail when needed. To enumerate matching canonical
subjects beyond a displayed member list, repeat the same navigation query and
scope with `grouping="none"`, using its node offsets. This enumerates that
query's matches, not an exact group-members endpoint. Inspect each returned
identity/source relation; a newer publication can change membership. No hidden
field is accepted as an expansion API. Verify an already supplied useful
handoff directly with zero graph calls, as in the optional CONSUMER1 example.
The consumer's default search branch is unchanged.

## Optional failures and evidence limits

PostgreSQL returns feature-specific `backend_unsupported` without a navigation
SQL read. Raw/search/locator backend behavior is preserved. Unknown/disabled/
hidden graphs and repository binding mismatches retain existing refusal
boundaries. Invalid new options are refused before graph/database reads. A
missing, stale or failing optional helper leaves raw and native navigation
available. Response text and source hints use existing public sanitization.

Repository-owned fixtures exercise real Markdown and Python static extraction,
canonicalization and publication in disposable SQLite stores. File observations
and snapshot manifests are synthetic; Unicode observation paths exceed the
ASCII-only manifest contract and are intentionally omitted from the synthetic
manifest. No claim is made about a complete source capture for that subcase.
Paired raw/scoped/grouped responses measure structural rows/groups, proven
destinations, truncation and serialized JSON bytes. They do not establish
model token/time, relevance or causal utility improvements.
