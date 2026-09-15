# ADR 0015: Feed Graph Model

## Status

Accepted

## Date

2026-06-30

## Context

ADR 0014 defines source ingestion as a policy-gated layer above RepoMap's local
extractors. It prefers official information feeds, documented APIs, public or
user-authorized bulk datasets, local/manual imports, saved-page archives, test
harness reports, fixtures, and static artifacts. It also keeps acquisition
separate from extraction: ingestion acquires artifacts under policy, while
extractors analyze local bytes.

RSS0 defines the first feed-specific graph model. RSS, Atom, and JSON Feed work
should come before any network-capable static source acquisition because feeds
are structured, explicit, auditable, and commonly intended for syndication.

RSS0 is ADR-only. It defines feed document identity, channel/feed identity, item
identity, links, enclosures, authors, categories, publication and update
timestamps, source-policy relationship, artifact provenance, and future
canonicalization behavior. It does not implement feed extraction or ingestion.

Supported feed formats for the first model:

- RSS 2.0;
- Atom 1.0; and
- JSON Feed 1.1 or compatible JSON Feed documents.

RepoMap should not attempt to model every historical RSS extension in the first
feed implementation. The model should cover a conservative core and define a
safe extension metadata policy.

## Decision

RepoMap will model feeds as local artifact analysis.

RSS1 should parse local feed fixtures or local feed artifacts only. RSS2 may
later ingest configured feed URLs, but only with explicit source configuration,
source policy, rate limits, timeouts, audit logging, and artifact retention.

RSS0 does not fetch URLs. Feed item links, alternate links, related links, and
enclosures are syntactic references only. Enclosures are not fetched unless a
later artifact-ingestion phase explicitly imports or acquires them under source
policy.

Feed summary and content bodies are evidence or limited metadata with size and
redaction limits. They are not canonical identity.

The first feed graph model accepts graph key version 1 namespace additions for:

```text
feed.document:<encoded-file-or-artifact-key>
feed.channel:<encoded-feed-document-key>:<encoded-channel-id>
feed.item:<encoded-feed-channel-key>:<encoded-item-id>
feed.author:<encoded-feed-channel-key>:<encoded-author-id>
feed.category:<encoded-feed-channel-key>:<encoded-category-id>
```

RSS1 may use file-based identity first, with `file:*` keys encoded into the
`feed.document:*` key. RSS2 may later integrate `source.definition:*`,
`source.artifact:*`, and source-run provenance after those source-ingestion
namespaces and storage records are implemented. RSS1 must not require source
ingestion storage to exist.

RSS0 does not add a new edge kind. It reuses:

- `defines` for feed document, channel, item, author, and category structural
  ownership; and
- `references` for item links, enclosures, alternate URLs, author/category
  associations, and other syntactic feed targets.

## Scope

In scope:

- RSS 2.0, Atom 1.0, and JSON Feed 1.1 or compatible documents;
- local feed fixture and artifact analysis;
- feed document, channel/feed, item, link, enclosure, author, category, content,
  and parse-error observations;
- conservative item identity rules;
- source-scoped author and category identity;
- date normalization policy;
- extension metadata policy;
- redaction and content summary policy;
- future source ingestion integration with ADR 0014; and
- RSS1 fixture, canonicalization, storage, and explain test requirements.

Out of scope:

- implementing feed extraction;
- HTTP fetching;
- source ingestion code;
- scheduler code;
- MCP tools;
- storage migrations;
- XML extraction changes;
- JSON extraction changes;
- HTML or CSS behavior changes;
- public readback default changes;
- existing CLI command changes;
- Phase F migration;
- ARCHIVE, API, BULK, or JS phases; and
- extraction from any particular third-party website.

## Feed Extraction As Local Artifact Analysis

Feed extraction is a deterministic extractor over local bytes.

RSS1 should accept local fixture files or local imported feed artifacts such as:

- `rss.xml`;
- `atom.xml`; and
- `feed.json`.

RSS1 must not:

- fetch feed URLs;
- fetch item links;
- fetch enclosure URLs;
- render or execute embedded HTML;
- execute JavaScript;
- expand remote entities;
- follow redirects;
- consult live HTTP headers; or
- add source-specific logic for named external publishers.

RSS2 may later add configured feed ingestion from explicit allowlisted feed URLs
after source policy, rate limits, timeouts, audit logging, and artifact
retention are accepted and implemented. MCP must not fetch arbitrary feed URLs
from model text.

