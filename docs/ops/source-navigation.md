# Optional node-to-source navigation

For selected context that must travel between callers, the optional
[portable handoff v1](portable-handoff.md) preserves relative locations,
authored findings, uncertainty and inert next checks. Loading it performs no
graph or source reads; local rechecking uses the importing caller's root mapping.

Read the fresh task handoff first. If it provides an owner or location, verify
that location directly in the checkout. Use RepoMap only for unresolved owners
or locations. Native symbol/file search remains available if RepoMap is absent,
broken, unsupported or returns no usable lead; no demonstration query is required.

For an already selected canonical node on a configured, enabled, MCP-visible
SQLite Local graph, call:

```text
repomap_node_locations(graph_id="example", canonical_key="python.function:sample.service:serve", evidence_role="direct", detail="compact", limit=2)
```

If the node is unknown, use `repomap_search_nodes` first and pass its exact key.
Node/navigation matching searches canonical key, kind and display name, not
source bodies. For an assignment, comment, string, error message or syntax
construct, use bounded native literal-text search in the caller-selected
workspace/subtree, then inspect source. A complete empty node result means no
match in its indexed fields and selected population/scope; it does not prove
source text, behavior, exports, tests or implementation absent. Incomplete,
unavailable and error results say less. The caller's question determines the
surface; no token spelling forces a route. File search matches path/language/role;
observation search includes retained payload text, not arbitrary workspace text.

Search eligibility, key order, metadata and pagination are unchanged. The locator
is an opt-in MCP tool, also callable as
`repomap_kg.server.mcp.repomap_node_locations`; it performs no acquisition,
source-tree reads or refresh. PostgreSQL reports `backend_unsupported` for this
helper; existing PostgreSQL read tools retain their contracts.

The default/full `locations` follows persisted node-evidence links, with a sanitized evidence key,
link kind, raw `(run_id, ordinal)` and payload hash. Each row carries available
extractor/confidence, publication bundle/manifest/receipt/candidate identifiers,
and canonical-evidence source binding/revision/snapshot facts. A revision is filled from
the run's snapshot vector only for an explicitly matching binding and snapshot.
Use `evidence_role="direct"` to locate the subject, `"reference"` for incoming
and outgoing links or containment context, and `"unknown"` to inspect unclassified
evidence. Omitting the selector or using `"all"` preserves the original mixed
evidence response, order and bounds. Filtered rows carry `evidence_role`.

Direct evidence requires an `observed` link and a supported matching subject
and raw kind: Python module/class/function/method; Markdown document/page,
heading/section, ADR metadata/ADR or skill metadata/skill. Their definition
producers persist this relationship. `observed` alone is not a universal
definition promise. `inferred_from_edge` is reference/context evidence on
either endpoint, including a page's outgoing links and definition evidence on
its containing file. Incoming link lines belong to the referring document,
never the selected target. Other combinations remain unknown. Missing raw payloads
or binding metadata do not erase supported persisted producer facts, but their
provenance gaps stay explicit. Unknown evidence remains available in the
default or unknown view; use native navigation when it cannot locate the subject.

Paths are stored **graph source-relative POSIX paths**, not host paths. For
example, `root/src/service.py` may have binding alias `root` and stored
`source_relative_path="src/service.py"`. Match that binding to the configured
source root before opening the checkout file. A single-source or older graph
may use another spelling or omit binding facts. Do not blindly strip `root/`,
infer a path from a Python module/key, or fetch a URI. Verify the mapping and
symbol locally; resolve uncertain mappings with native search.

The main `locations` window returns at most `limit` evidence rows (1–100,
default 10) from the
accepted run when it has linked evidence, ordered by observation ordinal,
evidence key and link kind. Otherwise it uses the newest linked historical run.
`location_scope` and `location_run_id` name that choice. Run selection uses
all linked evidence before role selection. In filtered views, the role
predicate applies before ordering and limiting both windows, so late direct
evidence remains reachable at `limit=1` behind earlier references. An accepted
run with references but no direct evidence has an empty direct main window;
older direct evidence stays historical. If accepted-run links are absent, the
newest linked historical run remains the main run even when it has no matching
role; the helper never selects an older run just to fill a direct window.
Distinct and
contradictory rows remain distinct. `has_more` reports main-window truncation;
increase the limit within 100 if useful. There is no ranking of locations
within that run. `ambiguity=multiple_stored_locations` identifies multiple
usable paths/ranges in this window; `truncated` means uniqueness is unresolved
beyond it. Even `single_stored_location` describes stored evidence only.

