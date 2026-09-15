# ADR 0024: Documented API Ingestion Architecture

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0014: Source Ingestion Architecture
- ADR 0015: Feed Graph Model
- ADR 0016: Saved-Page And Static Artifact Ingestion
- ADR 0017: WARC Archive Graph Model
- ADR 0022: Static Email Graph Model
- ADR 0023: Bulk Local Corpus Ingestion
- RSS2 configured feed ingestion exit audit
- ARCHIVE1 local static artifact ingestion exit audit
- WARC1 local WARC import extraction exit audit
- MAIL3 email readback polish exit audit
- BULK1 safe local import exit audit
- BULK2 readback polish exit audit

## Context

RepoMap now supports deterministic local graphing for source code,
configuration, documents, saved/static artifacts, WARC payloads, feeds,
JavaScript assets, local `.eml` files, local `.mbox` files, and policy-gated
bulk local corpus imports.

API ingestion is the next architectural boundary after MAIL and BULK, but it
must not jump straight to Gmail, Microsoft Graph, IMAP, SMTP, or any other
provider-specific integration. API acquisition is different from extraction and
from BULK:

- local static extraction analyzes bytes already present in a repository or
  artifact;
- BULK imports local files already present on disk;
- feed ingestion uses explicit feed policy and feed-specific acquisition rules;
- saved-page and WARC phases analyze local artifacts or archived payloads; and
- API acquisition requests remote data from documented APIs only after explicit
  user configuration, source policy, credentials, consent, endpoint allowlists,
  rate limits, and retention rules are in place.

The product story is:

RepoMap may eventually acquire data from documented APIs only when the user has
explicitly configured and authorized that source. API acquisition must be
policy-gated, rate-limited, auditable, read-only by default,
credential-safe, retention-aware, and mutation-guarded. API0 defines the
architecture only; it does not implement acquisition.

## Decision

RepoMap will model API ingestion as documented, user-authorized,
policy-gated acquisition that materializes local artifacts or normalized
response records before graphing.

The future API pipeline is:

```text
explicit API source config
-> source policy validation
-> credential/consent validation
-> rate-limit and retention policy validation
-> documented endpoint allowlist
-> read-only acquisition request planning
-> API response capture as local artifact/record
-> redaction and retention handling
-> route local artifacts through existing extractors when applicable
-> load observations through existing storage path
-> expose through existing readback and future read-only summaries
```

API0 is architecture only. It does not implement API ingestion, add CLI
commands, add OAuth, add credential storage, add network calls, add provider
behavior, add scheduler behavior, add discovery routing, add canonicalization
code, add fixtures, add tests, add MCP tools, add storage migrations, or change
MAIL, BULK, ARCHIVE, WARC, DOCS, YAML, RUBY, JS, HTML, CSS, feed, storage, or
public readback behavior.

## API And BULK Boundary

API acquisition and BULK local import are separate phases:

- BULK imports files the user already has on disk.
- API acquires data from remote documented APIs into local RepoMap-owned
  artifacts or response records.
- BULK may later ingest API-produced local artifact dumps after acquisition is
  complete.
- API acquisition must never be implicit inside BULK.
- BULK configs must not become a hidden provider sync mechanism.

This boundary keeps local corpus traversal, provider credentials, network
policy, consent, rate limits, and retention concerns independently auditable.

## Scope

In scope:

- documented API ingestion architecture;
- provider-neutral source classes;
- explicit source policy;
- credential reference model;
- consent model;
- endpoint allowlists;
- read-only default posture;
- rate-limit, retry, and retention requirements;
- API run artifact layout;
- generic raw observation vocabulary for future phases;
- response routing to existing extractors;
- redaction requirements;
- failure model;
- illustrative future CLI/config shape;
- future API1 test requirements; and
- provider-specific phase boundaries.

Out of scope:

- implementing API ingestion;
- adding CLI commands;
- implementing OAuth;
- adding credential storage;
- making network calls;
- adding Gmail API behavior;
- adding IMAP or SMTP behavior;
- adding Microsoft Graph behavior;
- adding provider-specific acquisition;
- adding scheduler or webhook behavior;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding MCP tools;
- adding storage migrations;
- changing MAIL, BULK, ARCHIVE, WARC, DOCS, YAML, RUBY, JS, HTML, CSS, feed,
  storage, or public readback behavior; and
- Phase F migration.

## Product Posture

API ingestion must be documented, explicit, auditable, and safe by default.

Requirements:

- documented APIs only;
- explicit user configuration only;
- explicit source policy required;
- explicit authorization and consent model required;
- read-only by default;
- mutation disabled by default;
- no write or mutate endpoints unless a future ADR explicitly accepts them;
- endpoint allowlist required;
- provider terms and rate-limit model required;
- retention policy required;
- redaction policy required;
- credential-handling model required;
- no arbitrary URL fetching;
- no scraping;
- no crawling;
- no browser automation;
- no login-wall automation;
- no CAPTCHA handling;
- no anti-bot circumvention;
- no secret leakage into graph facts;
- no MCP write, import, or run tools in API0; and
- no provider-specific implementation in API0.

