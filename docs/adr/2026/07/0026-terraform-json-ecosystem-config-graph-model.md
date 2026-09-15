# ADR 0026: Terraform, JSON, And Ecosystem Configuration Graph Model

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0010: Structured Configuration Graph Model
- ADR 0019: YAML Graph Model
- ADR 0021: Static JavaScript Graph Model
- ADR 0023: Bulk Local Corpus Ingestion
- ADR 0024: Documented API Ingestion Architecture
- YAML1 generic YAML extractor exit audit
- JS3 static asset integration exit audit
- BULK2 bulk readback polish exit audit

## Context

RepoMap already extracts and canonicalizes safe facts from local source code,
structured configuration, documents, saved/static artifacts, WARC payloads,
feeds, JavaScript assets, local email files, and policy-gated bulk local
corpora.

ADR 0010 accepted the generic structured configuration model for JSON, JSONL,
JSONC, TOML, and conservative references. ADR 0019 extended that posture to
YAML. ADR 0021 accepted a static JavaScript and TypeScript graph model, while
leaving package metadata and JSON configuration under the structured
configuration boundary.

The next useful configuration architecture increment is to make Terraform and
common ecosystem configuration files first-class enough that RepoMap can
understand real application and infrastructure repositories before deeper
framework source extraction. The graph should help answer:

- what packages, scripts, tools, frameworks, and runtimes a project declares;
- what Terraform providers, resources, modules, variables, and outputs are
  declared;
- what Docker, Kubernetes, GitOps, CI, testing, and database migration
  artifacts exist;
- what configuration files reference local files;
- what configuration files reference external artifacts without fetching them;
  and
- what sensitive values were redacted or intentionally avoided.

TFJSON0 defines the architecture only. It does not implement extraction,
parsing, CLI behavior, fixtures, tests, storage changes, MCP tools, network
access, package resolution, provider acquisition, or tool execution.

## Decision

RepoMap will model Terraform, Terraform JSON variants, and JSON/JSONC
ecosystem configuration as static local configuration analysis layered on ADR
0010.

The future TFJSON pipeline is:

```text
local Terraform, JSON, or JSONC config file
-> safe static parse or conservative parse diagnostic
-> generic config.document/config.path/config.reference observations
-> optional Terraform or ecosystem profile raw observations
-> optional conservative canonical graph facts only where identity is stable
-> load through existing storage path
-> expose through existing readback and future read-only summaries
```

TFJSON extraction is not tool execution. It must not run Terraform, OpenTofu,
Terragrunt, Node, package managers, test frameworks, browser automation,
Docker, Kubernetes, Argo CD, Liquibase, GitHub Actions tooling, shell commands,
or provider CLIs. It must not install packages, download providers, fetch
modules, fetch images, fetch GitHub Actions, read secrets, decrypt secrets,
evaluate runtime expressions, or call provider APIs.

The initial posture should be raw/profile-observation first. Existing
`config.document`, `config.path`, and `config.reference` remain the base public
model. Ecosystem-specific canonical namespaces are deferred unless future
implementation evidence proves that a stable domain identity is useful and
consistent with ADR 0001, ADR 0002, and ADR 0003.

## Scope

In scope:

- Terraform and Terraform JSON graph model design;
- JSON and JSONC ecosystem configuration profile design;
- future supported file-family policy;
- static-only parser and extraction requirements;
- raw observation names for Terraform and ecosystem profiles;
- possible future canonical namespaces;
- relationship to the existing ADR 0010 configuration graph;
- redaction and privacy requirements;
- conservative reference policy;
- future implementation phases; and
- future test requirements.

Out of scope:

- implementing Terraform extraction;
- implementing HCL parsing;
- implementing new JSON or JSONC extraction behavior;
- adding CLI commands;
- adding fixtures or tests;
- adding storage migrations;
- adding MCP tools;
- running Terraform, OpenTofu, Terragrunt, provider CLIs, or shell commands;
- running Node, npm, yarn, pnpm, bun, npx, Jest, Playwright, Docker,
  Kubernetes, kubectl, Helm, Argo CD, Liquibase, GitHub Actions, or package
  manager tooling;
