# ADR 0008: Markdown Documentation Graph Model

## Status

Accepted

## Date

2026-06-29

## Context

RepoMap now extracts shell, Python, and Nix facts into the raw observation,
evidence, canonical node, and canonical edge pipeline. Project documentation
also contains important project knowledge: README files describe the project
surface, ADRs record accepted decisions, phase status docs record boundaries and
verification, skills document operational workflows, AGENTS.md files constrain
agent behavior, and prompts often explain why a slice exists.

RepoMap should make this documentation queryable through the same pipeline
without pretending to understand arbitrary prose. The goal is structural
documentation graph extraction: pages, sections, links, frontmatter, code
fences, ADR metadata, and skill metadata. Free-text semantic extraction remains
out of scope.

## Decision

RepoMap will model Markdown and project documentation through deterministic
raw observations that canonicalize into durable documentation nodes and
registered edges.

The first Markdown documentation graph will use:

- raw observation kinds for Markdown documents, headings, links, frontmatter,
  code fences, ADR metadata, and skill metadata;
- new graph key namespaces for documentation pages, sections, ADRs, skills,
  and external URLs;
- the existing `defines` edge kind for file-to-document facts; and
- a new registered `links_to` edge kind for Markdown links.

Markdown extraction must be static. It must not fetch URLs, execute code
blocks, render Markdown to HTML, call an LLM, or perform semantic NLP over
arbitrary prose.

## Scope

In scope:

- `.md` files;
- `README.md`;
- `docs/adr/**/*.md`;
- `docs/status/**/*.md`;
- `docs/skills/*/SKILL.md`;
- `docs/contrib/skills/*/SKILL.md`;
- `AGENTS.md` where present;
- Markdown headings;
- Markdown links;
- YAML frontmatter;
- fenced code blocks;
- ADR metadata; and
- skill metadata.

Out of scope:

- LLM summaries;
- semantic NLP over arbitrary prose;
- fetching URLs;
- executing code blocks;
- rendered Markdown or HTML interpretation;
- cross-project link resolution;
- changing legacy command output; and
- Phase E migration.

## Raw Observation Kinds

Markdown extractors emit raw observations with the standard schema fields from
the raw-observation boundary: `kind`, `source_id`, `path`, optional line span,
optional `name`, optional `target`, `confidence`, `extractor`,
`extractor_version`, and `metadata`.

The first implementation should use `confidence="extracted"` for facts produced
by deterministic Markdown structure parsing. It may use
`confidence="heuristic"` for shallow YAML frontmatter or metadata interpretation
when the extractor intentionally accepts partial parsing.

### `markdown.document`

Represents one Markdown-like documentation file.

Required fields:

- `kind`: `markdown.document`
- `path`: repository-relative Markdown file path
- `source_id`: stable extractor-local id such as
  `<path>#markdown-document`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `doc_path`: repository-relative path;
- `doc_role`: one of `readme`, `adr`, `status`, `skill`, `agents`, or
  `markdown`;
- `title`: first level-1 heading when present;
- `frontmatter_present`: boolean;
- `content_hash`: optional file content hash copied from discovery when
  available; and
- `generated`: optional boolean copied from discovery or profile data.

Canonicalization creates a `doc.page:*` node and a `file:* --defines-->
doc.page:*` edge.

### `markdown.heading`

Represents an ATX Markdown heading outside frontmatter and code fences.

Required fields:

- `kind`: `markdown.heading`
- `path`
- `start_line`
- `end_line`
- `name`: heading text
- `target`: the `doc.section:*` key when the extractor can build it, or a
  placeholder when it cannot
- `source_id`: stable extractor-local id such as
  `<path>#heading:<anchor>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `level`: heading level 1 through 6;
- `text`: normalized heading text;
- `anchor`: normalized Markdown anchor;
- `base_anchor`: anchor before duplicate suffixing;
- `duplicate_index`: zero-based duplicate index for repeated anchors;
- `parent_anchor`: nearest preceding lower-level parent anchor when known; and
- `page_key`: documentation page key when available.

Canonicalization creates a `doc.section:*` node and a `file:* --defines-->
doc.section:*` edge.

### `markdown.link`

Represents a Markdown link outside frontmatter and code fences.

Required fields:

- `kind`: `markdown.link`
- `path`
- `start_line`
- `end_line`
- `name`: link text or URL text
- `target`: resolved canonical target key or explicit placeholder
- `source_id`: stable extractor-local id such as
  `<path>#link:<line>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `link_text`;
