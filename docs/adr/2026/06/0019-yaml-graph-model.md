# ADR 0019: YAML Graph Model

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap already models structured configuration files such as JSON, JSONL,
JSONC, and TOML through the ADR 0010 configuration graph. It also has local
document extraction for the closed DOCS set from ADR 0018. YAML is the major
remaining configuration format for modern developer, infrastructure, CI/CD,
backup, observability, and application ecosystems.

High-value local YAML inputs include:

- Serena configuration;
- custom Arq Backup configuration dumps;
- Helm charts and values;
- Spring Boot YAML configuration;
- OpenAPI YAML;
- Harness pipelines and configuration;
- Kubernetes manifests;
- Docker Compose;
- GitHub Actions workflows;
- CircleCI configuration; and
- Grafana provisioning, dashboards, and configuration.

YAML0 brings RepoMap back toward core configuration identity work after DOCS
while staying static, local, deterministic, and privacy-conscious.

## Decision

RepoMap will treat YAML as an extension of the structured configuration graph
from ADR 0010.

The future YAML pipeline is:

```text
local YAML file
-> safe YAML parse
-> raw config/document/path/reference observations
-> optional profile-specific ecosystem summaries
-> canonicalize using existing config/document/path/reference model where possible
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

YAML extraction is local file analysis. It does not render templates, execute
commands, validate remote schemas, consult APIs, decrypt secrets, or fetch
references.

YAML0 accepts generic configuration graph identity as the public model for
YAML1:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`

YAML-specific facts should be represented as metadata on these existing raw
observation kinds unless a later implementation proves that additional raw
kinds are required.

YAML0 does not add ecosystem-specific canonical namespaces. Kubernetes, Helm,
GitHub Actions, OpenAPI, Docker Compose, Grafana, Harness, Serena, Arq Backup,
and similar profiles are profile hints and metadata first.

## Scope

In scope:

- YAML graph model design;
- safe static YAML parser policy;
- multi-document YAML streams;
- duplicate-key policy;
- anchors, aliases, and merge-key policy;
- inert custom tag policy;
- generic configuration-path identity;
- conservative reference detection;
- profile hints for YAML-heavy ecosystems;
- redaction policy for YAML and infrastructure configuration;
- fixtures and tests required for YAML1; and
- future phase planning.

Out of scope:

- implementing YAML parsing;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding source ingestion;
- adding MCP tools;
- adding storage migrations;
- changing existing JSON, TOML, XML, DOCS, storage, or public readback
  behavior; and
- Phase F migration.

## Product Posture

YAML graphing must remain boring, local, static, and auditable.

Requirements:

- local files only;
- no network;
- no schema fetching;
- no Helm template rendering;
- no Kubernetes API access;
- no OpenAPI remote `$ref` fetching;
- no Docker daemon access;
- no GitHub, GitLab, CircleCI, Harness, or Grafana API calls;
- no secret decryption;
- no execution of YAML-defined commands;
- no workflow execution;
- no admission, controller, or defaulting simulation;
- no package, chart, or dependency fetching; and
- no external validation services.

## Supported Files

Future YAML1 should route:

- `.yaml`
- `.yml`

Future discovery may add explicit path/profile hints for:

- `docker-compose.yml`
- `docker-compose.yaml`
- `.github/workflows/*.yml`
- `.github/workflows/*.yaml`
- `.circleci/config.yml`
- Helm `Chart.yaml`
- Helm `values.yaml`
- Kubernetes manifest YAML
- Spring Boot `application.yml`
- Spring Boot `application-*.yml`
- OpenAPI YAML
- Grafana provisioning YAML
- Harness pipeline YAML
- Serena YAML config when local and plain YAML
- custom Arq Backup dump YAML when local and plain YAML

Explicit filenames are profile hints only. They must not trigger command
execution, network calls, schema fetching, or ecosystem-specific canonical
namespaces in YAML1.

## Parser Policy

