# ADR 0012: Static CSS Graph Model

## Status

Accepted

## Date

2026-06-30

## Context

RepoMap now extracts static HTML structure, and the generated test report visual
system is synchronized between RepoMap and `.flakes`. The report pages are
driven by static HTML plus CSS selectors and class names such as
`status-badge`, `report-header`, `tree-grid`, and related layout selectors.
CSS is therefore the missing static link between HTML structure and the visual
report system.

Immediate CSS graph use cases include:

- understanding generated test reports;
- connecting report HTML classes, ids, and elements to CSS selectors later;
- supporting the synchronized RepoMap and `.flakes` report visual system; and
- preparing for future static web-scraper fixture analysis.

The model should support report analysis without becoming a browser. RepoMap
must not apply the cascade, compute final styles, execute JavaScript, fetch
URLs, resolve imported CSS over the network, or emulate a CSSOM/browser layout
engine.

## Decision

RepoMap will model CSS as static source structure and conservative syntactic
references.

CSS0 accepts graph key version 1 namespace additions for CSS documents, rules,
selectors, and custom properties:

```text
css.document:<encoded-file-key>
css.rule:<encoded-file-key>:<encoded-rule-pointer>
css.selector:<encoded-file-key>:<encoded-selector-pointer>
css.custom_property:<encoded-file-key>:<encoded-property-name>
```

CSS0 does not add a new edge kind. It reuses:

- `defines` for file-to-CSS-document, file-to-rule, rule-to-selector, and
  file/rule-to-custom-property structural facts; and
- `references` for syntactic `url(...)` and `@import` targets.

CSS1 should extract CSS facts only. Static selector-to-HTML matching is
deferred until a later phase can define and test conservative matching rules.
Selectors are queryable as CSS facts, but CSS0 does not claim that a selector
matches any particular HTML element.

## Scope

In scope:

- `.css` files;
- `<style>` blocks as structural CSS sources only if already captured by HTML or
  by a future HTML refinement;
- selectors;
- rule blocks;
- declarations;
- custom properties;
- `@media`;
- `@supports`;
- `@font-face` metadata only;
- `@import` as a syntactic reference only;
- `url(...)` references;
- class selectors;
- id selectors;
- element selectors;
- attribute selectors as metadata;
- pseudo-classes and pseudo-elements as metadata; and
- source line spans where practical.

Out of scope:

- applying the cascade;
- computing final styles;
- layout or rendering;
- resolving browser defaults;
- executing JavaScript;
- fetching imported CSS or URL assets;
- validating CSS against browser engines;
- full CSSOM emulation;
- Sass, Less, or PostCSS preprocessing;
- minified CSS deobfuscation beyond basic parsing;
- CSS-in-JS;
- JavaScript extraction;
- changing report visuals;
- changing HTML extraction; and
- third-party parser dependencies unless separately approved.

## Raw Observation Kinds

CSS extractors emit raw observations with the standard RepoMap fields: `kind`,
`source_id`, `path`, optional line span, optional `name`, optional `target`,
`confidence`, `extractor`, `extractor_version`, and `metadata`.

Use `confidence="extracted"` for deterministic parser/scanner facts such as
rule boundaries, selector text, and declaration names. Use
`confidence="heuristic"` for conservative reference detection. Use
`confidence="unknown"` for malformed CSS or unsupported constructs.

### `css.document`

Represents one stylesheet source.

Required fields:

- `kind`: `css.document`
- `path`: repository-relative stylesheet path
- `source_id`: stable extractor-local id such as `<path>#css-document`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`: `css`;
- `parser`: parser/scanner family and mode;
- `source_kind`: `file` or `style-block`;
- `rule_count`;
- `selector_count`;
- `custom_property_count`;
- `reference_count`; and
- `parse_error_count`.

Canonicalization creates a `css.document:*` node and a `file:* --defines-->
css.document:*` edge for file-backed stylesheets.

### `css.rule`

Represents one deterministic CSS rule block.

Required fields:

- `kind`: `css.rule`
- `path`: repository-relative stylesheet path
- `name`: normalized rule pointer
- `target`: `css.rule:*` when the extractor can build it
- `source_id`: stable extractor-local id such as `<path>#css-rule:<pointer>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `rule_pointer`: deterministic structural pointer;
- `rule_type`: `style`, `media`, `supports`, `font-face`, `import`,
  `keyframes`, `unknown-at-rule`, or similar narrow type;
- `selector_text`: for style rules only, safe raw selector text;
- `at_rule_name`: for at-rules;
- `at_rule_prelude_summary`: safe summary for `@media` or `@supports`;
- `declaration_count`;
- `custom_property_names`;
- `reference_count`;
- `parent_rule_pointer` when nested under an at-rule; and
- `identity_mode`: `structural-document`.