- `raw_target`;
- `link_syntax`: `inline`, `reference`, `collapsed-reference`,
  `shortcut-reference`, `definition`, or `autolink`;
- `definition_id` for reference links;
- `source_anchor` when the link appears inside a known section;
- `resolved_target_kind`: `doc.page`, `doc.section`, `file`,
  `external.url`, `unknown`, `external`, or `dynamic`;
- `resolved_path` for repository-relative links when known;
- `resolved_anchor` for anchor links when present;
- `is_image`: boolean for image syntax links; and
- `resolution_reason` for unresolved, external, malformed, or dynamic targets.

Canonicalization creates a `links_to` edge from the source `doc.section:*` when
the source section is known, otherwise from the source `doc.page:*`. The target
is a `doc.page:*`, `doc.section:*`, `file:*`, `external.url:*`, or explicit
placeholder key.

### `markdown.frontmatter`

Represents YAML frontmatter delimited by `---` at the start of a Markdown file.

Required fields:

- `kind`: `markdown.frontmatter`
- `path`
- `start_line`: 1
- `end_line`
- `source_id`: stable extractor-local id such as
  `<path>#frontmatter`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `keys`: sorted list of frontmatter keys;
- `values`: shallow parsed scalar and list values when safe;
- `parse_status`: `parsed`, `partial`, or `malformed`;
- `malformed_reason` when applicable; and
- `redacted_keys` for secret-prone keys excluded from summary metadata.

Frontmatter observations support page, ADR, and skill metadata. They do not
create standalone canonical nodes in the first implementation.

### `markdown.code_fence`

Represents a fenced code block outside frontmatter.

Required fields:

- `kind`: `markdown.code_fence`
- `path`
- `start_line`
- `end_line`
- `name`: language tag when present
- `source_id`: stable extractor-local id such as
  `<path>#code-fence:<line>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `fence`: backtick or tilde fence marker;
- `fence_length`;
- `info_string`;
- `language`: first token of the info string when present;
- `section_anchor` when the code fence appears inside a known section; and
- `closed`: boolean.

Code fence observations provide evidence and page or section summary metadata.
They do not execute code and do not create code-block canonical nodes in the
first implementation.

### `markdown.adr_metadata`

Represents ADR-specific metadata extracted from an ADR file.

Required fields:

- `kind`: `markdown.adr_metadata`
- `path`
- `name`: ADR number or title when known
- `target`: `doc.adr:<number>` when the number is known, otherwise an
  explicit placeholder
- `source_id`: stable extractor-local id such as `<path>#adr-metadata`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `adr_number`: four-digit ADR number when present;
- `title`;
- `status`;
- `date`;
- `filename_slug`;
- `heading_anchor`; and
- `metadata_source`: `filename`, `heading`, `frontmatter`, or `mixed`.

Canonicalization creates a `doc.adr:*` node and a `file:* --defines-->
doc.adr:*` edge.

### `markdown.skill_metadata`

Represents Codex-style skill metadata in a `SKILL.md` file.

Required fields:

- `kind`: `markdown.skill_metadata`
- `path`
- `name`: skill name when known
- `target`: `doc.skill:<skill-name>` when known, otherwise an explicit
  placeholder
- `source_id`: stable extractor-local id such as `<path>#skill-metadata`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `skill_name`;
- `description`;
- `skill_path`;
- `frontmatter_keys`;
- `metadata_source`; and
- `parse_status`.

Canonicalization creates a `doc.skill:*` node and a `file:* --defines-->
doc.skill:*` edge.

## Canonical Key Namespaces

ADR 0008 adds documentation namespaces to graph key version 1. This is a
compatible graph key version 1 extension because the key grammar, escaping
rules, evidence rules, and identity rules from ADR 0002 do not change. The
implementation must still update the graph key namespace registry and storage
edge-kind constraints before canonical documentation rows are written.

If a future documentation model changes key identity semantics incompatibly,
that later change should use a new `graph_key_version`.

