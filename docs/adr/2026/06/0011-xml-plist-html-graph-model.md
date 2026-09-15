# ADR 0011: XML, Plist, And HTML Graph Model

## Status

Accepted

## Date

2026-06-30

## Context

RepoMap now extracts and canonicalizes Python, Nix, Markdown, and structured
JSON-family/TOML configuration facts, while retaining earlier shell-family file,
command, and host-mutation observations for legacy and compatibility workflows.
Canonical graph readback is the preferred public query model, while Phase F3
intentionally pauses further legacy-readback migration before higher-risk
commands.

XML-family files are both documents and structured configuration. Apple plist
XML is structurally closer to configuration than prose, and the immediate
motivation is a Chrome policy plist in `.flakes` that has caused
disproportionate maintenance friction. RepoMap should be able to answer which
file defines a managed preference, where policy keys live, and which static
paths, URLs, or environment variables are referenced without executing anything
or interpreting browser policy semantics deeply.

Longer term, XML and HTML graph coverage is useful for static web-scraper
fixtures, Maven POMs, Java and Spring Boot XML configuration, static HTML
structure, forms, links, and assets. These facts should enter the same raw
observation -> evidence -> canonical graph pipeline used by the rest of
RepoMap.

XML-family parsing must remain static and deterministic. RepoMap must not fetch
URLs, resolve external entities over the network, validate schemas, apply XSLT,
execute scripts, execute Java behavior, or store secrets in graph identity or
summary metadata.

## Decision

RepoMap will model XML-family documents conservatively.

The first implementation target should be plist XML, especially Apple managed
preference and Chrome policy files. Plist XML will reuse ADR 0010's structured
configuration model:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`

Plist observations should set metadata such as `format=plist-xml` so callers can
distinguish plist-derived config from JSON/TOML config without learning a new
canonical namespace.

Generic XML and HTML need their own raw observation kinds and canonical
namespaces because element structure, attributes, headings, forms, and links are
not always configuration paths. XML/HTML namespaces are compatible graph key
version 1 additions because they add new durable entity kinds without changing
existing key meanings.

RepoMap will reuse existing edge kinds where possible:

- `defines` for file-to-document and file-to-element/path facts; and
- `references` for syntactic references from XML, plist, or HTML values to
  files, tools, environment variables, external URLs, unknown placeholders, or
  dynamic placeholders.

This ADR does not add a new edge kind. It keeps Markdown `links_to` scoped to
Markdown/documentation links unless a later ADR explicitly broadens it.

## Scope

In scope:

- `.xml`;
- `.plist`;
- `.html`;
- `.htm`;
- selected extensionless XML or plist files only when discovery safely
  classifies them;
- XML element paths and attributes;
- plist dictionaries, arrays, keys, and scalar values;
- static HTML elements, headings, links, forms, ids/classes, and script/style
  tags as structural facts only;
- conservative references for file paths, URLs, environment variables,
  class/package names, Maven coordinates, Spring bean ids, and plist policy keys
  only when syntactically clear; and
- raw parse diagnostics for malformed, dangerous, or unsupported constructs.

Out of scope:

- executing scripts;
- fetching URLs;
- resolving external DTDs or entities over the network;
- validating XML schemas;
- applying XSLT;
- interpreting browser policy semantics deeply;
- executing Java or Spring behavior;
- resolving Maven dependencies online;
- crawling websites;
- rendering HTML;
- parsing CSS or JavaScript deeply;
- storing secret values;
- Phase F migration;
- Shell/Bats/AWK extraction; and
- storage migrations.

## Security Rules

XML-family extraction must use safe parsing.

Required behavior:

- disable external entity expansion where the parser supports it;
- never fetch external DTDs, entities, includes, or schemas;
- reject or emit raw-only diagnostics for dangerous constructs such as DOCTYPE
  declarations with external entities;
- avoid XXE-style file or network access;
- do not apply XSLT;
- do not execute script or style content; and
- avoid parser modes that implicitly resolve network resources.

If an implementation uses Python standard-library XML tools, it must document
the exact safe parser constraints. If the selected stdlib parser cannot provide
the safety needed for the accepted scope, implementation must add defensive
pre-scan checks before parsing and tests that prove external entities are not
expanded. Adding a third-party parser requires a separate phase approval.

## Relationship To ADR 0010 Configuration Model

Plist XML should be treated as structured configuration by default. This avoids
over-fragmenting policy and managed-preference graphs with plist-specific
namespaces when ADR 0010 already defines durable configuration document and path
identity.

Plist XML mapping:

- one plist file emits `config.document` with `format=plist-xml`;
- plist dictionary keys emit `config.path`;
- plist scalar values may emit safe `value_summary` metadata when non-secret;
- plist arrays follow ADR 0010 array policy;
- plist reference-like values may emit `config.reference`; and
- malformed plist emits `config.parse_error`.

Generic XML may emit XML-specific facts because arbitrary XML element paths and
attributes are not necessarily configuration keys. HTML should emit HTML/web
document facts rather than `config.path` by default, because static HTML is more
often document/web structure than application configuration.

## Raw Observation Kinds

All XML-family extractors emit raw observations with the standard RepoMap fields:
`kind`, `source_id`, `path`, optional line span, optional `name`, optional
`target`, `confidence`, `extractor`, `extractor_version`, and `metadata`.

Use `confidence="extracted"` for facts produced by deterministic safe parsing.
Use `confidence="heuristic"` for conservative reference detection. Use
`confidence="unknown"` for parse errors or unresolved/dangerous constructs.

### Generic XML

`xml.document`

- Represents one XML document.
- Required metadata: `format=xml`, parser, document role if detected, root tag,
  namespace summary when safe, parse error count.
- Canonical target: `xml.document:<encoded-file-key>`.

`xml.element`

- Represents one XML element path when the path can be identified
  deterministically.
- Required metadata: element name, namespace URI or prefix when safe,
  XML pointer, attribute count, child count, text summary only when safe and
  non-secret.
- Canonical target: `xml.element:<encoded-file-key>:<encoded-xml-pointer>`.

`xml.attribute`

- Represents one XML attribute on a deterministic XML element path.
- Required metadata: element pointer, attribute name, namespace, value type,
  redaction flags, safe value summary when allowed.
- Canonical target:
  `xml.attribute:<encoded-file-key>:<encoded-xml-pointer>:<encoded-attr-name>`.

`xml.reference`

- Represents a conservative syntactic reference from an XML element or
  attribute value.
- Metadata should include source element/attribute pointer, reference kind,
  raw key or attribute name, safe value summary or redaction reason, and source
  canonical key when known.
- Canonicalization creates a `references` edge only when source and target keys
  validate.

`xml.parse_error`

- Represents malformed XML, blocked external entity usage, unsupported XML
  constructs, or parser safety rejection.
- Raw/evidence-oriented in XML1 unless a later ADR accepts diagnostic nodes.

### Plist XML

Plist XML reuses ADR 0010 raw kinds:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`