YAML1 should use a safe parser configuration. It may use an existing approved
dependency if the project already accepts one for safe YAML parsing. If a new
dependency is needed, that dependency choice belongs in YAML1 implementation
review, not YAML0.

YAML1 parser requirements:

- parse local bytes only;
- support enough YAML 1.1 and YAML 1.2 for common configuration files;
- support multi-document YAML streams;
- reject duplicate keys or emit explicit diagnostics according to a documented
  deterministic policy;
- record anchors and aliases conservatively;
- do not execute tags;
- do not instantiate arbitrary objects;
- do not resolve external resources;
- do not process custom tags except as inert metadata;
- enforce maximum file bytes;
- enforce maximum document count;
- enforce maximum node count;
- enforce maximum nesting depth;
- enforce maximum scalar length;
- enforce alias expansion limits; and
- preserve parse diagnostics.

Malformed YAML emits `config.parse_error` and does not fabricate precise graph
facts.

## Tags

Built-in scalar tags may be normalized as scalar types.

Custom tags such as `!Ref`, `!Sub`, `!include`, `!vault`, `!secret`, or
application-specific tags are inert metadata only. They must not trigger file
loading, network access, shell commands, object construction, secret
decryption, or template rendering.

Secret-like tags must trigger redaction policy. A tagged scalar may still emit
a `config.path` observation with safe metadata such as value type, tag name,
redaction status, and structural pointer.

## Anchors, Aliases, And Merge Keys

YAML1 should preserve anchor and alias metadata when feasible:

- anchor definitions as metadata on path observations;
- alias references as raw metadata or `references` edges only when
  deterministic and useful;
- unsupported anchor behavior as diagnostics; and
- alias expansion limits to avoid exponential blowup.

YAML merge keys (`<<`) should not be deeply materialized into canonical
identity in YAML1. The implementation may record merge-key use and alias
references while keeping canonical paths tied to the parsed physical file
structure.

A later phase may accept a conservative merged-view mode if there is a clear
need and tests prove stable behavior.

## Raw Observations

YAML1 should reuse ADR 0010 observation kinds:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`

YAML-specific raw kinds are deferred unless implementation proves they are
needed:

- `config.yaml_document`
- `config.yaml_anchor`
- `config.yaml_alias`
- `config.yaml_tag`
- `config.yaml_profile`

YAML metadata fields may include:

- `format`: `yaml`;
- `parser`;
- `document_index`;
- `document_count`;
- `yaml_tag`;
- `anchor`;
- `alias`;
- `merge_key`;
- `profile`;
- `schema_hint`;
- `duplicate_key_policy`;
- `redacted`;
- `redaction_reason`;
- `array_policy`; and
- `identity_strength` when a structural identity is weak.

## Canonical Namespaces

YAML1 should reuse ADR 0010 canonical namespaces:

- `config.document:<encoded-file-key>`
- `config.path:<encoded-file-key>:<encoded-config-pointer>`

YAML0 explicitly defers ecosystem namespaces:

- `k8s.*`
- `helm.*`
- `github_actions.*`
- `circleci.*`
- `openapi.*`
- `grafana.*`
- `spring.*`
- `docker.*`
- `harness.*`
- `serena.*`
- `arq.*`

Ecosystem-specific namespaces may be proposed later only if generic
configuration graph facts prove insufficient.

Canonical keys must not include:

- scalar values;
- secret values;
- credentials;
- tokens;
- current time;
- absolute machine paths;
- parser object IDs;
- extractor versions;
- model-generated labels;
- resolved runtime values; or
- network-derived values.

## Pointer Model

YAML paths should use ADR 0010 JSON Pointer style where possible:

- mapping keys become pointer segments;
- `~` is escaped as `~0`;
- `/` is escaped as `~1`;
- document-level pointers refer to the parsed YAML document, not arbitrary
  rendered or merged views;
- the empty pointer represents the whole document and normally maps to
  `config.document`, not `config.path`.

Multi-document YAML requires deterministic document identity. YAML1 should
store `document_index` as metadata and include document context in the
extractor-local `source_id`. If the canonical `config.path` key would otherwise
collide across documents, the pointer grammar may include a reserved
document-index segment such as `/documents/<n>/...`, but YAML1 must document
the exact choice and keep it stable.

ADR 0010 discourages numeric indexes for ordinary arrays. YAML0 keeps that
policy:

- ordinary arrays should not create durable numeric canonical identity when the
  list is unordered or user-reorderable;
- ordered semantic arrays may record numeric index as evidence or weak
  structural metadata;
- profile-known arrays should use stable member keys when available.

Examples:

- Kubernetes `containers[]`: prefer container `name` when available.
- Kubernetes `ports[]`: prefer port name or a safe container plus port tuple
  when available.
- GitHub Actions `jobs.<job_id>`: map key identity is stable.
- GitHub Actions `steps[]`: numeric index is weak and structural; `id` may be
  stable when present, while `name` is generally display metadata.
- OpenAPI `paths./pets.get`: map keys are stable.
- Docker Compose `services.<service_name>`: map keys are stable.
- Helm `values.yaml` arrays: treat cautiously as value semantics.
- Grafana panels: prefer stable panel IDs if present; otherwise use structural
  index only as weak evidence.

## Edge Vocabulary

YAML0 adds no edge kind.

Use existing edge kinds:

- `defines`
- `references`

Expected canonical edges:

- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> file:* | external.url:* | external:* | unknown:* | dynamic:*`