Canonicalization creates a `css.rule:*` node and a `file:* --defines-->
css.rule:*` edge. Rule pointers are structural document identity: they are
stable for byte-identical parse trees but can change when rule order or nesting
changes. Line numbers are evidence only.

### `css.selector`

Represents one selector inside a style rule, including selectors that came from
a grouped selector list.

Required fields:

- `kind`: `css.selector`
- `path`: repository-relative stylesheet path
- `name`: normalized selector pointer
- `target`: `css.selector:*` when the extractor can build it
- `source_id`: stable extractor-local id such as
  `<path>#css-selector:<pointer>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `selector_pointer`;
- `rule_pointer`;
- `selector_text`;
- `selector_index` as structural evidence, not domain identity;
- `classes`;
- `ids`;
- `element_names`;
- `attributes`;
- `pseudo_classes`;
- `pseudo_elements`;
- `specificity_summary` only if cheap and deterministic; and
- `selector_kind`: `simple`, `compound`, `complex`, `group-member`, or
  `unknown`.

Canonicalization may create a `css.selector:*` node and a
`css.rule:* --defines--> css.selector:*` edge. Selector text is metadata, not
canonical identity.

### `css.declaration`

Represents one CSS declaration.

Required fields:

- `kind`: `css.declaration`
- `path`: repository-relative stylesheet path
- `name`: property name
- `source_id`: stable extractor-local id such as
  `<path>#css-declaration:<rule-pointer>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `rule_pointer`;
- `property_name`;
- `value_type`: `literal`, `function`, `url`, `custom-property-reference`,
  `unknown`, or similar;
- `value_summary` only when safe and non-secret;
- `important`: boolean;
- `redacted`: boolean;
- `redaction_reason` when redacted; and
- `reference_targets` when declaration values contain conservative references.

Ordinary declarations are raw/evidence or rule metadata in CSS1. They do not
receive canonical nodes because declaration values are often volatile settings,
not durable graph entities.

### `css.custom_property`

Represents one CSS custom property name defined in a stylesheet, such as
`--surface`.

Required fields:

- `kind`: `css.custom_property`
- `path`: repository-relative stylesheet path
- `name`: custom property name
- `target`: `css.custom_property:*` when the extractor can build it
- `source_id`: stable extractor-local id such as
  `<path>#css-custom-property:<property-name>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `property_name`;
- `rule_pointer`;
- `definition_count` when summarized;
- `value_type`;
- `value_summary` only when safe and non-secret;
- `redacted`;
- `redaction_reason`; and
- `reference_targets` for `url(...)` or similar references in the value.

Canonicalization creates a `css.custom_property:*` node. The first
implementation may use `file:* --defines--> css.custom_property:*`; it may also
add `css.rule:* --defines--> css.custom_property:*` when the defining rule is
known and tests prove this readback is useful. Multiple definitions of the same
custom property name in one stylesheet collapse to the same custom-property node
with multiple evidence records, because the node identifies the reusable
property name, not a particular declaration site.

### `css.reference`

Represents a syntactic reference from CSS, primarily `url(...)` and `@import`.

Required fields:

- `kind`: `css.reference`
- `path`: repository-relative stylesheet path
- optional line span
- `name`: source rule pointer, declaration pointer, or at-rule pointer
- `target`: resolved canonical target key or explicit placeholder
- `source_id`: stable extractor-local id such as
  `<path>#css-reference:<pointer>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `reference_kind`: `file`, `external.url`, `unknown`, `dynamic`, or
  `external.file`;
- `source_kind`: `url-function`, `import`, `font-face`, `asset`, or
  `unknown`;
- `rule_pointer`;
- `property_name` when the reference comes from a declaration;
- `raw_value_summary`: safe summary only;
- `resolution_reason`;
- `redacted`; and
- `redaction_reason` when needed.

Canonicalization creates a `references` edge from the most precise stable CSS
source node available, usually `css.rule:*`, to the resolved target. If a later
implementation accepts canonical declaration nodes, declaration-to-target edges
can be revisited. CSS1 should avoid fabricating precision from ambiguous values.

### `css.parse_error`

Represents malformed CSS, unsupported constructs, or parser limitations.

Required fields:

- `kind`: `css.parse_error`
- `path`: repository-relative stylesheet path
- optional line span
- `source_id`: stable extractor-local id such as
  `<path>#css-parse-error:<ordinal>`
- `confidence`: usually `unknown`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `error_kind`;
- `message_summary`;
- `recovered`: boolean;
- `rule_pointer` when known; and
- `line_number` and `column_number` as evidence only when known.

`css.parse_error` remains raw/evidence only unless a later ADR accepts
diagnostic nodes.

