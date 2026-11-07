# First-use workflows (source-level; installed proof pending)

This guide describes the bounded first-use experience for the public
`mixed-v1` material. It is a source-level operator and contributor reference
for `REPOMAP-CLOE-RESOURCE-EXPERIENCE1`. It is not an installed-wheel,
native-host, release-image, or W8 qualification record.

The workflows use the existing commands and test-owned temporary homes. They
add no CLI option, JSON field, MCP tool, body permission, dependency, schema,
or durable report. The evaluator, frozen tasks and golds, and held-out split
are not part of these workflows.

## What the first use proves

The first-use slice connects three existing product paths:

| Path | First-use delta | Existing owner reused for setup |
| --- | --- | --- |
| SQLite Local | Mixed-source context selection and packing, source-blind reads before and after a new generation, pinned-selection staleness, and recovery after a refused refresh | `cli/sqlite_local_operator_workflow.int.test.py` |
| PostgreSQL Server | Context selection and packing across an accepted-generation change, explicit expansion fallback behavior, and native PostgreSQL FTS build/query/revoke | `cli/lexical_cli_roundtrip.int.test.py` |
| Mixed privacy | Alias-qualified context provenance, metadata-only feed/mailbox treatment, and lexical refusal before body capture | The mixed-v1 materialize/write-home helpers and the two owners above |

The existing owners retain ownership of generic SQLite Local initialization,
ordinary lexical CLI serialization, and evaluation capability observations.
The first-use tests do not repeat those assertions.

## Binding treatment

The public mixed-v1 fixture has four declared aliases. The policy-derived
expectation is:

| Alias family | Context treatment | Lexical body treatment |
| --- | --- | --- |
| `core` and `companion` | Full-authorized metadata and locators | Eligible when the graph is otherwise authorized |
| `feeds` | Metadata-only | Refused before body capture |
| `mailbox` | Private-memory and metadata-only | Refused before body capture |

Feed and mailbox files are synthetic test material, but they remain excluded
from body projection. No body text is needed to prove their metadata scope,
and no canary is an expected output.

## SQLite Local first use

Create a disposable working copy and SQLite Local home, then run the existing
Local setup commands:

```sh
cloe ops sqlite-init --repo-map-home <sqlite-home> --graph mixed-v1 --json
cloe ops refresh-graph --repo-map-home <sqlite-home> --graph mixed-v1 --json
```

The Local path is independent of Psycopg, PostgreSQL, Docker, parsers and
enrichment. The guarded integration owner supplies the temporary home and
blocks those dependencies in each CLI child.

Create a reusable, pinned source selection for the four configured binding
IDs:

```sh
cloe ops context-select --repo-map-home <sqlite-home> \
  --graph mixed-v1 \
  --binding <core-binding-id> \
  --binding <companion-binding-id> \
  --binding <feeds-binding-id> \
  --binding <mailbox-binding-id> \
  --pin-publication --output <selection-v1.json>
```

Pack bounded metadata context without a freshness source root:

```sh
cloe ops context-pack --repo-map-home <sqlite-home> \
  --graph mixed-v1 --mode ranked_discovery \
  --query "RetrievalExecutionPipeline" --intent implementation \
  --selection <selection-v1.json>
```

This is source-blind: the accepted publication supplies the locators and
metadata, while `context-pack` does not open source files unless the caller
explicitly selects advisory freshness with `--freshness check` and
`--source-root`. The bounded packet retains source binding IDs and relative
paths; it does not authorize body reads.

After rematerializing the working copy for generation 2, an in-process Local
refresh produces a new accepted generation. The old pinned selection then
returns the existing `stale` status with the existing
`selection_publication_advanced` reason. This is a selection identity result,
not a ranking or efficiency threshold.

If a configured source root is unavailable, Local refuses the refresh before
publication. Restoring the disposable root and invoking the same existing
refresh command recovers to the next accepted generation. The first-use owner
checks the resource report for both the refusal and the recovery; LOCAL6
continues to own the generic generation-preservation proof.