Markdown `links_to` remains Markdown-specific. YAML syntactic links use
`references`.

## Reference Model

YAML1 should emit `config.reference` only for conservative syntactic
references. Candidate references include:

- local file paths;
- container images;
- Docker build contexts;
- Kubernetes ConfigMap, Secret, service account, PVC, and similar names;
- Helm chart dependencies;
- OpenAPI `$ref`;
- GitHub Actions `uses`;
- reusable workflow references;
- CircleCI orb references;
- CircleCI Docker images;
- Harness connector, template, and secret references;
- Grafana datasource, dashboard, and folder references;
- Spring profile includes and imports;
- Arq destination or profile references when the file is a local plain dump;
- Serena project, tool, or server references when local and plain YAML.

Target policy:

- repo-local paths -> `file:*`;
- repo-escaping paths -> `unknown:file:repo-escaping-config-reference`;
- absolute filesystem paths -> `external:file:absolute-config-reference`;
- `http`, `https`, and `mailto` -> `external.url:*`;
- Docker images -> `external:*` or raw metadata unless a later package/image
  target vocabulary is accepted;
- GitHub Actions `uses` -> `external:*` or raw metadata unless a later package
  target vocabulary is accepted;
- OpenAPI remote refs -> `external.url:*`, never fetched;
- local OpenAPI refs -> `file:*` or same-document pointer metadata when
  conservative;
- Kubernetes object name references -> raw/reference metadata unless a later
  `k8s.*` model is accepted;
- unknown, dynamic, template, or expression-bearing targets -> `dynamic:*`,
  `unknown:*`, or raw-only diagnostics.

References are never fetched.

## Redaction

YAML1 reuses ADR 0010 secret markers:

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

YAML1 also adds infrastructure/configuration markers:

- `client_secret`
- `secret_key`
- `access_token`
- `id_token`
- `session`
- `cookie`
- `kubeconfig`
- `service_account`
- `dockerconfigjson`
- `registry_password`
- `connection_string`
- `jdbc_url`
- `datasource_password`
- `grafana_api_key`
- `arq_encryption_key`
- `arq_password`
- `arq_destination_password`

YAML1 must redact values when:

- key name is secret-prone;
- tag is secret-prone;
- path is secret-prone;
- value looks like a private key or token;
- the value is under Kubernetes Secret `data` or `stringData`;
- the value is Docker auth config;
- the value references GitHub Actions `secrets` context;
- CircleCI context or environment values are secret-prone;
- Harness secret refs are present;
- Spring datasource or password config is present;
- Grafana `secureJsonData` is present;
- Arq Backup credentials, encryption keys, or passwords are present;
- Serena tokens or keys are present.