## Canonical Key Namespaces

Accepted graph key version 1 namespace additions:

```text
css.document:<encoded-file-key>
css.rule:<encoded-file-key>:<encoded-rule-pointer>
css.selector:<encoded-file-key>:<encoded-selector-pointer>
css.custom_property:<encoded-file-key>:<encoded-property-name>
```

`<encoded-file-key>` is the percent-encoded canonical `file:*` key string. For
example, `file:tools/test/report/static/report.css` becomes one encoded segment
inside CSS keys.

Pointers and property names are escaped using the canonical graph-key escaping
rules from ADR 0002. Canonical keys must not include:

- declaration values;
- raw selector text as the identity segment;
- raw CSS text;
- line numbers;
- parser-generated ids;
- source ids;
- extractor names or versions;
- content hashes;
- secret values; or
- browser-computed layout/style data.

CSS namespaces are compatible graph key version 1 additions because they add new
durable entity kinds without changing existing key meanings.

## Pointer Identity

CSS rule and selector pointers identify structural stylesheet locations, not
browser-applied style results.

Rules:

- CSS document identity is based on the file key;
- rule pointers are deterministic from the parsed stylesheet tree;
- nested at-rules include parent structure in the pointer;
- grouped selectors may become distinct selector pointers beneath one rule;
- numeric structural indexes may be used for rules and grouped selectors when no
  better structural label exists;
- metadata must state when identity uses structural-document indexes;
- line and column numbers are evidence only; and
- selector text remains metadata so formatting normalization does not become the
  public identity contract.

Example pointer shapes:

```text
/rule:1
/rule:2/selector:1
/media:1/rule:1
/supports:1/rule:2/selector:1
```

The exact pointer grammar should be finalized in CSS1 tests before storage
readback is relied on publicly. The grammar must be byte-stable for identical
input and deterministic across platforms.

## Edge Vocabulary

CSS0 uses existing edge kinds.

Definitions:

```text
file:* --defines--> css.document:*
file:* --defines--> css.rule:*
css.rule:* --defines--> css.selector:*
file:* --defines--> css.custom_property:*
css.rule:* --defines--> css.custom_property:*
```

References:

```text
css.rule:* --references--> file:* | external.url:* | unknown:* |
dynamic:* | external:*
```

The `references` edge means a CSS value syntactically references another
durable target. It does not imply runtime dependency resolution, fetchability,
browser loading success, cascade application, or asset existence.

CSS0 does not use Markdown `links_to`. HTML links and CSS asset references use
`references`.

## Selector Policy

Selectors are CSS facts, not HTML-match facts in CSS1.

Rules:

- store selector text as metadata;
- use pointer-based canonical identity for `css.selector:*`;
- extract selector components into metadata arrays when conservative:
  `classes`, `ids`, `element_names`, `attributes`, `pseudo_classes`, and
  `pseudo_elements`;
- preserve grouped selectors as separate selector observations when possible;
- preserve complex selector structure only as metadata unless the parser can
  model it deterministically;
- do not claim selector-to-HTML matches in CSS1; and
- defer cross-linking selectors to `html.element:*` or `html.anchor:*` until a
  later tested matching phase.

The later selector-matching phase should begin with conservative class, id, and
element matches from local HTML and CSS files only. It must avoid claiming
browser cascade results.

## Declaration Policy

Declarations are useful evidence for explaining a rule but are usually not
durable graph entities.

Rules:

- ordinary declaration values remain raw/evidence or `css.rule` metadata;
- ordinary declaration values do not become canonical nodes;
- property names may be summarized as metadata;
- `!important` is metadata;
- `url(...)` values may emit `css.reference`;
- CSS custom properties are canonicalized as `css.custom_property:*` because
  they are named reusable design tokens within a stylesheet; and
- multiple declaration sites for the same custom property in a file collapse
  onto one custom-property node with multiple evidence records.

Secret-prone values must be redacted using ADR 0010-style markers when property
names, custom property names, comments used by the parser, or nearby metadata
imply secrets.

## Reference Policy

CSS references are syntactic only.

Rules:

- local relative `url(...)` paths normalize to `file:*` when they remain inside
  the repository;
- repo-escaping paths become `unknown:file:repo-escaping-css-reference`;
- absolute filesystem paths become `external:file:absolute-css-reference`;
- `http`, `https`, and `mailto` URLs become `external.url:*`;
- `data:` URLs should remain raw/evidence or become `external.url:*` only when
  the implementation can preserve a safe compact summary without storing
  payloads;
- dynamic values using CSS variables, template markers, globs, or unresolved
  functions become `dynamic:*` or raw-only diagnostics;
- malformed URLs become `unknown:*` or `css.parse_error` observations; and
- `@import` emits a `references` edge but is never fetched by RepoMap.

