# ADR 0027: JS/TS Framework Source Extraction

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0021: Static JavaScript Graph Model
- ADR 0026: Terraform, JSON, And Ecosystem Configuration Graph Model
- `docs/adr/2026/07/0021-static-javascript-graph-model.md`
- `docs/adr/2026/07/0026-terraform-json-ecosystem-config-graph-model.md`
- `docs/status/2026/07/01/00042-js1-static-javascript-extractor-exit.md`
- `docs/status/2026/07/01/00043-js2-profile-readback-polish-exit.md`
- `docs/status/2026/07/01/00044-js3-static-asset-integration-exit.md`
- `docs/status/2026/07/01/00054-tfjson1-terraform-json-ecosystem-config-exit.md`

## Context

RepoMap already extracts local JavaScript and TypeScript source facts through
the static JS model accepted by ADR 0021 and implemented across JS1, JS2, and
JS3. That model recognizes generic JavaScript-family structure, profiles,
tests, components, routes, references, saved-page/report/static JavaScript
assets, and source-map references without executing JavaScript or invoking the
JavaScript ecosystem.

TFJSON1 now adds package and configuration profile evidence for common
JavaScript and TypeScript projects. It can statically observe facts such as
`package.json` dependencies, scripts, package entrypoint fields, TypeScript
config references, Angular/Nest/Jest/Playwright JSON config, and ecosystem
framework hints. Those config facts are useful context for later JS/TS source
extraction, but they do not prove runtime behavior by themselves.

The next useful architecture increment is to define how RepoMap should improve
static JS/TS framework source extraction for npm/package-informed projects,
Node.js, Express, NestJS, Next.js, Jest, and jQuery before implementation.

JS4 defines that model only. It does not implement extraction, change current
JS behavior, add commands, add fixtures, add tests, add migrations, add MCP
tools, run any tool, read `node_modules`, fetch any package or URL, or change
public readback defaults.

## Decision

RepoMap will continue to model JavaScript and TypeScript framework source as
static local source analysis. Future framework extraction may combine:

- local JS/TS/JSX/TSX source text;
- existing generic `js.*` observations;
- TFJSON1 package and config profile evidence; and
- local artifact provenance from JS3.

The extraction pipeline remains:

```text
local JS/TS source file
-> safe static scanner or accepted parser
-> generic js.* observations
-> optional framework-profile raw observations
-> existing canonical js.* facts where already accepted
-> load through existing storage path
-> expose through existing readback or later read-only summaries
```

Framework extraction must stay valid and deterministic even when package or
config profile facts are absent. Package/config evidence can improve profile
confidence, explainability, and scope selection, but future implementation must
not infer runtime truth from dependency names or scripts alone.

The initial posture remains raw/profile-observation first. Existing generic
`js.*` canonical nodes remain the main public graph for JavaScript-family
source. JS4 defers broad framework canonical namespaces until implementation
evidence proves that stable identity is useful and consistent with ADR 0001,
ADR 0002, and ADR 0003.

## Scope

In scope:

- JS and TS framework source extraction architecture;
- `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts`, and `.tsx` source
  families;
- npm/package-informed project context;
- Node.js source model;
- Express source model;
- NestJS source model;
- Next.js source model;
- Jest source model;
- jQuery source and static-artifact relationship model;
- how JS/TS source extraction may use TFJSON1 package/config profile hints;
- static-only route, controller, test, event, selector, and AJAX reference
  boundaries;
- framework raw observation names;
- possible future canonical namespaces;
- relationship to the existing generic `js.*` raw and canonical model;
- relationship to saved-page/report/static artifact extraction for jQuery;
- redaction and privacy requirements;
- future implementation phases; and
- future test requirements.

Out of scope:

