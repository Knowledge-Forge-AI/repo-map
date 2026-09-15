# ADR 0014: Source Ingestion Architecture

## Status

Accepted

## Date

2026-06-30

## Context

RepoMap can now model local source files and static document formats:
Markdown, JSON-family and TOML configuration, plist/XML, generic XML, HTML,
CSS, and conservative CSS-to-HTML selector matches. These extractors turn local
bytes into raw observations, evidence, canonical nodes, and canonical edges.

The next product direction is source ingestion: mapping official information
feeds, documented APIs, public or user-authorized bulk datasets, local/manual
imports, saved-page archives, test harness reports, fixtures, and
policy-approved static artifacts into Postgres-backed knowledge graphs that can
later be queried through CLI reports and read-only MCP surfaces.

Ingestion has different risks than extraction. Extractors analyze bytes that
RepoMap already has. Ingestion acquires bytes or artifacts from configured
sources. That acquisition step can involve network behavior, rate limits,
terms, privacy, credentials, audit logging, and source-specific policy.

RepoMap should remain a deterministic local knowledge-graph builder. It should
not advertise, endorse, or facilitate third-party site extraction, anti-bot
circumvention, login-wall extraction, CAPTCHA bypass, stealth scraping, or
terms-hostile extraction. Source ingestion must be explicit, auditable,
reversible, and policy-gated before any network acquisition occurs.

## Decision

RepoMap will define source ingestion as a separate pipeline layer above
extractors.

The ingestion pipeline is:

```text
source definition
-> source policy evaluation
-> fetch/import/acquire raw source material
-> preserve raw evidence/artifacts
-> run appropriate existing extractors or future feed extractors
-> canonicalize observations
-> load into a selected Postgres-backed graph database
-> expose read-only query/report/MCP surfaces
```

Extraction and fetching remain separate:

- extractors analyze local bytes or artifacts;
- ingestion acquires those bytes or artifacts under a source policy; and
- MCP may request ingestion only through explicit configured sources, not
  arbitrary model-chosen URLs.

ING0 defines the architecture, policy model, and future phase boundaries. It
does not implement ingestion code, HTTP fetching, RSS parsing, source-specific
connectors, scheduler behavior, MCP tools, JavaScript execution, browser
automation, or public CLI changes.

## Scope

In scope:

- source ingestion architecture;
- source type taxonomy;
- source policy status model;
- guardrails for local/manual sources, saved artifacts, feeds, APIs, bulk
  datasets, test reports, fixtures, and policy-approved static artifacts;
- conceptual source identity and future raw observation vocabulary;
- explicit Postgres database or schema mapping requirements;
- future read-only MCP direction; and
- phase planning for RSS, archive/static artifact, API, bulk, and MCP
  ingestion work.

Out of scope:

- implementing ingestion code;
- RSS, Atom, or JSON feed extraction;
- HTTP fetching;
- terms-hostile extraction;
- scheduler code;
- source-specific connectors;
- MCP source-ingestion tools;
- JavaScript execution;
- browser automation;
- changes to HTML, CSS, XML, JSON, TOML, Markdown, Python, Nix, or storage
  behavior;
- public readback default changes;
- Phase F migration; and
- Shell/Bats/AWK extraction.

## Source Type Taxonomy

RepoMap source definitions should classify each configured source with one of
these initial source types.

`local.file`

One local file supplied by the user or project configuration. The source is
already local and does not require network acquisition.

`local.directory`

One local directory tree supplied by the user or project configuration. Profile
and traversal rules decide which files become artifacts.

`manual.import`

A user-provided file, archive, export, or captured artifact imported into
RepoMap. The import path is explicit and local.

`saved_page.archive`

A saved page, page bundle, browser export, WARC-like archive, or other
user-supplied page archive that the user lawfully obtained outside RepoMap.
RepoMap analyzes the local saved artifact; it does not infer permission to
fetch the original site.

`test_report.artifact`

A generated test report, coverage report, build report, or similar local
harness artifact. RepoMap treats these as first-class source artifacts for
project understanding.

`fixture.corpus`

