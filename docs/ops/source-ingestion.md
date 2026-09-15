# Source Ingestion Operations

This reference owns the detailed current-state procedure for RepoMap's
explicit source ingestion families. The operator entry point and routing live
in the `repomap-cli-workflow` skill under
[docs/ops/skills](skills/README.md); this document carries the per-family
detail so the skill stays bounded.

## Shared Contract

Every ingestion family:

- runs only from an explicit, policy-approved source config file supplied
  with `--config`; there is no `--url` or ad hoc target argument;
- is a versioned acquisition-only command: results report
  `graph_mutated=false` and `freshness_updated=false`, and no repository or
  PostgreSQL mutation selectors exist on the command;
- writes RepoMap-owned artifacts beneath the required `--root-path`;
- redacts secret-prone content in retained artifacts and summaries;
- exits `0` on success and `1` on handled policy or acquisition failure;
- supports `--json` for a machine-readable acquisition summary.

Publication into graph storage happens separately through the normal
storage/refresh path (`storage load-files` staged publication or configured
graph refresh). Acquisition never mutates final graph state or freshness.

Do not use any ingestion command to fetch item links, enclosures, web pages,
schemas, namespaces, arbitrary model-selected URLs, or publisher-specific
targets, and do not resolve credentials or call live provider APIs beyond
what a family's config policy explicitly allows.

## Local Multi-Source Graph Refresh

MS-FLAKE2 is not a hosted acquisition family. An operator may define an
open-ended local constellation with repeated `[[graphs.source_bindings]]`
tables in operations TOML. Each table provides a stable `binding_id`, `alias`,
`revision`, `kind`, `role`, optional `input_name`, selection policy, privacy,
and an operator-supplied `root_path`. Generate the concrete configuration
outside this repository so machine paths and private repository membership do
not enter public history.

Use `kind = "folder"` or `kind = "git-working-tree"`; all bindings must be
enabled. `input_name` explicitly maps a literal Nix `inputs.<name>` reference
to a binding. Input names use `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` and must be
unique within the graph. Roles use the extensible
`[a-z0-9][a-z0-9_-]{0,63}` grammar; names such as `entry`, `composition`,
`security`, and `developer` are examples, not a closed product vocabulary.
Refresh first binds every selected file through a descriptor-stable read and
extracts only from immutable staged bytes. After extraction and resolution it
rechecks the complete inventory once. Any missing, unreadable, unsupported,
disabled, duplicated, replaced, or changed binding refuses the whole candidate;
no successful subset is publishable. Coordinator and worker fences perform the
same manifest/generation scan without semantic extraction.

For exact cross-source Nix module relations, the target flake must directly
export the referenced `nixosModules` attribute to a literal selected path.
Filename convention and a bare input reference are never enough. Dynamic,
conditional, inherited, merged, interpolated, indirect, and helper-generated
output shapes re-enter only through a separately accepted static rule; RepoMap
does not evaluate Nix.

After an authorized refresh, use `repomap-kg ops graph-files --graph
<graph-id> --json` for countable source-qualified membership and candidate
readback. Keep private dogfood to redacted/count-only inspection. Do not commit
the concrete operations TOML, source paths, private bytes, raw observations, or
credentials.

## Configured Feed Ingestion

```sh
repomap-kg sources ingest-feed --config <feed-source.toml> \
  --root-path <repo-root> --json
```

Fetches exactly the configured feed URL, retains the response bytes as a
local artifact, and runs the local feed extractor over that artifact. RSS,
Atom, and JSON Feed documents produce feed document, channel, item, author,
category, link, enclosure, and reference facts. Artifacts are retained under
`<repo-root>/.repomap/source-artifacts/` unless `--artifact-dir` supplies a
different in-root directory.

## Local Archive Import

```sh
repomap-kg sources import-archive --config <archive-source.toml> \
  --root-path <repo-root> --json
```

Imports one configured local saved-page/static artifact source. The input is
a local artifact already on disk; nothing is fetched.

## Local WARC Import

```sh
repomap-kg sources import-warc --config <warc-source.toml> \
  --root-path <repo-root> --json
```

Imports one configured local WARC artifact source. The input is a local WARC
file already on disk; nothing is fetched.

## Bulk Corpus Plan And Import

```sh
repomap-kg bulk plan --config <bulk-corpus.toml> --json
repomap-kg bulk import --config <bulk-corpus.toml> --root-path <repo-root> --json
```

`bulk plan` projects the plan for one explicitly configured local corpus
without acquiring or publishing anything. `bulk import` performs the
acquisition-only import. Inspect aggregate results afterward with
`repomap-kg storage bulk-summary --root-path <repo-root> --json`.

## Documented API Acquisition

```sh
repomap-kg api plan --config <api-source.toml> --json
repomap-kg api acquire --config <api-source.toml> --root-path <repo-root> --json
```

The config must provide source policy, read-only consent, an opaque
credential reference, limits, retention, redaction, endpoint allowlists, and
local fixture response paths. Acquisition is fixture-only: it validates
credential reference shape but does not resolve credentials, read
environment variables or keychains, implement OAuth, call live provider
APIs, mutate provider state, or schedule work. Acquired artifacts land under
`.repomap/api-runs/...` with redacted response artifacts. Inspect aggregate
API provenance afterward with
`repomap-kg storage api-summary --root-path <repo-root> --json`; that
readback never reads credentials, opens response bodies, or calls
transports.

## GitHub REST Fixture Acquisition

```sh
repomap-kg github plan --config <github-source.toml> --json
repomap-kg github acquire --config <github-source.toml> --root-path <repo-root> --json
```

Plans and acquires one explicitly configured GitHub REST fixture source under
the same fixture-only, credential-shape-only policy as documented API
acquisition.

## Readback After Ingestion

Query ingested facts through the normal canonical readback surfaces once the
observations have been published to storage: `storage nodes` /
`storage edges` with feed and config kinds, `storage explain-canonical-edge`
for evidence, and the domain summaries (`storage bulk-summary`,
`storage api-summary`). Read-only MCP source/feed tools
(`repomap_ingested_sources`, `repomap_source_summary`, `repomap_source_runs`,
`repomap_source_feed_items`, `repomap_explain_source_feed_item`,
`repomap_source_references`) expose the same already-ingested metadata; see
the `repomap-mcp-readback` skill.