## Raw Observation Principles

Feed raw observations use the standard RepoMap raw observation shape:
`kind`, `source_id`, `path`, optional line span, optional `name`, optional
`target`, `confidence`, `extractor`, `extractor_version`, and `metadata`.

Principles:

- observations include the local source file or artifact path;
- observations include `feed_format`: `rss`, `atom`, or `json-feed`;
- observations include `parser` and parser mode metadata;
- observations include source, artifact, and run metadata only when a future
  ingestion layer provides it;
- parse errors are raw/evidence only and do not produce canonical nodes;
- content bodies are summarized, size-limited, and redacted;
- links and enclosures are references only and are not fetched; and
- unsupported extension fields may be summarized as metadata without creating
  new graph namespaces.

Use `confidence="extracted"` for deterministic parser facts. Use
`confidence="heuristic"` for fallback identity, extension summaries, or
conservative reference classification. Use `confidence="unknown"` for parse
errors and unresolved or malformed targets.

## Raw Observation Kinds

### `feed.document`

Represents one local feed artifact.

Required fields:

- `kind`: `feed.document`
- `path`: repository-relative or artifact-relative feed path
- `source_id`: stable extractor-local id such as `<path>#feed-document`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`: `rss`, `atom`, or `json-feed`;
- `format_version`: `2.0`, `1.0`, `1.1`, or parser-observed compatible value;
- `parser`;
- `document_role`: `feed`;
- `document_key` when the extractor can build it;
- `channel_count`;
- `item_count`;
- `link_count`;
- `enclosure_count`;
- `author_count`;
- `category_count`;
- `content_count`;
- `parse_error_count`;
- optional `source_id_configured` when future source ingestion provides it;
- optional `source_artifact_id` when future source ingestion provides it; and
- optional `source_run_id` when future source ingestion provides it.

Canonicalization creates a `feed.document:*` node and a
`file:* --defines--> feed.document:*` edge for file-backed RSS1 artifacts. A
future RSS2 source artifact may also define the document from
`source.artifact:*` after source graph namespaces are implemented.

### `feed.channel`

Represents the feed channel or top-level feed metadata.

Required fields:

- `kind`: `feed.channel`
- `path`
- `source_id`: stable extractor-local id such as `<path>#feed-channel:<id>`
- `name`: channel id or display title when safe
- `target`: `feed.channel:*` when the extractor can build it
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `document_key`;
- `channel_id`;
- `channel_identity_source`;
- `identity_strength`: `strong`, `medium`, `weak`, or `structural`;
- safe `title_summary`;
- safe `description_summary`;
- `home_url`;
- `self_url`;
- `language`;
- `copyright_summary`;
- `updated_at`;
- `published_at`;
- `item_count`;
- `author_count`;
- `category_count`; and
- extension summaries when safe.

Canonicalization creates a `feed.channel:*` node and a
`feed.document:* --defines--> feed.channel:*` edge.

### `feed.item`

Represents one RSS item, Atom entry, or JSON Feed item.

Required fields:

- `kind`: `feed.item`
- `path`
- `source_id`: stable extractor-local id such as `<path>#feed-item:<id>`
- `name`: item id or safe title summary
- `target`: `feed.item:*` when the extractor can build it
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `document_key`;
- `channel_key`;
- `item_id`;
- `identity_source`;
- `identity_strength`: `strong`, `medium`, `weak`, or `structural`;
- `duplicate_identity`: boolean;
- `duplicate_disambiguator`: optional deterministic disambiguator;
- safe `title_summary`;
- safe `summary`;
- `published_at`;
- `updated_at`;
- `original_published`;
- `original_updated`;
- `link_count`;
- `enclosure_count`;
- `author_count`;
- `category_count`;
- `content_policy`;
- `content_summary_present`;
- `content_truncated`; and
- extension summaries when safe.

Canonicalization creates a `feed.item:*` node and a
`feed.channel:* --defines--> feed.item:*` edge when item identity is stable
enough. Items with structural ordinal-only identity may remain raw/evidence-only
or may create a weak canonical node only if RSS1 explicitly implements the
diagnostic and metadata contract.

### `feed.link`

Represents a syntactic feed link, alternate link, related link, item URL, feed
URL, or source URL.

Required fields:

- `kind`: `feed.link`
- `path`
- `source_id`: stable extractor-local id such as `<path>#feed-link:<pointer>`
- `name`: source pointer or link relation
- `target`: resolved canonical target key or explicit placeholder
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `source_node_key`: feed document, channel, or item key when known;
- `source_kind`: `document`, `channel`, or `item`;
- `relation`: `self`, `alternate`, `related`, `via`, `hub`, `comments`,
  `next`, `previous`, `canonical`, `unknown`, or format-specific safe value;
- `href_summary`;
- `media_type`;
- `hreflang`;
- `title_summary`; and
- `not_fetched=true`.

Canonicalization creates `references` edges from the source feed node to the
target when both source and target are known:

```text
feed.document:* --references--> external.url:* | file:* | unknown:* | dynamic:*
feed.channel:* --references--> external.url:* | file:* | unknown:* | dynamic:*
feed.item:* --references--> external.url:* | file:* | unknown:* | dynamic:*
```

### `feed.enclosure`

Represents an RSS enclosure, Atom link with enclosure-like relation, JSON Feed
attachment, or similar media reference.

Required fields:

- `kind`: `feed.enclosure`
- `path`
- `source_id`
- `name`: enclosure relation or pointer
- `target`: resolved canonical target key or explicit placeholder
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `item_key`;
- `url_summary`;
- `media_type`;
- `length`;
- `duration`;
- `size`;
- `title_summary`;
- `not_fetched=true`; and
- `artifact_ingestion_deferred=true`.

Canonicalization creates a `feed.item:* --references--> <target>` edge when the
item node exists. It does not fetch the enclosure.

### `feed.author`

Represents source-scoped author metadata from a feed channel or item.

Required fields:

- `kind`: `feed.author`
- `path`
- `source_id`
- `name`: safe author display name, email hash/summary, URI summary, or id
- `target`: `feed.author:*` when the extractor can build it
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `channel_key`;
- `author_id`;
- `identity_source`;
- `identity_strength`;
- safe `display_name`;
- safe `uri_summary`;
- `email_present`;
- `email_redacted`; and
- `scope=feed-channel`.

Authors are source-level metadata, not global human identity. Canonicalization
may create `feed.author:*` nodes scoped to a channel. The channel defines those
author nodes, and items may reference them:

```text
feed.channel:* --defines--> feed.author:*
feed.item:* --references--> feed.author:*
```

### `feed.category`

Represents source-scoped categories or tags from a feed channel or item.

Required fields:

- `kind`: `feed.category`
- `path`
- `source_id`
- `name`: safe category term or label
- `target`: `feed.category:*` when the extractor can build it
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `channel_key`;
- `category_id`;
- `term`;
- `scheme_summary`;
- `label_summary`;
- `identity_source`;
- `identity_strength`; and
- `scope=feed-channel`.

Categories are source-level labels, not a global taxonomy. Canonicalization may
create `feed.category:*` nodes scoped to a channel. The channel defines those
category nodes, and items may reference them:

```text
feed.channel:* --defines--> feed.category:*
feed.item:* --references--> feed.category:*
```

### `feed.content`

Represents summary/content/body fields from a channel or item.

Required fields:

- `kind`: `feed.content`
- `path`
- `source_id`
- `name`: content pointer or content role
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format`;
- `source_node_key`;
- `source_kind`: `channel` or `item`;
- `content_role`: `summary`, `description`, `content`, `content_html`,
  `content_text`, or `unknown`;
- `content_type`;
- safe `text_summary`;
- `content_length`;
- `content_truncated`;
- `html_present`;
- `html_not_rendered=true`;
- `redacted`; and
- `redaction_reason`.

`feed.content` remains raw/evidence-oriented in RSS1. It does not create a
canonical node. Safe summaries may be copied to item/channel metadata under
size limits.

### `feed.parse_error`

Represents malformed feed input or unsupported dangerous constructs.

Required fields:

- `kind`: `feed.parse_error`
- `path`
- `source_id`
- `confidence="unknown"`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `feed_format` when detectable;
- `error_kind`;
- `message_summary`;
- optional `line`;
- optional `column`;
- `recoverable`; and
- `facts_emitted_before_error`.

Parse errors are raw/evidence only. They do not produce canonical nodes or
edges.

## Canonical Key Namespaces

RSS0 accepts these graph key version 1 namespace additions for future
implementation:

```text
feed.document:<encoded-file-or-artifact-key>
feed.channel:<encoded-feed-document-key>:<encoded-channel-id>
feed.item:<encoded-feed-channel-key>:<encoded-item-id>
feed.author:<encoded-feed-channel-key>:<encoded-author-id>
feed.category:<encoded-feed-channel-key>:<encoded-category-id>
```

RSS1 file-backed examples:

```text
feed.document:file%3Afeeds%2Frss.xml
feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:self
feed.item:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Aguid%253Apost-1:guid%3Apost-1
feed.author:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Aself:name%3AAda
feed.category:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Aself:term%3Arelease-notes
```

The examples show nested encoded keys. Implementations should use
`repomap_kg.graph_keys` helpers rather than hand-formatting these strings.

Canonical keys must not include:

- full content bodies;
- secret values;
- fetch timestamps;
- ingestion run timestamps;
- line numbers;
- extractor versions;
- raw observation source IDs;
- current time;
- model labels; or
- database integer IDs.

## Feed Document Identity

RSS1 uses file-backed document identity:

```text
feed.document:<encoded-file-key>
```

The encoded segment is the canonical `file:*` key for the local artifact.

RSS2 may later use source-artifact-backed identity:

```text
feed.document:<encoded-source.artifact-key>
```

That requires source-ingestion storage and source artifact keys to exist first.
RSS1 must not depend on those future namespaces.

## Channel Identity

Channel identity is scoped to the feed document or source artifact.

Priority order:

1. Feed self URL or Atom `link rel="self"` when present and stable.
2. Stable channel/feed id when present.
3. Channel link/home URL when present.
4. Normalized safe title plus document key as a weak fallback.
5. File/artifact fallback such as `self` when the document has one channel and
   no stronger id exists.

Channel titles alone are not global identity. A channel key always includes the
encoded feed document key so the same title in different feed artifacts does
not collide.

Metadata must record:

- `channel_identity_source`;
- `identity_strength`; and
- the safe original fields that contributed to identity.

## Item Identity Policy

Item identity is scoped to the channel.

### RSS 2.0

Priority order:

1. `guid` when present and stable.
2. Item link when `guid` is absent.
3. Normalized title plus `pubDate` as a weak fallback.
4. Structural ordinal as a last resort.

### Atom 1.0

Priority order:

1. `entry/id` when present.
2. Entry `link rel="alternate"` when id is absent.
3. Normalized title plus `updated` or `published` as a weak fallback.
4. Structural ordinal as a last resort.

### JSON Feed

Priority order:

1. `items[].id` when present.
2. Item `url` or `external_url` when id is absent.
3. Normalized title plus `date_published` or `date_modified` as a weak
   fallback.
4. Structural ordinal as a last resort.

Rules:

- item identity must not use full content body;
- item identity must not use fetch timestamp;
- item identity must not use current time;
- item identity must not use line number;
- item identity must not use parser-generated object IDs;
- identity metadata must record `identity_source`;
- weak identities must be labeled with `identity_strength="weak"`;
- structural ordinal identities must be labeled
  `identity_strength="structural"`; and
- RSS1 may skip canonical item creation for structural-only identities if doing
  so avoids presenting volatile identity as durable.

Duplicate item IDs within one feed should emit diagnostics. RSS1 should prefer
deterministic disambiguation only when it can preserve both facts without
pretending the duplicate ids are clean, for example by adding an encoded
duplicate ordinal to the item id and setting `duplicate_identity=true`. If the
implementation cannot do that safely, it should skip canonical item creation
for the conflicting items and keep raw evidence plus diagnostics.

## Link And Reference Policy

Feed links and enclosures are syntactic references only.

Target behavior:

- `http`, `https`, and `mailto` values become `external.url:*`;
- repo-local relative paths in local fixtures may become `file:*` when they
  normalize inside the repository;
- absolute filesystem paths become
  `external:file:absolute-feed-reference`;
- repo-escaping paths become `unknown:file:repo-escaping-feed-reference`;
- malformed links become `unknown:external.url:malformed-feed-reference` or a
  `feed.parse_error`;
- template, variable, or dynamic links become
  `dynamic:external.url:feed-reference-expanded-from-template` or another
  explicit dynamic placeholder; and
- unsupported schemes remain raw/evidence-only or become explicit placeholders
  without fetching.

No link target is fetched in RSS0 or RSS1. Enclosure URLs are references only
until a later artifact-ingestion phase imports or acquires them under policy.

## Author And Category Policy

Authors and categories are useful for source-level filtering, but RSS0 does not
turn them into global identities.

Authors:

- `feed.author:*` identity is scoped to the channel;
- author display names are metadata, not global person identity;
- email-like values are redacted or summarized;
- URI values may be references only when safe and are not fetched; and
- item-to-author association may use `references` when the author node exists.

Categories:

- `feed.category:*` identity is scoped to the channel;
- category terms and labels are source-level labels, not a global taxonomy;
- schemes may be metadata or safe URL references when deterministic;
- item-to-category association may use `references` when the category node
  exists; and
- category terms never imply endorsement, taxonomy equivalence, or ownership.

## Date Policy

RSS0 accepts date parsing as metadata normalization, not identity by itself.

Rules:

- preserve original date strings in evidence metadata when safe;
- parse common RSS, Atom, and JSON Feed date formats when deterministic;
- store normalized UTC timestamp metadata when parsing succeeds;
- record the source field, such as `pubDate`, `updated`, `published`,
  `date_published`, or `date_modified`;
- parsing failure should emit a diagnostic or metadata flag but should not block
  item extraction;
- do not use current time as publication or update time unless it is explicitly
  ingestion run metadata from a future source layer; and
- weak item identity may combine safe title summary with a parsed publication or
  update timestamp, but metadata must record the weak identity source.

## Content Policy

Feed summaries and content bodies are useful evidence but risky to put into
canonical graph metadata.

Rules:

- canonical keys never include content body text;
- canonical metadata stores safe summaries only;
- summary text is size-limited and redacted;
- configurable max content length should apply before serialization;
- full bodies, when retained, belong to source artifacts or evidence, not
  canonical nodes or edge metadata;
- content hashes are deferred until artifact-retention policy defines whether
  secret-derived hashes are allowed;
- HTML content inside feeds is not executed, rendered, sanitized as browser
  output, or interpreted as live page structure in RSS1;
- embedded HTML may be summarized as text or later become a saved-page/static
  artifact only after ARCHIVE phases; and
- secret-prone content is redacted before raw observation serialization,
  canonicalization, golden fixtures, readback, or explain output.

## Extension Policy

RSS and Atom ecosystems include many extensions. RSS0 keeps extension support
conservative.

Rules:

- common extension fields from Dublin Core, Media RSS, iTunes,
  `content:encoded`, and similar namespaces may be captured as safe metadata
  when namespace, field name, and value are simple;
- RSS1 should support core fields first and only shallow extension summaries;
- unknown extensions do not create new canonical namespaces;
- extension values that look like links or enclosures may emit
  `feed.link` or `feed.enclosure` only when the reference is clear;
- media URLs remain references only;
- extension text is subject to content and redaction limits; and
- extension handling must not add source-specific logic in RSS0.

## Redaction

RSS0 reuses ADR 0010 secret-prone markers:

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

- canonical keys;
- raw observation metadata;
- canonical node metadata;
- canonical edge metadata;
- golden fixtures;
- readback output; or
- explain output.

Redacted feed facts may retain safe metadata such as `value_type`,
`redacted=true`, `redaction_reason`, field name, source pointer, parser,
extractor, confidence, and line span.

## Canonicalization

RSS1 canonicalization should map local feed observations as follows.

```text
file:* --defines--> feed.document:*
feed.document:* --defines--> feed.channel:*
feed.channel:* --defines--> feed.item:*
feed.channel:* --defines--> feed.author:*
feed.channel:* --defines--> feed.category:*
feed.item:* --references--> external.url:* | file:* | unknown:* | dynamic:*
feed.item:* --references--> feed.author:*
feed.item:* --references--> feed.category:*
feed.channel:* --references--> external.url:* | file:* | unknown:* | dynamic:*
feed.document:* --references--> external.url:* | file:* | unknown:* | dynamic:*
```

`feed.content` and `feed.parse_error` remain raw/evidence-oriented in RSS1.

Edge metadata should include:

- `feed_format`;
- source pointer;
- relation;
- media type when present;
- `not_fetched=true` for links and enclosures;
- identity source and identity strength when relevant; and
- source/artifact/run metadata only when a future ingestion layer provides it.

Confidence aggregation follows ADR 0004's canonicalizer rules when implemented:
manual strongest, then extracted, heuristic, and unknown. Conflicting duplicate
ids should preserve per-evidence confidence and expose diagnostics or conflict
metadata rather than silently selecting a winner.

## Source Ingestion Integration

RSS2 should integrate with ADR 0014 only after RSS1 proves local feed artifact
extraction and canonicalization.

RSS2 requirements:

- configured source ID;
- source type `feed.rss`, `feed.atom`, or `feed.json`;
- source policy snapshot;
- explicit allowlisted feed URL;
- target Postgres database or schema mapping;
- source artifact record for acquired bytes;
- ingestion run record;
- rate limits;
- timeouts;
- audit logs;
- artifact retention policy;
- content-size limits;
- no arbitrary model-selected feed URLs; and
- read-only MCP query behavior only unless a later ADR accepts ingestion tools.

Source policy and artifact provenance should be linked to evidence. Canonical
feed facts should remain explainable back to the local feed artifact and, in
RSS2, to source run and policy snapshot metadata.

## Required RSS1 Fixtures

RSS1 should add a discovery fixture:

```text
src/test/fixtures/discovery/feed_static_basic/
  rss.xml
  atom.xml
  feed.json
  malformed-rss.xml
  secret-feed.xml