- installing packages;
- fetching providers, modules, images, packages, actions, charts, Git repos,
  URLs, or provider data;
- network access;
- evaluating Terraform expressions dynamically;
- evaluating JavaScript or TypeScript config files dynamically;
- reading, decrypting, or resolving secrets;
- provider API acquisition;
- changing public readback defaults; and
- Phase F migration.

## Product Posture

TFJSON graphing must remain static, local, deterministic, non-executing,
no-fetch, and redaction-aware.

Requirements:

- local files only;
- no Terraform, OpenTofu, or Terragrunt execution;
- no `terraform init`, `plan`, `apply`, `validate`, provider download, or
  module download;
- no HCL expression evaluation beyond safe syntactic recognition;
- no provider schema loading;
- no remote state lookup;
- no data source lookup;
- no JavaScript or TypeScript config execution;
- no Node or package-manager invocation;
- no package install or package metadata fetch;
- no test framework execution;
- no browser launch or page fetch;
- no Docker daemon access;
- no Kubernetes, Helm, Argo CD, or Liquibase command execution;
- no GitHub or CI provider calls;
- no remote container image, action, chart, module, provider, or package
  fetching;
- no secret decryption or credential resolution;
- no source file mutation except RepoMap-owned output artifacts in later
  implementation phases; and
- no MCP write, import, or run tools.

TFJSON0 is not "run the tools." TFJSON0 is "statically map declared
configuration intent."

## Supported Future File Families

### Terraform

Future Terraform phases may support:

- `.tf`;
- `.tfvars`;
- `.tf.json`;
- `.tfvars.json`.

OpenTofu extensions such as `.tofu` and `.tofuvars` are deferred unless a later
phase explicitly documents their file-family policy. Terragrunt files are also
deferred unless separately accepted.

### JSON And JSONC Ecosystem Configuration

Future TFJSON implementation phases may specialize these already-supported
structured configuration families:

- `.json`;
- `.jsonc`;
- selected extensionless JSON config files only when discovery already
  classifies them safely.

JSONL remains governed by ADR 0010 and should not be used for Terraform or
ecosystem profile identity unless a specific later phase accepts a stable
record model.

YAML-heavy infrastructure tools remain governed by ADR 0019 and future YAML
infrastructure phases. JavaScript and TypeScript executable config files remain
governed by ADR 0021 and later JS/TS static extraction phases.

## Terraform Model

Future Terraform extraction should be static and non-evaluating. It may
recognize declared Terraform/OpenTofu-style blocks where syntactically clear:

- `terraform`;
- `provider`;
- `resource`;
- `data`;
- `module`;
- `variable`;
- `output`;
- `locals`;
- `moved`;
- `import`;
- `check`;
- `removed`.

Future Terraform JSON extraction should recognize Terraform JSON equivalents:

- `terraform`;
- `provider`;
- `resource`;
- `data`;
- `module`;
- `variable`;
- `output`;
- `locals`.

The extractor must not evaluate:

- expressions;
- interpolation;
- functions;
- variables;
- provider schemas;
- module source contents;
- remote state;
- data source lookups;
- dependency graphs from runtime evaluation.

Literal block type, labels, provider names, resource type names, resource
local names, variable names, output names, backend type, required provider
names, required provider source names, and version constraints may be recorded
when parsed statically.

Expression-bearing values should be metadata with `dynamic=true`, a safe
summary, or a parse/evaluation-deferred diagnostic. They must not be
interpreted as runtime truth.

## Terraform Raw Observations

Future Terraform phases may emit raw observations such as:

- `terraform.file`;
- `terraform.block`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.local`;
- `terraform.backend`;
- `terraform.required_provider`;
- `terraform.required_version`;
- `terraform.reference`;
- `terraform.parse_error`;
- `terraform.redaction`.

These observations are raw/evidence/profile facts first. They may coexist with
generic ADR 0010 observations:

- `config.document`;
- `config.path`;
- `config.reference`;
- `config.parse_error`.

Terraform-specific raw observations should preserve safe parser and provenance
metadata, such as file path, block kind, labels, profile, source span when
available, redaction status, and confidence. They must not store secret values,
runtime-evaluated values, provider-returned values, remote state, or fetched
module/provider data.

## Terraform Canonical Namespace Policy

TFJSON0 does not add Terraform canonical namespaces.

Possible future canonical namespaces, if implementation evidence supports
them:

- `terraform.file`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.backend`.

Future implementation should start with raw observations and existing
`config.*` canonical facts. A small Terraform canonical set may be accepted
only when identity is stable, useful, and consistent with ADR 0001/0002/0003.

Potential identity guidance for future review:

- resource identity should be scoped by repository file or Terraform module
  context plus resource type and local name, not by provider runtime ID;
- module identity should use local block identity and source summary, not
  fetched module content;
- variables and outputs should use declared names scoped to a file or module
  context;
- backend identity should use backend type and config file context, not remote
  state contents; and
- canonical keys must never include secret values, runtime state values, line
  numbers, provider IDs, absolute machine paths, current time, or fetched data.

## Terraform References

Terraform reference extraction should record safe references without fetching.

Candidate references:

- provider source names;
- provider version constraints;
- module source strings as redacted or summarized metadata;
- backend type;
- local file references when obvious;
- variable references when statically obvious;
- resource and data references when statically obvious;
- required Terraform version constraints;
- local path-like values in non-secret contexts.

Target policy:

- local file references may become `file:*` only when they normalize inside the
  repository;
- repo-escaping paths become `unknown:*` or `external:*` placeholders;
- provider and module sources remain raw metadata or `external:*` references
  unless a later package/module namespace is accepted;
- remote source URLs may become `external.url:*` summaries only when safe and
  must never be fetched;
- expression-bearing references become `dynamic:*` or raw-only diagnostics.

Future Terraform extraction must not fetch:

- registry modules;
- Git modules;
- providers;
- remote state;
- HTTP data sources;
- S3, GCS, Azure, or other backends;
- secrets managers.

## Terraform Variable Redaction

Terraform config can contain sensitive values even when files are local.
Redact or avoid raw values for keys, names, paths, or attributes containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `private_key`;
- `access_key`;
- `secret_key`;
- `client_secret`;
- `credential`;
- `connection_string`;
- `auth`;
- `bearer`;
- `session`;
- `cookie`.

For `.tfvars` and `.tfvars.json`, future extraction must be stricter:

- treat values as sensitive by default;
- preserve variable names and value type or shape only;
- hash or omit literal values only if a later implementation explicitly accepts
  non-reversible hashes;
- never expose secret-like values in raw observations, canonical keys,
  metadata, readback, explain output, fixtures, or diagnostics.

## JSON/JSONC Ecosystem Profiles

TFJSON0 defines ecosystem profiles as metadata and raw observations layered on
ADR 0010. Profile detection may use path, filename, and shallow parsed content.
It must remain deterministic and static.

Possible generic ecosystem raw observations:

- `ecosystem.config_profile`;
- `ecosystem.package`;
- `ecosystem.script`;
- `ecosystem.dependency`;
- `ecosystem.tool`;
- `ecosystem.framework_hint`;
- `ecosystem.reference`;
- `ecosystem.parse_error`;
- `ecosystem.redaction`.

Possible profile-specific raw observations:

- `npm.package`;
- `npm.script`;
- `npm.dependency`;
- `typescript.config`;
- `angular.project`;
- `angular.target`;
- `jest.config`;
- `nest.config`;
- `playwright.config`;
- `terraform.resource`;
- `terraform.module`;
- `terraform.variable`;
- `docker.reference`;
- `kubernetes.resource`;
- `github_actions.workflow`;
- `argocd.application`;
- `liquibase.changelog`.

These are raw/profile observations unless a later phase explicitly accepts
canonical namespaces.

## Package And Runtime Profile

For `package.json`, future extraction should recognize static metadata:

- package name, version, type, and private flag;
- scripts;
- dependencies;
- devDependencies;
- peerDependencies;
- optionalDependencies;
- package manager field;
- engines;
- workspaces;
- bin entries;
- main, module, browser, types, exports, and imports fields;
- repository, bugs, and homepage as safe URL summaries; and
- framework or tool profile hints.

Future extraction must not:

- run scripts;
- install dependencies;
- resolve packages;
- inspect `node_modules`;
- fetch package metadata;
- execute package-manager lifecycle hooks;
- treat package versions as proof of runtime behavior.

`package-lock.json`, `npm-shrinkwrap.json`, and similar JSON lock metadata may
be summarized conservatively. `pnpm-lock.yaml` remains a YAML profile candidate
for a later YAML phase. `yarn.lock`, `bun.lock`, and binary lockfiles are
deferred unless a later text or binary lockfile profile accepts them.

## TypeScript And JavaScript Config Profiles

Future JSON/JSONC extraction may profile:

- `tsconfig.json`;
- `tsconfig.*.json`;
- `jsconfig.json`;
- `angular.json`;
- `.angular-cli.json`;
- `project.json`;
- `workspace.json`;
- `nx.json`;
- `nest-cli.json`;
- `jest.config.json`;
- `babel.config.json`;
- `.babelrc`;
- `.babelrc.json`;
- `.eslintrc`;
- `.eslintrc.json`;
- `.prettierrc`;
- `.prettierrc.json`;
- `next.config.json` if present.

Executable JavaScript or TypeScript config files remain under ADR 0021 and
later JS/TS static extraction, not JSON execution:

- `jest.config.js`;
- `jest.config.ts`;
- `vite.config.*`;
- `vue.config.js`;
- `webpack.config.*`;
- `next.config.*` when JavaScript or TypeScript.

Future config profiles may recognize:

- compiler options;
- path aliases and project references;
- `extends` relationships;
- Angular project roots, source roots, builders, and architect targets;
- Nest CLI source roots and collection metadata;
- Jest config embedded in `package.json` or `jest.config.json`;
- Babel, ESLint, and Prettier profile hints;
- local config-file references.

They must not invoke TypeScript, Babel, Jest, Angular CLI, Vite, Webpack,
Next.js, Vue CLI, or any framework tool.

## JS/TS Framework Profile Notes

TFJSON0 covers only configuration and static document/profile hints. It does
not implement JS/TS framework source-code extraction. A later JS framework
phase should handle source behavior.

### Angular

Angular profile hints may be inferred from:

- `angular.json`;
- package dependencies;
- tsconfig paths and compiler options;
- builders and architect targets;
- project roots and source roots;
- scripts;
- testing config.

### React

React profile hints may be inferred from:

- package dependencies;
- scripts;
- Vite, Create React App, Next.js, Gatsby, or Remix markers when present;
- `tsconfig` or `jsconfig` JSX settings;
- static JS/TS extraction later.

TFJSON0 does not create React canonical namespaces.

### Vue

Vue profile hints may be inferred from:

- package dependencies;
- Vue CLI or Vite config markers;
- `vue` dependency;
- project files discovered later;
- static JS/TS extraction later.

### Node.js

Node.js profile hints may include:

- package type or module system;
- scripts;
- engines;
- bin, main, module, exports, and imports;
- runtime dependencies;
- config references.

### Express

Express profile hints may come from package dependency metadata. Route
extraction is deferred to a future JS/TS source phase.