### Documentation Page Keys

```text
doc.page:<encoded-file-key>
```

Examples:

- `doc.page:file%3AREADME.md`
- `doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md`
- `doc.page:file%3AAGENTS.md`

The segment after `doc.page:` is the canonical `file:*` key encoded as one
non-file key segment. This scopes a documentation page to the repository file
that contains it without using line numbers, content hashes, extractor names,
or raw source ids.

### Documentation Section Keys

```text
doc.section:<encoded-file-key>:<anchor>
```

Examples:

- `doc.section:file%3AREADME.md:current-status`
- `doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:link-resolution`

The section key uses the encoded canonical file key plus a deterministic
Markdown anchor. Duplicate headings use the normalized duplicate anchor, such
as `usage`, `usage-1`, and `usage-2`. Section keys do not include line numbers,
heading ordinals, extractor versions, raw source ids, or content hashes.

### ADR Keys

```text
doc.adr:<adr-number>
```

Examples:

- `doc.adr:0001`
- `doc.adr:0008`

ADR keys identify durable ADR records by their accepted repository ADR number.
The title and filename slug are display metadata, not identity.

### Skill Keys

```text
doc.skill:<skill-name>
```

Examples:

- `doc.skill:postgres-test-ipc-cleanup`
- `doc.skill:docs-only-change-hygiene`

Skill keys identify durable skill documents inside the repository graph. The
skill path, description, and frontmatter values are metadata, not identity.

### External URL Keys

```text
external.url:<normalized-url>
```

Examples:

- `external.url:https%3A%2F%2Fexample.com%2Fdocs`
- `external.url:https%3A%2F%2Fexample.com%2Fdocs%23install`
- `external.url:mailto%3Amaintainers%40example.com`

The URL is a syntactically normalized absolute URL or URI encoded as one graph
key segment. RepoMap does not fetch the URL. Query strings and fragments remain
part of identity because they can identify different documentation targets.

## Edge Vocabulary

ADR 0008 adds one registered edge kind:

| Edge kind | Direction | Meaning |
| --- | --- | --- |
| `links_to` | `doc.page` or `doc.section` -> `file`, `doc.page`, `doc.section`, `external.url`, or placeholder | A Markdown link points from a documentation page or section to another durable target. |

This edge kind is structural. It means a Markdown link exists. It does not mean
the source endorses, semantically describes, or depends on the target.

The existing `defines` edge kind is used for documentation entities defined by
files:

- `file:* --defines--> doc.page:*`
- `file:* --defines--> doc.section:*`
- `file:* --defines--> doc.adr:*`
- `file:* --defines--> doc.skill:*`

ADR 0008 does not add broad semantic edge kinds such as `mentions`,
`describes`, `documents`, `recommends`, or `supersedes`. Such edges require a
future ADR with strict extraction rules and confidence behavior.

## Markdown Parsing Rules

The first implementation should use a small Python standard-library parser or
scanner. It must not require a third-party Markdown parser unless a later slice
explicitly approves that dependency.

The parser must ignore Markdown constructs inside fenced code blocks and YAML
frontmatter unless it is specifically extracting the frontmatter or code fence
observation.

### ATX Headings

Supported headings are ATX headings:

```text
# Heading
## Heading
### Heading ###
```

Rules:

- allow up to three leading spaces;
- require one through six `#` characters;
- require whitespace after the opening `#` sequence unless the heading text is
  empty;
- strip optional closing `#` characters and surrounding whitespace; and
- ignore headings inside frontmatter or fenced code blocks.

Setext headings are deferred.

### Heading Anchor Normalization

Heading anchors are deterministic and GitHub-like, but intentionally simpler
than rendered Markdown semantics:

1. Strip leading and trailing whitespace from the heading text.
2. Remove simple inline formatting delimiters: backticks, `*`, `_`, `[`, `]`,
   `(`, and `)`.
3. Lowercase ASCII letters.
4. Replace runs of ASCII whitespace with `-`.
5. Remove characters other than ASCII letters, ASCII digits, `-`, and `_`.
6. Collapse repeated `-`.
7. Strip leading and trailing `-`.
8. Use `section` when the result is empty.
9. For duplicates within the same file, append `-1`, `-2`, and so on.