A local fixture corpus used for tests, examples, smoke checks, or deterministic
development. Fixture corpora are preferred for early ingestion implementation
because they avoid network policy risk.

`feed.rss`

An RSS feed. RSS is preferred when an information source provides one.

`feed.atom`

An Atom feed. Atom is preferred when an information source provides one.

`feed.json`

A JSON feed or similar documented feed endpoint. JSON feeds are preferred when
an information source provides one.

`api.rest`

A documented or explicitly authorized REST-style API. API requests must follow
configured authentication, rate limits, pagination, timeouts, and audit policy.

`bulk.archive`

A public or user-authorized downloadable data dump, archive, export, or snapshot
intended for bulk ingestion.

`static_artifact`

A local static artifact supplied by a user, fixture, test harness, bulk export,
feed enclosure, or documented API response. Examples include saved HTML, CSS,
XML, JSON, images, text files, and report assets. RepoMap analyzes the local
artifact and does not need to fetch the origin.

`policy_approved_static_source`

A future network-capable static source that has explicit source configuration
and policy approval for narrow acquisition. This source type is not part of the
first ingestion implementation and is not a general site acquisition mechanism.

`dynamic_source_deferred`

A source that appears to require JavaScript, browser/runtime behavior, session
state, login, CAPTCHA, or other dynamic behavior. Early ingestion phases do not
implement this source type.

`unknown`

An unclassified source. Unknown sources require manual classification and
policy review before ingestion.

Local/manual imports, saved-page archives, test reports, fixtures, official
feeds, documented APIs, and bulk datasets are first-class source types. Network
acquisition of static artifacts is a later, policy-gated path.

## Source Policy Statuses

Source policy evaluation returns one of these statuses:

- `allowed`
- `allowed_with_limits`
- `rss_preferred`
- `api_preferred`
- `bulk_preferred`
- `manual_review_required`
- `blocked_login_required`
- `blocked_anti_bot_circumvention`
- `blocked_terms_risk`
- `blocked_privacy_risk`
- `blocked_circumvention_required`
- `blocked_unknown`

Policy status is not a legal conclusion. It is an operational guardrail that
decides whether RepoMap may proceed, must prefer a safer source type, must
request review, or must stop.

Suggested policy metadata:

- `source_type`;
- `policy_status`;
- `policy_reasons`;
- `allowed_methods`;
- `preferred_method`;
- `rate_limit`;
- `timeout`;
- `user_agent`;
- `contact`;
- `robots_policy`;
- `terms_policy`;
- `credential_policy`;
- `artifact_retention_policy`;
- `max_artifact_bytes`;
- `max_items_per_run`;
- `requires_manual_review`;
- `last_reviewed_at`; and
- `review_notes`.

## Source Policy Rules

RepoMap ingestion must not:

- bypass CAPTCHA;
- rotate proxies to evade blocking;
- spoof identity to defeat anti-bot systems;
- bypass login walls;
- perform stealth scraping;
- extract private or authenticated user data unless the user explicitly
  supplies an export or authorized API path;
- circumvent rate limits;
- fetch in ways inconsistent with robots or configured source policy;
- execute untrusted JavaScript;
- use headless browser automation in early phases;
- fetch arbitrary URLs selected by a model without user or source
  configuration;
- treat a public page as permission to ingest at scale; or
- store secrets in canonical keys, logs, readback metadata, or explain output.

Ingestion may proceed when:

- the source is local or user-provided;
- the source has an RSS, Atom, or JSON feed and feed policy permits it;
- the source has a documented API or bulk export and policy permits it;
- the source is a saved-page archive lawfully obtained by the user;
- the source is a test harness report or fixture corpus;
- the source is a static artifact supplied locally by a feed, API, archive,
  report, fixture, or manual import;
- a future policy-approved static source permits narrow acquisition;
- rate limits, timeouts, and user-agent or contact metadata are configured when
  needed;
- the acquisition plan is narrow and auditable; and
- the resulting artifacts can be removed or replayed without mutating source
  systems.

If a source is ambiguous, RepoMap defaults to `manual_review_required` or a
blocked status. It does not guess permission from the existence of a URL.

