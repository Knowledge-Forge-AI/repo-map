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
An unpinned current selection supports native PostgreSQL graph
investigation. The maintained Server workflow requires complete/partial
readback and an expansion reason other than `backend_unsupported`; an
explicit ranked-discovery fallback remains available under the existing
contract. This workload composes that existing implementation.

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

## Reproducing the first-use workload (checkout only)

`REPOMAP-CLOE-FIRST-USE-WORKLOAD1` turns the three flows above into one frozen,
reproducible workload with inspectable evidence
([ADR 0180](../adr/2026/11/0180-reproducible-first-use-workloads-and-evidence.md),
[contract](../specs/cloe-first-use-workload-v1.md)). It is checkout-only: no
installed module, console script, CLI option, MCP field, configuration key,
runner flag or package data changes, and no product module imports it.

### What is frozen

| Input | Owner | Binding |
| --- | --- | --- |
| Materialized `mixed-v1` generations 1 and 2 | `src/test/fixtures/first_use_workload/mixed-v1-census-v1.json` | Census digest; any materialized drift refuses as `stale_input` before execution |
| Committed fixture inputs (four alias trees and `python-sources-v1.json`) | `tools/first_use_workload_census.py` | `fixture_digest`; task, gold, held-out and trial material is never read |
| Ordered steps, expected codes, labels and manual locations | `tools/first_use_workload_recipe.py` | `recipe_digest` |
| Product bytes (`src/main`, `pyproject.toml`) | `tools/first_use_workload_source_identity.py` | Git-free `product_digest` |
| Complete candidate source | same | `candidate_census`, the runner's `candidate_identity.source_sha256` algorithm |

The recipe has 13 Local, 15 Server and 8 mixed rows. Local uses all four
aliases; Server uses `core` and `companion`; mixed uses all four on both
backends. Only the two planned-refusal rows pass a limit (`4S`, with `S` from
the census). Manual locations come from public fixture text:
`RetrievalExecutionPipeline` in `core:pkg/pipeline.py`, the generation-2
marker in `core:pkg/gen2_extension.py`, and no generation-1-only token location
after generation 2. These are fixture readback checks, not evaluation claims.

### Running it

The three integration owners run the recipe inside the canonical integration
sandbox over pytest-owned homes, SQLite and the temporary PostgreSQL cluster:

```text
python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
  src/test/int/python/repomap_kg/ops/first_use_workload_local.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_workload_server.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_workload_mixed.int.test.py
```

Each row is prepared, called once, observed by witnesses and cleaned up, with
`prepare_ns`, `call_ns`, `observe_ns` and `cleanup_ns` recorded separately.
`parent_process_ns` is test-process CPU; `waited_descendants_ns` covers every
descendant reaped during the call span (CLI children, `psql` and helpers) and
is attributable only under the runner's serial default. PostgreSQL server
CPU, memory, physical I/O and peak RSS are never recorded or inferred. A
failed row is recorded once and never retried; later ordinary rows are recorded as
`unavailable/not_reached`. The terminal cleanup row still records actual
cleanup before its final witnesses; the owner fails citing verdict categories.
These are per-row phase measurements, not a whole-run timer: framework
bookkeeping around execution (intent/census reads and bundle/index/verdict
serialization and reconciliation) is outside the row spans, so no aggregate
wall/CPU cost or completeness claim is made.

### Where the bundle goes

Each scenario writes one bundle directory `<scenario>-<attempt>` under a
`first-use-workload/` base:

- in the existing coverage-enabled hosted `--report` run, the base is the
  inner report root, so the bundles
  are exported beside the HTML report by the existing bounded export;
- without `--report`, the base is the test's pytest temporary directory and
  the bundles are discarded with the sandbox (the in-sandbox verdict still
  gates the test).

A bundle holds `intent.json`, `observation-SS-U.json` rows, referenced
`reports/report-SS-U.json` and `plans/plan-SS-U.json` members, then
`index.json` (every payload member, excluding itself and `verdict.json`) and
finally `verdict.json`. Members are written exclusively and never repaired.

The runner forbids `--report --no-coverage`: local scoped proof validates
bundles in the sandbox and does not export them. Hosted CI137's normal staging
artifact carries the final-source bundles; host validation is required after
that run before accepting this bounded milestone. No local coverage or runner
override follows from this guide.

### Checking a bundle on the host

Extract the hosted artifact outside `src/main`, `src/test` and `tools` (or
under a gitignored location). Read the same-attempt CI137
`candidate_identity.source_sha256` and recorded merge commit/tree, then use
that exact executed tree for the host check. A staging checkout/head is valid
only when its complete candidate census equals the reported executed tree;
otherwise obtain the exact recorded tree. Never repin the artifact or weaken
the check; unavailable exact-tree evidence keeps acceptance pending.

```text
python3 tools/first_use_workload.py plan [--source-parent HEX40]
python3 tools/first_use_workload.py check --bundle <bundle-dir>
python3 tools/first_use_workload.py show --bundle <bundle-dir> [--json]
```

`plan` prints the canonical intent of the current checkout. `check`
recomputes the intent and the verdict and prints `<outcome> <scenario>
<categories>`; it exits 0 for `accepted`, 1 for `rejected` or `incomplete`,
and 2 for usage errors or an unreadable bundle. `show` prints per-step spans,
CPU scope labels, results and refusals and never sums them. Neither command
writes to the bundle, and output names no path.

A host `check` proves format, binding, ordering and arithmetic consistency of
the retained bytes. It does not prove producer authenticity: bundles are
unsigned, like resource reports. Source or product drift appears as
`candidate_mismatch`; other intent drift as `intent_mismatch`. A stored
verdict never supplies acceptance.

### Boundaries

The evidence formats (`cloe-first-use-census-v1`, `-intent-v1`,
`-observation-v1`, `-bundle-v1`, `-verdict-v1`) are derived observations with
no graph, publication or resource authority. Resource-report and sealing-plan
schemas are only decoded. Evidence holds no absolute path, host, port,
database name, user, password, environment value, body, snippet or query
text beyond recipe constants. Installed-wheel, W6, full W7, held-out
evaluation, efficiency and coverage claims stay outside this workload.