This anchor is part of `doc.section:*` identity. It is not an evidence span.
Line numbers remain evidence metadata only.

### Inline Links

Supported inline links:

```text
[text](target)
![alt](target)
```

The extractor records images as `markdown.link` with `is_image=true`. Nested
bracket parsing may be conservative in the first implementation; malformed
links should produce diagnostics or unknown placeholders rather than fabricated
targets.

### Reference Links

Supported reference links:

```text
[text][id]
[text][]
[id]

[id]: target "optional title"
```

Definitions are resolved case-insensitively after trimming and collapsing
internal whitespace in the reference id. Link definition observations may use
`link_syntax="definition"` and should support evidence for the resolved
reference link.

### Autolinks

Supported autolinks:

```text
<https://example.com/docs>
<mailto:maintainers@example.com>
```

Autolinks create `markdown.link` observations targeting `external.url:*` when
the URL or URI is syntactically valid.

### Fenced Code Blocks

Supported fences use backticks or tildes:

````text
```python
print("example")
```
````

Rules:

- a fence opener starts with at least three backticks or tildes;
- the closing fence must use the same character and at least the opener length;
- the language is the first token in the info string;
- an unclosed fence still emits a `markdown.code_fence` observation with
  `closed=false`; and
- code block content is never executed.

### YAML Frontmatter

YAML frontmatter is recognized only when the file starts with `---` on line 1
and a later line contains a closing `---`.

The first implementation should use a conservative stdlib parser for shallow
frontmatter:

- parse `key: value` scalar lines;
- parse simple list items under a key;
- preserve unknown or complex values as strings when safe;
- mark unsupported structures as `parse_status="partial"`; and
- redact values for secret-prone keys such as `token`, `secret`, `password`,
  `api_key`, and `credential`.

Full YAML parsing requires a separately approved dependency.

## Link Resolution

Markdown link targets are resolved relative to the source document path.

RepoMap must prefer explicit `unknown:*`, `external:*`, or `dynamic:*`
placeholder nodes over fabricated precision.

### Relative File Links

Relative links without an anchor resolve to:

- `doc.page:*` when the target is a Markdown file;
- `file:*` when the target is another repository file; or
- an explicit unknown placeholder when the target is malformed, missing, or
  cannot be safely normalized.

Examples:

- `README.md` linking to `docs/adr/2026-06/0001-graph-identity-model.md` targets
  `doc.page:file%3Adocs%2Fadr%2F2026-06%2F0001-graph-identity-model.md`.
- `docs/status/2026-06/00007-phase-d-canonical-readback-exit.md` linking to
  `../../adr/2026-06/0007-...md` targets the corresponding `doc.page:*`.
- `README.md` linking to `bin/tool` targets `file:bin/tool`.

### Relative File And Anchor Links

Relative Markdown file links with anchors resolve to `doc.section:*` when the
target file and anchor are known.

If the target file exists but the anchor is not known from extracted headings,
the target should be `unknown:doc.section:missing-anchor` with metadata
including the resolved file path and requested anchor.

### Same-File Anchor Links

Links such as `#usage` resolve to a `doc.section:*` node in the same page when
the anchor exists. Missing same-file anchors use
`unknown:doc.section:missing-anchor`.

### Absolute URLs

HTTP and HTTPS links resolve to `external.url:*` keys after syntactic
normalization. RepoMap must not fetch the target or infer whether it exists.

### Mailto URLs

`mailto:` links resolve to `external.url:*`. RepoMap must not validate or send
mail.

### Missing Files

Missing repository file links use an unknown placeholder, usually
`unknown:file:missing-markdown-link-target` or
`unknown:doc.page:missing-markdown-link-target` depending on the expected target
kind. Evidence metadata must preserve the raw target and source span.

### Repo-Escaping Links

Links that normalize outside the repository root use
`unknown:file:repo-escaping-markdown-link` unless a future profile explicitly
declares an external path policy.

### Dynamic Or Malformed Links

Markdown links with variable-like targets, template syntax, unmatched brackets,
invalid percent escapes, or otherwise malformed target strings use
`dynamic:*` or `unknown:*` placeholders with a diagnostic. The extractor must
not guess a canonical target.