```

`secret-feed.xml` may be optional if the redaction cases are covered in another
feed fixture file, but RSS1 must include secret-prone feed data somewhere in
the fixture corpus.

Fixture coverage:

- RSS channel and items;
- Atom feed and entries;
- JSON Feed items;
- GUID or id identity;
- link fallback identity;
- duplicate item id case;
- item links;
- enclosures;
- authors;
- categories;
- publication and update dates;
- content summary;
- HTML content in item summary or content;
- malformed feed parse error;
- secret-prone values redacted; and
- proof that no URL fetching occurs.

RSS1 should also add a golden canonicalization fixture:

```text
src/test/fixtures/canonicalization/feed_static_basic/
```

## Required RSS1 Tests

RSS1 implementation must add tests for:

- RSS document, channel, and item extraction;
- Atom document, channel, and item extraction;
- JSON Feed document, channel, and item extraction;
- item identity priority for each format;
- duplicate id behavior;
- link references;
- enclosure references;
- source-scoped author nodes and item associations, if implemented;
- source-scoped category nodes and item associations, if implemented;
- date normalization;
- content summary and redaction;
- HTML content not executed or rendered;
- malformed feed parse errors;
- canonicalization for `feed.document`, `feed.channel`, and `feed.item`;
- canonicalization for `feed.author` and `feed.category` if nodes are
  implemented;
- `references` edges for item links and enclosures;
- storage readback for feed nodes and edges;
- explain output for one item link reference;
- RSS1 local fixture behavior without source-ingestion storage; and
- proof that no URL fetching occurs.

## Rejected Alternatives

### Feed Model That Depends On Live HTTP Fetching

Rejected. RSS1 must parse local fixtures and artifacts. RSS2 may add configured
feed URL ingestion only after source policy, retention, and audit behavior are
defined and tested.

### Globally Identifying Authors Across Feeds

Rejected. Feed author metadata is source-scoped. Matching authors across feeds
would require identity resolution that RSS0 does not define.

### Globally Identifying Categories Across Feeds

Rejected. Feed categories and tags are source-level labels. They are not a
global taxonomy.

### Using Feed Title Alone As Stable Identity

Rejected. Titles are display labels and can change or collide. Channel identity
must be scoped to the feed document or source artifact and should use stronger
fields when available.

### Using Content Body As Item Identity

Rejected. Full content bodies are volatile, large, and potentially sensitive.
They belong in evidence or retained artifacts under policy, not canonical
identity.

### Fetching Enclosures In RSS1

Rejected. Enclosures are syntactic references in RSS1. Fetching or importing
them belongs to a later artifact ingestion phase.

### Rendering Or Executing Embedded HTML

Rejected. Embedded HTML in feed content is not rendered, executed, or treated as
live page structure in RSS1.

### Adding Source-Specific Feed Logic In RSS0

Rejected. RSS0 defines generic RSS, Atom, and JSON Feed behavior. Named
publisher-specific behavior requires a later explicit source policy and
implementation decision, if ever needed.

### Adding MCP Ingestion Or Write Tools In RSS0

Rejected. RSS0 is a graph-model ADR. MCP remains read-only, and ingestion/write
tools require a later ADR.

## Consequences

- Feed work has a safe local-artifact first step before any configured network
  acquisition.
- Feed identity is scoped and explainable rather than globally overclaiming
  authors, categories, or titles.
- Links and enclosures become queryable as references without fetching them.
- RSS2 has a clear bridge to ING0 source policy, artifacts, and run metadata.
- RSS1 can be implemented without source-ingestion storage, scheduler code,
  HTTP fetching, MCP changes, or public readback default changes.