Required plist-specific metadata:

- `format=plist-xml`;
- parser and safety mode;
- plist top-level type;
- policy/document role when shallowly detected;
- key path or pointer;
- value type;
- redaction flags; and
- array policy where arrays are present.

### HTML

`html.document`

- Represents one static HTML document.
- Metadata: `format=html`, parser mode, title when safe, doctype summary,
  root element, language attribute when safe, and parse error count.
- Canonical target: `html.document:<encoded-file-key>`.

`html.element`

- Represents one deterministic structural HTML element path.
- Metadata: tag name, pointer, id/classes as metadata, attribute count, child
  count, and safe text summary only when non-secret and small.
- Canonical target: `html.element:<encoded-file-key>:<encoded-html-pointer>`.

`html.heading`

- Represents heading elements `h1` through `h6`.
- Metadata: heading level, text summary when safe, anchor/id when present, and
  source element pointer.
- Canonical target may be `html.anchor:<encoded-file-key>:<encoded-fragment-or-pointer>`
  when a stable id/fragment exists, otherwise an `html.element:*` target.

`html.link`

- Represents links from `href`, `src`, `action`, and similar attributes when
  statically clear.
- Canonicalization may create `references` edges from an `html.element:*` or
  `html.anchor:*` source to `file:*`, `external.url:*`, `unknown:*`, or
  `dynamic:*` targets.

`html.form`

- Represents static form structure.
- Metadata: method, action target if present, field count, ids/classes as
  metadata, and redaction flags.
- Action URLs or paths may emit `references` edges.

`html.asset`

- Represents static asset references such as images, stylesheets, scripts, and
  iframes. Script and style contents are not executed or parsed deeply.
- Metadata: tag name, attribute name, media/type hints, and source element
  pointer.

`html.parse_error`

- Represents malformed HTML or parser limitations. Since HTML parsers often
  recover, implementations should distinguish recoverable parse warnings from
  unrecoverable document rejection.

## Canonical Key Namespaces

Accepted XML/HTML namespaces:

```text
xml.document:<encoded-file-key>
xml.element:<encoded-file-key>:<encoded-xml-pointer>
xml.attribute:<encoded-file-key>:<encoded-xml-pointer>:<encoded-attr-name>
html.document:<encoded-file-key>
html.element:<encoded-file-key>:<encoded-html-pointer>
html.anchor:<encoded-file-key>:<encoded-fragment-or-pointer>
```