## Documentation Duplication Policy

Each repository graph should be self-contained. If a project contains
documentation, RepoMap should index that documentation as part of that
repository graph.

This remains true even when `/Users/slair/.codex/codex-vc` also indexes
symlinked or copied documentation:

- project graphs should answer questions about the project from the project
  checkout alone;
- the codex-vc graph acts as Codex's library and catalog;
- duplicate content across repository-scoped graphs is acceptable;
- cross-project deduplication is deferred; and
- symlink traversal requires explicit profile policy.

The first implementation should not follow all symlinks by default. A profile
may later declare which documentation symlinks should be traversed and how
their canonical file paths should be spelled.

## Required Implementation Tests

The implementation that follows this ADR must include:

- unit tests for Markdown ATX heading parsing and anchor normalization;
- unit tests for duplicate heading anchors;
- unit tests for inline, image, reference, collapsed reference, shortcut
  reference, definition, and autolink parsing;
- unit tests for relative link, same-file anchor, external URL, mailto, missing
  file, repo-escaping, malformed, and dynamic link resolution;
- unit tests for shallow YAML frontmatter parsing and secret-prone value
  redaction;
- unit tests for fenced code blocks, language tags, and unclosed fences;
- canonicalization tests for `doc.page`, `doc.section`, `doc.adr`,
  `doc.skill`, and `links_to`;
- a discovery fixture containing README, ADR, status, skill, AGENTS, headings,
  links, frontmatter, and code fences;
- a golden canonicalization fixture for documentation facts;
- a storage integration test loading documentation observations through
  `storage load-files` and querying canonical readback; and
- an explain edge integration test for a Markdown `links_to` edge.

The first implementation must not change legacy command output. Any canonical
readback should use the existing canonical commands added in Phase D.

## Compatibility And Storage Notes

ADR 0008 does not implement code or migrations. It defines the documentation
graph contract that a later implementation phase may add.

Implementation will need to update:

- graph key builders, parsers, validators, and tests for the new namespaces;
- canonical edge vocabulary and tests for `links_to`;
- canonical storage edge-kind constraints before storing `links_to` rows;
- raw observation schema documentation for Markdown kinds;
- discovery to emit Markdown observations; and
- canonicalization to map Markdown observations into canonical graph facts.

Existing legacy readback commands must remain unchanged. Phase E migration is
not part of the Markdown documentation graph implementation.

## Examples

### Markdown Document

Raw observation:

```json
{"schema_version":1,"kind":"markdown.document","path":"README.md","source_id":"README.md#markdown-document","confidence":"extracted","extractor":"repo-markdown","extractor_version":"0.1.0","metadata":{"doc_path":"README.md","doc_role":"readme","title":"RepoMap","frontmatter_present":false}}
```

Canonical nodes:

- `file:README.md`
- `doc.page:file%3AREADME.md`

Canonical edge:

- `file:README.md --defines--> doc.page:file%3AREADME.md`

### Markdown Heading

Raw observation:

```json
{"schema_version":1,"kind":"markdown.heading","path":"README.md","start_line":33,"end_line":33,"name":"Current Status","target":"doc.section:file%3AREADME.md:current-status","confidence":"extracted","extractor":"repo-markdown","extractor_version":"0.1.0","source_id":"README.md#heading:current-status","metadata":{"level":2,"text":"Current Status","anchor":"current-status","base_anchor":"current-status","duplicate_index":0,"page_key":"doc.page:file%3AREADME.md"}}
```

Canonical nodes:

- `file:README.md`
- `doc.section:file%3AREADME.md:current-status`

Canonical edge:

- `file:README.md --defines--> doc.section:file%3AREADME.md:current-status`

### Markdown Link To ADR Section

Raw observation:

```json
{"schema_version":1,"kind":"markdown.link","path":"README.md","start_line":48,"end_line":48,"name":"ADR 0007","target":"doc.section:file%3Adocs%2Fadr%2F2026-06%2F0007-canonical-readback-and-explain-query-contracts.md:storage-canonical-edges","confidence":"extracted","extractor":"repo-markdown","extractor_version":"0.1.0","source_id":"README.md#link:48:0","metadata":{"link_text":"ADR 0007","raw_target":"docs/adr/2026-06/0007-canonical-readback-and-explain-query-contracts.md#storage-canonical-edges","link_syntax":"inline","source_anchor":"current-status","resolved_target_kind":"doc.section","resolved_path":"docs/adr/2026-06/0007-canonical-readback-and-explain-query-contracts.md","resolved_anchor":"storage-canonical-edges"}}
```