## Robots And Terms Policy

Robots.txt, source-specific policies, terms, and rate limits are policy inputs
for any future network-capable static source acquisition.
ING0 does not decide legal compliance and does not implement robots or terms
checking.

Future implementations should:

- record source policy metadata;
- require explicit user or project configuration for any network-capable
  non-feed source;
- respect configured robots/source-policy decisions;
- keep per-run audit logs for network-capable acquisition;
- prefer local/manual imports, saved-page archives, feeds, APIs, and bulk
  exports over network acquisition; and
- default ambiguous sources to `manual_review_required` or blocked.

Examples in RepoMap docs and tests should use generic fixture names only, such
as:

- `example-news-feed`
- `example-saved-page-archive`
- `example-public-api`
- `example-bulk-export`
- `example-test-report`

RepoMap documentation must not name or endorse extraction from any particular
third-party website.

## Ingestion Identity

ING0 does not change the current graph key grammar in code. It defines
conceptual source identity for later ADRs and implementation phases.

Proposed future graph key namespaces:

```text
source.definition:<encoded-source-id>
source.run:<encoded-source-id>:<encoded-run-id>
source.artifact:<encoded-source-id>:<encoded-artifact-id>
source.policy:<encoded-source-id>
feed.channel:<encoded-source-id>:<encoded-feed-id>
feed.item:<encoded-source-id>:<encoded-item-id>
```

These namespaces are not implemented by ING0. RSS0 may refine or replace
feed-specific namespaces before they are accepted in graph key version 1.

Identity rules:

- source IDs are explicit configuration identifiers, not raw URLs selected by a
  model;
- source IDs should be stable within the configured project or graph database;
- run IDs identify ingestion attempts and are provenance, not the identity of
  fetched domain entities;
- artifact IDs may be assigned from source-provided IDs, normalized URLs,
  content hashes, or import paths according to a later source-specific ADR;
- credentials, tokens, session IDs, and secret-derived values are never key
  material;
- line numbers, fetch timestamps, extractor versions, and raw source IDs are
  evidence, not canonical identity; and
- model-generated labels are display metadata, not stable graph identity.

## Conceptual Raw Observation Kinds

ING0 proposes the following future raw observation kinds. Exact schemas must be
accepted by later source-specific ADRs before implementation.

`source.definition`

Represents a configured source. Metadata includes source type, display name,
configured origin summary, target database or schema mapping, and safe policy
summary.

`source.policy`

Represents the result of source policy evaluation. Metadata includes status,
reasons, limits, preferred acquisition method, review metadata, and blocked
conditions.

`source.run`

Represents one ingestion run. Metadata includes run ID, source ID, started and
ended timestamps, acquisition method, item counts, artifact counts, error
counts, and policy status at run time.

`source.artifact`

Represents one acquired or imported artifact. Metadata includes artifact ID,
safe origin summary, media type, byte length, content hash when allowed,
retention policy, and artifact storage reference.

`source.fetch`

Represents one acquisition operation. For local/manual imports this is an
import event. For future network-capable sources it may represent a fetch
attempt. Metadata includes method, status class, retry count when relevant,
timeout policy, rate-limit bucket when relevant, and safe response or import
summary. It must not store secrets or full response bodies in canonical
metadata.

`source.error`

Represents policy, network, parsing, retention, or validation errors that are
evidence-oriented and may not produce canonical domain facts.

`feed.channel`

Represents a feed channel or top-level feed document.

`feed.item`

Represents a feed entry/item when a later feed ADR accepts stable feed item
identity.

`feed.link`

Represents feed links, enclosures, alternate URLs, or related item URLs as
syntactic references only.

`feed.author`

Represents feed author metadata if a later ADR accepts how to identify authors
without overclaiming identity.

`feed.category`

Represents feed categories or tags if a later ADR accepts category identity and
normalization.

These observations follow ADR 0001: raw observations are extractor or ingestion
interchange and audit records. Canonical nodes and edges are built later
through a tested canonicalization layer.

## Postgres Mapping

A configured source or source group may map to a target Postgres database or
schema on a configured Postgres server.

