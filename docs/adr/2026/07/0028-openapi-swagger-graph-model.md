# ADR 0028: OpenAPI And Swagger Graph Model

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
- ADR 0026: Terraform, JSON, And Ecosystem Configuration Graph Model
- ADR 0027: JS/TS Framework Source Extraction
- `docs/adr/2026/06/0010-structured-configuration-graph-model.md`
- `docs/adr/2026/06/0019-yaml-graph-model.md`
- `docs/adr/2026/07/0026-terraform-json-ecosystem-config-graph-model.md`
- `docs/adr/2026/07/0027-js-ts-framework-source-extraction.md`
- `docs/status/2026/07/01/00054-tfjson1-terraform-json-ecosystem-config-exit.md`
- `docs/status/2026/07/01/00056-js6-framework-readback-polish-exit.md`

## Context

RepoMap already extracts local structured configuration, YAML, Terraform JSON
and ecosystem JSON profiles, static JavaScript and TypeScript framework source
facts, and JS framework readback summaries. OpenAPI is the next useful
configuration and contract target because it connects backend services,
frontend clients, documentation, tests, and future route/API graphing without
requiring enterprise observability tooling or live service access.

OpenAPI and Swagger documents are API contract artifacts. They describe
declared API intent, not runtime truth. A repository may contain stale specs,
generated specs, hand-written specs, partial specs, public-facing specs,
internal specs, test-only specs, or vendor examples. RepoMap should preserve
that distinction by modeling local OpenAPI/Swagger files as static evidence
with provenance and redaction, not by calling APIs, generating clients, or
asserting that runtime routes exist.

The current active first-class tooling stack for this line of work is:

- Liquibase;
- Docker;
- Kubernetes;
- Playwright;
- GitHub Actions;
- Argo CD;
- Terraform; and
- OpenAPI.

Prometheus, Grafana, Grafana Loki, and Vault remain archived until a later
enterprise, observability, or security-configuration phase. They do not
influence OPENAPI0.

OPENAPI0 defines architecture only. It does not implement extraction, change
JSON or YAML parsing behavior, add CLI commands, add fixtures, add tests, add
storage migrations, add MCP tools, validate specs against remote schemas,
fetch references, call APIs, generate clients or servers, run tooling, execute
source code, or change public readback defaults.

## Decision

RepoMap will model local OpenAPI and Swagger documents as static API contract
artifacts layered on the existing ADR 0010 configuration graph and ADR 0019
YAML graph posture.

The future OpenAPI pipeline is:

```text
local OpenAPI or Swagger JSON/YAML document
-> safe static JSON/YAML parse or conservative parse diagnostic
-> generic config.document/config.path/config.reference observations
-> optional OpenAPI profile raw observations
-> optional conservative canonical facts only after identity review
-> load through existing storage path
-> expose through existing readback and future read-only summaries
```

OpenAPI extraction is not API acquisition. It must not fetch remote `$ref`s,
fetch server URLs, validate through network schemas, call described endpoints,
execute examples, run Swagger UI, run OpenAPI Generator, generate clients,
generate servers, run web servers, or infer runtime behavior from the contract
alone.

The initial posture is raw/profile-observation first. Existing
`config.document`, `config.path`, and `config.reference` remain the base
public model for local JSON and YAML structure. OpenAPI-specific canonical
namespaces are deferred unless future implementation evidence proves that a
stable identity model is useful and consistent with ADR 0001, ADR 0002, and
ADR 0003.

## Scope

In scope:

- local OpenAPI and Swagger document graph model design;
- supported future file-family policy;
- supported OpenAPI and Swagger spec-family policy;
- static-only parser and extraction requirements;
- raw observation names for OpenAPI profile facts;
- possible future canonical namespaces;
- relationship to ADR 0010 JSON/config behavior;
- relationship to ADR 0019 YAML behavior;
- relationship to JS/TS framework route extraction;
- relationship to future Python web-framework extraction;
- local `$ref` and remote `$ref` policy;
- server URL and security scheme safety policy;
- redaction and privacy requirements;
- future implementation phases; and
- future test requirements.

