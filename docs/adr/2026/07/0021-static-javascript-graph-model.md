# ADR 0021: Static JavaScript Graph Model

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap can now graph local code, configuration, documents, saved artifacts,
archives, and WARC payloads without executing them. JavaScript is the next
useful language-family target because it connects several existing graph
surfaces:

- source-code graphing;
- frontend and framework source awareness;
- saved-page and static artifact extraction;
- generated report extraction;
- HTML and CSS integration;
- WARC payload routing; and
- Jest test discovery.

High-value JavaScript-family inputs include:

- vanilla JavaScript;
- TypeScript;
- JSX;
- TSX;
- Jest tests;
- React source files;
- Angular source files;
- Vue-related JavaScript and TypeScript files;
- JavaScript assets from saved pages;
- JavaScript assets from generated documents and reports; and
- JavaScript references from HTML, CSS, ARCHIVE, and WARC contexts.

JavaScript is executable, dynamic, bundler-driven, framework-heavy, and often
browser or runtime dependent. JS0 defines a static graph model that extracts
useful syntax and framework cues without running JavaScript, invoking Node,
installing dependencies, bundling, hydrating, rendering, executing tests, or
fetching modules or source maps.

## Decision

RepoMap will model JavaScript-family files as static local source analysis.

The future JavaScript pipeline is:

```text
local JS/TS/JSX/TSX file or archived JS asset
-> safe static parse or lexical scan
-> raw JavaScript observations
-> canonicalize observations
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

JavaScript extraction is source analysis, not JavaScript execution. Future JS1
must not run JavaScript, invoke Node, run package managers, install
dependencies, bundle, transpile, invoke framework tooling, execute tests,
render browser content, resolve runtime imports, or fetch references.

JS0 accepts generic `js.*` graph identity for files, modules, imports, exports,
functions, classes, methods, variables, components, tests, routes, and
conservative references if JS1 proves them useful. JS0 explicitly defers
framework-specific namespaces such as `jest.*`, `react.*`, `angular.*`,
`vue.*`, `node.*`, `npm.*`, `webpack.*`, and `vite.*`.

Profile hints are metadata only. Jest, React, Angular, Vue, saved-page assets,
and report assets should be readable through generic JavaScript observations
before any framework-specific model is considered.

## Scope

In scope:

- static JavaScript-family graph model design;
- supported file and profile policy for JS1;
- safe parser or scanner policy;
- raw JavaScript observation vocabulary;
- generic JavaScript canonical namespace policy;
- canonical edge policy using existing edge kinds only;
- conservative reference detection;
- generic JavaScript and TypeScript structure extraction goals;
- Jest, React, Angular, Vue, saved-page, report, and frontend-asset profile
  hints;
- minified and bundled JavaScript policy;
- redaction policy;
- dynamic JavaScript policy;
- fixture and test requirements for JS1; and
- future phase planning.

Out of scope:

- implementing JavaScript parsing;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding MCP tools;
- adding storage migrations;
- changing HTML, CSS, ARCHIVE, WARC, DOCS, YAML, RUBY, storage, or public
  readback behavior; and
- Phase F migration.

## Product Posture

JavaScript graphing must remain static, local, deterministic, and
non-executing.

Requirements:

- local files only;
- no JavaScript execution;
- no Node execution;
- no npm, yarn, pnpm, bun, or npx execution;
- no package installation;
- no bundling;
- no transpilation;
- no TypeScript compiler invocation;
- no Babel invocation;
- no Vite, Webpack, Rollup, Parcel, esbuild, or SWC invocation;
- no Jest execution;
- no Angular CLI;
- no Vue CLI;
- no React application boot;
- no browser automation;
- no DOM execution;
- no hydration;
- no rendering;
- no service worker execution;
- no source-map fetching;
- no remote module fetching;
- no runtime import resolution;
- no dependency graph resolution beyond static references; and
- no MCP write, import, run, or source-creation tools.

## Supported Files

Future JS1 should route:

- `.js`
- `.mjs`
- `.cjs`
- `.jsx`
- `.ts`
- `.mts`
- `.cts`
- `.tsx`

Optional future config and file hints:

- `package.json` remains governed by structured config extraction. JavaScript
  phases may later read stored config facts for readback, but JS1 should not
  add npm-specific namespaces.
- `tsconfig.json` remains governed by structured config extraction.
- `jest.config.js` and `jest.config.ts` are executable configuration files and
  should be treated as static JavaScript or TypeScript source, not executed.
- `vite.config.*`, `webpack.config.*`, `rollup.config.*`, `babel.config.*`,
  `next.config.*`, `nuxt.config.*`, `angular.json`, and `vue.config.*` are
  future profile hints only. They must not trigger tool execution, bundler
  resolution, framework boot, or dependency loading.

Future profile hints:

- `generic_javascript`
- `generic_typescript`
- `jest`
- `react`
- `angular`
- `vue`
- `node_config`
- `frontend_asset`
- `saved_page_asset`
- `test_report_asset`

Profile hints are metadata only. They must not create framework-specific
canonical namespaces in JS1.

## Parser Policy

JS1 should prefer a small safe parser already accepted by the project if one
exists. If no suitable parser exists, JS1 may begin with a conservative lexical
and shallow structural scanner. If adding a parser dependency becomes
necessary, JS1 must justify the dependency and document safe parser
configuration in its exit audit.

Parser or scanner requirements:

- parse local bytes only;
- do not execute JavaScript;
- do not invoke Node;
- do not invoke npm, npx, yarn, pnpm, or bun;
- do not invoke TypeScript, Babel, esbuild, SWC, or framework compilers;
- do not evaluate imports;
- do not resolve `node_modules`;
- do not fetch remote modules;
- do not fetch source maps;
- do not execute custom loaders or plugins;
- enforce maximum file bytes;
- enforce maximum token or node count;
- enforce maximum nesting depth;
- preserve parse diagnostics; and
- gracefully degrade to lexical observations when syntax is unsupported.

Syntax that cannot be parsed safely should emit `js.parse_error` or a
diagnostic observation and may still allow conservative lexical facts, such as
literal imports, when those facts are unambiguous.

## Supported Syntax Goals

JS1 should detect these facts statically and conservatively:

- file or module observations;
- ES module imports;
- ES module exports and re-exports;
- CommonJS `require("literal")`;
- `module.exports` and `exports.foo`;
- dynamic `import(...)` as dynamic/reference metadata, not runtime resolution;
- function declarations;
- arrow functions assigned to stable names;
- class declarations;
- simple class methods;
- variables and constants with safe literal type summaries;
- object literal route or config hints when profile-specific and static;
- JSX/TSX component-looking declarations where static;
- TypeScript interfaces, type aliases, and enums if easy and useful; and
- dynamic constructs as diagnostics or metadata.

JS1 must not attempt:

- full type inference;
- runtime module resolution;
- bundler alias resolution unless a later ADR accepts it;
- tree shaking;
- control-flow graph construction;
- dataflow analysis;
- call graph construction;
- code execution;
- JSX rendering;
- React hook execution;
- Angular template compilation;
- Vue single-file component compilation;
- Jest test execution;
- Node environment resolution;
- minified code recovery beyond basic lexical facts; or
- source map application.

## Raw Observations

Future JavaScript raw observations may include:

- `js.file`
- `js.module`
- `js.import`
- `js.export`
- `js.function`
- `js.class`
- `js.method`
- `js.variable`
- `js.constant`
- `js.call`
- `js.component`
- `js.hook`
- `js.route`
- `js.test_suite`
- `js.test_case`
- `js.test_expectation`
- `js.reference`
- `js.parse_error`

TypeScript-specific raw observations may be added if useful:

- `js.type_alias`
- `js.interface`
- `js.enum`

JS1 should keep the implementation small:

- generic module, import, export, function, class, and component observations
  first;
- profile-specific observations only when cheap, static, and deterministic;
- framework observations raw/evidence-first before new canonical namespaces are
  accepted; and
- dynamic or ambiguous constructs as diagnostics or safe metadata, not guessed
  graph edges.

Suggested safe metadata fields:

- `format`: `javascript`, `typescript`, `jsx`, or `tsx`;
- `profile`;
- `parser`;
- `module_system`;
- `export_kind`;
- `import_kind`;
- `import_specifier`;
- `local_name`;
- `exported_name`;
- `qualified_name`;
- `function_name`;
- `class_name`;
- `method_name`;
- `component_name`;
- `test_framework`;
- `route_method`;
- `route_pattern`;
- `dynamic`;
- `dynamic_reason`;
- `redacted`;
- `redaction_reason`; and
- `identity_strength`.

## Canonical Namespaces

JS0 accepts conservative generic JavaScript namespaces for future JS1 if tests
prove them useful:

- `js.file:<encoded-file-key>`
- `js.module:<encoded-file-key>`
- `js.function:<encoded-file-key>:<encoded-function-pointer-or-name>`
- `js.class:<encoded-file-key>:<encoded-class-name>`
- `js.method:<encoded-class-key>:<encoded-method-name>`
- `js.variable:<encoded-file-key>:<encoded-variable-pointer-or-name>`
- `js.component:<encoded-file-key>:<encoded-component-name-or-pointer>`
- `js.test_suite:<encoded-file-key>:<encoded-suite-pointer>`
- `js.test_case:<encoded-test-suite-or-file-key>:<encoded-test-pointer>`
- `js.route:<encoded-file-key>:<encoded-route-pointer>`

`js.file:*` represents the JavaScript-family interpretation of a source file
or archived JavaScript asset. It does not replace `file:*` identity.

`js.component:*`, `js.test_suite:*`, `js.test_case:*`, and `js.route:*` are
generic JavaScript namespaces. They are not React, Angular, Vue, or Jest
namespaces. Their metadata may record the profile that made the fact
recognizable.

Deferred framework or tooling namespaces:

- `jest.*`
- `react.*`
- `angular.*`
- `vue.*`
- `node.*`
- `npm.*`
- `webpack.*`
- `vite.*`

JS0 does not add package-manager-specific namespaces. Package imports may use
generic external references or raw metadata until a later package model accepts
more specific identity.

## Canonical Key Rules

Canonical keys must not include:

- function bodies;
- JSX rendered output;
- arbitrary string literal values;
- secret literal values;
- runtime-evaluated values;
- current time;
- absolute machine paths;
- parser object IDs;
- extractor versions;
- line numbers;
- model-generated labels;
- bundler-resolved paths; or
- values produced by executing JavaScript.

JavaScript modules can re-export, shadow, and redefine names. The graph should:

- preserve evidence for multiple observations;
- record conflict or redefinition metadata where useful;
- avoid appending line numbers to identity unless the identity is explicitly
  weak and structural;
- avoid fabricating runtime override semantics; and
- avoid resolving export barrels beyond static references in JS1.

## Edge Vocabulary

Use existing edge kinds only:

- `defines`
- `references`

JS0 does not add a runtime call edge.

Expected structural edges:

- `file:* --defines--> js.file:*`
- `js.file:* --defines--> js.module:*`
- `js.file|js.module --defines--> js.function:*`
- `js.file|js.module --defines--> js.class:*`
- `js.class:* --defines--> js.method:*`
- `js.file|js.module --defines--> js.variable:*`
- `js.file|js.module --defines--> js.component:*`
- `js.file|js.module --defines--> js.test_suite:*`
- `js.test_suite|js.file --defines--> js.test_case:*`
- `js.file|js.module --defines--> js.route:*`

Expected reference edges:

- `js.file|js.module|js.function|js.class|js.component|js.test_case --references--> file:* | external.url:* | external:* | unknown:* | dynamic:*`

## Reference Model

JS1 should emit references only for conservative syntactic references.

Candidate references:

- ES module imports;
- ES module exports and re-exports;
- CommonJS `require("literal")`;
- dynamic `import("literal")` as dynamic import metadata/reference, not
  executed;
- `fetch("literal-url")` or `axios.get("literal-url")` as external URL
  references when static and safe;
- `importScripts("literal")` in service workers as references only;
- source map comments as metadata or references only, never fetched;
- JSX/TSX asset imports;
- React lazy imports;
- Angular route lazy imports where literal;
- Vue component imports where literal;
- Jest test helper imports or requires;
- template or static asset references when literal;
- archived or saved-page JavaScript source map references as not-fetched
  references.

Target policy:

- relative local imports become `file:*` when resolvable conservatively;
- repo-escaping paths become `unknown:file:repo-escaping-js-reference`;
- absolute filesystem paths become `external:file:absolute-js-reference`;
- package imports become `external:js-package:<package-name>` or raw metadata
  unless a package namespace is accepted later;
- scoped npm packages may use a safe external package reference or raw metadata;
- URLs become `external.url:*`;
- import aliases remain raw metadata or `dynamic:*` unless a later ADR accepts
  resolver configuration;
- dynamic or interpolated imports become `dynamic:*` or raw-only diagnostics;
- source maps become `external.url:*` or `file:*` with `not_fetched=true`
  metadata; and
- no reference target is fetched, loaded, installed, executed, or resolved at
  runtime.

## Generic JavaScript And TypeScript Behavior

JS1 should model generic JavaScript and TypeScript before framework-specific
behavior:

- one file/module observation per eligible source file or archived asset;
- import and export observations with module-system metadata;
- functions, classes, methods, and simple named arrow functions;
- variables and constants with safe literal type summaries;
- CommonJS `require`, `module.exports`, and `exports.foo`;
- JSX/TSX component-looking declarations where static;
- TypeScript interface, type alias, and enum observations if implementation is
  small and deterministic; and
- parse errors and dynamic diagnostics when syntax cannot be safely modeled.

No function body, JSX tree, or TypeScript inferred type should become canonical
metadata in JS1.

## Jest Profile

Jest profile detection should recognize:

- files under `__tests__`;
- `*.test.js`, `*.spec.js`, and TypeScript, JSX, and TSX variants;
- imports or requires of `jest` or `@jest/globals`;
- `describe`;
- `it`;
- `test`;
- `expect`;
- `beforeEach`, `afterEach`, `beforeAll`, and `afterAll`;
- `jest.mock`, `jest.fn`, and `jest.spyOn` as metadata.

Future behavior:

- emit `js.test_suite` for literal `describe`;
- emit `js.test_case` for literal `it` or `test`;
- store expectation/assertion counts as metadata when safe;
- do not execute tests;
- do not execute module mocking;
- do not generate or update snapshots; and
- do not execute jsdom or browser behavior.

## React Profile

React profile detection should recognize:

- imports from `react`;
- JSX and TSX files;
- function components with PascalCase names returning JSX where detectable;
- class components extending `React.Component` or `Component`;
- common hooks:
  - `useState`
  - `useEffect`
  - `useMemo`
  - `useCallback`
  - `useReducer`
- custom hooks named `use*`;
- React Router route declarations where literal and easy; and
- asset imports.

Future behavior:

- emit `js.component` for static components;
- store hooks as metadata or raw `js.hook` observations;
- emit `js.route` only for literal route patterns;
- do not render;
- do not hydrate;
- do not execute hooks; and
- do not boot a React app.

## Angular Profile

Angular profile detection should recognize:

- imports from `@angular/*`;
- `@Component`, `@NgModule`, `@Injectable`, `@Directive`, and `@Pipe`
  decorators if the parser or scanner can detect them;
- literal component `selector`, `templateUrl`, `template`, and `styleUrls`
  metadata;
- routes arrays with literal `path`, `component`, or `loadChildren`; and
- Angular test files when Jest or Karma-like syntax is static.

Future behavior:

- represent component, controller, module, directive, and pipe facts as
  `js.component` or metadata;
- emit `templateUrl` and `styleUrls` as references;
- emit route literal paths as `js.route`;
- do not invoke the Angular compiler;
- do not run Angular CLI;
- do not compile templates; and
- do not resolve dependency injection or runtime providers.

## Vue Profile

Vue profile detection should recognize:

- imports from `vue`;
- `defineComponent`;
- `createApp`;
- Options API keys such as `components`, `props`, `data`, `methods`,
  `computed`, and `watch`;
- Composition API setup functions and refs where static; and
- route declarations with literal paths.

JS0 defers full `.vue` single-file component parsing to JS2 or a future VUE0
unless JS1 proves that a tiny safe subset is enough. JS1 may detect
Vue-related JavaScript and TypeScript files without parsing `.vue` SFCs.

Requirements:

- no Vue compiler;
- no template compilation;
- no app boot;
- no runtime route resolution; and
- no DOM execution.

## Saved-Page, Report, And Frontend Asset Profiles

JavaScript assets discovered through saved-page, ARCHIVE, WARC, HTML, CSS, DOCS,
or generated-report contexts are local source bytes, not execution
instructions.

Future JS behavior:

- JavaScript assets discovered through saved-page/static artifact/WARC import
  may be parsed as local bytes when source policy allows;
- inline `<script>` blocks may be modeled later only if the HTML extractor can
  hand them off safely;
- external script URLs remain references and are never fetched;
- source map references are not fetched;
- report UI JavaScript is inert source text only;
- service workers are not executed;
- event handlers are not executed;
- no browser execution;
- no DOM simulation; and
- no chart or report runtime extraction.

This supports future analysis of:

- generated test reports;
- coverage reports;
- static documentation sites;
- saved pages;
- WARC response payloads; and
- local frontend bundles.

## Minified And Bundled JavaScript

Minified and bundled JavaScript may be too dense to model usefully.

Rules:

- apply file size and token limits;
- emit file/module metadata and references where cheap;
- avoid giant canonical graphs from minified bundles;
- profile as `frontend_asset` or `saved_page_asset` when appropriate;
- do not beautify using external tools;
- do not apply source maps; and
- do not execute.

If minified content exceeds limits, JS1 should emit safe diagnostics rather
than fabricating precise graph facts.

## Package And Config Notes

`package.json` remains part of structured configuration extraction. Package
dependencies, scripts, and metadata may already exist as config facts. JS
phases may later read those facts for readback polish, but JS1 should not add
`npm.*` namespaces or run package managers.

`tsconfig.json`, `angular.json`, and other JSON config files remain structured
configuration facts. JavaScript or TypeScript config files such as
`jest.config.ts`, `vite.config.js`, and `webpack.config.cjs` are static source
files and must not be executed.

Dependencies, plugins, loaders, scripts, and framework commands are references
or metadata only. They are not installed, loaded, executed, or fetched.

## Redaction

JavaScript files and configuration-like source often contain secrets in
literals, environment names, URLs, headers, tokens, and config objects.

JS1 should reuse ADR 0010, YAML, and Ruby markers:

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
- `client_secret`
- `secret_key`
- `access_token`
- `id_token`
- `session`
- `cookie`
- `connection_string`
- `jdbc_url`
- `datasource_password`

Additional JavaScript and frontend markers:

- `apiToken`
- `authToken`
- `bearerToken`
- `sessionToken`
- `csrfToken`
- `xsrfToken`
- `firebaseApiKey`
- `sentryDsn`
- `stripeSecret`
- `npmToken`
- `githubToken`
- `jestToken`
- `angularToken`
- `vueToken`

Redaction requirements:

- secret literal values must not appear in canonical keys;
- secret literal values must not appear in raw observation metadata;
- secret literal values must not appear in canonical node metadata;
- secret literal values must not appear in edge metadata;
- secret literal values must not appear in golden fixtures, readback, or
  explain output;
- URL credentials must be stripped or redacted before metadata serialization;
- source map and package references must not leak credentials; and
- redacted observations may preserve safe metadata such as literal type,
  redaction reason, key/call/argument name, profile, and structural pointer.

## Dynamic JavaScript

If an expression is dynamic:

- record a diagnostic or safe metadata;
- do not fabricate precise edges;
- use `dynamic:*` only when a canonical placeholder is useful;
- preserve evidence location when available; and
- do not execute JavaScript to resolve it.

Dynamic examples:

- template literals and string interpolation;
- computed imports;
- computed property names;
- `eval`;
- `Function` constructor;
- dynamic `require`;
- runtime route arrays;
- environment-variable-driven configuration;
- generated tests, routes, or components; and
- framework decorators or config objects with nonliteral arguments.

Environment variables:

- references to `process.env.NAME`, `import.meta.env.NAME`, and similar
  patterns may be metadata only;
- JS1 must never read the current environment;
- secret-prone environment names trigger redaction; and
- JS1 must not resolve build-time environment injection.

## Fixtures Required For JS1

JS1 should add fixtures under:

```text
src/test/fixtures/discovery/js_basic/
src/test/fixtures/canonicalization/js_basic/
```

Required fixture files:

- `src/index.js`
- `src/util.mjs`
- `src/common.cjs`
- `src/app.ts`
- `src/component.jsx`
- `src/component.tsx`
- `src/react/App.jsx`
- `src/angular/app.component.ts`
- `src/angular/app.routes.ts`
- `src/vue/main.ts`
- `src/jest/example.test.js`
- `src/jest/example.spec.ts`
- `public/report.js`
- `public/minified.js`
- `redaction.js`
- `dynamic.js`

Optional config fixtures:

- `package.json`
- `tsconfig.json`

Those optional files remain config fixtures unless a later phase explicitly
uses stored config facts for JavaScript readback context.

Fixture values must be fake. Fixtures must not include real tokens, private
endpoints, internal service names, or secret literals.

## Required JS1 Tests

JS1 should include tests for:

- generic JavaScript file extraction;
- TypeScript file extraction or graceful fallback;
- JSX and TSX file extraction or graceful fallback;
- import and export detection;
- CommonJS `require`, `module.exports`, and `exports.foo` detection;
- function, class, method, variable, and constant detection;
- static local import reference extraction;
- package import reference extraction;
- URL reference extraction;
- dynamic import diagnostics;
- source map reference detection without fetching;
- Jest suite and test detection without execution;
- React component and profile detection without rendering;
- Angular decorator, route, and profile detection without compiler invocation;
- Vue JavaScript and TypeScript profile detection without compiler invocation;
- saved-page and report asset profile detection;
- minified file safety behavior;
- redaction;
- no Node execution;
- no npm, npx, yarn, pnpm, or bun execution;
- no bundler, compiler, or test execution;
- no browser automation;
- storage load and readback;
- explain output for one JavaScript reference edge; and
- absence of secret values in readback and explain output.

## Rejected Alternatives

JS0 rejects:

- executing JavaScript to discover structure;
- invoking Node or `node --check` in JS1;
- using npm, npx, yarn, pnpm, or bun;
- installing dependencies;
- bundling or transpiling;
- running Jest;
- rendering React, Angular, or Vue;
- compiling Angular templates;
- parsing `.vue` single-file components in JS1 unless explicitly accepted and
  tiny;
- using source maps to recover original source in JS1;
- browser automation;
- DOM, hydration, or event execution;
- fetching remote imports or source maps;
- adding framework-specific namespaces in JS0;
- adding call graph or dataflow analysis in JS0; and
- storing function bodies, JSX rendered output, or secret literals in canonical
  metadata.

## Proposed Phases

- JS1: generic JS/TS/JSX/TSX static extraction with profile hints.
- JS2: profile readback polish for Jest, React, Angular, and Vue using existing
  generic `js.*` facts.
- JS3: saved-page, report, and static-asset enhancement, including better
  integration with HTML script references, ARCHIVE/WARC payloads, and report
  fixtures.
- Future REACT0, ANGULAR0, or VUE0 only if a profile needs first-class
  namespaces after generic JavaScript proves insufficient.

## Consequences

JS0 positions JavaScript as another static source family in RepoMap rather than
as a runtime or browser automation feature. It keeps the first implementation
slice small enough to prove value through generic local facts while preserving
clear extension points for frontend framework readback and archived asset
analysis.

The tradeoff is that JS1 will not answer runtime questions such as "what route
is actually registered after all plugins run" or "what component renders after
hydration." Those questions require execution or framework simulation and
remain outside this graph model.