## PostgreSQL Server first use

Use the existing temporary PostgreSQL harness and the mixed-v1 PostgreSQL
home writer. The Server path uses the core PostgreSQL profile and retains
the accepted publication as the source for the lexical build.

The context commands have the same shape as Local, with a PostgreSQL home:

```sh
cloe ops context-select --repo-map-home <postgres-home> \
  --graph mixed-v1 --binding <core-binding-id> \
  --binding <companion-binding-id> --pin-publication \
  --output <selection-v1.json>

cloe ops context-pack --repo-map-home <postgres-home> \
  --graph mixed-v1 --mode ranked_discovery \
  --query "RetrievalExecutionPipeline" --intent implementation \
  --selection <selection-v1.json>
```

When the accepted publication advances, the pinned selection becomes stale.
An unpinned current selection can be used to demonstrate that PostgreSQL
graph expansion remains `unavailable` with `backend_unsupported` unless the
caller explicitly requests an existing ranked-discovery fallback. The
first-use workflow records that status; it does not add a PostgreSQL
expansion implementation.

Native PostgreSQL FTS uses the existing explicit body authorization and
binding selection:

```sh
cloe ops lexical-build --repo-map-home <postgres-home> \
  --graph mixed-v1 --authorize-body \
  --binding <core-binding-id> --binding <companion-binding-id> --json

cloe ops lexical-query --repo-map-home <postgres-home> \
  --graph mixed-v1 --authorize-body \
  --query "RetrievalExecutionPipeline" --query-style ranked_terms \
  --binding-id <core-binding-id> --json

cloe ops lexical-revoke --repo-map-home <postgres-home> \
  --graph mixed-v1 --yes --reason first_use_review --json
```

The lexical build is observed in-process through the internal resource view;
the query and revoke continue to use their existing owner contracts. The
derived lexical index is never canonical graph authority and never changes
the context or MCP surfaces.

## Mixed privacy and provenance

Context selection may include all four aliases. A context packet's locations
carry the binding ID, revision, snapshot, relative path and publication
relation. Consumers can map those IDs back to the configured aliases without
assuming that a locator grants body permission.

The `docs` and `messages` intents are useful first-use probes because they
exercise public companion material alongside feed and mailbox metadata. The
expected result is metadata and alias-qualified provenance only. The packet
schema contains no source excerpt field, and synthetic private/feed body
canaries must remain absent.

Lexical selection of `feeds` or `mailbox` is refused before body capture by
the existing projection policy. An empty binding selection is likewise left
to the current lexical owner's `binding-selection-required` refusal; this
guide does not invent an empty-scope success or a substitute outcome.

## Resource reports

First-use owners pass a call-owned `ResourceObserver` to Local refresh, Server
refresh and the Server lexical build, then read `observer.report()` after the
owner returns or raises. Compact-context packets are passed through the pure
`project_compact_context` projection. Reports are descriptive and bounded:

- they identify the operation, backend, closed outcome and instrumentation
  state;
- they retain only owner-held counters, spans and plan aggregates;
- they do not include paths, binding IDs, graph content, query text, refusal
  details or credentials;
- they do not add SQL, source reads, staging measurements, thresholds or
  efficiency claims.

An operation refusal or exception remains the owning command's result. A
resource report marked incomplete or not-recorded is not publication success.

## Source-level verification boundary

The bounded Unit 2 selectors are:

```text
src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py
src/test/int/python/repomap_kg/ops/first_use_local.int.test.py
src/test/int/python/repomap_kg/ops/first_use_server.int.test.py
src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py
```

They are scoped source-level owners and do not establish installed proof,
native host acceptance, a complete suite, coverage, a release image, a
campaign result, or evaluator/held-out qualification. The parent phase
owner records execution results and any required runtime qualification
separately.