### NestJS

NestJS profile hints may come from `nest-cli.json`, package dependency
metadata, and tsconfig references. Module, controller, and provider extraction
is deferred to a future JS/TS source phase.

### Next.js

Next.js profile hints may come from package dependency metadata, `next`
scripts, and JSON config when present. Next config JavaScript/TypeScript static
analysis and app/pages route extraction are deferred.

### Jest

Jest profile hints may come from package dependency metadata, a `jest` key in
`package.json`, and `jest.config.json`. JS/TS Jest tests remain governed by ADR
0021 and later JS implementation phases.

### jQuery

jQuery should be a future target in both source-code extraction and saved
artifact/document/static extraction. TFJSON0 covers only config/document/static
artifact hints. Future JS/TS source extraction may detect `$()`, `jQuery()`,
selectors, event bindings, and AJAX-like calls when static and non-executing.
Saved-page and report extraction may use HTML script references and already
safely extracted inline markers, but must not execute script.

## First-Class Infrastructure And Tooling Profiles

The user's first-class cross-language tooling stack is:

- Liquibase;
- Docker;
- Kubernetes;
- Playwright;
- GitHub Actions;
- Argo CD;
- Terraform.

TFJSON0 defines how these should be considered whenever a relevant language or
config file family is incremented.

### Liquibase

Future extraction should recognize:

- `liquibase.properties`;
- `liquibase.json` if used;
- `liquibase.yaml` and `liquibase.yml`;
- XML changelogs;
- YAML, JSON, and XML changelogs;
- changelog include and includeAll references;
- databaseChangeLog structure;
- changeSet IDs and authors;
- rollback markers;
- preconditions;
- contexts and labels;
- path references.

RepoMap must not run Liquibase, connect to databases, execute migrations, or
resolve remote includes.

### Docker

Future extraction should recognize:

- `Dockerfile`;
- `Containerfile`;
- `.dockerignore`;
- `docker-compose.yml`;
- `compose.yaml`;
- `compose.yml`;
- JSON Compose variants if present.

TFJSON0 models only JSON/JSONC aspects if present. Dockerfile and Compose YAML
belong to later Dockerfile/YAML phases unless separately accepted. RepoMap must
not build images, pull images, or run containers.

### Kubernetes

Future extraction should recognize YAML and JSON manifests:

- `apiVersion`;
- `kind`;
- `metadata.name`;
- `metadata.namespace`;
- labels;
- spec references;
- container images as references, not fetches;
- ConfigMap and Secret markers with strict redaction;
- deployments, services, jobs, cronjobs, ingresses, roles, bindings, and other
  resources as safe profile facts when parsed locally.

TFJSON0 includes JSON Kubernetes manifests as config profiles. YAML Kubernetes
manifests remain YAML infrastructure work. RepoMap must not call `kubectl`,
connect to clusters, simulate admission/defaulting, or decode secrets beyond
safe metadata.

### Playwright

Future extraction should recognize:

- `playwright.config.json` if present;
- package dependency and script hints;
- test directory and project names;
- statically configured browser or project metadata;
- local report artifacts if supported by a later artifact phase.

`playwright.config.js` and `playwright.config.ts` are deferred to JS/TS static
analysis. RepoMap must not run browsers, run tests, fetch pages, or start
servers.

### GitHub Actions

GitHub Actions is primarily a YAML profile:

- `.github/workflows/*.yml`;
- `.github/workflows/*.yaml`;
- jobs;
- steps;
- `uses`;
- run markers;
- permissions;
- secrets contexts;
- workflow triggers.

JSON is uncommon for workflows. TFJSON0 keeps GitHub Actions first-class as a
tooling target but does not mis-model it as JSON-only. Actions and reusable
workflow references are references only. RepoMap must not run workflows, call
GitHub, or fetch actions.

### Argo CD