`historical_locations` contains a separate window from the remaining runs,
ordered by descending run ID, then observation ordinal, evidence key and link
kind, with the same per-window limit and its own `historical_has_more` flag.
History does not fill the accepted-run window or affect its ambiguity. Repeated
refreshes can truncate history; unchanged repeats and old line ranges do not
make an otherwise unique accepted-run location ambiguous. Both windows retain
their supporting identifiers; total evidence output is at most twice `limit`.

`publication_relation=historical_run` explicitly marks evidence outside the
accepted run, including retained nodes absent from that publication. An
`accepted_run` row still has `freshness=unverified`: no live filesystem or Git
revision check occurred. Source binding revisions and snapshot IDs are stored
provenance, not a claim that the checkout matches them.

`status=located` means at least one returned evidence path is usable as a lead.
Missing/invalid ranges are null with `range_status=missing_or_invalid`; a path
alone remains useful. Unsafe, redacted, empty or overlong paths become null with
`path_status=missing_or_withheld`. `metadata_location` is a separately labelled
`node_metadata.doc_path` lead with no invented range/raw observation. Its
`path_namespace=source_relative` differs from evidence's
`path_namespace=graph_source_relative`: Markdown routing prefixes observation
paths with the binding alias but preserves the source-relative `doc_path`.
Node metadata does not retain that binding, so `binding_status=unavailable`;
verify the mapping through evidence/configuration or native search. The helper
does not compare an unbound metadata path with evidence to infer ambiguity.
In filtered views that metadata lead is explicitly `evidence_role=unknown`;
it cannot satisfy a direct-evidence request. `status=metadata_only` reports
that partial route even when the filtered evidence window is empty. Such a
filtered window has `ambiguity=metadata_only`, rather than claiming a stored
location for the requested role; the default view preserves its original
`single_stored_location` metadata behavior.
`status=unavailable` covers
missing node/publication, unsupported backend or a complete main window with
no usable location. In filtered views, `reason=historical_locations_only` signals
a usable path in the returned historical window when the main window has no
usable lead, no metadata lead and no truncation. The status remains unavailable
for the main window; inspect the historical row's publication relation before
using it, and verify it locally. `status=incomplete` with
`reason=no_usable_location_in_window` means no returned path is usable but the
main window has more rows; a later row may provide a lead.
Consult `reason`, `has_more`, and native search; these states do not disable
ordinary search or the runtime.

If the linked raw observation is absent, the canonical evidence still supplies
its stored observation identity, path/range and source metadata.
`raw_observation.status=unavailable` and a null payload hash expose that gap;
the helper does not silently discard the evidence or fabricate a raw payload.

Fixture success establishes this stored read contract. It does not establish
measured context, speed or investigation-correctness gains. Any later small
utility check requires a separate manager decision; the closed pilot remains
the baseline.

## Compact presentation and expansion

`detail="full"` is the unchanged default. `detail="compact"` projects the same
bound, sanitized read without another query or source read. Compact has
`detail="compact", schema_version=1`. This version identifies the following
presentation, independently of the product version and canonical graph key version:

- Graph ID/repository name, canonical/repository identity, requested role,
  status/reason, limit, ambiguity, selected run/scope, accepted publication,
  first/last seen runs, freshness and fallback retain their full meanings.
- Both evidence windows retain every row and their order. `has_more` and
  `historical_has_more` describe their respective bounded windows. No distinct
  or conflicting location is merged. The top-level `path_namespace` applies
  to both windows. `metadata_location` is unchanged, including its separate
  namespace, null range and unavailable binding.
