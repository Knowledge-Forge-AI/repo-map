# ADR 0013: CSS HTML Selector Matching

## Status

Accepted

## Date

2026-06-30

## Context

CSS1 made static CSS documents, rules, selectors, custom properties, and
stylesheet references queryable. It intentionally did not claim that a CSS
selector matches any HTML element.

HTML1 made local static HTML documents, elements, anchors, links, assets, and
forms queryable. It intentionally did not render pages, execute JavaScript,
fetch URLs, parse CSS deeply, or compute browser behavior.

CSS2 defines the deliberately limited bridge between these two fact sets for
local report pages and web-fixture analysis. The goal is source-level selector
matching, not a browser cascade, layout engine, CSSOM, JavaScript runtime, or
visual appearance model.

The immediate motivating fixtures are generated test reports and report-like
static pages that use classes such as `report-header`, `status-badge`,
`tree-grid`, `path-cell`, `metric-cell`, `status-cell`, and `row`.

## Decision

RepoMap accepts a new canonical edge kind for conservative static selector
matching:

```text
css.selector:* --styles--> html.element:* | html.anchor:*
```

The `styles` edge means that, based only on local static source facts, a CSS
selector syntactically matches an HTML element or stable anchor under the
matching rules in this ADR.

The `styles` edge does not mean:

- the CSS rule applies at runtime;
- the selector wins the cascade;
- the element has the computed style;
- media or supports conditions are true;
- pseudo-class runtime state is active;
- JavaScript did not later mutate the DOM;
- browser defaults or inheritance were considered;
- layout or rendering occurred; or
- the page visually appears a certain way.

CSS2 is an ADR-only phase. The code registry, storage edge-kind constraints,
extractors, canonicalizer, CLI, MCP, and report visuals remain unchanged until
a later implementation phase, expected to be CSS3.

## Scope

In scope:

- defining `css.selector_match` raw observations;
- defining the `styles` edge kind semantics;
- defining which CSS and HTML files are eligible for matching;
- defining the first supported selector subset;
- defining skipped and unsupported selector behavior;
- defining canonicalization and metadata policy for future implementation;
- defining report fixture requirements; and
- defining CSS3 implementation tests.

Out of scope:

- implementing matching code;
- changing extractors;
- changing canonicalization code;
- changing storage schema or migrations;
- changing CLI public readback defaults;
- changing MCP behavior;
- changing report visuals;
- JavaScript extraction;
- URL fetching;
- HTML rendering;
- JavaScript execution;
- CSS cascade, specificity effects, inheritance, computed style, layout, media
  query truth, supports query truth, pseudo-class runtime state, browser
  defaults, CSSOM emulation, or visual appearance inference.

## Raw Observation Kind

CSS3 should introduce `css.selector_match`.

Required fields:

- `kind`: `css.selector_match`;
- `path`: repository-relative CSS file path;
- `name`: source `css.selector:*` key when known, otherwise the selector
  pointer;
- `target`: matched `html.element:*` or `html.anchor:*` canonical key;
- `source_id`: stable extractor-local id including CSS file, selector pointer,
  HTML file, and HTML pointer or anchor;
- `confidence`;
- `extractor`;
- `extractor_version`; and
- `metadata`.

`path` uses the CSS file because the observation is primarily evidence that a
selector selected a target. The matched HTML file is required metadata.

Required metadata:

- `selector_key`;
- `selector_text`;
- `html_key`;
- `html_pointer`;
- `match_kind`: `class`, `id`, `element`, `compound`, or
  `limited-descendant`;
- `matched_components`;
- `css_file`;
- `html_file`;
- `stylesheet_reference_source` when known;
- `scope`: `local-html-css`;
- `not_runtime_style`: `true`; and
- `limitations`.

Use `confidence="extracted"` for simple class, id, element, and supported
compound matches when all required CSS and HTML source facts are deterministic.
Use `confidence="heuristic"` for limited descendant matching or fixture-paired
matching where the pairing is explicit but not derived from an HTML stylesheet
link. Use `confidence="unknown"` only for diagnostic observations about
unsupported or ambiguous matching attempts.