Future extraction should recognize Argo CD Application and ApplicationSet YAML
or JSON manifests:

- repoURL, path, and targetRevision as references;
- destination clusters and namespaces as redacted or summarized metadata;
- Helm, Kustomize, directory, and source-plugin markers;
- syncPolicy markers.

RepoMap must not call `argocd`, connect to clusters, fetch Git repos, fetch
Helm charts, or apply manifests.

### Terraform

Terraform is primary scope for TFJSON0:

- `.tf`;
- `.tfvars`;
- `.tf.json`;
- `.tfvars.json`.

The first JSON implementation after TFJSON0 should get Terraform JSON support
off the ground for `.tf.json`, `.tfvars.json`, and `terraform.tfvars.json`
where discovered safely.

## Relationship To Existing Config Graph

TFJSON0 layers ecosystem profiles on ADR 0010.

Base behavior:

- keep `config.document` as the file-level structured config fact;
- keep `config.path` as the stable structural path fact;
- keep `config.reference` as conservative syntactic reference evidence;
- keep `config.parse_error` for parse diagnostics;
- add profile metadata on documents and paths when detected;
- emit profile-specific raw observations only when they clarify ecosystem
  facts without forcing canonical identity;
- add canonical nodes only when identity is stable and useful;
- use existing edge kinds only; and
- treat external packages, images, modules, actions, providers, and charts as
  references only, never as fetched content.

JSON/JSONC ecosystem extraction should avoid duplicating generic config facts.
Profile observations should point back to source `config.document` and
`config.path` keys or raw source IDs as provenance.

## Potential Canonical Namespaces

TFJSON0 does not add canonical namespaces.

Potential namespaces for later review, if useful:

- `npm.package`;
- `npm.script`;
- `npm.dependency`;
- `terraform.resource`;
- `terraform.module`;
- `terraform.variable`;
- `kubernetes.resource`;
- `github_actions.workflow`;
- `argocd.application`;
- `liquibase.changelog`.

Most profile namespaces should be deferred until implementation evidence shows
that generic `config.*` facts and raw profile observations are insufficient.

Canonical keys must not include:

- raw values;
- secret values;
- package script bodies;
- Terraform evaluated values;
- provider runtime IDs;
- Docker image digests fetched from registries;
- Kubernetes cluster runtime values;
- GitHub Actions fetched metadata;
- Liquibase database state;
- current time;
- absolute machine paths;
- parser object IDs;
- extractor versions;
- model-generated labels; or
- line numbers.

## Edge Vocabulary

TFJSON0 adds no edge kinds.

Use existing edge kinds:

- `defines`;
- `references`.

Expected relationships:

- `file:* --defines--> config.document:*`;
- `file:* --defines--> config.path:*`;
- `config.path:* --references--> file:* | external.url:* | external:* | unknown:* | dynamic:* | config.path:* | config.document:*`;
- future raw/profile observations may be canonicalized to `defines` only when
  the target namespace is accepted later.

References do not imply runtime dependency, successful resolution, execution,
provider availability, package installation, or fetch success.

## Reference Policy

TFJSON extraction should record references without fetching.

Candidate references:

- npm package names;
- package repository, homepage, and bugs URL summaries;
- Docker images;
- Kubernetes container images;
- Terraform provider, module, backend, and source references;
- GitHub Actions `uses` references;
- Argo CD repoURL, path, and targetRevision summaries;
- Liquibase include and includeAll paths;
- Playwright test and report references;
- tsconfig `extends`, `references`, and `paths`;
- Angular project source roots;
- Nest, Next, Jest, Babel, ESLint, Prettier, and package config references.

Do not fetch:

- npm packages;
- Docker images;
- Git repos;
- GitHub Actions;
- Terraform modules or providers;
- Helm charts;
- Kubernetes clusters;
- Liquibase includes outside the allowed local root;
- browser pages;
- arbitrary URLs.

Target policy:

- repo-local paths become `file:*` only when they normalize inside the
  repository;
- external URLs may become `external.url:*` summaries when safe;
- packages, modules, providers, images, charts, and actions may use
  `external:*` or raw metadata until a more specific namespace is accepted;
- dynamic, templated, expression-bearing, or interpolation-bearing references
  become `dynamic:*`, `unknown:*`, or raw-only diagnostics.

## Redaction And Privacy

TFJSON0 defines strict redaction for configuration values.

Redact or summarize values for key names, path segments, or contexts
containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `private_key`;
- `access_key`;
- `secret_key`;
- `client_secret`;
- `credential`;
- `connection_string`;
- `auth`;
- `bearer`;
- `session`;
- `cookie`;
- `kubeconfig`;
- `certificate`;
- `cert`;
- `tls`;
- `ssh`;
- `webhook`;
- `datasource`;
- `jdbc`;
- `database_url`;
- `url` when the value appears credentialed.

Kubernetes Secret policy:

- never expose secret data values;
- preserve kind, name, namespace, and key names only if safe;
- preserve value type, length, or hash only if accepted by the implementation
  phase.

Terraform variables policy:

- `.tfvars` and `.tfvars.json` values are sensitive by default;
- preserve names, types, shapes, and redaction metadata only;
- do not emit literal values into canonical keys, metadata, readback, explain
  output, or fixtures.

Package script policy:

- record script names;
- store only safe command summaries;
- avoid full script command text when it contains obvious secret, credential,
  env injection, or shell expansion risk;
- never execute scripts.

Secret values must not appear in raw observation metadata, canonical keys,
canonical node metadata, edge metadata, golden fixtures, status docs, CLI
readback, or explain output.

## Static Parsing Requirements

Future implementation phases must parse only supplied local bytes and must
enforce limits such as:

- maximum file bytes;
- maximum document size;
- maximum JSON/HCL node count;
- maximum nesting depth;
- maximum scalar length;
- maximum profile observations per file;
- safe parse diagnostics for malformed input.

Parser errors should emit raw diagnostics such as `config.parse_error`,
`terraform.parse_error`, or `ecosystem.parse_error` without fabricating precise
graph facts.

Terraform HCL parsing requires a safe parser strategy accepted by a future
implementation review. If no safe parser is accepted, Terraform work may begin
with `.tf.json` and `.tfvars.json` only.

## Future Implementation Phases

Suggested future phases:

- TFJSON1: Terraform JSON and package/ecosystem JSON implementation;
- TFJSON2: Terraform HCL implementation if a safe parser strategy is accepted;
- TFJSON3: ecosystem config readback polish;
- JS4: JS/TS framework source extraction ADR or implementation for npm,
  Node.js, Express, NestJS, Next.js, Jest, jQuery, React, Angular, and Vue;
- YAML-INFRA0/YAML-INFRA1: Kubernetes, GitHub Actions, Argo CD, Liquibase, and
  other YAML infrastructure profile extraction;
- DOCKER0/DOCKER1: Dockerfile and Docker Compose extraction if not covered
  elsewhere.

Each implementation phase must restate its non-execution, no-fetch, redaction,
and namespace boundaries in its exit audit.

## Future TFJSON1 Test Requirements

TFJSON1 should include tests for:

- `package.json` dependencies, scripts, exports, imports, bin entries,
  package manager field, engines, and workspaces;
- `tsconfig.json` and `jsconfig.json` compiler options, paths, references, and
  extends;
- `angular.json` projects, targets, builders, source roots, and file
  references;
- `nest-cli.json`;
- Jest config in `package.json` and `jest.config.json`;
- Playwright JSON config if present;
- Terraform `.tf.json` resources, modules, providers, variables, outputs,
  backend, and required providers;