Requirements:

- database and schema mapping is explicit configuration, not model-selected;
- source IDs map deterministically to a repository, project, source group, or
  database context;
- ingestion supports isolated per-source, per-project, or per-source-group
  databases or schemas where configured;
- raw artifacts, source policy records, source runs, raw observations, and
  canonical graph rows preserve provenance;
- read-only MCP queries configured mappings but does not create arbitrary
  databases;
- write and ingest operations remain explicit, auditable, and separate from
  read-only graph query tools; and
- rollback can delete or disable an ingestion run without deleting unrelated
  source or project graphs.

Future storage design should decide whether source definitions, source runs,
artifact records, and policy snapshots live in RepoMap's existing graph
database, a sidecar schema, or a source-ingestion control database. That choice
requires a storage ADR or implementation plan before code changes.

## MCP Direction

RepoMap's MCP surface remains read-only unless a later ADR explicitly accepts a
write or ingestion tool surface.

Future read-only MCP tools may include:

- list configured sources;
- show source policy;
- show source health;
- list ingestion runs;
- search ingested items;
- explain an ingested item;
- query graph by source;
- query source artifacts; and
- query canonical relationships.

Future write or ingest MCP tools, if ever added, require a separate ADR. They
must not be model-autonomous by default and must not allow arbitrary URL
fetching from model text. A model may select among configured sources only when
the tool contract and source policy allow that action.

The read-only multi-project MCP registry remains a graph selection layer. It is
not a mutation surface and must not be extended into implicit discovery,
loading, fetching, or ingestion as part of ING0.

## Security Posture

Network-capable ingestion must have rate-limit, timeout, credential, and audit
logging design before implementation.

Security requirements:

- no arbitrary URL fetch from MCP in early phases;
- no source addition from model text alone;
- no credentials in canonical keys;
- no credentials in raw observation metadata, canonical metadata, logs, readback,
  or explain output;
- source configs may reference environment variables or local secret stores, but
  secret values must not be stored as graph facts;
- policy and acquisition logs must distinguish configured/intended state from
  verified working state;
- acquired artifacts must be size-limited and content-type checked before
  extraction;
- parsers must continue to avoid executing scripts or active content;
- source-specific credential scopes must be narrow and documented; and
- failures must stop safely rather than broadening acquisition.

RepoMap should prefer explicit `unknown:*`, `external:*`, or `dynamic:*`
placeholders over fabricated precision when source identity, artifact identity,
or target references are ambiguous.

## Artifacts And Evidence

Ingestion should preserve raw artifacts as evidence when policy permits.

Artifact requirements:

- acquired bytes are stored as raw evidence or hash-addressed
  artifacts, not canonical summary metadata;
- canonical graph facts point back to source run and artifact evidence;
- large bodies are not duplicated into canonical node or edge metadata;
- content hashing may be used for deduplication;
- hash policy must not leak secret-derived values unless separately reviewed;
- retention policy decides whether full bodies, redacted bodies, hashes, or
  artifact paths are retained; and
- raw observations derived from artifacts remain replayable into newer
  canonical graphs.

When policy disallows retaining full bodies, RepoMap may keep safe metadata,
hashes, and evidence references sufficient to explain what happened without
keeping the sensitive content itself.

## Query And Readback Direction

Source ingestion should eventually make these questions answerable:

- which configured sources exist for this graph;
- which policy status gates each source;
- which ingestion runs succeeded, failed, or were skipped;
- which artifacts supported a canonical node or edge;
- which feed items, API records, archive entries, reports, or fixtures
  contributed to a fact;
- why an ingested fact exists;
- which source should be replayed after canonicalization changes; and
- which source policy blocked or limited acquisition.

Readback should use canonical graph identity where accepted, and evidence
records should carry line spans, fetch/import metadata, source IDs, run IDs,
artifact IDs, and parser/extractor details.

## Phase Plan

Future phases should proceed in this order unless a later ADR changes the plan:

`RSS0`

RSS, Atom, and JSON Feed graph model ADR. Feed work should come before any
network-capable static source acquisition.

`RSS1`