Out of scope:

- implementing OpenAPI extraction;
- adding JSON or YAML extraction behavior;
- adding CLI commands;
- adding fixtures or tests;
- adding storage migrations;
- adding MCP tools;
- validating OpenAPI against remote schemas;
- fetching remote `$ref`s;
- fetching server URLs;
- calling APIs described by specs;
- generating clients;
- generating servers;
- running Swagger UI, OpenAPI Generator, validators, web servers, tests, or
  framework tooling;
- executing JavaScript, TypeScript, Python, examples, scripts, or generated
  code;
- linking OpenAPI operations to runtime route tables as truth;
- provider/API acquisition;
- public readback default changes; and
- Phase F migration.

## Product Posture

OPENAPI0 is not "call the API." OPENAPI0 is "statically map declared API
contract intent from local OpenAPI and Swagger documents."

Requirements for future implementation:

- local repository files only;
- no remote `$ref` fetching;
- no schema fetching;
- no server URL fetching;
- no API endpoint calls;
- no example execution;
- no Swagger UI execution;
- no OpenAPI Generator execution;
- no client or server generation;
- no live validation through network resources;
- no credential resolution;
- no secret exposure;
- no runtime-route truth claims from specs alone;
- no source execution;
- no framework startup;
- no provider/API acquisition; and
- no MCP import, write, or run tools.

OpenAPI facts should be deterministic, provenance-preserving, redaction-aware,
bounded, and explainable from local files.

## Supported Future File Families

Future OpenAPI phases may route explicit filenames:

- `openapi.json`;
- `openapi.yaml`;
- `openapi.yml`;
- `swagger.json`;
- `swagger.yaml`;
- `swagger.yml`;
- `*.openapi.json`;
- `*.openapi.yaml`;
- `*.openapi.yml`;
- `*.swagger.json`;
- `*.swagger.yaml`; and
- `*.swagger.yml`.

Future extraction may also detect local JSON or YAML documents with top-level
`openapi` or `swagger` keys when discovery and parser limits have already
classified the file safely.

OpenAPI profile detection must not cause network validation, schema fetching,
tool execution, or API calls.

## Supported Spec Families

Future extraction may support:

- OpenAPI 3.x; and
- Swagger/OpenAPI 2.0.

OpenAPI 3.1 should be accepted as OpenAPI 3.x if local parsing is safe.
OPENAPI1 should not require full schema validation. A malformed or unsupported
spec emits diagnostics rather than fabricating precise graph facts.

Swagger 2.0-compatible observations may reuse `openapi.*` raw observation
names with `spec_family = "swagger2"` metadata. OpenAPI 3.x observations
should use `spec_family = "openapi3"` or a more specific bounded value when
useful.

## Relationship To Existing Configuration Graph

OpenAPI and Swagger JSON/YAML documents layer on existing structured
configuration behavior:

- `config.document` remains the base document fact;
- `config.path` remains the base structural path fact;
- `config.reference` remains the base conservative reference fact;
- `config.parse_error` remains the base parse diagnostic where applicable;
- OpenAPI-specific observations are profile/raw observations beside generic
  config observations;
- canonical OpenAPI namespaces are deferred unless identity is stable and
  useful; and
- edge vocabulary remains the existing graph vocabulary.

Profile extraction must not replace generic configuration facts. A local
OpenAPI YAML file should still be inspectable through YAML/config paths, while
OpenAPI-specific facts provide contract-oriented evidence on top.

## Raw Observation Model

Future OpenAPI phases may emit raw/profile observations such as:

- `openapi.document`;
- `openapi.info`;
- `openapi.server`;
- `openapi.path`;
- `openapi.operation`;
- `openapi.parameter`;
- `openapi.request_body`;
- `openapi.response`;
- `openapi.schema`;
- `openapi.component`;
- `openapi.security_scheme`;
- `openapi.tag`;
- `openapi.reference`;
- `openapi.example`;
- `openapi.parse_error`; and
- `openapi.redaction`.