Requirements:

- secret values must not appear in canonical keys;
- secret values must not appear in raw observation metadata;
- secret values must not appear in canonical node metadata;
- secret values must not appear in edge metadata;
- secret values must not appear in golden fixtures;
- secret values must not appear in CLI readback or explain output.

Redacted observations may preserve safe metadata:

- value type;
- `redacted=true`;
- redaction reason;
- key, path, or tag name;
- document index; and
- structural pointer.

## Profile Detection

YAML0 defines profile hints, not full ecosystem graph models.

Profile hints may be detected from path, filename, or shallow content:

- `kubernetes`
- `helm_chart`
- `helm_values`
- `spring_boot`
- `openapi`
- `docker_compose`
- `github_actions`
- `circleci`
- `grafana`
- `harness`
- `serena`
- `arq_backup`
- `generic_yaml`

Profile detection must:

- be deterministic;
- be metadata only in YAML1;
- not create ecosystem-specific canonical namespaces;
- not trigger network or API calls;
- not execute tools;
- not validate against remote schemas.

## Profile Notes

### Kubernetes

Recognize `apiVersion`, `kind`, `metadata.name`, and `metadata.namespace`.
References may include images, ConfigMaps, Secrets, service accounts, PVCs,
ingress hosts, and ports. Kubernetes Secret `data` and `stringData` must be
redacted.

YAML1 must not call the Kubernetes API, run `kubectl`, or simulate admission,
controllers, defaults, scheduling, or runtime state.

### Helm

Recognize `Chart.yaml`, `values.yaml`, and `templates/*.yaml` as YAML files.
YAML1 must not render templates, run Helm, fetch dependencies, or resolve chart
repositories. Chart dependencies may be conservative references. Values remain
generic config paths unless a later Helm model is accepted.

### Spring Boot

Recognize `application.yml` and `application-*.yml`. Profile includes and
imports may be references. Datasource, password, and credential keys must be
redacted. YAML1 must not boot the application or resolve environment-specific
values.

### OpenAPI

Recognize `openapi`, `swagger`, `info`, `paths`, and `components`. `$ref`
targets may become references. Remote refs are never fetched. Local refs remain
local file or same-document pointer metadata. YAML1 performs no external schema
validation.

### Docker Compose

Recognize `services`, `networks`, `volumes`, `configs`, and `secrets`. Images,
build contexts, env files, and referenced compose files may be references.
YAML1 must not contact the Docker daemon or render `compose config`. Secret and
environment values are redacted.

### GitHub Actions

Recognize `.github/workflows/*.yml` and `.github/workflows/*.yaml`. Jobs,
steps, `uses`, `with`, `env`, and `secrets` contexts may be summarized.
Actions and reusable workflows are references. YAML1 must not call the GitHub
API or execute workflows. Secret contexts are redacted.

### CircleCI

Recognize `.circleci/config.yml`. Jobs, workflows, executors, orbs, and
commands may be summarized. Orb references and Docker images may be references.
YAML1 must not call CircleCI APIs or execute pipelines. Context and
environment values are redacted when secret-prone.

### Harness

Recognize common Harness pipeline keys when present. Connector, template, and
secret refs may be references or raw metadata. YAML1 must not call Harness APIs
or execute pipelines. Secret refs are redacted or summarized.

### Grafana

Recognize provisioning configs and dashboard-like YAML where applicable.
Datasource, dashboard, and folder references may be metadata or references.
`secureJsonData` must be redacted. YAML1 must not call Grafana APIs.

### Serena

Recognize local Serena YAML configs by filename, path, or content when
feasible. Project, tool, or server references may be metadata or references.
Tokens and keys must be redacted. YAML1 must not execute Serena or modify
Serena state.

### Custom Arq Backup Config Dumps

Recognize configured local Arq Backup dump YAML by path or profile hint, not by
scanning system backup locations. Destination, profile, schedule, and
encryption metadata may be summarized. Credentials, encryption keys, and
passwords must be redacted.