Local fixture-based feed extraction and canonicalization. This phase uses local
feed fixtures before network fetching.

`RSS2`

Configured feed ingestion from explicit allowlisted feed URLs, with source
policy, rate limits, timeouts, audit logging, and artifact retention defined
before implementation.

`MCP-ING0`

Read-only source and feed MCP query tools for configured sources, policy, runs,
artifacts, and graph relationships. No write or arbitrary fetch tools.

`ARCHIVE0`

Saved-page and static artifact ingestion ADR. This must define artifact layout,
source policy, size limits, content-type handling, retention, provenance, and
audit logging before implementation.

`ARCHIVE1`

Local saved-page archive ingestion using the existing HTML, CSS, XML, JSON, and
other local-byte extractors. No login, CAPTCHA, browser automation, JavaScript
execution, URL fetching, or open-ended site acquisition.

`JS0`

Shallow static JavaScript graph ADR only if saved-page/archive fixtures prove it
is needed. This is an ADR-only planning phase unless separately approved.

`API0`

Documented API ingestion ADR covering authentication references, pagination,
rate limits, retries, response retention, and source-specific schema policy.

`BULK0`

Bulk/archive ingestion ADR covering archive validation, extraction limits,
hashing, retention, replay, and provenance.

## Rejected Alternatives

### Scraper-First Roadmap

Rejected. RepoMap should prefer feeds, APIs, bulk exports, local files, and
explicit imports before any network-capable static source acquisition. A
scraper-first posture would blur extraction with acquisition and create
unnecessary legal, social, and operational risk.

### Naming Or Advertising Third-Party Scraping Targets

Rejected. RepoMap docs and fixtures should use generic examples. The project
should not endorse extraction from particular third-party websites.

### Anti-Bot Circumvention

Rejected. Proxy rotation to evade blocking, CAPTCHA bypass, stealth user-agent
behavior, login-wall bypass, and similar circumvention tactics are outside the
project's acceptable source policy.

### Headless Browser Automation In Early Phases

Rejected. Browser automation expands risk and nondeterminism. Early ingestion
must focus on feeds, local fixtures, documented APIs, bulk exports, and low-
friction static pages where policy permits.

### Executing Arbitrary JavaScript

Rejected. RepoMap's static graph model must not execute untrusted active
content. If a future phase needs JavaScript analysis, it should start with a
static JS ADR.

### Arbitrary Model-Selected URL Fetching

Rejected. Ingestion sources must be configured and policy-evaluated. MCP tools
must not fetch arbitrary URLs chosen from model text.

### Treating Public Pages As Permission To Ingest At Scale

Rejected. A public page is not by itself a source policy. RepoMap should prefer
feeds, APIs, bulk exports, saved-page archives, local artifacts, and fixtures;
ambiguous network sources require manual review or a blocked status.

### Matching All Websites To Generic Acquisition Logic

Rejected. Different source types have different policies, identity models,
rate limits, artifact semantics, and replay needs. Generic acquisition logic
would hide those differences.

### Storing Fetched Bodies Directly As Canonical Metadata

Rejected. Bodies are artifacts or evidence. Canonical metadata should hold
small summaries and durable identity fields, not large fetched content.

### Mixing Ingestion Writes Into Existing Read-Only MCP Query Tools

Rejected. Read-only MCP graph queries remain separate from ingestion writes.
Any write or ingest MCP surface requires a later ADR.

### Treating Source Policy As Purely Technical

Rejected. Robots, terms, privacy, user authorization, credentials, rate limits,
and source expectations are policy inputs. They cannot be reduced to whether a
request technically succeeds.

## Consequences

- RepoMap can plan source ingestion without weakening the deterministic local
  extractor model.
- RSS, API, bulk, saved-page archive, fixture, report, and static artifact work
  have clear phase boundaries.
- Source acquisition becomes auditable and policy-gated before network-capable
  implementation begins.
- Read-only MCP remains safe while ingestion architecture matures.
- Future implementation ADRs can refine source identity, feed identity, storage
  layout, artifact retention, and query contracts without changing existing
  extractor behavior in ING0.
