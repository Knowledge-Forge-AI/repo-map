# ADR 0017: WARC Archive Graph Model

## Status

Accepted

## Date

2026-06-30

## Context

ARCHIVE1 imports local saved-page and static artifact directories, applies
local artifact policy, creates deterministic manifests, routes eligible local
files to existing extractors, and loads observations through the existing
storage path. WARC is the next archive-completeness step, but only as analysis
of archive files the user already possesses.

WARC files can contain archived HTTP exchanges, request metadata, response
payloads, redirects, revisits, conversion records, and crawl metadata. That
history is useful for graphing saved pages, static assets, feeds, config
payloads, and generated or exported content. It is also privacy-sensitive:
captures can include cookies, authorization headers, session-bearing URLs,
private page bodies, and data from authenticated sessions.

WARC0 defines how RepoMap should inspect local WARC files as archival
containers, route safe payloads to existing extractors, preserve provenance,
and avoid turning WARC support into crawling, replay, browser automation, HAR
analysis, or live website acquisition.

## Decision

RepoMap will model WARC support as local archive artifact analysis.

The future WARC1 pipeline is:

```text
WARC source config
-> local WARC policy validation
-> WARC file validation / bounded scan
-> WARC record manifest / evidence records
-> route eligible response/resource payloads to existing extractors
-> canonicalize observations
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

WARC archives are input artifacts, not acquisition instructions. Original
target URLs are provenance and syntactic references only. Redirect records are
archived evidence only. Missing resources are not fetched. Pages are not
replayed. JavaScript is not executed. HAR remains out of scope.

WARC0 accepts graph key version 1 namespace additions for:

```text
warc.document:<encoded-file-key>
warc.record:<encoded-warc-document-key>:<encoded-record-id>
```

These namespaces are accepted for WARC1 only if they improve readback and
explainability without requiring storage migrations. WARC payload facts should
still be represented by existing namespaces after payload routing, such as
`html.*`, `css.*`, `xml.*`, `config.*`, `feed.*`, and `file:*`. WARC nodes
should remain provenance and archive-structure nodes, not replacements for
payload-domain nodes.

WARC0 adds no edge kind. WARC1 should reuse:

- `defines` for WARC document and record structural ownership when WARC nodes
  are emitted; and
- `references` for target URIs, `WARC-Concurrent-To`, `WARC-Refers-To`,
  profile URIs, payload URLs, and other syntactic links.

## Scope

In scope:

- local `.warc` files;
- optional `.warc.gz` support only if bounded decompression is implemented
  safely;
- WARC record validation and bounded scanning;
- WARC record manifests;
- WARC and HTTP header redaction;
- target URI redaction and reference modeling;
- response and resource payload routing to existing extractors;
- payload materialization policy;
- WARC record identity;
- fixture and test requirements for WARC1; and
- local-only security and privacy policy.

Out of scope:

- implementing WARC parsing in WARC0;
- building WARC archives;
- archive decompression implementation;
- HTTP fetching;
- crawler behavior;
- fetching missing resources;
- replaying pages;
- browser automation;
- JavaScript execution;
- HAR parsing;
- MCP tools;
- storage migrations;
- changes to ARCHIVE1 behavior;
- changes to HTML, CSS, XML, JSON, feed, storage, or public readback behavior;
- Phase F migration;
- API, BULK, JS, DOCS, or YAML work; and
- source-specific publisher logic.

## Supported WARC Shape

WARC1 should initially support local `.warc` files. `.warc.gz` may be included
only if the implementation has explicit bounded decompression limits for:

- compressed byte count;
- decompressed byte count;
- record count;
- per-record payload bytes; and
- total routed payload bytes.

If bounded decompression is not small and safe enough, WARC1 should support
plain `.warc` only and defer `.warc.gz`.

WARC1 should handle common WARC record types conservatively:

`warcinfo`

Metadata and evidence-first. May define a `warc.document:*` summary when WARC
nodes are enabled.

`response`

May provide an HTTP response payload for extractor routing after header
redaction, payload limit checks, content-type checks, and safe sniffing.

`resource`

May provide a non-HTTP or resource payload for extractor routing after the same
bounded safety checks used for responses.

`request`

Metadata and evidence-first. Request headers and bodies are sensitive and must
not be exposed by default.

`metadata`

Metadata and evidence-first. May contribute safe summaries and references.

`revisit`

Preserve provenance and links to referenced records, but do not fabricate
payload facts.

`conversion`

Metadata and evidence-first unless a later phase accepts conversion payload
routing.

`continuation`

May be deferred in WARC1. If unsupported, emit diagnostics and avoid guessing
reconstructed payload facts.

Unknown record types should become diagnostics or metadata-only records.

## Raw Observation Kinds

WARC1 should define future raw observations using the standard RepoMap raw
observation shape.

### `warc.document`

Represents one local WARC file.

Required metadata:

- `format`: `warc`;
- WARC version when available;
- parser and parser mode;
- local WARC path;
- record count;
- parsed record count;
- skipped record count;
- routed payload count;
- total payload bytes observed within limits;
- policy status; and
- manifest ID when available.

Canonicalization may create a `warc.document:*` node and a
`file:* --defines--> warc.document:*` edge when WARC nodes are enabled.

### `warc.record`

Represents one WARC record summary.

Required metadata:

- record ordinal;
- record type;
- redacted record ID summary;
- identity source;
- identity strength;
- redacted target URI summary when present;
- WARC date;
- safe content type summary;
- payload byte length when known;
- payload digest when policy allows;
- extractor route;
- materialized path when used;
- skip reason when skipped; and
- duplicate identity flag when applicable.

Canonicalization may create a `warc.record:*` node and a
`warc.document:* --defines--> warc.record:*` edge when WARC nodes are enabled.

### `warc.header`

Represents safe summarized header facts. Header observations are raw/evidence
or record metadata in WARC1 and should not create canonical nodes.

### `warc.payload`

Represents a bounded local payload handoff. Payload bodies are not stored in
canonical metadata. The observation links record evidence to either a
materialized safe local payload path or an extractor handoff summary.

### `warc.reference`

Represents syntactic WARC references, such as target URI, concurrent-to,
refers-to, profile, payload URL, redirect location, or safe link-like headers.
Canonicalization may create `references` edges when the target is conservative
and redacted.

### `warc.parse_error`

Represents malformed records, unsupported constructs, dangerous privacy
conditions, limit failures, and parser failures. Parse errors remain
raw/evidence-only.

Observation principles:

- WARC observations are evidence and provenance-heavy.
- Payload bodies are not canonical metadata.
- Headers are redacted before serialization.
- Original URLs are safe summaries and references only.
- Network headers may include sensitive values and must be filtered.
- Parse errors do not block unrelated safe records when the parser can resume.

## Canonical Identity

WARC0 accepts `warc.document:*` and `warc.record:*` as graph key version 1
namespace additions for WARC1 if implementation remains small and storage-free.

`warc.document:<encoded-file-key>`

The document key is based on the local WARC file key. It must not include
absolute checkout paths, current time, content hashes, target URLs, or source
config paths.

`warc.record:<encoded-warc-document-key>:<encoded-record-id>`

The record ID is derived by the record identity policy below. It must not use
payload body content, current time, parser object IDs, line numbers, or raw
secret-bearing URLs.

If implementing WARC nodes expands WARC1 too much, WARC1 may defer canonical
WARC nodes and keep WARC observations raw/evidence-oriented while routing safe
payloads into existing canonical namespaces. That deferral must be documented
in the WARC1 exit audit.

## Edge Vocabulary

WARC0 adds no new edge kind.

Accepted edge uses:

- `file:* --defines--> warc.document:*` when WARC document nodes are emitted;
- `warc.document:* --defines--> warc.record:*` when WARC record nodes are
  emitted;
- `warc.record:* --references--> external.url:* | file:* | unknown:* |
  dynamic:*` for redacted target URIs and syntactic header references;
- `warc.record:* --references--> warc.record:*` for record IDs such as
  `WARC-Concurrent-To` and `WARC-Refers-To` when both records are present and
  safely identifiable; and
- existing extractor edges for routed payloads.

WARC provenance belongs in raw observation metadata and evidence metadata.
Payload-domain facts should continue to use the canonical graph emitted by the
HTML, CSS, XML, config, and feed extractors.

## Record Identity

Record identity priority:

1. `WARC-Record-ID` when present and safe.
2. `WARC-Date` plus redacted `WARC-Target-URI` plus record type when present.
3. Deterministic record ordinal as a last resort.

Identity metadata must record:

- `identity_source`;
- `identity_strength`: `strong`, `medium`, `weak`, or `structural`;
- `duplicate_identity`: boolean;
- record type; and
- whether target URI redaction affected the fallback identity.

Rules:

- record identity must not use payload body content;
- record identity must not use current time;
- record identity must not use parser object IDs;
- record identity must not use raw secret-bearing target URLs;
- structural ordinal identity must be marked `structural`; and
- duplicate `WARC-Record-ID` values must emit diagnostics and either
  deterministic disambiguation or raw-only behavior.

## Target URI Policy

WARC target URIs are provenance and syntactic references. They are never fetch
instructions.

Target handling:

- `http`, `https`, and `mailto` become `external.url:*` after credential and
  secret-prone query redaction;
- repo-local relative file references may become `file:*` only when produced by
  a routed local payload extractor, not from arbitrary target URI guessing;
- `file:`, `data:`, `about:`, `blob:`, `javascript:`, and unsupported schemes
  require conservative placeholder behavior or raw-only diagnostics;
- credentials embedded in URLs must be stripped or redacted;
- query strings should be redacted or summarized when keys are secret-prone;
- target URI summaries must not leak tokens, sessions, passwords, or private
  keys; and
- target URI values are never fetched.

## Header Policy

WARC and HTTP headers may contain sensitive values. Header redaction applies to:

- `Authorization`;
- `Cookie`;
- `Set-Cookie`;
- `Proxy-Authorization`;
- `X-Api-Key`;
- `API-Key`;
- names containing `token`, `secret`, `password`, `passwd`, `private_key`,
  `access_key`, `refresh_token`, `bearer`, or `auth`;
- session-like headers; and
- any configured secret markers.

Safe headers may be summarized:

- `Content-Type`;
- `Content-Length`;
- `Last-Modified`;
- `ETag` only when not secret-prone;
- `WARC-Type`;
- `WARC-Date`;
- `WARC-Record-ID`;
- redacted `WARC-Target-URI`;
- `WARC-Concurrent-To`;
- `WARC-Refers-To`;
- `WARC-Block-Digest`; and
- `WARC-Payload-Digest`.

Full WARC or HTTP header blocks must not be stored in canonical metadata,
manifests intended for readback, CLI output, MCP output, or explain output.

## Payload Routing

WARC1 should route eligible local payloads to existing extractors by content
type and safe local sniffing.

Recommended routing:

- `text/html` -> HTML extractor;
- `text/css` -> CSS extractor;
- XML, RSS, and Atom -> XML/feed routing;
- JSON and JSON Feed -> JSON/feed/config routing;
- `text/plain` -> metadata/evidence only until a text/document extractor is
  accepted;
- JavaScript -> inert static asset only until JS0;
- images, fonts, media, and binaries -> metadata/evidence only; and
- unknown content types -> metadata/evidence only.

Requirements:

- no payload execution;
- no browser rendering;
- no JavaScript execution;
- no CSS execution;
- no embedded resource fetching;
- no remote schema, DTD, namespace, or source map fetching;
- payload size limits before extraction;
- record count limits;
- total payload byte limits; and
- decompression limits if `.warc.gz` is supported.

## Synthetic Local Paths

If WARC payloads are routed to existing extractors, WARC1 must use safe,
deterministic synthetic paths.

Example shape:

```text
.warc/<safe-warc-file-name>/<record-ordinal-or-id>/payload.html
```

Rules:

- synthetic paths must be deterministic;
- synthetic paths must not include secret target URLs;
- synthetic paths must not include raw query strings;
- synthetic paths must not include cookies, auth tokens, or header values;
- synthetic paths must be root-relative under the import context;
- synthetic paths are artifact identity and evidence, not proof of a real
  filesystem file unless materialized; and
- synthetic paths must avoid accidental collision with user source paths.

## Materialization Policy

WARC1 may either:

- materialize eligible payloads under a retained source-artifact directory such
  as `.repomap/source-artifacts/<source-id>/<run-id>/`; or
- run extractors over temporary or synthetic in-memory payloads if existing
  extractor APIs support that cleanly.

Prefer materialization if it keeps implementation simple and explainable.

Materialized files:

- must be size-limited;
- must use safe deterministic filenames;
- must avoid target URL secrets;
- must be retained under source artifact policy;
- must be excluded from accidental recursive re-import loops;
- must preserve record provenance in evidence metadata; and
- must not be exposed as full bodies through canonical metadata, readback, or
  MCP.

## Manifest

WARC1 should create a deterministic manifest.

Manifest fields:

- `source_id`;
- `source_type`;
- `artifact_run_id`;
- WARC file path summary;
- record count;
- parsed record count;
- skipped record count;
- total payload bytes;
- policy snapshot;
- warnings and errors; and
- per-record summaries.

Per-record summaries:

- record ordinal;
- record type;
- redacted record ID summary;
- target URI summary;
- WARC date;
- content type;
- payload byte length;
- payload digest if policy allows;
- extractor route;
- materialized path if used; and
- skip reason.

Manifest fields must not include:

- full payload bodies;
- sensitive headers;
- cookies;
- auth tokens;
- raw secret-bearing URLs; or
- request bodies by default.

## Policy Config

WARC1 should require an explicit local source config.

Example:

```toml
[source]
id = "example-warc-archive"
type = "saved_page.archive"
display_name = "Example WARC Archive"