## Candidate Source Relationship

RepoMap must not match arbitrary CSS files against arbitrary HTML files
repository-wide by default.

A CSS file is eligible to match an HTML file only when at least one conservative
source relationship exists:

- the HTML file references the CSS file through a static local
  `<link rel="stylesheet" href="...">`;
- the HTML file and CSS file are explicitly paired by a test fixture; or
- a generated report fixture explicitly pairs known source HTML with known
  source CSS.

Remote stylesheet links are never fetched. Remote CSS is not matched.

`@import` matching is deferred unless a later implementation proves a safe,
repo-local imported CSS file was already discovered and can be included without
network access. CSS3 may still defer `@import` matching.

When more than one eligible stylesheet exists, matching remains per stylesheet
and per HTML document. The canonical `styles` edge identity is still the
selector key, edge kind, target key, graph key version, and identity metadata,
not a database id.

## Supported Selector Subset

CSS3 should support only this initial selector subset:

- simple class selectors such as `.status-badge`;
- simple id selectors such as `#welcome`;
- simple element selectors such as `a`, `main`, and `section`;
- compound selectors with no combinator, such as `a.external`,
  `.status-badge.status-passed`, and `button[disabled]` if attribute support is
  implemented;
- grouped selectors, by evaluating each group member independently; and
- limited descendant selectors only when straightforward and tested, such as
  `.report-header .status-badge` and `main a`.

If descendant matching is not implemented in CSS3, descendant selectors must be
reported as unsupported or skipped rather than guessed.

CSS3 should not support:

- child, adjacent sibling, or general sibling combinators: `>`, `+`, `~`;
- complex `:not()`, `:has()`, `:is()`, or `:where()`;
- runtime pseudo-classes such as `:hover`, `:focus`, `:active`, or `:visited`;
- pseudo-elements as element matches;
- media-query truth evaluation;
- supports-query truth evaluation;
- shadow DOM;
- CSS nesting;
- browser-specific selector behavior; or
- selectors requiring a JavaScript-mutated DOM.

Pseudo-classes and pseudo-elements may remain selector metadata. They must not
create a positive match unless CSS3 explicitly documents a safe ignored case and
tests it.

## Matching Semantics

Static matching rules:

- A class selector matches when the HTML element class list contains that exact
  class.
- An id selector matches when the HTML element has that exact id and the id is
  unique in the document.
- An element selector matches when HTML tag names match case-insensitively.
- A supported compound selector matches when every supported component matches
  the same HTML element.
- A grouped selector is split into group members, and each member is evaluated
  independently.
- A limited descendant selector matches only when the descendant element and all
  tested ancestors can be identified from static HTML structure.
- An unsupported selector component causes that selector or group member to be
  skipped or emitted as unsupported. RepoMap must not fabricate a match.
- Duplicate HTML ids are ambiguous. They must not create `html.anchor:*`
  targets, and id selector matching should either fall back to structural
  `html.element:*` matches only when unambiguous or skip with a diagnostic.
- Attribute selectors are deferred unless CSS3 implements exact `[attr]` or
  `[attr=value]` matching against attributes already extracted by HTML1.

Selector matching uses parsed CSS selector metadata and parsed HTML element
metadata. It must not inspect runtime DOM state, rendered layout, fetched
assets, JavaScript results, browser defaults, or computed CSS.

## Canonicalization

When CSS3 implements this ADR, `css.selector_match` canonicalizes to:

```text
css.selector:* --styles--> html.element:*
css.selector:* --styles--> html.anchor:*
```

Edge metadata should include:

- `match_kind`;
- `matched_components`;
- `css_file`;
- `html_file`;
- `stylesheet_reference_source` when known;
- `scope`: `local-html-css`;
- `not_runtime_style`: `true`; and
- `limitations`.

Identity metadata should remain empty unless a later implementation needs it to
distinguish multiple semantically different matches between the same selector
and HTML target. Evidence records carry CSS and HTML locations, selector
pointers, HTML pointers, extractor details, line spans, and source ids.

No database integer id is public graph identity. Public readback should identify
these facts with canonical edge identity fields:

- `source_key`;
- `edge_kind=styles`;
- `target_key`;
- `graph_key_version`; and
- `identity_metadata_hash`.

## Report Fixture Policy

CSS3 must include report-oriented fixtures that pair one local HTML file with
one local CSS file.

The fixture should include:

- a static HTML file that references the stylesheet through a local
  `<link rel="stylesheet" href="...">`;
- report classes such as `report-header`, `status-badge`, `tree-grid`,
  `path-cell`, `metric-cell`, `status-cell`, and `row`;
- id and element selector examples;
- a grouped selector example;
- a compound selector example;
- an unsupported selector example;
- a remote stylesheet link that is not fetched or matched; and
- an unrelated CSS file in the same repository that is not matched because it
  is not eligible.

Tests must prove that only linked or explicitly paired local CSS files are
matched to the HTML file.

## Safety And Non-Goals

CSS selector matching is a static source-level fact only.

RepoMap must not:

- render HTML;
- execute JavaScript;
- execute CSS;
- fetch URLs;
- fetch remote stylesheets;
- apply the cascade;
- compute specificity effects;
- compute final or inherited styles;
- compute media-query or supports-query truth;
- compute layout;
- emulate browser defaults;
- claim visual appearance; or
- infer that a styled element is visible, hidden, clickable, interactive, or
  accessible at runtime.

## Required CSS3 Tests

CSS3 implementation must include unit, canonicalization, discovery, storage, and
readback coverage for:

- class selector match;
- id selector match;
- element selector match;
- compound selector match;
- grouped selectors evaluated independently;
- unsupported selectors skipped or reported without fabricated matches;
- runtime pseudo-class selectors skipped or limited exactly as documented;
- duplicate ids handled conservatively;
- linked CSS-to-HTML pairing;
- explicit fixture pairing;
- no repository-wide arbitrary matching;
- no matching for remote CSS links;
- no URL fetching;
- canonical `styles` edge readback;
- explain-canonical-edge for one selector match;
- evidence that includes both CSS selector context and HTML element context;
- table and JSON output that use canonical identity fields; and
- regression coverage showing CSS1 and HTML1 extraction behavior is unchanged.

## Rejected Alternatives

### Full Browser Selector Engine

Rejected. A full selector engine would imply browser-specific behavior,
runtime DOM state, pseudo-class truth, shadow DOM details, and more compatibility
surface than RepoMap needs for source graph analysis.

### Cascade Or Computed Style Facts

Rejected. Cascade order, specificity winners, inheritance, media-query truth,
supports-query truth, and computed styles are runtime or browser-model facts.
RepoMap should keep CSS2 to explainable source relationships.

### Match All CSS Against All HTML

Rejected. Repository-wide matching would create noisy false positives and imply
relationships that do not exist in the source. Matching requires a static local
stylesheet relationship or an explicit fixture pairing.

### Treat Runtime Pseudo-Class State As Static Fact

Rejected. `:hover`, `:focus`, `:active`, `:visited`, and similar selectors
depend on runtime user agent state. They may remain metadata but must not create
positive source matches in CSS3.

### Execute JavaScript To Build The DOM

Rejected. JavaScript execution is outside the RepoMap static graph boundary and
would undermine deterministic, safe extraction.

### Fetch Remote Stylesheets

Rejected. CSS2 and CSS3 are local static analysis phases. Remote links may be
represented as `external.url:*` references, but no network fetch is allowed.

### Infer Visual Appearance

Rejected. A `styles` edge means a source-level selector match only. It does not
mean a report looks a certain way, an element is visible, or a CSS declaration
is active.

## Proposed Next Phase

CSS3 should implement conservative local selector matching according to this
ADR.

CSS3 must:

- update the registered edge vocabulary and storage edge-kind constraints for
  `styles`;
- add `css.selector_match` extraction;
- canonicalize accepted matches into `styles` edges;
- include report-oriented fixtures;
- prove no arbitrary repository-wide matching occurs; and
- preserve CSS1, HTML1, CLI, MCP, and public readback compatibility except for
  any explicitly added canonical `styles` facts.