No implementation may fetch `@import` or `url(...)` targets in CSS1.

## At-Rule Policy

At-rules are structural CSS facts.

Rules:

- `@media` and `@supports` may become `css.rule:*` nodes with nested child rule
  pointers;
- `@font-face` may become a `css.rule:*` node with metadata such as
  `font_family_summary` and redacted source references;
- `@import` may become a `css.rule:*` node and a `css.reference` observation;
- unknown at-rules should emit conservative `css.rule` metadata or
  `css.parse_error` diagnostics depending on parse confidence; and
- no at-rule is evaluated against the host environment or a browser.

## Redaction

CSS extraction reuses ADR 0010 secret-prone marker detection for property names,
custom property names, URLs, comments consumed by the parser, and metadata keys.

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
  golden expected outputs, readback output, or explain output;
- value type, redaction flag, and redaction reason may be preserved;
- data URL payloads are secret-prone by default and should not be stored; and
- non-reversible value hashes remain deferred unless a later ADR accepts them.

## Report-Specific Fixtures

CSS1 must include fixture coverage for the synchronized report styles:

- RepoMap source CSS:
  `tools/test/report/static/report.css`;
- `.flakes` source CSS:
  `nix-darwin/tools/test/report/static/report.css`;
- generated report copies such as
  `.test-reports/**/static/report.css` as generated artifacts, not primary
  source of truth; and
- selectors used by the report system, including `status-badge`,
  `report-header`, `report-badges`, `tree-grid`, `test-grid`, `path-cell`,
  `metric-cell`, `status-cell`, `row`, and status classes.

Generated `.test-reports/**` files should normally remain ignored. Tests should
prefer stable source CSS fixtures over generated report outputs unless a
specific smoke test is checking generated report packaging.

## Required Implementation Tests

CSS1 must include:

- CSS document extraction;
- simple class selectors;
- simple id selectors;
- element selectors;
- grouped selectors;
- attribute selectors as metadata;
- pseudo-classes and pseudo-elements as metadata;
- nested `@media` rules;
- nested `@supports` rules;
- `@font-face` metadata without fetching fonts;
- custom properties;
- `url(...)` references to repo-local files;
- repo-escaping, absolute, malformed, and dynamic URL references;
- `@import` references without fetching;
- malformed CSS diagnostics;
- generated report CSS fixture coverage;
- canonicalization tests for `css.document`;
- canonicalization tests for `css.rule`;
- canonicalization tests for `css.selector` if selector nodes are implemented in
  CSS1;
- canonicalization tests for `css.custom_property`;
- storage readback tests for `css.document`, `css.rule`, and
  `css.custom_property`;
- canonical `references` readback for one CSS asset reference; and
- `explain-canonical-edge` coverage for one CSS asset or `@import` reference.

Implementation tests must also prove that CSS extraction does not fetch URLs,
execute JavaScript, execute CSS, or compute layout.

## Proposed Phases

Recommended next phases:

- CSS1: static `.css` extractor, canonicalization, report CSS fixtures, and
  storage readback tests.
- CSS2: optional style-block extraction from HTML observations if the HTML
  source model can identify style blocks safely.
- CSS3: conservative selector-to-HTML matching for local fixtures only, after a
  separate ADR or phase note defines matching semantics and false-positive
  limits.

## Rejected Alternatives

### Full Browser Cascade Or Layout Engine

Rejected. RepoMap is a static graph builder. Cascade application, computed
style, layout, and rendering require browser semantics and are outside the
repository graph boundary.

### Fetch `@import` Or `url(...)` Targets

Rejected. Fetching introduces network dependency, nondeterminism, privacy risk,
and surprising host behavior. CSS references can be represented without
retrieving them.

### Treat Selector Matches As Facts In CSS1

Rejected for CSS1. Selector matching needs careful semantics around classes,
ids, generated markup, media queries, pseudo-classes, and browser behavior.
CSS1 should first make CSS facts queryable; a later phase can add conservative
matching with tests.

### Store All Declaration Values As Canonical Nodes

Rejected. Most declaration values are settings, colors, sizes, or volatile
styling details, not durable entities. They belong in evidence or summarized
metadata when safe.

### Add JavaScript Extraction In CSS0

Rejected. JavaScript extraction has different safety and graph-model questions.
CSS0 is only the static CSS model.

### Change Report Visuals In CSS0

Rejected. RPT1 already refreshed the report visual system. CSS0 only defines how
RepoMap should model CSS in the graph before implementation.

### Add Third-Party Parser Dependencies By Default

Rejected for the first implementation. CSS1 should start with a conservative
stdlib parser/scanner unless a later implementation phase explicitly approves a
dependency and adds supply-chain and behavior tests.