[policy]
status = "allowed"
max_artifact_bytes = 104857600
max_file_count = 10
max_warc_records = 1000
max_record_bytes = 1048576
max_total_payload_bytes = 52428800
retention_policy = "materialize-safe-payloads"
requires_manual_review = false

[artifact]
path = "archives/example.warc"
kind = "warc"
profile = "warc-local-archive"
```

Policy rules:

- WARC input is a local file only;
- path must normalize inside the configured root;
- source ID must be explicit and not URL-shaped;
- blocked and manual-review statuses stop before parse;
- no URL acquisition field is allowed;
- no network behavior is allowed;
- no crawling behavior is allowed;
- no HAR behavior is allowed;
- no browser automation is allowed;
- size and record limits are required; and
- authenticated-session archives should default to manual review unless policy
  explicitly permits redacted local import.

## Security And Privacy

WARC files may include private captures. WARC1 must require:

- local-only import;
- redaction of cookies, authorization headers, proxy authorization headers,
  session headers, and secret-prone header names;
- URL credential redaction;
- secret-prone query redaction;
- no full payload bodies in canonical metadata;
- no exposure of retained payload bytes through MCP, default readback, or
  explain output;
- optional manual-review policy for archives from authenticated sessions;
- blocked or manual-review status if sensitive headers are detected and policy
  does not permit redacted import; and
- clear diagnostics when records are skipped for safety or policy reasons.

RepoMap must not treat archived pages as permission to refetch live pages or
missing resources.

## Fixture Requirements For WARC1

WARC1 fixtures should use generic names only and should not name real websites.

Add fixtures under:

```text
src/test/fixtures/source_ingestion/warc_sources/
src/test/fixtures/source_ingestion/warc_artifacts/
```

Fixture coverage:

- small WARC with one HTML response;
- CSS response;
- JSON or feed response;
- binary/image response metadata-only;
- request record with sensitive headers redacted;
- response with sensitive `Set-Cookie` redacted;
- duplicate record ID case;
- malformed WARC case;
- oversized record case;
- unsupported record type case;
- target URI with credential/query redaction; and
- no network proof.

## Required Tests For WARC1

WARC1 implementation must include tests for:

- WARC source config parsing;
- policy allowed/manual-review/blocked behavior;
- local path normalization and repo-escaping rejection;
- max WARC record and byte limits;
- WARC record parsing;
- record identity priority;
- duplicate record ID behavior;
- header redaction;
- target URI redaction;
- HTML payload routing to the HTML extractor;
- CSS payload routing to the CSS extractor;
- JSON/feed payload routing where applicable;
- binary payload metadata-only behavior;
- malformed WARC diagnostics;
- manifest determinism;
- materialized payload path safety when used;
- storage load/readback for routed HTML, CSS, feed, and config facts;
- explainability back to WARC record evidence;
- no URL fetching;
- no crawler behavior;
- no JavaScript execution; and
- no HAR parsing.

## Proposed Next Phase

`WARC1`

Local WARC import and extraction implementation. WARC1 should parse explicit
local WARC fixtures and user-provided WARC files under source policy, route safe
payloads to existing extractors, and load through existing storage paths. It
must not add live acquisition, crawling, page replay, JavaScript execution, HAR
parsing, browser automation, or MCP tools.

## Rejected Alternatives

### WARC As Crawler Or Acquisition Feature

Rejected. WARC archives are input artifacts, not instructions to crawl, refetch,
or acquire more data.

### Fetching Missing Resources

Rejected. Missing resources remain missing archived evidence. WARC support must
not use target URLs or page references as fetch instructions.

### Replaying WARC As A Website

Rejected. Page replay requires browser/runtime behavior and can blur archived
evidence with live behavior. RepoMap should analyze local bytes statically.

### Executing Archived JavaScript

Rejected. JavaScript remains inert source text or future static analysis input.
It is never executed in WARC1.

### HAR Support In WARC1

Rejected. HAR files have different privacy and browser-state risks and require
a separate ADR.

### Storing Raw HTTP Headers In Canonical Metadata

Rejected. Header blocks frequently contain cookies, authorization data, and
session identifiers. Only redacted safe summaries belong in metadata.

### Using Target URLs As Synthetic Paths

Rejected. Target URLs can contain credentials, tokens, query secrets, and
private paths. Synthetic paths must be generated from safe deterministic record
identity, not raw URLs.

### Native Browser Rendering

Rejected. Rendering introduces active content, nondeterminism, browser defaults,
and privacy risks. Existing static extractors are the WARC1 payload boundary.

### Treating Archived Pages As Permission For Live Refetching

Rejected. Archived target URIs are provenance and references only.

## Consequences

WARC0 keeps WARC support local, boring, and auditable. It allows RepoMap to
plan useful archive-completeness work without broadening into crawling, replay,
or live acquisition.

The tradeoff is that WARC1 must be conservative: some record types, compressed
archives, continuations, conversion payloads, sensitive headers, and large
payloads may remain raw/evidence-only or skipped until a later phase defines
additional safety rules.