Accepted plist namespaces are ADR 0010 namespaces:

```text
config.document:<encoded-file-key>
config.path:<encoded-file-key>:<encoded-config-pointer>
```

Canonical keys must not include:

- raw scalar values;
- secret values;
- line numbers;
- source ids;
- extractor names or versions;
- content hashes;
- volatile parser object ids;
- generated browser/runtime ids; or
- arbitrary text content.

## Pointer And Path Identity

XML and HTML element pointers identify structural document locations, not
durable domain entities. They are useful for explaining and querying static
structure, but they may change when document structure changes.

Rules:

- element paths use deterministic structural paths from the document root;
- namespace-aware tag names should be normalized consistently and escaped
  through graph-key percent encoding;
- same-name siblings require disambiguation;
- numeric sibling indexes may be used for generic XML/HTML structural identity
  when no stable id exists;
- if numeric indexes are used, metadata must make clear the identity is
  structural-document identity;
- id attributes may be used for `html.anchor:*` keys only when they are present,
  unique in the document, and syntactically stable;
- ids/classes are metadata for `html.element:*` and should not replace pointer
  identity unless the key namespace explicitly supports them; and
- text content is never canonical identity.

Plist pointer rules follow ADR 0010:

- plist dictionary keys provide stable config path segments;
- plist arrays of scalars produce summary metadata;
- plist arrays of dictionaries may use stable member keys such as `name`, `id`,
  `key`, or `project` only when deterministic;
- ordinary numeric array indexes are evidence-only for plist config identity;
  and
- malformed or ambiguous plist paths use diagnostics or placeholders instead of
  fabricated precision.

## Edge Vocabulary

XML0 uses existing edge kinds.

Definitions:

```text
file:* --defines--> xml.document:*
file:* --defines--> xml.element:*
file:* --defines--> xml.attribute:*
file:* --defines--> html.document:*
file:* --defines--> html.element:*
file:* --defines--> html.anchor:*
file:* --defines--> config.document:*
file:* --defines--> config.path:*
```

References:

```text
xml.element:* | xml.attribute:* | html.element:* | html.anchor:* |
config.path:* --references--> file:* | tool:* | env:* | external.url:* |
unknown:* | dynamic:* | external:*
```

The `references` edge means a structured value syntactically references another
durable target. It does not imply runtime execution, ownership, dependency
resolution, browser policy enforcement, Java behavior, or web crawling.

Markdown `links_to` remains Markdown/documentation-specific in XML0. HTML
links and assets should use `references` unless a later ADR broadens
`links_to`.

No new edge kind is accepted by XML0.

## Plist Policy Model

Apple plist XML should be parsed as structured configuration.

Rules:

- the plist root document emits `config.document` with `format=plist-xml`;
- `dict/key/string/integer/real/true/false/date/data/array` structures are
  translated into `config.path` observations;
- policy names become config path segments, not new namespaces in XML1;
- dictionary nesting maps to JSON Pointer-style paths;
- scalar values get safe summaries only when non-secret;
- secret-prone keys are redacted using ADR 0010 rules;
- arrays follow ADR 0010 array policy;
- repo-local paths, URLs, and environment-variable references may emit
  `config.reference` observations when syntactically clear;
- unknown, dynamic, or repo-escaping targets use explicit placeholders; and
- malformed plist emits `config.parse_error`.

The XML1 implementation must include a Chrome policy plist fixture because that
is the immediate motivating file class.

## HTML Model

HTML extraction should record static document structure only.

Rules:

- record a document node and safe title metadata;
- record headings as structural facts;
- record links, assets, and form actions as syntactic references;
- keep ids/classes as metadata unless a stable anchor key is accepted;
- do not render HTML;
- do not execute JavaScript;
- do not parse CSS or JavaScript deeply;
- script/style tags may emit structural element or asset observations, but
  contents are summary-only or raw/evidence-only; and
- malformed HTML handling depends on the parser, but recovery must be
  deterministic and tested.

HTML is not modeled as `config.path` by default because static HTML is a
document/web artifact, not necessarily structured application configuration.

## Java, Spring, And Maven XML Model

Java/Spring/Maven XML should remain conservative in XML1/XML2.

Rules:

- do not execute Java or Spring behavior;
- do not validate schemas or fetch namespaces;
- record XML elements and attributes structurally;
- class names may be preserved as metadata or external/unknown references until
  Java canonical namespaces are accepted;
- Spring bean ids may be represented as XML/config paths, not `spring.bean:*`
  keys, unless a later ADR accepts a Spring namespace;
- Maven coordinates may be metadata, not package/dependency nodes, unless a
  later ADR accepts package/dependency namespaces;