Only observations that can be implemented cleanly and tested well should be
added in the first implementation phase. Prefer fewer accurate observations
over broad noisy output.

Raw observations should include safe provenance metadata such as:

- source file path;
- source document key when available;
- spec family and version summary;
- extractor name and version;
- local JSON pointer or YAML path when available;
- line evidence when available;
- redaction status;
- confidence; and
- local-only reference classification.

Raw observations must not include raw credentials, authorization headers,
cookies, tokens, secret examples, credentialed URLs, large descriptions, large
examples, absolute machine paths, generated client names, or runtime route
truth claims.

## Core Extraction Targets

Future extraction may statically recognize:

- spec version;
- API title;
- API version;
- description presence;
- bounded description length/hash if needed;
- servers or Swagger `host`, `basePath`, and `schemes` as redacted/summarized
  references;
- path templates;
- HTTP methods;
- `operationId`;
- tags;
- summary and description presence;
- parameters;
- request body media types;
- response status codes;
- response media types;
- component and schema names;
- schema `$ref`s;
- security scheme names and types;
- security requirements;
- externalDocs presence and safe URL summary; and
- local file references where safe.

HTTP method labels are:

- GET;
- POST;
- PUT;
- PATCH;
- DELETE;
- OPTIONS;
- HEAD; and
- TRACE.

Descriptions, summaries, examples, defaults, and server URLs must be bounded
and redacted according to the policies below. Future readback should prefer
counts and safe summaries over raw text.

## Identity Guidance

Future stable identities may use:

- document identity from the local file key;
- path identity scoped by document plus normalized path template;
- operation identity scoped by document plus HTTP method and normalized path;
- component identity scoped by document plus component type and name; and
- schema identity scoped by document plus schema/component path.

Future identity must not use:

- server URL alone;
- `operationId` alone;
- line numbers;
- current time;
- absolute machine paths;
- remote URL contents;
- generated client or server names; or
- runtime route table assumptions.

`operationId` may be useful metadata and may participate in matching or
readback, but it is not globally unique enough to be the only identity.

Server URLs are references or summaries, not canonical API identity.

## Possible Future Canonical Namespaces

Potential canonical namespaces, only if a later implementation phase accepts
them after identity review, include:

- `openapi.document`;
- `openapi.path`;
- `openapi.operation`;
- `openapi.schema`;
- `openapi.component`;
- `openapi.security_scheme`; and
- `openapi.tag`.

OPENAPI0 does not accept broad OpenAPI canonical namespaces. The recommended
first implementation is raw/profile-first, with existing `config.document`,
`config.path`, and `config.reference` remaining the public canonical model.

## Edge Vocabulary

OPENAPI0 adds no new edge kinds.

Future extraction should prefer existing:

- `defines`; and
- `references`.

Examples:

- a file defines a configuration document;
- a file or document defines OpenAPI raw/profile facts;
- an operation references schemas, security schemes, or tags;
- a schema references other schemas;
- a document references local files; and
- a document references external URLs as safe, not-fetched summaries.

If later route-contract matching needs richer relationship semantics, that
requires a separate ADR or explicit implementation review.

## Reference Policy

OpenAPI `$ref` handling must remain no-fetch.

Internal references:

- internal references such as `#/components/schemas/User` may be recorded as
  local document references;
- internal references should preserve enough pointer information to explain the
  relationship;
- malformed internal references should emit diagnostics instead of guessed
  targets.

Local relative file references:

- relative file references may be recorded only if they normalize within the
  repository/root and are allowed by local file policy;
- repo-contained local refs may become `file:*` references or raw
  `openapi.reference` observations;
- references that escape the repository/root must be diagnostics or redacted
  summaries, not file reads.

Remote references:

- `http://...` and `https://...` `$ref`s must never be fetched;
- remote refs may be recorded as redacted `external.url:*` summaries with
  `not_fetched=true` if safe;