- Each row's `binding` and `publication` are zero-based indexes into
  `bindings` and `publications`, ordered by first use in main then history.
  These group identical sanitized objects. Binding objects contain the full
  stored source metadata except `source_relative_path`, which stays on each
  row when present. An empty binding object means unavailable binding facts;
  a withheld relative path stays null and an absent one stays absent.
- Path/range statuses and nullable line numbers, role (when filtered), link
  kind, run/publication relation, extractor/version/confidence and observation
  status/ordinal/kind remain per row. The row run ID also identifies its raw
  observation. A missing raw observation remains explicitly unavailable.
- Omitted fields are graph operational/display details, static `safety`,
  evidence keys, raw payload hashes/source IDs and repeated raw run IDs and
  path namespaces. Redacted keys remain inaccessible. Observation identity
  can still be correlated by graph, row run/ordinal/kind and publication.

History detail follows the same projection as the main window: it is not
silently omitted. Empty history means no rows in that window; it is not an
unbounded absence claim. Truncated history remains flagged. In particular,
`historical_locations_only` remains a reason for an unavailable primary lead,
and a historical primary window still has `location_scope="historical_run"`.
Neither becomes current direct evidence in compact form.

For expansion, repeat **the same** `graph_id`, `canonical_key`, `evidence_role`
and `limit` on `repomap_node_locations`, setting `detail="full"`. Expansion
is a new read and may observe a newer publication. There is no snapshot pin or
evidence dereference endpoint. Inspect needed full evidence when that helps;
otherwise perform bounded native search. Do not repeat a failed lookup in a loop.

## Executable caller-side example

[source_navigation_consumer.py](../../tools/source_navigation_consumer.py)
is a small standard-library example, not a runtime dependency or global
configuration. Import its `navigate` function from a repository checkout or
load the file with `runpy.run_path`. Its optional `tool_call` callback accepts
the existing `handle_tool_call(name, arguments)` envelope; tests use the actual
SQLite/publication/callable route. Graph reads remain source-blind. Only the
separate caller-side verification function opens a source file.

Supply an explicit `bindings={stored_binding_id: intended_workspace_root}`,
expected repository identity, and a task-specific `source_check(text)`.
The check must examine the expected definition/content, not just file existence.
A source record is supplied directly, without a new handoff API:

```python
location = {
    "repository_identity": "repo1:example",
    "binding_id": "bind1:explicitly-matched-binding",
    "source_relative_path": "src/helpers.py",
    "start_line": 8,
    "end_line": 10,
}
result = navigate(
    graph_id="example", repository_identity="repo1:example",
    bindings={location["binding_id"]: source_workspace},
    source_check=lambda text: "def normalize_label(" in text,
    handoff=location,
)
```

Choose the next action according to the information already available:

| Input/state | Example sequence | Local source reads |
| --- | --- | --- |
| Usable handoff | verify supplied record; zero graph calls | one bounded read |
| Explicit source-text purpose, no handoff | return bounded native literal-search plan; zero graph calls | none |
| Selected node, unresolved location | direct compact locator once → verify mapped lead | at most one |
| Unknown node | existing search once → locator only for one unambiguous key → verify | at most one |
| Ambiguous/truncated/historical/unbound lead | inspect needed full evidence or bounded native search | no automatic source promotion |
| Absent/broken/unsupported/stale helper, or failed source check | return native-search next action once | zero, or one failed verification |

The example returns `branch`, `outcome`, `graph_calls` and a decision trace.
`outcome="native_search"` is an explicit next-action handoff to the caller;
the example does not implement a native-search engine. Full expansion is also
a caller decision. Thus it makes at most one search and one locator request,
never automatically choosing history or retrying failures. An old helper that
does not support compact follows the same fallback. Zero graph calls is valid.

To declare source-text purpose, supply the optional example-only argument
`source_text_paths=(source_workspace / "src",)` together with the existing
`query` literal. Supply a tuple of paths; a bare string or another container
raises `TypeError` when the source-text branch is reached. A usable `handoff`
is verified first; otherwise this explicit purpose takes priority over
`canonical_key`. Omitting it (`None`) preserves indexed-subject behavior:

```python
result = navigate(
    graph_id="example", repository_identity="repo1:example", bindings={},
    source_check=lambda text: False,
    query="public_labels =", source_text_paths=(source_workspace / "src",),
)
```

After any supplied handoff is verified first, this branch returns one
`native_search` trace event with separate `literal`, `paths`, `max_matches=20`
and `ready` fields. Paths retain the caller's workspace/subtree choices. The
caller applies that bound with its existing native search tool and inspects
source; no shell command is constructed or executed and no executable is needed
at import time. `ready=false` for a missing/empty query or empty path tuple asks
the caller to supply those inputs; it never implies a wider scope. Even an
absent or broken graph callback is not consulted on this branch. A content
question with a usable supplied location still verifies that location directly.
If that verification fails, the explicit source-text plan retains the same
caller-selected paths and literal, without a graph call.

Source verification resolves only an explicitly mapped source-relative path
within the intended workspace and refuses escaping symlinks. It reads at most
65,537 bytes, accepts files no larger than 65,536 bytes, and checks at most 80
lines (a supplied range or the first 80 for path-only records). Larger inputs
fall back for task-specific native navigation. A check passing at read time
does not prove the whole working copy matches a graph snapshot or remains
unchanged afterward. The example never strips `root/` or derives paths from keys.

Focused fixtures include a separate `normalize_label` handoff subject, a path-only
document, a Python definition range, ambiguity/history refusals, absent/broken
helpers and a changed source range. Existing Python observations and
Markdown-to-symbol links are synthetic; Markdown document/link extraction,
canonicalization, publication, SQLite reads and caller-side file reads are real.
The separate search-surface regression uses real Python static extraction and
publication to pair body-only no-matches with true indexed names, including a
same-spelling symbol. These programmatic examples establish branch behavior,
not improved live-agent tool choice or efficiency.
Consumer traces are deterministic program executions, not live model usage.

## Optional scoped search

When a broad literal node search repeats documentation destinations, callers
can opt into [scoped source-document navigation](scoped-navigation-search.md)
with explicit code/docs and bound subtree filters. The sibling tool groups
complete supported direct identities before selecting a group page and reports
incomplete scans explicitly. It does not infer task intent or change raw search
or this locator's defaults. Existing handoff-first consumer behavior applies.

## Optional one-hop related sources

`tools/related_source_context.py` composes existing reads after the caller has
selected an exact canonical subject. It uses the same `handle_tool_call` callback
envelope as the existing consumer. It is optional and imports only the standard
library; ordinary navigation and the handoff-first `navigate()` remain independent.

```python
from tools.related_source_context import inspect_related, expand_selected, export

# chosen_graph, chosen_center and existing_call come from the caller.
view = inspect_related(graph_id=chosen_graph, canonical_key=chosen_center,
                       direction="out", tool_call=existing_call)
print(export(view))
# After reviewing the view, the caller explicitly chooses a displayed eligible key.
expanded = expand_selected(view, (chosen_neighbor,), tool_call=existing_call)
print(export(expanded))
```

Direct callers may opt into `repomap_neighborhood` limits on SQLite Local with
`node_limit=...` and/or `edge_limit=...`, each a positive integer from 1 through
100. Booleans, nulls and non-integers refuse. Both omitted preserve the existing
response exactly; one omitted leaves that dimension unbounded. PostgreSQL
refuses bounded requests and retains its default behavior. Nodes exclude the
center and sort by canonical key. Edges sort by source key, kind, target key,
then identity metadata hash. Each limited SQL read fetches at most limit plus
one candidate records. The opt-in SQLite path selects outgoing and incoming
incident keys through existing endpoint indexes before combining and ordering
them. Self-loop overlap is deduplicated by edge ID; distinct parallel edges
remain. Unrelated graph edges no longer drive the measured fixed-degree
incoming/both scan. Incident-degree materialization/sorting and B-tree work can
still grow; these limits do not promise bounded CPU or bytes. Omitted-limit
reads retain the existing query path.
The opt-in result adds `bounds.nodes` and `bounds.edges` with `requested_limit`
(null when omitted), `returned_count`, `has_more` and `completeness` (`complete`
or `truncated`) for the requested directional one-hop membership. This does not
describe unredacted content or freshness. No next page or retry is implicit.
Edges to excluded nodes retain withheld endpoints under the existing privacy
gate. These source-blind reads do not establish a shared snapshot with later
locator reads or complete dependency, impact, call or coverage analysis. See
[ADR 0083](../adr/2026/10/0083-bounded-configured-neighborhood.md).