- property placeholders and profile activation expressions should use
  `dynamic:*` or `unknown:*` placeholders when unresolved; and
- schema locations and namespaces should be references only when they are
  syntactically clear and must never be fetched.

## Redaction

XML-family extraction reuses ADR 0010 secret-prone key detection for XML
attributes, plist keys, element names, and HTML form/input names.

Secret-prone markers:

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

Rules:

- secret values must never appear in canonical keys;
- secret values must not appear in raw observation metadata, canonical metadata,
  golden expected outputs, or readback;
- value type, redaction flag, and redaction reason may be preserved;
- implementation fixtures may use harmless sentinel values only to prove
  redaction, and expected outputs must not contain those sentinel values; and
- non-reversible value hashes remain deferred unless a later ADR accepts them.

## Required Implementation Tests

XML1 must include:

- plist dictionary fixture for a Chrome policy file;
- plist nested dictionaries;
- plist arrays of scalars;
- plist arrays of dictionaries with and without stable member keys;
- XML/plist parse error coverage;
- XXE/external entity safety tests;
- redaction tests for plist keys and XML attributes/elements;
- conservative references for repo-local paths, URLs, and environment variables
  when present;
- canonicalization tests for plist `config.document` and `config.path`;
- canonicalization tests for plist `references` edges when present;
- storage readback tests for `config.document`, `config.path`, `defines`, and
  `references`; and
- `explain-canonical-edge` coverage for one plist reference edge.

Later HTML1 must include:

- basic HTML document fixture;
- heading extraction;
- links;
- forms;
- assets;
- malformed but recoverable HTML if the parser supports it;
- assertions that script/style content is not executed;
- storage readback tests for HTML document/element nodes; and
- explain-edge coverage for one HTML link or asset reference.

XML2 Java/Spring/Maven smoke should include:

- a Spring XML fixture with bean ids and class attributes;
- a Maven POM fixture with coordinates preserved as metadata;
- schema/namespace URLs that are recorded but not fetched;
- property placeholders represented as dynamic/unknown when unresolved; and
- redaction and parser-safety coverage.

## Rejected Alternatives

### Execute XML, HTML, Script, Or Style Content

Rejected. RepoMap is a static repository graph builder. Executing scripts,
styles, XSLT, Java behavior, or browser policy behavior would cross the
deterministic extraction boundary and create host risk.

### Fetch Schemas, DTDs, Entities, Or URLs

Rejected. Network resolution is not needed for structural graph facts and would
make indexing non-deterministic. XML-family extractors must not fetch schemas,
DTDs, external entities, Maven dependencies, or web pages.

### Validate Java, Spring, Maven, Or Browser Policy Semantics Online

Rejected. XML0 records static structure and syntactic references. Deep
application semantics can come later through explicit, tested, project-specific
phases.

### Store Arbitrary Text Values As Canonical Nodes

Rejected. Text values are often volatile, noisy, or secret-prone. They may
appear as safe summaries or evidence metadata when allowed, but not as durable
graph identity.

### Use Secret Values In Keys Or Metadata

Rejected. Secret values must be redacted before raw observation metadata,
canonical metadata, golden expected outputs, and readback.

### Treat HTML Rendering As Extraction

Rejected. Rendering requires browser behavior, CSS/JS interpretation, and often
network resources. XML0 covers static source structure only.

### Invent Spring, Maven, Or Browser-Policy Domain Namespaces In XML0

Rejected. XML0 should not introduce untested domain vocabulary. Spring beans,
Maven coordinates, and browser policy keys remain structural XML/config facts
until a later ADR accepts domain-specific namespaces.

### Resume Phase F As Part Of XML/HTML Extraction

Rejected. XML0 is a graph-coverage planning ADR. It does not change public
readback defaults or legacy-output migration policy.

## Proposed Phases

XML1: implement a safe plist/XML extractor focused on Apple plist XML and a
Chrome policy plist fixture. Reuse ADR 0010 config nodes and `references`
edges. Include parser-safety, redaction, canonicalization, storage readback, and
explain-edge tests.

HTML1: implement a conservative static HTML extractor for documents, headings,
links, forms, and assets. Do not render, execute JavaScript, parse CSS/JS
deeply, crawl, or fetch URLs.

XML2: add Java/Spring/Maven XML fixture smoke coverage. Keep class names,
Spring bean ids, schema URLs, Maven coordinates, and placeholders conservative
until domain-specific namespaces are accepted by a later ADR.

## Verification

Docs-only verification for this ADR:

```sh
git diff --check
git diff --cached --check
```

Source-code tests and compile-style checks were intentionally not run because
this change is docs-only.