- credentialed URLs must be redacted or omitted;
- unknown or unsafe refs become raw diagnostics.

Do not fetch:

- remote schemas;
- external docs;
- server URLs;
- examples;
- OAuth or OpenID discovery docs;
- linked API docs;
- generated clients; or
- any URL discovered in the spec.

## Servers And Base URLs

Server URLs and Swagger `host`/`basePath`/`schemes` can contain environment
names, internal hostnames, credentials, private topology, or tenant-specific
paths.

Future extraction should:

- store server count;
- store scheme and host summary only when safe;
- store path presence or bounded path summary only when safe;
- redact credentialed URLs;
- optionally store hash, length, and presence metadata;
- mark all server URLs as `not_fetched=true`; and
- never call server URLs.

Server URLs must not become canonical API identity by themselves.

## Security Schemes

Future extraction may record safe metadata for security schemes:

- scheme name;
- type: `apiKey`, `http`, `oauth2`, `openIdConnect`, or `mutualTLS`;
- `in`: `header`, `query`, or `cookie` when applicable;
- HTTP scheme and bearer format when safe;
- OAuth flow names; and
- scope names only when safe.

Future extraction must not record:

- actual API key values;
- token examples;
- authorization headers;
- client IDs or secrets;
- OAuth URLs with credentialed query strings;
- cookies;
- private discovery document contents; or
- values from environment variables or secret stores.

Security requirements may reference security scheme names as contract facts,
but they must not imply that credentials exist or are valid.

## Examples, Defaults, And Descriptions

OpenAPI specs often include examples, defaults, descriptions, and vendor
extensions that may leak secrets or private implementation details.

For examples and defaults:

- default to presence, type, shape, hash, and bounded size metadata;
- omit or summarize body examples by default;
- redact schema examples with secret-like fields;
- bound large example payloads; and
- never store secret-looking literal values.

For descriptions and summaries:

- record presence;
- optionally record bounded length/hash;
- avoid raw descriptions by default unless a later readback policy accepts
  bounded safe excerpts;
- never include raw descriptions in canonical keys; and
- treat very large descriptions as summary-only metadata.

Vendor extensions such as `x-*` fields should be treated conservatively. They
may contain generated metadata, internal URLs, framework hints, or secrets.
Future implementation should record extension key presence and safe summaries
only when bounded and redacted.

## Redaction And Privacy

OpenAPI extraction must redact or summarize values for keys containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `api_key`;
- `apikey`;
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
- `authorization`;
- `jwt`;
- `database_url`;
- `webhook`;
- `oauth`;
- `openid`; and
- `x-api-key`.

Credentialed URLs must be redacted. API keys, bearer tokens, cookies,
authorization headers, JWT-looking values, private hostnames with credentials,
and secret examples must not appear in raw observations, canonical keys,
metadata, fixtures, readback, explain output, manifests, or status docs.

Redaction should happen before observations enter the raw/canonical pipeline.
When a value is redacted, preserve safe metadata such as field name, value
type, shape, length, hash, redaction reason, and confidence when useful.

## Relationship To JS/TS Framework Extraction

OpenAPI documents are contracts, not runtime route tables.

Future linking may compare OpenAPI operations to Express, NestJS, Next.js, or
other JS/TS route facts by method and path pattern. Such links should be
evidence-backed, confidence-labeled, and clearly described as possible
contract-to-source matches.

OPENAPI0 does not implement route matching. It must not treat OpenAPI docs as
proof that a route is implemented, and it must not treat source routes as proof
that a contract is current.

## Relationship To Future Python Web Framework Extraction

OpenAPI may later connect to Python web-framework evidence such as:

- FastAPI route declarations and generated OpenAPI docs;
- Flask or Connexion route/spec bindings; and
- Django or Django REST Framework schema docs.

OPENAPI0 does not assume a Python runtime framework, start services, call local
servers, fetch generated docs, or validate contracts against live behavior.

## Relationship To Generated Clients

OpenAPI may also explain generated client or server code already present in a
repository.

Future extraction may detect local evidence such as:

- generated client package markers;
- generated-source comments;
- operationId-like method names;
- API client source references; and
- local generated file paths.

OPENAPI0 must not generate clients or servers. It must not infer generated
status without local source/config evidence.

## Limits And Diagnostics

Future implementation should enforce deterministic limits for:

- maximum file bytes;
- maximum document count for YAML streams;
- maximum paths;
- maximum operations;
- maximum parameters per operation;
- maximum responses per operation;
- maximum schemas/components;
- maximum references;
- maximum examples/defaults retained as summaries;
- maximum description length considered for hashing; and
- maximum nesting depth.

Overflow should emit safe diagnostics or skip reasons. Diagnostics must not
include secret-like values, raw credentialed URLs, full descriptions, full
examples, or source contents.

Malformed specs should emit `openapi.parse_error` or generic configuration
parse diagnostics where appropriate and should not fabricate precise contract
facts.

## Future OPENAPI1 Tests

OPENAPI1 must include tests for:

- OpenAPI 3 JSON document detection;
- OpenAPI 3 YAML document detection;
- Swagger 2 JSON document detection;
- Swagger 2 YAML document detection;
- top-level `openapi` and `swagger` key detection;
- info title/version extraction;
- path and operation extraction;
- HTTP method extraction;
- `operationId` extraction;
- tag extraction;
- parameter extraction;
- request body extraction;
- response status and media type extraction;
- component and schema extraction;
- internal `$ref` extraction;
- local relative `$ref` extraction;
- remote `$ref` marked `not_fetched=true`;
- repository escape diagnostics for local refs;
- credentialed URL redaction;
- server URL summary and no-fetch markers;
- security scheme extraction with secrets omitted;
- examples/defaults redaction;
- descriptions summarized, not raw by default;
- large document limits;
- malformed spec diagnostics;
- generic `config.document` and `config.path` still emitted;
- no network fetch;
- no API calls;
- no Swagger/OpenAPI tool execution;
- no generated client or server execution; and
- no broad canonical namespaces unless a later phase explicitly accepts them.

## Proposed Phases

- OPENAPI1: static OpenAPI/Swagger JSON and YAML extraction implementation.
- OPENAPI2: OpenAPI readback summary polish.
- OPENAPI3: optional route-contract comparison ADR or implementation, only
  after JS/Python route extraction evidence exists.
- PYWEB0/PYWEB1: Python web-framework extraction if FastAPI, Flask,
  Connexion, Django, or Django REST Framework support becomes useful.

## Rejected Alternatives

Reject:

- calling APIs described by OpenAPI;
- fetching remote `$ref`s;
- validating against remote schemas;
- running Swagger UI or OpenAPI Generator;
- generating clients or servers;
- treating `operationId` as globally unique identity;
- treating server URLs as canonical identity;
- storing raw examples/defaults/descriptions without redaction policy;
- linking OpenAPI operations to runtime routes as truth without source
  evidence;
- scoping Prometheus, Grafana, Grafana Loki, or Vault into OPENAPI0;
- adding OpenAPI canonical namespaces before identity review; and
- mixing OpenAPI contract extraction with provider/API acquisition.

## Consequences

OPENAPI0 creates a clear boundary for future local API contract extraction. It
lets RepoMap represent OpenAPI/Swagger specs as local configuration and
contract evidence while preserving existing JSON/YAML behavior, JS framework
source boundaries, privacy constraints, and no-fetch posture.

The tradeoff is that initial OpenAPI facts remain evidence-first and may not
immediately provide polished canonical route or operation identities. That is
intentional. Future implementation should earn canonical namespaces and route
matching through tests, identity review, and readback evidence.

## Acceptance

OPENAPI0 is accepted only if it remains internally consistent,
architecture-only, static-only, local-first, no-fetch, no-execution,
redaction-aware, and clearly separates:

- OpenAPI contract extraction;
- JS/TS framework source extraction;
- future Python web-framework extraction;
- YAML infrastructure extraction; and
- provider/API acquisition.