YAML1 must not run Arq commands, access backup repositories, or call cloud
providers.

## YAML Document Model

For every parsed YAML file, YAML1 should:

- emit one `config.document` observation;
- emit `config.path` observations for object keys and safe scalar or collection
  structure;
- emit `config.reference` observations for conservative syntactic references;
- emit `config.parse_error` observations for malformed YAML or unsupported
  dangerous constructs;
- include profile metadata when detected.

For multi-document YAML:

- each document gets a document index;
- paths include document context in metadata and/or pointer identity;
- Kubernetes multi-document manifests preserve document order as evidence;
- canonical identity does not use body text, current time, parser object IDs,
  or model-generated labels.

## Fixtures For YAML1

YAML1 should add fixtures under:

```text
src/test/fixtures/discovery/yaml_basic/
src/test/fixtures/canonicalization/yaml_basic/
```

Fixture coverage should include generic examples for:

- generic YAML;
- multi-document Kubernetes manifest;
- Kubernetes Secret with fake redacted values;
- Helm `Chart.yaml`;
- Helm `values.yaml`;
- Spring Boot `application.yml`;
- OpenAPI YAML with local and remote `$ref`;
- Docker Compose YAML;
- GitHub Actions workflow;
- CircleCI config;
- Grafana provisioning YAML;
- Harness pipeline YAML;
- Serena config YAML;
- custom Arq Backup config dump YAML;
- malformed YAML;
- duplicate key YAML;
- anchors, aliases, and merge keys;
- unsupported custom tags;
- secret marker redaction.

Fixtures must not use real credentials, real private backup destinations, or
real internal service names. Use `example.invalid` and obviously fake values.

## Required YAML1 Tests

YAML1 must test:

- generic YAML parsing;
- multi-document YAML parsing;
- duplicate-key behavior;
- anchors and aliases;
- merge keys or diagnostics;
- inert custom tags;
- malformed YAML diagnostics;
- max depth, node, scalar, and file limits;
- `config.document` and `config.path` canonicalization;
- reference extraction;
- secret-prone key, tag, path, and value redaction;
- Kubernetes profile detection and Secret redaction;
- Helm profile detection without rendering;
- Spring Boot profile detection and password redaction;
- OpenAPI `$ref` detection without fetching;
- Docker Compose references without Docker access;
- GitHub Actions `uses` references without GitHub API or workflow execution;
- CircleCI orb and image references without CircleCI API;
- Grafana `secureJsonData` redaction without Grafana API;
- Harness secret and connector refs without Harness API;
- Serena config redaction without execution;
- Arq Backup dump redaction without Arq or cloud access;
- storage load/readback;
- explain output for one YAML reference edge;
- absence of secret values from readback and explain output.

## Rejected Alternatives

Rejected:

- rendering Helm templates in YAML1;
- running Kubernetes, Helm, Docker, GitHub, CircleCI, Harness, Grafana, Serena,
  or Arq tools;
- fetching schemas or remote refs;
- executing YAML-defined commands;
- decrypting secrets;
- adding ecosystem-specific canonical namespaces in YAML0;
- automatic scanning of backup or system configuration locations;
- MCP import or write tools;
- storing scalar secret values in canonical metadata;
- using YAML scalar values as canonical identity.

## Proposed Next Phases

- YAML1: generic YAML extraction with profile hints and references.
- YAML2: optional profile-specific readback polish if YAML1 generic config graph
  proves insufficient.
- K8S0, HELM0, OPENAPI0, or similar ecosystem ADRs only if a specific ecosystem
  needs first-class namespaces.
- Return to MCP/readback polish only after YAML1 proves useful on RepoMap and
  private `.flakes`.

## Verification

YAML0 is docs-only. Verification is:

```sh
git diff --check
git diff --cached --check
```

Python tests are intentionally not run because this phase adds only an ADR and
does not change parser, discovery, canonicalization, storage, CLI, or MCP
behavior.
