# ADR 0016: Saved-Page And Static Artifact Ingestion

## Status

Accepted

## Date

2026-06-30

## Context

RepoMap can now graph local Markdown, JSON/TOML configuration, plist/XML,
generic XML, HTML, CSS, CSS-to-HTML selector matches, and local or configured
RSS/Atom/JSON Feed artifacts. ADR 0014 established source ingestion as a
separate, policy-gated layer above extractors: ingestion acquires or imports
artifacts, while extractors analyze local bytes.

ARCHIVE0 defines the local artifact ingestion path for files and bundles the
user already possesses. The motivating artifacts include:

- generated test reports;
- generated documentation;
- local fixture corpora;
- browser "Save Page As" page bundles;
- locally saved public pages;
- exported static pages;
- static assets referenced by saved pages;
- feed-provided local artifacts; and
- later WARC archives.

This phase is not live website acquisition. It is not crawling, browser
automation, HAR parsing, JavaScript execution, or arbitrary URL fetching.
RepoMap should analyze saved bytes on disk, preserve provenance, and then reuse
the existing raw observation -> evidence -> canonical graph pipeline.

## Decision

RepoMap will model saved-page and static artifact ingestion as local import and
graphing of bytes already present on disk.

The pipeline is:

```text
artifact source config
-> artifact policy validation
-> local artifact discovery
-> artifact manifest / evidence records
-> run existing extractors over eligible files
-> canonicalize observations
-> load into configured graph storage
-> expose through existing readback and future read-only MCP
```

ARCHIVE0 accepts local/manual artifact ingestion as a first-class source
ingestion path. It does not add new canonical key namespaces, edge kinds,
storage tables, CLI commands, MCP tools, network acquisition, or extractor
behavior.

The first implementation after this ADR should prefer a small local-only
`ARCHIVE1` slice that imports an explicit artifact directory or manifest, emits
safe provenance metadata, runs existing local extractors, and loads through the
current storage path.

## Scope

In scope:

- saved HTML pages;
- browser "Save Page As" directories and asset folders;
- generated test reports and coverage reports;
- generated static documentation;
- local fixture corpora;
- local static exports;
- feed-provided local artifacts;
- local static assets such as HTML, CSS, XML, JSON, TOML, images, text, and
  report assets;
- artifact policy validation;
- artifact manifests;
- provenance and evidence metadata;
- retention and replay policy;
- local path and reference resolution rules; and
- future implementation phases for local saved-page ingestion and later WARC
  planning.

Out of scope:

- implementing saved-page ingestion;
- WARC support;
- HAR support;
- HTTP fetching;
- live website acquisition;
- crawler behavior;
- browser automation;
- JavaScript execution;
- rendering pages;
- fetching referenced URLs or assets;
- resolving remote schemas, DTDs, namespaces, imports, or source maps;
- MCP write or ingestion tools;
- storage migrations;
- changes to HTML, CSS, XML, JSON, TOML, feed, canonicalization, storage, or
  public readback behavior;
- Phase F migration;
- API, BULK, JS, DOCS, or YAML phases; and
- source-specific publisher logic.

## Source Type Mapping

ARCHIVE0 uses the ADR 0014 source taxonomy.

Recommended source types:

- `saved_page.archive` for browser-saved page bundles and similar saved-page
  directories;
- `test_report.artifact` for generated test, coverage, build, and analysis
  reports;
- `fixture.corpus` for deterministic local fixture sets;
- `manual.import` for explicit user-provided files or directories;
- `static_artifact` for individual local artifacts supplied by feeds, APIs,
  reports, exports, or manual import; and
- `local.directory` or `local.file` when a project profile already describes
  the local path directly.

WARC-like bundles are conceptually part of `saved_page.archive` or
`bulk.archive`, but WARC parsing is deferred. HAR is out of scope for ARCHIVE0.

Unknown source types must default to `manual_review_required` or
`blocked_unknown` until a user or project configuration classifies them.

## Artifact Policy

Artifact policy is evaluated before import.

Allowed local artifact sources:

- files or directories already present on disk;
- artifacts produced by the local test harness or build system;
- fixture corpora checked into the repository;
- saved-page archives the user lawfully obtained outside RepoMap;
- static exports created by a local tool;
- local artifacts retained by RSS2 feed ingestion; and
- manual imports explicitly selected by the user or project configuration.

Policy must block or require review when:

- the artifact path is outside the configured import root;
- the source type is unknown;
- the source requires login-wall extraction, CAPTCHA bypass, anti-bot
  circumvention, proxy rotation, stealth behavior, or browser automation;
- the requested ingestion would fetch live URLs;
- the artifact includes credentials or secret material that cannot be safely
  redacted;
- size, file-count, or archive-depth limits are exceeded;
- symlink traversal is requested without explicit profile policy; or
- the source policy is ambiguous.