## Source Classes

API source classes are metadata only. They do not create provider-specific graph
namespaces in API0.

Supported future source classes:

- `api.rest`
- `api.graphql`
- `api.webhook_export`
- `api.bulk_export`
- `api.provider_export`
- `api.email_provider`
- `api.issue_tracker`
- `api.document_provider`
- `api.calendar_provider`
- `api.storage_provider`
- `api.chat_provider`
- `api.code_hosting_provider`
- `api.observability_provider`
- `api.crm_provider`
- `api.custom_documented_api`

API0 explicitly defers provider-specific canonical namespaces, including:

- `gmail.*`
- `google_mail.*`
- `imap.*`
- `smtp.*`
- `microsoft_graph.*`
- `outlook.*`
- `exchange.*`
- `github.*`
- `slack.*`
- `notion.*`
- `jira.*`
- `linear.*`
- `google_drive.*`
- `google_calendar.*`

Provider-specific canonical namespaces require later ADRs.

## Source Policy

API acquisition requires source policy before any network request. An absent,
ambiguous, or incomplete policy fails closed.

Policy fields should include:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name`;
- `provider_product`;
- `policy_status`;
- `allowed_endpoints`;
- `allowed_methods`;
- `read_only`;
- `mutation_allowed`;
- `credentials_ref`;
- `consent_ref`;
- `rate_limit_profile`;
- `retention_policy`;
- `redaction_profile`;
- `sensitivity`;
- `provenance_label`;
- `created_by`;
- `created_at`;
- `expires_at`;
- `max_requests_per_run`;
- `max_bytes_per_run`;
- `max_items_per_run`;
- `pagination_policy`;
- `retry_policy`; and
- `backoff_policy`.

Allowed policy statuses:

- `allowed`
- `allowed_with_limits`

Rejected or blocked statuses:

- `unknown`
- `blocked`
- `requires_review`
- `requires_login`
- `terms_unclear`
- `unsafe`
- `dynamic_source_deferred`
- `mutation_not_allowed`
- `credential_missing`
- `consent_missing`
- `rate_limit_unknown`

API implementations must fail closed unless policy, consent, credentials,
allowed endpoints, and rate limits are explicit.

## Credential Handling Model

API0 defines credential safety without implementing credential storage or
credential access.

Requirements:

- no credentials in repo files;
- no credentials in canonical keys;
- no credentials in raw observation metadata;
- no credentials in manifests;
- no credentials in logs;
- no credentials in readback or explain output;
- no credentials in committed fixtures;
- credentials are referenced only by opaque local secret reference;
- secret references never expose token values;
- token refresh behavior is deferred unless a future ADR accepts it; and
- credential validation must not leak token values.

Allowed credential reference shapes for future configs:

- `local_secret_ref:<name>`
- `os_keychain_ref:<name>`
- `env_ref:<name>`

API0 does not read environment variables, access an OS keychain, implement
OAuth, refresh tokens, or validate credentials.

## Consent Model

API acquisition requires explicit consent metadata before any request.

Consent fields should include:

- `consent_id`;
- `user_id` or local user label;
- `scope_description`;
- `authorized_source_id`;
- `authorized_operations`;
- `authorized_data_classes`;
- `created_at`;
- `expires_at`;
- `revoked`;
- `retention_policy`; and
- `mutation_allowed`.

Default consent allows read-only data export or acquisition only.

Default rejected operations:

- mutation;
- sending;
- deleting;
- labeling;
- writing;
- webhook registration;
- subscription creation;
- archiving;
- marking read or unread; and
- any provider state change.

For future email providers, default consent still rejects sending, deleting,
archiving, labeling, marking read or unread, and mailbox mutation unless a
later ADR explicitly accepts a mutation model.

## Endpoint Allowlist

API implementations must use explicit endpoint allowlists.

Each endpoint policy should include:

- provider;
- method;
- path or template;
- purpose;
- expected response type;
- max page size;
- pagination behavior;
- allowed query parameters;
- prohibited query parameters;
- response retention class;
- redaction class; and
- downstream route.

Default allowed method:

- `GET`

Disallowed by default:

- `POST`
- `PUT`
- `PATCH`
- `DELETE`

Write methods require a separate mutation ADR and must not be included in API0.

## Rate Limits And Retries

API phases must model provider limits before implementation.

Required fields:

- max requests per run;
- max requests per minute;
- max concurrent requests;
- max bytes per run;
- max items per run;
- retryable status codes;
- max retries;
- backoff strategy;
- jitter policy;
- hard stop behavior; and
- provider quota notes.

Default behavior:

- conservative request limits;
- no concurrency unless explicitly accepted;
- stop on unknown rate-limit state; and
- fail closed when rate-limit policy is absent.

## Retention Model

API acquisitions produce local artifacts or normalized records. Retention must
be explicit before acquisition.

Retention fields should include:

- artifact retention period;
- raw response retention class;
- redacted response retention class;
- delete-after policy if supported;
- local-only policy;
- user-controlled deletion note;
- sensitivity class;
- allowed storage path; and
- prohibited storage path.

Default retention:

- local user controlled;
- raw responses minimized;
- redacted manifests preferred; and
- no cloud upload.

## Acquisition Artifacts

Future API implementations should write under RepoMap-owned paths, such as:

```text
.repomap/api-runs/<source-id>/<api-run-id>/
```

Possible files:

- `plan.json`;
- `manifest.json`;
- `requests.jsonl`;
- `responses.jsonl`;
- `redacted-responses.jsonl`;
- `diagnostics.jsonl`; and
- `artifacts/`.

Do not store:

- credentials;
- authorization headers;
- cookies;
- refresh tokens;
- access tokens;
- session IDs;
- raw secrets; or
- unnecessary raw response bodies when redacted records suffice.

API run IDs should be deterministic where practical from:

- `source_id`;
- policy hash;
- endpoint allowlist hash; and
- request plan hash.

Timestamps may be metadata only. They must not be run identity.

## Future Raw Observations

Future API phases may define generic raw/provenance observations:

- `api.source`
- `api.run`
- `api.request`
- `api.response`
- `api.item`
- `api.artifact`
- `api.reference`
- `api.diagnostic`

Initial API phases should keep these raw and provenance-first. They should not
force a generic API canonical graph before implementation evidence shows that it
is useful.

## Canonical Namespace Policy

API0 defers generic `api.*` canonical namespaces.

Preferred behavior:

- API source, run, request, and response facts remain provenance/raw manifest
  facts;
- downstream extracted domain facts use existing namespaces such as `email.*`,
  `document.*`, `config.*`, `js.*`, `feed.*`, and `file:*`; and
- provider-specific identity requires provider-specific ADRs.

Possible future namespaces only if needed:

- `api.source:<encoded-source-id>`
- `api.run:<encoded-api-run-id>`
- `api.request:<encoded-request-id>`
- `api.response:<encoded-response-id>`
- `api.item:<encoded-item-id>`

No provider-specific canonical namespace is accepted in API0.

## Edge Vocabulary

API0 adds no new edge kind.

Future API facts should reuse existing edge kinds only:

- `defines`
- `references`

## Response Routing

API responses may become:

- local JSON or JSONL artifacts routed through configuration extraction;
- local EML or MBOX artifacts routed through MAIL;
- local documents routed through DOCS;
- local saved-page or static artifacts routed through ARCHIVE;
- local feed artifacts routed through feed extraction; or
- local generic API records kept as redacted response manifests.

Do not route:

- executable content;
- attachment bodies unless a later ADR accepts them;
- remote references;
- HTML rendering;
- JavaScript execution; or
- dynamically resolved provider state.

## Future Email Provider Model

API0 may inform future email provider phases, but it does not implement them.

Future Gmail, Microsoft, IMAP, or other email provider phases require:

- explicit provider ADR;
- explicit source policy;
- explicit consent;
- explicit credential model;
- read-only default;
- endpoint allowlist;
- no sending;
- no deleting;
- no archiving;
- no labeling;
- no marking read or unread;
- no mailbox mutation;
- export messages as local EML-like artifacts or redacted API records;
- route local artifacts through MAIL or BULK only after acquisition;
- no remote image loading;
- no attachment body download unless a later ADR accepts it;
- no body indexing unless a later ADR accepts it; and
- no provider-thread truth claims in the generic email graph.

Email provider phases are future work after API0.

## Webhooks And Schedules

API0 defers active scheduling and webhook registration.

Rejected in API0:

- schedulers;
- recurring API polling;
- webhook registration;
- listener/server behavior; and
- background tasks.

Future scheduler or webhook support requires a separate ADR.

## Mutation Model

Mutation is rejected by default.

Rejected in API0:

- `POST`, `PUT`, `PATCH`, or `DELETE` acquisition;
- sending email;
- modifying labels;
- creating calendar events;
- changing issues or tickets;
- writing comments;
- uploading files;
- registering webhooks;
- creating subscriptions; and
- deleting remote records.

Future mutation support requires a separate ADR, explicit user action, dry-run
support, confirmation, idempotency, audit logs, and rollback or compensation
model where possible.

## Redaction

API responses are sensitive and may contain personal data, provider IDs,
secrets, tokens, cookies, URLs with identifiers, and embedded documents.

Redaction requirements:

- no credentials;
- no auth headers;
- no cookies;
- no tokens;
- no secrets;
- no raw personal data in canonical keys;
- no raw email bodies in API manifests;
- no raw email addresses unless a downstream model safely hashes or redacts
  them;
- no provider mutable IDs in generic canonical keys unless a future ADR accepts
  them;
- no raw response bodies in readback unless explicitly redacted and allowed;
- no sensitive URLs with tracking identifiers; and
- no full absolute machine paths.

## Provider Mutable IDs

Provider IDs can be useful but dangerous.

Policy:

- raw provider IDs may be stored as redacted or hashed metadata only if needed;
- provider mutable IDs are not generic domain canonical identity by default;
- provider-specific identity requires provider ADRs; and
- generic extracted facts should use existing identity rules.

## Failure Model

API acquisition should fail closed before network and fail soft after an
approved request plan begins.

Future implementations should distinguish:

- policy failure;
- missing consent;
- missing credential;
- endpoint not allowlisted;
- method not allowed;
- rate limit exceeded;
- provider error;
- network error;
- parse error;
- redaction error; and
- retention/storage error.

Artifacts should record safe diagnostics without secrets.

## Illustrative Future CLI

Future phases may add commands like:

```sh
repomap-kg api plan --config api-source.toml --json
repomap-kg api acquire --config api-source.toml --json
repomap-kg storage api-summary --root-path <repo> --json
```

These commands are illustrative only. API0 does not implement them.

## Illustrative Future Config

This TOML example is illustrative only and is not implemented in API0:

```toml
[source]
source_id = "example-readonly-api"
source_type = "api.rest"
api_source_class = "api.custom_documented_api"
provider_name = "Example Provider"
provider_product = "Example API"
policy_status = "allowed_with_limits"
read_only = true
mutation_allowed = false