Inspection performs one `repomap_neighborhood(graph_id=..., node=..., depth=1,
direction=...)` read. The node/edge display limits default to 8/16 and can only be
reduced; they do not change backend bounds. The adapter still omits the optional
node/edge arguments, so its response has no completeness or publication field.
The view therefore reports backend completeness as unknown, with independent display
truncation. No returned relation means only none returned in that read/direction.
`project_neighborhood(captured_reply, graph_id=..., canonical_key=..., direction=...)`
and `export(view)` require no callback, filesystem, source, process or network I/O.
Projection admits up to 262,144 serialized UTF-8 input bytes; the view/export bound
is 65,536 bytes. Oversized capture/projection returns `unusable_or_reduction_needed`, without
clipping keys. In the adapter, direction is the only forwarded route filter.
Direct SQLite callers can separately request the opt-in limits above; the adapter
does not forward them. Smaller display limits cannot reduce an oversized captured
response. If the chosen direction still exceeds the bound, use native navigation
or review; the helper does not retry or broaden it.

Expansion admits a tuple of at most two distinct explicitly selected, uniquely
identified displayed neighbor keys. Each receives one `repomap_node_locations`
call with `evidence_role="direct", detail="compact", limit=2`. No selection costs
no further reads. Invalid selections are rejected before any locator call, and an
already expanded view refuses further expansion. This is caller-held state, not
a tamper-proof or global call budget; callers must retain the returned view.
Keys containing withheld `[private-path]` placeholders remain visible but cannot
be selected. Each lookup failure retains the
relationships and other requested result, with an inert
`native_navigation_or_review` action. There is no automatic choice, retry,
recursive walk, source acquisition or graph-scope widening.

The view retains returned edge kinds, endpoints and identity metadata, including
self-loops and distinct edges, and labels missing/conflicting endpoints. For an
enabled, MCP-visible `public-dev` selected graph with public source bindings and
`private=false`, the producer preserves an edge endpoint only when its exact,
unchanged canonical key is already disclosed as the center or a listed node in
that same sanitized response and key version. Encoded repository-relative keys
remain encoded. The conservative spelling check accepts known namespaces and
segment counts, ASCII unreserved characters and uppercase percent escapes;
other spellings, including lowercase escapes and unlisted namespaces, stay
withheld even when visible as node keys. Unseen, unsafe, placeholder or
sanitizer-altered identities stay withheld independently; private, hidden and
legacy routes keep their prior policy.
Withheld endpoints leave direction unknown. Visible returned neighbor identities
can still be explicitly selected. The helper
never reconstructs hidden endpoints or paths. Exact edge explanation is marked
unavailable: the existing explanation route uses legacy project resolution, and
this helper has no established project mapping. It never substitutes `graph_id`
for `project`. Runtime readback is unchanged by this optional example.

Stored Python `imports` and Markdown `links_to` relationships describe extractor
observations, not function calls, dependency completeness, impact or test coverage.
Location facts retain freshness, ambiguity, history, withheld paths and independent
current/history truncation flags (`has_more` and `historical_has_more`) when supplied;
contradictory rows remain visible. Joined graph/repository/key-version facts are
checked when supplied. Publication labels may differ across reads; equal labels
still do not establish a shared snapshot, and missing facts remain unknown.
The view never declares source verified or current. Source verification is a
separate caller operation using explicit repository/binding/path mappings and the
existing reader or [portable handoff](portable-handoff.md), or native navigation.