Canonical edge:

- `doc.section:file%3AREADME.md:current-status --links_to-->
  doc.section:file%3Adocs%2Fadr%2F2026-06%2F0007-canonical-readback-and-explain-query-contracts.md:storage-canonical-edges`

### External URL

Raw observation:

```json
{"schema_version":1,"kind":"markdown.link","path":"docs/status/example.md","start_line":10,"end_line":10,"name":"example","target":"external.url:https%3A%2F%2Fexample.com%2Fdocs","confidence":"extracted","extractor":"repo-markdown","extractor_version":"0.1.0","source_id":"docs/status/example.md#link:10:0","metadata":{"link_text":"example","raw_target":"https://example.com/docs","link_syntax":"inline","resolved_target_kind":"external.url"}}
```

Canonical edge:

- `doc.page:file%3Adocs%2Fstatus%2Fexample.md --links_to-->
  external.url:https%3A%2F%2Fexample.com%2Fdocs`

### ADR Metadata

Raw observation:

```json
{"schema_version":1,"kind":"markdown.adr_metadata","path":"docs/adr/2026-06/0008-markdown-documentation-graph-model.md","name":"0008","target":"doc.adr:0008","confidence":"extracted","extractor":"repo-markdown","extractor_version":"0.1.0","source_id":"docs/adr/2026-06/0008-markdown-documentation-graph-model.md#adr-metadata","metadata":{"adr_number":"0008","title":"Markdown Documentation Graph Model","status":"Accepted","date":"2026-06-29","metadata_source":"heading"}}
```

Canonical edge:

- `file:docs/adr/2026-06/0008-markdown-documentation-graph-model.md --defines-->
  doc.adr:0008`

### Skill Metadata

Raw observation:

```json
{"schema_version":1,"kind":"markdown.skill_metadata","path":"docs/skills/example/SKILL.md","name":"example","target":"doc.skill:example","confidence":"heuristic","extractor":"repo-markdown","extractor_version":"0.1.0","source_id":"docs/skills/example/SKILL.md#skill-metadata","metadata":{"skill_name":"example","description":"Example skill.","metadata_source":"frontmatter","parse_status":"parsed"}}
```

Canonical edge:

- `file:docs/skills/example/SKILL.md --defines--> doc.skill:example`

## Rejected Alternatives

### Treating Markdown As Opaque File Nodes Only

Rejected. File nodes alone preserve that a Markdown file exists, but they do
not expose sections, ADR decisions, skill metadata, or links between docs and
code. That would leave major project knowledge outside canonical readback.

### Free-Text Semantic Entity Extraction In MD1

Rejected. Semantic extraction from arbitrary prose would require NLP or LLM
behavior that is outside RepoMap's deterministic extractor model. Structural
Markdown facts are useful without guessing prose meaning.

### Using Line Numbers In Doc Section Keys

Rejected. Line numbers are evidence locations and change whenever surrounding
text moves. Section keys use page identity plus deterministic anchors; line
spans stay in evidence records.

### Making codex-vc The Only Graph That Contains Project Docs

Rejected. codex-vc can be Codex's library and catalog, but each project graph
should remain self-contained. A RepoMap graph for a repository should include
the repository's own docs.

### Following All Symlinks By Default

Rejected. Symlink traversal can duplicate content, escape the repository, or
blur ownership boundaries. Symlink behavior should be controlled by explicit
profile policy.

### Adding MCP Write Tools To Maintain Docs Graphs

Rejected. Markdown documentation graph extraction is a read/indexing feature.
MCP write tools would expand scope and introduce mutation risks unrelated to
the graph model.

### Adding Broad Semantic Edge Kinds Now

Rejected. Edge kinds such as `mentions`, `describes`, `documents`, and
`supersedes` are tempting but ambiguous without strict extraction rules.
`links_to` and `defines` are enough for the first structural documentation
graph.