- implementing JS/TS framework extraction;
- changing JS extractor behavior;
- adding CLI commands;
- adding fixtures or tests;
- adding storage migrations;
- adding MCP tools;
- running Node;
- running npm, yarn, pnpm, bun, or npx;
- installing packages;
- running Express, NestJS, Next.js, Jest, Playwright, or browser tooling;
- running browser automation;
- rendering HTML;
- executing JavaScript or TypeScript;
- bundling or transpiling;
- type-checking with TypeScript;
- loading framework plugins;
- reading `node_modules`;
- fetching npm metadata;
- fetching source maps;
- fetching remote assets;
- provider/API acquisition;
- public readback default changes; and
- Phase F migration.

## Product Posture

JS4 is not "run the app." JS4 is "statically map framework intent and likely
application structure from local JS/TS source plus already-extracted
config/package evidence."

Requirements for future implementation:

- local source files only;
- no JavaScript or TypeScript execution;
- no Node, npm, yarn, pnpm, bun, npx, `tsc`, Vite, Webpack, Babel, Jest,
  Next.js, NestJS, Angular, Vue, Playwright, or browser tooling invocation;
- no package installation;
- no `node_modules` inspection;
- no dynamic module resolution;
- no config file execution;
- no server startup;
- no test execution;
- no browser launch;
- no DOM rendering, hydration, or runtime simulation;
- no network URL following;
- no source-map fetching;
- no package registry fetching;
- no dependency-name-only runtime claims; and
- no broad framework canonical namespaces without implementation evidence.

## Relationship To TFJSON1

TFJSON1 provides package and configuration profile evidence such as:

- package dependencies;
- package scripts;
- package entrypoint fields;
- package manager and engine metadata;
- TypeScript and JavaScript config;
- Angular, React, Vue, Node, Express, NestJS, Next.js, Jest, jQuery, and
  Playwright hints; and
- local config references.

Future JS framework extraction may use those facts as context. Examples:

- a `package.json` dependency on `express` can increase confidence that
  static `express()` or `Router()` calls belong to the Express profile;
- a `package.json` dependency on `@nestjs/core` can increase confidence that
  NestJS decorators should be interpreted as Nest profile facts;
- a `package.json` dependency on `next` can increase confidence that `pages/`
  and `app/` conventions are Next.js route conventions;
- a Jest config or dependency can improve test profile confidence; and
- a jQuery dependency or script reference can improve selector/event profile
  confidence.

TFJSON1 evidence is not required for source extraction. A source file that
statically contains recognizable Express, NestJS, Next.js, Jest, or jQuery
patterns may still emit framework-profile raw observations. Conversely,
package/config evidence alone must not fabricate routes, controllers, tests,
events, selectors, AJAX calls, or runtime entrypoints.

## Supported Source File Families

Future JS framework implementation may inspect:

- `.js`;
- `.mjs`;
- `.cjs`;
- `.jsx`;
- `.ts`;
- `.mts`;
- `.cts`; and
- `.tsx`.

`.vue` single-file component extraction remains deferred. Angular template
parsing remains deferred. Source-map reconstruction remains deferred.

## Existing JS Model

JS4 preserves the JS1 raw observation model, including:

- `js.file`;
- `js.module`;
- `js.import`;
- `js.export`;
- `js.function`;
- `js.class`;
- `js.method`;
- `js.variable`;
- `js.constant`;
- `js.component`;
- `js.hook`;
- `js.route`;
- `js.test_suite`;
- `js.test_case`;
- `js.test_expectation`;
- `js.reference`;
- `js.parse_error`;
- TypeScript-oriented raw observations such as `js.type_alias`,
  `js.interface`, and `js.enum`.

Existing generic JS canonical namespaces remain the main public graph where
already implemented:

- `js.file`;
- `js.module`;
- `js.function`;
- `js.class`;
- `js.method`;
- `js.variable`;
- `js.component`;
- `js.test_suite`;
- `js.test_case`; and
- `js.route`.

Framework-specific observations should be additional raw/profile facts, not a
replacement for generic JS facts.

## Raw Observation Model

Future JS framework phases may add generic framework raw observations:

- `js.framework_profile`;
- `js.runtime_profile`;
- `js.package_context`;
- `js.route_handler`;
- `js.middleware`;
- `js.controller`;
- `js.provider`;
- `js.module_binding`;
- `js.test_config`;
- `js.dom_selector`;
- `js.dom_event`;
- `js.ajax_reference`;
- `js.server_entrypoint`;
- `js.client_entrypoint`; and
- `js.framework_reference`.

Possible profile-specific raw observations include:

- `node.entrypoint`;
- `node.export`;
- `node.require`;
- `express.app`;
- `express.router`;
- `express.route`;
- `express.middleware`;
- `express.error_handler`;
- `nest.module`;
- `nest.controller`;
- `nest.provider`;
- `nest.route`;
- `nest.decorator`;
- `next.route`;
- `next.page`;
- `next.api_route`;
- `next.app_route`;
- `next.component`;
- `jest.suite`;
- `jest.test`;
- `jest.expectation`;
- `jquery.selector`;
- `jquery.event`;
- `jquery.ajax`; and
- `jquery.plugin_reference`.

These observations should start as raw/provenance-first facts. Future
implementation should prefer fewer well-tested observations over broad shallow
noise.

## Canonical Graph Policy

JS4 does not accept broad new framework canonical namespaces.

Possible future canonical namespaces, only if implementation evidence and
identity review later support them, include:

- `express.route`;
- `nest.controller`;
- `nest.provider`;
- `nest.module`;
- `next.route`;
- `next.page`;
- `jest.test`; and
- `jquery.selector`.

These namespaces are not accepted by JS4. A later implementation phase or ADR
must define identity, key grammar, collision behavior, evidence links,
redaction, and readback semantics before they become public canonical graph
vocabulary.

Existing generic `js.*` canonical nodes may continue to represent framework
facts when the generic identity is already accepted. For example, a literal
Express route may still be represented as a generic `js.route:*` fact, with
Express profile metadata, until a later phase accepts `express.route:*`.

## Edge Vocabulary

JS4 adds no new edge kinds.

Future framework extraction must use existing edge kinds:

- `defines`;
- `references`.

If framework relationships later need richer vocabulary, such as route mounts,
controller ownership, provider injection, or test coverage relationships, that
requires a later ADR or explicit implementation review.

## Package-Informed Source Context

Future implementation may build a safe package context from already-extracted
TFJSON1 facts and local source observations. Package context may include:

- package name and workspace hints;
- package type and module-system hints;
- main/module/browser/types/exports/imports fields;
- scripts as non-executed labels or summaries;
- dependency names as profile evidence;
- TypeScript config references; and
- local framework config profile hints.

Package context must not:

- execute scripts;
- install dependencies;
- fetch package metadata;
- inspect `node_modules`;
- resolve package export maps dynamically;
- run TypeScript or bundler resolution;
- treat dependencies as proof of runtime behavior; or
- fabricate source facts that are absent from local source text.

## Node.js Extraction Model

Future Node.js extraction may statically recognize:

- CommonJS `require("literal")`;
- ESM imports, exports, and re-exports;
- package entrypoints from TFJSON1 context;
- obvious server entrypoint files and source-level entrypoint exports;
- `module.exports` and `exports.*`;
- `process.env.NAME` and `import.meta.env.NAME` as redacted environment
  references;
- local file references from literal `require` or import specifiers; and
- Node built-in module references.

Future Node raw observations may include `node.entrypoint`, `node.export`, and
`node.require`, but generic `js.import`, `js.export`, and `js.reference` facts
remain the base model.

Future implementation must not:

- resolve modules dynamically;
- inspect `node_modules`;
- execute files;
- evaluate environment variables;
- infer runtime behavior from package scripts alone; or
- claim a complete runtime dependency graph.

## Express Extraction Model

Future Express extraction may statically recognize:

- `express()`;
- `express.Router()`;
- `app.get`, `app.post`, `app.put`, `app.patch`, `app.delete`, `app.options`,
  `app.head`, `app.all`, and `app.use`;
- `router.get`, `router.post`, `router.put`, `router.patch`,
  `router.delete`, `router.options`, `router.head`, `router.all`, and
  `router.use`;
- route path literals;
- middleware chains when statically visible;
- handler function names or local references;
- mounted routers via literal `app.use("/base", router)` patterns; and
- error-handler-shaped middleware when obvious.

Supported method labels for future static route facts:

- `GET`;
- `POST`;
- `PUT`;
- `PATCH`;
- `DELETE`;
- `OPTIONS`;
- `HEAD`;
- `ALL`; and
- `USE`.

Express extraction must not:

- evaluate dynamic route expressions;
- execute route registration;
- resolve imported routers beyond conservative local references unless a later
  implementation explicitly accepts and tests that behavior;
- claim a complete runtime route table;
- infer middleware order beyond what is statically present in one file or an
  accepted local reference boundary; or
- boot an Express application.

## NestJS Extraction Model

Future NestJS extraction may statically recognize decorators:

- `@Module`;
- `@Controller`;
- `@Injectable`;
- `@Get`;
- `@Post`;
- `@Put`;
- `@Patch`;
- `@Delete`;
- `@All`;
- `@Param`;
- `@Body`;
- `@Query`;
- `@UseGuards`;
- `@UseInterceptors`; and
- `@UsePipes`.

Future extraction may record:

- module classes;
- controller classes;
- provider classes;
- imported module references;
- controller route prefix literals;
- method route literals;
- HTTP method labels; and
- provider tokens only when statically safe.

NestJS extraction must not:

- execute decorators;
- invoke the TypeScript compiler runtime;
- resolve dependency injection dynamically;
- instantiate modules, controllers, providers, guards, pipes, or interceptors;
- inspect runtime metadata emitted by decorators; or
- claim runtime provider graph truth.

## Next.js Extraction Model

Future Next.js extraction may statically recognize file conventions and source
patterns for both Pages Router and App Router.

Pages Router conventions may include:

- `pages/*.js`;
- `pages/*.jsx`;
- `pages/*.ts`;
- `pages/*.tsx`;
- `pages/api/*.js`; and
- `pages/api/*.ts`.

App Router conventions may include:

- `app/**/page.*`;
- `app/**/layout.*`;
- `app/**/route.*`;
- `app/**/loading.*`; and
- `app/**/error.*`.

Future extraction may record:

- route patterns derived from file paths;
- dynamic route segment filenames as static route patterns;
- route handlers exporting `GET`, `POST`, `PUT`, `PATCH`, `DELETE`,
  `OPTIONS`, or `HEAD` in `route.*`;
- metadata exports as raw profile hints;
- `next/link`, `next/router`, and `next/navigation` references; and
- generic component facts through existing JS/TS extraction.

Next.js extraction must not:

- run Next.js;
- evaluate Next config;
- bundle;
- render React;
- inspect generated `.next` output;
- fetch remote data;
- apply runtime routing rewrites;
- evaluate middleware; or
- claim a complete runtime route table.

## Jest Extraction Model

Existing JS extraction already captures generic test suites, cases, and
expectations. JS4 accepts improving Jest-specific recognition while preserving
the no-execution model.

Future Jest extraction may statically recognize:

- `describe`;
- `it`;
- `test`;
- `expect`;
- `beforeEach`;
- `afterEach`;
- `beforeAll`;
- `afterAll`;
- `jest.mock`;
- `jest.fn`;
- `jest.spyOn`; and
- matcher names such as `.toBe` and `.toEqual` as bounded metadata.

Future implementation may emit `jest.suite`, `jest.test`, and
`jest.expectation` raw observations, while existing generic `js.test_suite`,
`js.test_case`, and `js.test_expectation` remain the public base model.

Jest extraction must not:

- run tests;
- import test files;
- execute mocks;
- resolve the Jest environment;
- generate or update snapshots;
- start jsdom; or
- infer test outcomes.

## jQuery Extraction Model

jQuery is relevant to both JS/TS source extraction and saved-page/report/static
artifact extraction.

For JS/TS source, future extraction may statically recognize:

- `$()`;
- `jQuery()`;
- selector string literals;
- `.on(...)`;
- `.click(...)`;
- `.submit(...)`;
- `.change(...)`;
- `.ready(...)`;
- `$(document).ready(...)`;
- `$.ajax`;
- `$.get`;
- `$.post`;
- `.load`; and
- plugin-style `$.fn.<name>` definitions.

Potential source observations include:

- `jquery.selector`;
- `jquery.event`;
- `jquery.ajax`; and
- `jquery.plugin_reference`.

For saved-page, report, document, or static artifact extraction, future
behavior may use:

- HTML script references to jQuery as profile evidence;
- inert local JavaScript assets routed by JS3;
- inline script markers only if already safely extracted as text;
- selector/event patterns only when static and non-executing; and
- conservative links between HTML elements and selectors only when static
  matching is accepted by a later phase.

jQuery extraction must not:

- execute scripts;
- render the DOM;
- fetch remote jQuery;
- fetch AJAX URLs;
- infer dynamic selector effects;
- simulate event dispatch; or
- claim complete runtime behavior.

## Angular, React, And Vue Boundary

Angular, React, and Vue remain important JavaScript ecosystem targets, but JS4
does not become a full Angular, React, or Vue source extraction phase.

For this roadmap:

- React support may appear indirectly through existing JSX, component, hook,
  and Next.js source facts;
- Angular source extraction is deferred unless a later Angular-specific phase
  accepts decorator and template handling;
- Vue single-file component extraction is deferred; and
- Angular, React, and Vue package/config hints remain TFJSON/YAML/JS static
  profile facts.

Future framework phases must avoid using JS4 as blanket approval for Angular
template compilation, Vue SFC compilation, React rendering, DOM hydration, or
runtime framework execution.

## First-Class Tooling Boundary

The user's first-class cross-language/config/tooling stack includes:

- Liquibase;
- Docker;
- Kubernetes;
- Playwright;
- GitHub Actions;
- Argo CD;
- Terraform;
- OpenAPI;
- Prometheus;
- Grafana;
- Grafana Loki; and
- Vault.

JS4 does not implement these tools. Future config and source increments should
consider them when relevant, but keep their boundaries explicit.

For JS4 specifically:

- Playwright may be relevant as JS/TS source, config, or test-adjacent evidence,
  but it must not be executed;
- OpenAPI may later connect generated client/server code and route metadata,
  but OpenAPI JSON/YAML extraction is deferred; and
- Docker, Kubernetes, Argo CD, GitHub Actions, Terraform, Liquibase,
  Prometheus, Grafana, Loki, and Vault remain config or infrastructure phases,
  not JS4 implementation scope.

## Redaction And Privacy

Future JS/TS framework extraction must redact, omit, or summarize sensitive
values. Sensitive examples include:

- environment variable names when the name itself is sensitive;
- all `process.env` or `import.meta.env` values;
- secret-like object keys;
- hardcoded tokens, secrets, passwords, and API keys;
- URLs with embedded credentials;
- auth headers;
- cookies;
- database URLs;
- private keys;
- JWT-looking values; and
- provider or service credentials.

Secret-like literals must never be placed in:

- raw observations;
- canonical keys;
- canonical metadata;
- edge metadata;
- readback;
- explain output;
- fixtures;
- status documents; or
- ADR examples.

Safe metadata may include value type, presence, length, hash, redaction reason,
environment variable name when not itself sensitive, route path literal when
not credential-bearing, selector literal when not sensitive, and bounded
matcher or method names.

## Reference Policy

Future JS framework extraction may record references without fetching:

- local import or require paths;
- package names;
- framework package references;
- route path literals;
- static AJAX URL summaries if safe;
- static selector strings;
- local file references;
- local config references; and
- source-map references with `not_fetched=true`.

Future JS framework extraction must not fetch:

- packages;
- source maps;
- remote scripts;
- AJAX URLs;
- API endpoints;
- generated bundles;
- HTML pages; or
- framework-generated files.

Dynamic, interpolated, computed, or runtime-derived references should remain
raw metadata, dynamic placeholders, unknown placeholders, or diagnostics.

## Future JS5 Test Requirements

Future JS5 implementation tests should cover:

- package/context hints are optional and do not fabricate source facts;
- Express app route literals;
- Express router route literals;
- Express mounted router base paths;
- Express middleware chains;
- Express dynamic route diagnostics;
- NestJS module, controller, and provider decorators;
- NestJS controller method route decorators;
- Next.js Pages Router file routes;
- Next.js App Router page, layout, and route files;
- Next.js route handler HTTP method exports;
- Jest suites, tests, expectations, mocks, and spies;
- jQuery selectors, events, AJAX references, and plugin definitions in source;
- jQuery static artifact hints from saved-page/report HTML where safe;
- Node CommonJS and ESM entrypoints;
- `process.env` and `import.meta.env` redaction;
- secret-like literal redaction;
- no JavaScript or TypeScript execution;
- no package install;
- no `node_modules` inspection;
- no network fetch;
- no source-map fetch;
- no CLI or framework tool invocation; and
- no broad canonical framework namespaces unless a later phase explicitly
  accepts them.

## Rejected Alternatives

Rejected:

- executing JS/TS;
- running Node;
- running framework CLIs;
- requiring TypeScript compiler semantic analysis as the first implementation
  dependency;
- installing npm packages;
- resolving dependencies through `node_modules`;
- bundling or transpiling;
- rendering React, Next.js, Vue, or Angular;
- running Jest;
- running Playwright;
- browser automation;
- DOM hydration;
- source-map fetching;
- package registry fetching;
- accepting broad canonical framework namespaces in JS4;
- treating package dependencies as runtime proof; and
- mixing JS4 with Terraform, OpenAPI, or YAML infrastructure implementation.

## Proposed Phases

Possible future phases:

- JS5: static JS/TS framework source extraction implementation for Express,
  NestJS, Next.js, Jest, jQuery, and Node profile improvements;
- JS6: JS/TS framework readback summary polish;
- ANGULAR0/ANGULAR1: Angular source and template architecture/implementation if
  Angular source extraction becomes important;
- VUE0/VUE1: Vue single-file component architecture/implementation if Vue SFC
  extraction becomes important;
- OPENAPI0/OPENAPI1: OpenAPI JSON/YAML extraction;
- YAML-INFRA0/YAML-INFRA1: Kubernetes, GitHub Actions, Argo CD, Prometheus,
  Grafana, Loki, Vault, and related YAML-heavy tools; and
- DOCKER0/DOCKER1: Dockerfile and Compose support if not covered elsewhere.

## Consequences

JS4 gives future JS framework implementation a narrow, reviewable target:

- source extraction can improve framework-aware facts without executing apps;
- TFJSON1 package/config hints become context, not runtime truth;
- existing generic `js.*` canonical facts remain the stable public base;
- framework raw observations can be added incrementally and tested in isolation;
- broad framework canonical namespaces remain deferred; and
- jQuery can bridge JS source and static artifact extraction without DOM
  execution.

## Acceptance

JS4 is accepted because it is internally consistent, static-only,
non-executing, no-fetch, redaction-aware, explicit about JS and TS source
coverage, and clearly separates:

- JS/TS framework source extraction;
- saved-page/report/static jQuery extraction;
- TFJSON/package/config profile evidence;
- future OpenAPI/config/infrastructure phases; and
- future implementation phases from this architecture-only ADR.