ARCHIVE0 does not decide legal compliance. It defines operational guardrails.
Ambiguous cases should stop with `manual_review_required` or a blocked status.

## Artifact Source Config

A future ARCHIVE1 implementation should require an explicit local source config
or command arguments equivalent to a config.

Suggested TOML shape:

```toml
[source]
id = "example-test-report"
type = "test_report.artifact"
display_name = "Example Test Report"

[policy]
status = "allowed"
max_artifact_bytes = 52428800
max_file_count = 5000
max_depth = 20
symlink_policy = "do_not_follow"
retention_policy = "retain-local-path-and-hash"
requires_manual_review = false

[artifact]
path = "reports/latest"
kind = "directory"
profile = "saved-page-bundle"
```

Requirements:

- source IDs are explicit stable identifiers, not raw URLs;
- source IDs must not contain credentials, tokens, session IDs, or
  secret-derived values;
- artifact paths must be local and must normalize inside the configured
  repository or import root;
- source display names are metadata, not identity;
- original URLs from saved pages are provenance metadata only, not permission to
  fetch; and
- model-generated labels are never durable source identity.

## Local Artifact Discovery

ARCHIVE1 should discover local artifacts under an explicit import root.

Discovery rules:

- normalize all paths relative to the import root;
- reject repo-escaping paths;
- preserve file mode, byte length, content hash, media/type guess, and safe
  timestamps as evidence metadata when useful;
- apply file-count, byte-count, and depth limits before extraction;
- skip or diagnose files that exceed limits;
- do not follow symlinks unless policy explicitly allows it;
- do not read special device files, sockets, or pipes;
- do not execute files;
- do not decompress archives in ARCHIVE1 unless a later phase accepts archive
  expansion rules; and
- preserve skipped-file diagnostics so imports remain auditable.

When a saved page has a main HTML file and an asset directory, the source config
or manifest should identify the root and optionally the entry document. RepoMap
must not infer a remote crawl scope from local links.

## Artifact Manifest

Saved-page and static artifact ingestion should create a deterministic manifest
for the import attempt.

Manifest fields should include:

- `source_id`;
- `source_type`;
- `policy_status`;
- `artifact_run_id`;
- `artifact_manifest_id`;
- import root or safe path summary;
- source profile, such as `saved-page-bundle`, `test-report`, `fixture-corpus`,
  or `static-export`;
- file count;
- total byte count;
- skipped file count;
- per-file relative path;
- per-file byte length;
- per-file SHA-256 hash when allowed;
- detected media type or extractor family;
- extractor eligibility;
- parse/extraction status; and
- redaction or skip reasons.

The manifest is evidence and replay metadata. It is not a replacement for
canonical graph identity.

## Raw Observation Concepts

ARCHIVE0 proposes these future raw observation kinds for artifact ingestion.
Exact schemas should be accepted by ARCHIVE1 before implementation.

`source.definition`

Represents the configured local artifact source. Metadata includes source type,
display name, import root summary, and safe policy summary.

`source.policy`

Represents policy evaluation for the import. Metadata includes status, reasons,
limits, symlink policy, retention policy, and review metadata.

`source.run`

Represents one local import attempt. Metadata includes run ID, started and ended
timestamps, file counts, byte counts, skipped counts, error counts, and policy
status.

`source.artifact`

Represents one local artifact or artifact bundle entry. Metadata includes
relative path, media type, byte length, hash, retention policy, and extractor
handoff status.

`source.error`

Represents policy, path, limit, parsing, retention, or extraction errors that
are evidence-oriented and may not produce canonical domain facts.

ARCHIVE1 may choose a smaller implementation by attaching safe source/run/
artifact metadata to existing `file`, `html.*`, `css.*`, `xml.*`,
`config.*`, and `feed.*` observations, mirroring RSS2. Full canonical
`source.*` namespaces remain deferred unless a later ADR accepts them.

## Canonical Identity

ARCHIVE0 does not add canonical key namespaces.

Initial local artifact ingestion should reuse existing canonical identity:

- `file:*` for local files inside the import root or repository root;
- `html.document:*`, `html.element:*`, and `html.anchor:*` for HTML;
- `css.document:*`, `css.rule:*`, `css.selector:*`, and
  `css.custom_property:*` for CSS;
- `xml.document:*`, `xml.element:*`, and `xml.attribute:*` for generic XML;
- `config.document:*` and `config.path:*` for configuration-shaped artifacts;
  and
- `feed.document:*`, `feed.channel:*`, and `feed.item:*` for local feed
  artifacts.

Artifact run IDs, import timestamps, source config paths, extractor versions,
file hashes, and line numbers are evidence and provenance, not canonical
identity.