[credentials]
credentials_ref = "local_secret_ref:example-api-token"

[consent]
consent_ref = "local_consent_ref:example-readonly-api-2026-07"

[limits]
max_requests_per_run = 100
max_requests_per_minute = 10
max_bytes_per_run = 10485760
max_items_per_run = 1000

[[endpoints]]
method = "GET"
path = "/v1/items"
purpose = "Export item metadata"
response_type = "application/json"
max_page_size = 100
pagination = "cursor"

[retention]
policy = "local_user_controlled"
raw_response_retention = "minimized"
redacted_response_retention = "retain"

[redaction]
profile = "strict"
sensitivity = "private"
```

## Future API1 Tests

API0 requires future implementation tests for:

- config required;
- policy absent fails closed;
- blocked policy fails closed;
- missing consent fails closed;
- missing credentials reference fails closed;
- unsupported method fails closed;
- non-allowlisted endpoint fails closed;
- rate-limit policy required;
- retention policy required;
- redaction policy required;
- run plan deterministic;
- no network before validation;
- no credentials in logs, manifests, readback, or explain output;
- no mutation endpoints;
- no provider-specific namespaces;
- artifact path under `.repomap/api-runs/...`;
- response artifact redaction;
- failure diagnostics safe;
- no scheduler or webhook behavior; and
- no MCP import, write, or run behavior.

## Rejected Alternatives

Rejected in API0:

- implementing Gmail;
- implementing Microsoft Graph;
- implementing IMAP or SMTP;
- implementing OAuth;
- arbitrary URL fetching;
- scraping or crawling;
- login-wall automation;
- CAPTCHA handling;
- browser automation;
- anti-bot circumvention;
- mutation endpoints by default;
- scheduler or polling behavior;
- webhook registration;
- storing credentials in repo files, configs, manifests, readback, or explain
  output;
- provider-specific canonical namespaces;
- provider API acquisition hidden inside BULK;
- mailbox mutation;
- sending, deleting, archiving, labeling, or marking email;
- raw body indexing by default; and
- attachment downloads by default.

## Proposed Phases

- API1: generic documented REST API acquisition skeleton, if still desired.
- API2: API readback polish.
- GMAIL0/GMAIL1 only after an explicit Gmail ADR.
- MICROSOFT_GRAPH0 or OUTLOOK0 only after an explicit Microsoft/provider ADR.
- IMAP0 only after an explicit IMAP ADR.
- GITHUB_API0 only after an explicit GitHub API ADR.
- Scheduler or webhook support only after a separate ADR.
- Mutation support only after a separate ADR.

## Consequences

API0 keeps RepoMap's next acquisition boundary explicit and provider-neutral.
It makes future API work possible without weakening the local-only BULK model or
turning API support into implicit provider sync.

The cost is that provider integrations remain deferred. Future API phases must
first implement policy, consent, credential references, rate limits, retention,
redaction, and safe artifact storage before any provider-specific behavior can
land.