- `.tfvars.json` strict redaction;
- Kubernetes JSON resource manifest profile;
- Argo CD JSON Application profile;
- Liquibase JSON changelog profile;
- Docker JSON-like metadata if supported;
- GitHub Actions as YAML-first, not mis-modeled as JSON-only;
- redaction of secret-like fields;
- no fetching;
- no execution;
- no package install;
- no Terraform provider or module download;
- no Docker, Kubernetes, Liquibase, Playwright, or GitHub Actions execution;
- references only;
- no provider-specific canonical namespaces unless explicitly accepted by that
  phase;
- no new edge kinds.

Tests must prove that secret values do not appear in raw observation metadata,
canonical keys, node metadata, edge metadata, golden fixtures, serialized
readback, or explain output.

## Rejected Alternatives

### Run Terraform Or OpenTofu

Rejected. RepoMap extraction is static graphing, not infrastructure planning,
validation, provider acquisition, or remote state evaluation.

### Dynamically Evaluate HCL

Rejected. Evaluating expressions, functions, variables, provider schemas, data
sources, or runtime dependency graphs would cross the static extraction
boundary.

### Load Provider Schemas Or Modules

Rejected. Provider schemas and modules require external downloads or installed
state. TFJSON phases should record declared references without fetching them.

### Install Packages Or Resolve Package Metadata

Rejected. Package-manager resolution is networked, mutable, and can execute
scripts. Package JSON extraction records declared metadata only.

### Execute Package Scripts Or JS/TS Config Files

Rejected. Scripts and executable config files are source text, not commands for
RepoMap to run.

### Run Jest, Playwright, Docker, Kubernetes, Argo CD, Liquibase, Or CI Tools

Rejected. Runtime tool behavior belongs outside extraction. RepoMap records
declared configuration intent only.

### Fetch Remote Packages, Images, Actions, Modules, Charts, Or Repos

Rejected. References may be represented as `external:*`, `external.url:*`, raw
metadata, or placeholders, but they must not be fetched.

### Model Every Framework As Canonical Namespaces Immediately

Rejected. Generic `config.*` facts and raw profile observations should prove
query value before RepoMap commits to framework-specific canonical identity.

### Store Secret Configuration Values

Rejected. Secret and secret-like values are not graph identity and must not
appear in raw observations, canonical metadata, readback, explain output, or
fixtures.

### Treat YAML-First Tools As JSON-Only

Rejected. GitHub Actions, Kubernetes, Argo CD, Liquibase, and Docker Compose
often use YAML. TFJSON0 keeps them first-class tooling concerns while leaving
YAML behavior to ADR 0019 and future YAML infrastructure phases.

### Cram JS/TS Source Framework Extraction Into TFJSON

Rejected. TFJSON covers Terraform and configuration profiles. Source-code
framework extraction belongs in later JS/TS phases governed by ADR 0021.

## Consequences

- Terraform JSON and ecosystem JSON/JSONC work can proceed without weakening
  ADR 0010's structured configuration model.
- Terraform HCL remains blocked on an explicit safe parser strategy.
- Package, framework, testing, infrastructure, CI/CD, and migration tools can
  become visible through safe config profiles before deeper source extraction.
- Query value can be proven through raw/profile observations and existing
  `config.*` nodes before accepting new canonical namespaces.
- No new edge vocabulary is needed for TFJSON0.
- No network, tool execution, provider API, secret resolution, MCP write, or
  public readback default behavior is accepted by this ADR.

## Acceptance Criteria

TFJSON0 is accepted only if it is internally consistent, static-only,
non-executing, no-fetch, redaction-aware, config-profile-oriented, and clearly
separates:

- Terraform and Terraform JSON configuration extraction;
- JSON/JSONC ecosystem configuration extraction;
- future JS/TS source framework extraction;
- future YAML infrastructure extraction;
- future Dockerfile and Compose extraction; and
- future provider/API acquisition.

Implementation phases must restate their boundaries and prove them with tests
before adding extractors, readback, canonical namespaces, or any public graph
surface.