If future implementation needs first-class artifact nodes, it should start from
ADR 0014's conceptual `source.artifact:*` namespace in a separate source
storage/model ADR. ARCHIVE0 deliberately avoids adding that namespace now.

## Edge Vocabulary

ARCHIVE0 adds no edge kind.

Existing edge kinds remain sufficient for the local-byte facts produced by
current extractors:

- `defines` for file-to-document, file-to-element/path, and structural
  ownership facts;
- `references` for syntactic local file paths, URLs, assets, forms, feed links,
  CSS `url(...)`, CSS `@import`, XML/config references, and similar targets;
- `links_to` for Markdown documentation links only; and
- `styles` for accepted CSS-to-HTML selector matches.

Source/run/artifact provenance belongs in evidence metadata and raw observation
metadata. It should not create duplicate canonical edges for every artifact run.

## Saved-Page Bundle Semantics

A saved-page bundle is a local artifact set, not a permission grant for live
acquisition.

Recommended bundle interpretation:

- one configured import root contains the saved main page and assets;
- the main HTML file is identified by config, manifest, or deterministic local
  heuristics;
- local asset references are resolved only within the import root;
- missing local assets produce diagnostics or `unknown:*` placeholders;
- remote URLs remain `external.url:*` references with `not_fetched=true`;
- fragment links resolve only against local parsed HTML anchors when
  deterministic;
- `javascript:` links are not executed and remain dynamic/unknown/raw-only
  according to HTML1 rules;
- original page URLs, save timestamps, and browser metadata are provenance
  metadata only; and
- saved script/style contents are parsed only by static extractors already
  accepted for local bytes.

RepoMap must not chase a saved page's links back to the network.

## Static Reference Resolution

Reference resolution should reuse the existing extractor-specific rules.

General archive-level rules:

- repo-local or import-root-local relative paths may target `file:*`;
- paths escaping the import root become `unknown:*` placeholders;
- absolute filesystem paths become `external:file:*` or unknown placeholders
  unless an explicit profile maps them safely;
- `http`, `https`, and `mailto` become `external.url:*`;
- `data:` URLs remain metadata or external placeholders according to the
  extractor's safety policy;
- templated, globbed, home-relative, variable-derived, or JavaScript-derived
  paths become `dynamic:*` or raw-only diagnostics; and
- no reference target is fetched.

Credential-like URL components must be stripped from metadata and must not enter
canonical keys, raw observation metadata, readback, or explain output.

## Retention And Replay

Local artifact ingestion should be replayable.

Retention policy should decide whether RepoMap stores:

- a path reference to the existing local artifact;
- a copied artifact under `.repomap/source-artifacts`;
- a manifest and hashes only;
- redacted metadata only; or
- nothing beyond raw observation/evidence records when policy requires minimal
  retention.

Requirements:

- canonical metadata must not contain full large bodies;
- raw artifacts or copied bytes are evidence, not canonical node metadata;
- hashes may be used for deduplication when policy allows;
- secret-derived values must not be hashed or stored without separate review;
- manifests should be deterministic for byte-stable tests;
- removing an artifact import should not delete unrelated source graphs; and
- replay should be possible from retained local bytes or an explicit manifest
  plus artifact path policy.

## Redaction And Secret Handling

ARCHIVE0 reuses ADR 0010 secret-prone markers for artifact paths, config keys,
HTML attributes, form fields, XML names, CSS custom properties, feed metadata,
and manifest fields:

- `token`
- `secret`
- `password`
- `passwd`
- `api_key`
- `apikey`
- `credential`
- `private_key`
- `access_key`
- `refresh_token`
- `bearer`
- `auth`

Secret values must not appear in:

- source IDs;
- canonical keys;
- raw observation metadata;
- canonical node metadata;
- canonical edge metadata;
- artifact manifests intended for readback;
- golden fixtures;
- MCP responses;
- CLI readback; or
- explain output.

When a secret-like field is encountered, RepoMap should preserve safe metadata
such as value type, redacted flag, redaction reason, and source location.

## Test Reports And Generated Reports

Test reports are first-class local artifacts.

ARCHIVE1 should include fixtures that resemble generated test reports, including
HTML index pages, CSS, JavaScript files as inert assets, source drilldown pages,
coverage summaries, and static images or fonts when present.

RepoMap may extract:

- HTML structure;
- CSS rules and references;
- CSS-to-HTML selector matches;
- local asset references;
- report title and status text summaries when safe;
- JSON or XML report sidecars when present; and
- Markdown or text report artifacts when present.

RepoMap must not execute report JavaScript, fetch external assets, compute
browser layout, or treat report UI state as runtime truth.

## WARC And HAR Policy

WARC support is deferred.

A future WARC phase must define:

- archive validation;
- decompression limits;
- record identity;
- response metadata retention;
- payload hashing;
- redirect handling as archived evidence only;
- content-type routing to existing extractors;
- replay semantics; and
- privacy/secret redaction for archived bodies and headers.

HAR support is out of scope for ARCHIVE0. If accepted later, HAR needs a
separate ADR because it may contain request headers, cookies, authorization
metadata, timing data, and sensitive browser state.

## MCP Direction

ARCHIVE0 adds no MCP tools.

Future read-only MCP tools may inspect already-ingested artifact sources, runs,
manifests, and canonical facts. They must not:

- fetch URLs;
- ingest artifacts;
- create source configs;
- mutate storage;
- schedule imports;
- expose full artifact bodies;
- expose credentials; or
- execute active content.

Any future ingestion-capable MCP surface requires a separate ADR and must be
explicitly source-configured, policy-gated, and non-autonomous by default.

## Required Tests For ARCHIVE1

ARCHIVE1 implementation should include tests for:

- artifact source config parsing;
- policy allowed/manual-review/blocked behavior;
- local path normalization and repo-escaping rejection;
- size, file-count, and depth limits;
- symlink policy;
- manifest determinism;
- saved-page bundle discovery;
- browser Save Page As style asset directories;
- generated test report fixtures;
- fixture corpus import;
- static HTML/CSS/XML/JSON/TOML/feed extractor handoff;
- local asset reference resolution;
- missing asset diagnostics;
- remote URL references with `not_fetched=true`;
- `javascript:` and dynamic references not executing;
- redaction of secret-prone paths and values;
- canonical readback for documents, elements, paths, rules, and references;
- explainability from canonical facts back to artifact evidence; and
- proof that no HTTP fetching, browser automation, JavaScript execution, HAR
  parsing, or WARC parsing occurs.

Fixtures should use generic names such as:

- `example-saved-page-archive`;
- `example-test-report`;
- `example-static-export`;
- `example-fixture-corpus`; and
- `example-static-artifact`.

Fixtures must not name or endorse extraction from any particular third-party
website.

## Proposed Phases

`ARCHIVE1`

Local saved-page/static artifact ingestion from an explicit local directory or
manifest. Reuse existing extractors. No fetching, WARC, HAR, browser
automation, JavaScript execution, or MCP tools.

`ARCHIVE2`

Read-only artifact source/run/manifest query surfaces if ARCHIVE1 metadata is
useful enough to expose. CLI should come before MCP.

`WARC0`

WARC graph and retention ADR. ADR-only.

`WARC1`

Local WARC fixture ingestion if WARC0 is accepted. No live acquisition.

`HAR0`

HAR policy and graph ADR only if a concrete need appears and privacy/security
risks are acceptable.

`JS0`

Shallow static JavaScript graph ADR only if saved-page or report fixtures show
that inert script structure is necessary. This remains static analysis, not
execution.

## Rejected Alternatives

### Live Website Acquisition In ARCHIVE1

Rejected. ARCHIVE0 and ARCHIVE1 are local artifact phases. Live acquisition
requires separate policy, rate-limit, timeout, audit, and source configuration
work.

### Crawling Saved Page Links

Rejected. A saved page's links are references, not crawl instructions. RepoMap
must not expand local artifact ingestion into site acquisition.

### Browser Automation

Rejected. Browser automation introduces runtime state, active content,
credentials, nondeterminism, and policy risk. Saved artifacts should be analyzed
as local bytes.

### Executing JavaScript

Rejected. RepoMap may treat JavaScript files or inline scripts as inert assets
or future static source text. It must not execute them.

### HAR As The First Archive Format

Rejected. HAR files often contain sensitive request headers, cookies,
authorization details, and browser timing state. WARC or simpler static bundles
are safer first targets.

### New Canonical Artifact Namespaces In ARCHIVE0

Rejected for now. Existing `file`, `html`, `css`, `xml`, `config`, and `feed`
namespaces can model useful local artifact facts. First-class `source.*` or
`artifact.*` namespaces need a later storage/model decision.

### Storing Full Artifact Bodies In Canonical Metadata

Rejected. Large bodies and saved page contents belong in retained artifacts or
evidence, not canonical node or edge summaries.

### Treating Original URLs As Permission

Rejected. Original URLs in saved artifacts are provenance and references only.
They do not authorize live fetching, crawling, or broad ingestion.

## Consequences

ARCHIVE0 keeps RepoMap's ingestion posture boring, local, and auditable. It
allows useful saved-page, report, fixture, and static-export graphing without
expanding into live network behavior.

The tradeoff is that source/run/artifact metadata remains evidence-oriented
until a later storage/model phase accepts first-class source or artifact
identity. That is intentional: local artifact ingestion can become useful by
reusing existing extractors before RepoMap commits to additional storage tables
or MCP surfaces.
