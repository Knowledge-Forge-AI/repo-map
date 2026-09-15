# ADR 0025: GitHub API Provider Architecture

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0014: Source Ingestion Architecture
- ADR 0023: Bulk Local Corpus Ingestion
- ADR 0024: Documented API Ingestion Architecture
- API1 Generic REST Acquisition Skeleton Exit Audit
- API2 API Readback Polish Exit Audit
- BULK2 Bulk Readback Polish Exit Audit
- GitHub REST API documentation: `https://docs.github.com/en/rest`
- GitHub REST API authentication documentation:
  `https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api`
- GitHub REST API rate-limit documentation:
  `https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api`
- GitHub REST API pagination documentation:
  `https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api`

## Context

ADR 0024 defines RepoMap's generic documented API ingestion model. API1 proved
a provider-neutral, fixture-only REST acquisition skeleton with policy-gated
planning, redacted RepoMap-owned run artifacts, safe config extraction routing,
and raw API provenance. API2 added read-only summary/readback for those generic
API runs.

GitHub is a natural first code-hosting provider candidate because its
documented REST API exposes repository metadata, issues, pull requests,
reviews, commits, releases, and Actions metadata that can help coding agents
reason about project activity. The first valuable public and developer demo is:

RepoMap can connect repository code facts with GitHub issues, pull requests,
reviews, commits, releases, and Actions metadata through deterministic,
provenance-preserving graph context for coding agents.

GITHUB_API0 only designs that provider boundary. It does not implement GitHub
API acquisition.

GitHub provider ingestion must remain separate from BULK. BULK imports local
files already present on disk. GitHub API acquisition would request remote data
from GitHub's documented REST API only after explicit policy, consent,
credential mode, endpoint allowlist, rate-limit, retention, and redaction
requirements are satisfied.

## Decision

RepoMap will treat GitHub REST API acquisition as a future read-only,
policy-gated documented API provider that materializes local RepoMap-owned
artifacts before graphing.

GITHUB_API0 specializes ADR 0024 for GitHub's documented REST API by defining:

- read-only provider posture;
- GitHub source policy requirements;
- explicit authorization and credential reference requirements;
- consent requirements;
- endpoint allowlist requirements;
- initial endpoint families for future phases;
- GitHub API run artifact layout;
- retention and redaction requirements;
- provider identity and URL safety rules;
- raw observation and provenance model;
- canonical namespace policy;
- failure model;
- future test requirements; and
- future phase plan.

GITHUB_API0 is architecture only. It does not implement a GitHub API client,
OAuth, GitHub App authentication, personal access token handling, network
acquisition, provider transport, scheduler, webhook handling, MCP tools,
storage migrations, fixtures, tests, extractors, provider-specific canonical
graph namespaces, new edge kinds, public readback default changes, Gmail,
Microsoft, IMAP, SMTP, other provider work, or Phase F migration.

## Relationship To API1 And API2

API1 proved a provider-neutral fixture-only REST acquisition skeleton. API2
added read-only API summary/readback. GITHUB_API0 defines the GitHub-specific
policy, endpoint, artifact, redaction, and identity boundaries that a future
GitHub implementation must follow.

A future GITHUB_API1 may reuse API1's config, planning, artifact, provenance,
and readback patterns. It must still be separately reviewed as a GitHub
provider phase. Reusing generic machinery must not hide GitHub acquisition
inside BULK or generic API behavior.

## Scope

In scope:

- ADR and architecture only;
- GitHub documented REST API provider design;
- read-only-by-default provider posture;
- explicit source policy;
- explicit authorization and credential references;
- explicit consent;
- endpoint allowlists;
- initial endpoint families;
- GitHub source classes as source and provenance metadata only;
- RepoMap-owned artifact and run layout;
- retention and redaction requirements;
- provider identity and URL safety;
- raw observation and provenance model;
- canonical namespace deferral;
- failure model;
- future tests; and
- future phase plan.

Out of scope:

- implementing GitHub API acquisition;
- adding CLI commands;
- adding OAuth;
- adding GitHub App authentication;
- adding personal access token handling;
- reading environment variables;
- reading credential values;
- accessing OS keychains;
- token refresh;
- network calls;
- real GitHub client;
- GraphQL client;
- webhook handling;
- scheduler or polling behavior;
- MCP tools;
- storage migrations;
- fixtures;
- tests;
- new extractors;
- new canonical namespaces;
- new edge kinds;
- public readback default changes;
- Gmail, Microsoft, IMAP, SMTP, or other provider work; and
- Phase F migration.

## Hard Guardrails

GITHUB_API0 must not:

- implement any GitHub API request;
- add production HTTP transport;
- read or validate real credentials;
- store credentials in repo files, manifests, logs, observations, readback, or
  explain output;
- implement OAuth;
- implement GitHub App private-key authentication;
- implement webhook receivers;
- create subscriptions or webhooks;
- write comments;
- mutate issues or pull requests;
- change labels, milestones, or assignees;
- dispatch workflows;
- rerun or cancel workflows;
- upload or download release assets unless a later ADR accepts asset handling;
- clone repositories;
- fetch arbitrary raw URLs;
- scrape GitHub HTML;
- use browser automation;
- bypass login, rate limits, or anti-bot behavior;
- add `github.*` canonical namespaces; or
- hide GitHub acquisition inside BULK.

## Product Posture

GitHub API ingestion must be documented, explicit, auditable, and safe by
default.

Requirements:

- GitHub documented REST API only;
- explicit source config only;
- explicit source policy required before any request;
- explicit consent required before any request;
- explicit credential mode required before any request;
- read-only by default;
- mutation disabled;
- GET-only endpoint allowlist;
- provider terms and rate-limit model required;
- retention policy required;
- redaction policy required;
- no arbitrary URL fetching;
- no `raw.githubusercontent.com` fetching;
- no repository cloning;
- no GitHub HTML scraping;
- no browser automation;
- no login-wall automation;
- no anti-bot circumvention;
- no credential leakage into artifacts, logs, graph facts, readback, or explain
  output; and
- no provider-specific implementation in GITHUB_API0.

## GitHub Source Classes

Provider-specific source classes are future metadata only. In GITHUB_API0 they
are source and provenance classes, not canonical graph namespaces.

Future GitHub source classes:

- `api.github.repository`
- `api.github.issues`
- `api.github.pull_requests`
- `api.github.reviews`
- `api.github.commits`
- `api.github.actions`
- `api.github.releases`
- `api.github.discussions`
- `api.github.code_scanning`
- `api.github.dependabot`
- `api.github.security_advisories`

These source classes must not create canonical `github.*` namespaces in
GITHUB_API0.

Initial recommended GITHUB_API1 source class:

- `api.github.repository`

Initial recommended endpoint family:

- repository metadata;
- issues;
- pull requests;
- pull request reviews and comments;
- commits;
- releases; and
- workflow runs and job summaries if safe and read-only.

Deferred source classes and endpoint families:

- Discussions unless clearly scoped;
- code scanning and security advisories unless the permission model is
  explicit;
- Dependabot alerts unless the permission model is explicit;
- Actions logs unless retention and redaction are explicit;
- release assets and binary downloads;
- repository contents API for arbitrary file fetching unless separately scoped;
  and
- GraphQL.

## Source Policy

GitHub API acquisition requires source policy before any request. An absent,
ambiguous, or incomplete policy fails closed.

Policy fields should include:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name = "GitHub"`;
- `provider_product = "GitHub REST API"`;
- `policy_status`;
- `owner`;
- `repository`;
- `repository_visibility`;
- `allowed_endpoints`;
- `allowed_methods`;
- `read_only`;
- `mutation_allowed`;
- `credentials_ref`;
- `credential_mode`;
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

Rejected or blocked policy statuses:

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
- `private_repo_without_explicit_consent`
- `scope_too_broad`
- `endpoint_not_allowlisted`

GitHub source policy must fail closed unless policy, consent, credential mode,
allowed endpoints, allowed methods, rate limits, redaction, and retention are
explicit.

## Credential And Authorization Model

GITHUB_API0 defines credential safety without implementing credential storage,
credential access, credential validation, or provider authentication.

Supported future credential modes:

- `none_public_readonly`
- `pat_readonly_ref`
- `github_app_installation_ref`

GITHUB_API0 does not implement any credential mode.

Credential refs are opaque only:

- `local_secret_ref:<name>`
- `os_keychain_ref:<name>`
- `env_ref:<name>`

Rules:

- Public unauthenticated access may be allowed only for public repositories and
  explicit `credential_mode = "none_public_readonly"`.
- Private repositories require explicit consent and credential reference in a
  future implementation.
- Personal access tokens, GitHub App private keys, installation tokens, refresh
  tokens, authorization headers, cookies, and session IDs must not be stored.
- Credential reference suffixes must not appear in public readback when tests
  treat them as sensitive.
- OAuth is not used in GITHUB_API0.
- GitHub App authentication is not implemented in GITHUB_API0.
- Environment variables and keychains are not read in GITHUB_API0.

GitHub REST authentication documentation describes token-based authentication
and endpoint-specific permissions. A future implementation must use those docs
as inputs to policy validation, but GITHUB_API0 does not resolve or test any
credential.

## Consent Model

GitHub acquisition requires explicit consent metadata before any request.

Consent fields should include:

- `consent_id`;
- `user_id` or local user label;
- `authorized_source_id`;
- `authorized_owner`;
- `authorized_repository`;
- `authorized_visibility`;
- `authorized_operations`;
- `authorized_data_classes`;
- `created_at`;
- `expires_at`;
- `revoked`;
- `retention_policy`; and
- `mutation_allowed`.

Default consent allows read-only metadata acquisition only.

Default consent rejects:

- issue, pull request, review, or comment mutation;
- label, milestone, or assignee changes;
- workflow dispatch, rerun, or cancel;
- webhook registration;
- repository content mutation;
- release asset upload or delete;
- secret access; and
- any provider state change.

## Endpoint Allowlist

GitHub acquisition requires explicit endpoint allowlists.

Each endpoint policy should include:

- `endpoint_name`;
- `method`;
- `path_template`;
- `purpose`;
- `expected_response_type`;
- `max_page_size`;
- `pagination`;
- `allowed_query_parameters`;
- `prohibited_query_parameters`;
- `required_permissions`;
- `response_retention_class`;
- `redaction_class`; and
- `downstream_route`.

Allowed method:

- `GET`

Rejected by default:

- `POST`
- `PUT`
- `PATCH`
- `DELETE`

Initial safe endpoint families for future implementation:

- `GET /repos/{owner}/{repo}`
- `GET /repos/{owner}/{repo}/issues`
- `GET /repos/{owner}/{repo}/issues/{issue_number}`
- `GET /repos/{owner}/{repo}/pulls`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`
- `GET /repos/{owner}/{repo}/commits`
- `GET /repos/{owner}/{repo}/commits/{ref}`
- `GET /repos/{owner}/{repo}/releases`
- `GET /repos/{owner}/{repo}/actions/runs`
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs`

Explicitly deferred endpoints:

- workflow logs;
- artifacts;
- release assets;
- repository contents;
- trees and blobs;
- code search;
- GraphQL;
- organization, team, and member endpoints;
- secrets endpoints;
- billing endpoints;
- admin endpoints;
- write endpoints; and
- webhooks.

Endpoint paths must remain within the configured owner and repository. Future
validation must reject path injection, URL schemes in endpoint paths,
unallowlisted query parameters, and endpoint templates that escape the
configured repository scope.

## Repository Identity

GitHub repository identity should be represented safely.

Future raw metadata may include:

- owner;
- repo;
- full name;
- repository numeric ID if safely retained;
- visibility;
- default branch;
- HTML URL summary;
- API URL summary;
- clone URL presence, not credentialed clone URL; and
- source policy ID.

Canonical identity policy:

- Do not add canonical `github.repository` in GITHUB_API0.
- A future provider ADR may decide whether
  `github.repository:<owner>/<repo>` is canonical.
- Avoid using mutable provider IDs as generic domain identity without a
  provider ADR.
- Repository owner/name may change.
- Numeric IDs may be stable but are provider-specific.
- Provider-specific identity belongs in provider ADRs, not generic API
  identity.

URL safety rules:

- Store summaries for GitHub HTML and API URLs only when allowed by policy.
- Do not store credentialed clone URLs.
- Do not store signed URLs, temporary download URLs, workflow log URLs with
  tokens, artifact URLs with tokens, or release asset download URLs unless a
  later ADR accepts them.
- Do not fetch arbitrary raw URLs or follow provider links outside the endpoint
  allowlist.

## Response Artifact Layout

Future GitHub acquisition should write under RepoMap-owned paths:

```text
.repomap/api-runs/<source-id>/<api-run-id>/
```

Possible files:

- `plan.json`;
- `manifest.json`;
- `requests.jsonl`;
- `responses.jsonl` only if minimized and redacted;
- `redacted-responses.jsonl`;
- `diagnostics.jsonl`;
- `artifacts/repository.json`;
- `artifacts/issues.jsonl`;
- `artifacts/pulls.jsonl`;
- `artifacts/reviews.jsonl`;
- `artifacts/commits.jsonl`;
- `artifacts/releases.jsonl`;
- `artifacts/actions-runs.jsonl`; and
- `artifacts/actions-jobs.jsonl`.

Do not store:

- authorization headers;
- cookies;
- tokens;
- secrets;
- private keys;
- raw credential references if considered sensitive;
- credentialed clone URLs;
- unnecessary raw response bodies;
- workflow logs unless a later ADR accepts them; or
- release assets or binaries unless a later ADR accepts them.

GitHub API run IDs should be deterministic where practical from:

- `source_id`;
- owner/repository summary;
- policy hash;
- endpoint allowlist hash; and
- request plan hash.

Timestamps may be metadata only. They must not be run identity.

## Raw Observation Model

Future GitHub phases may emit the generic API raw observations from API1:

- `api.source`
- `api.run`
- `api.request`
- `api.response`
- `api.artifact`
- `api.diagnostic`

Future provider implementation ADRs may accept GitHub-specific raw
observations. Possible future raw observations:

- `github.repository`
- `github.issue`
- `github.pull_request`
- `github.review`
- `github.review_comment`
- `github.commit`
- `github.release`
- `github.workflow_run`
- `github.workflow_job`
- `github.reference`
- `github.diagnostic`

GitHub-specific observations should remain raw and provenance-first initially.
GITHUB_API0 does not canonicalize them.

Raw provenance should preserve safe fields such as:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name`;
- `provider_product`;
- `api_run_id`;
- `api_manifest_id`;
- `endpoint_name`;
- `method`;
- `path_template`;
- `owner`;
- `repository`;
- `repository_visibility`;
- `downstream_route`;
- `api_policy_status`;
- `api_retention_policy`; and
- `api_sensitivity`.

Raw provenance must not include credentials, authorization headers, cookies,
tokens, secret values, raw response bodies, credentialed URLs, sensitive query
strings, or full local machine paths.

## Canonical Namespace Policy

GITHUB_API0 defers `github.*` canonical namespaces.

Preferred initial behavior:

- GitHub source, run, request, response, and artifact facts remain
  raw/provenance/manifest facts.
- Artifacts may be routed through existing JSON/config extraction where useful.
- Existing repo source-code facts remain in language and file namespaces.
- Later provider ADRs may add `github.*` canonical nodes only if implementation
  evidence proves the identity model is useful.

Possible future canonical namespaces only if later accepted:

- `github.repository:<encoded-owner-repo-or-id>`
- `github.issue:<repository-key>/<number>`
- `github.pull_request:<repository-key>/<number>`
- `github.commit:<repository-key>/<sha>`
- `github.release:<repository-key>/<tag-or-id>`
- `github.workflow_run:<repository-key>/<run-id>`

Do not add these in GITHUB_API0.

## Edge Vocabulary

GITHUB_API0 adds no new edge kinds.

Future GitHub provider phases should prefer existing edge kinds:

- `defines`
- `references`

If issue, pull request, review, workflow, or release relationships later need a
richer vocabulary, that requires a separate ADR or provider implementation
review.

## Response Routing

GitHub API responses may become:

- local JSON or JSONL artifacts routed through config extraction;
- provider raw observations;
- redacted response manifests; or
- future GitHub-specific raw observations.

Do not route:

- release assets or binaries;
- workflow logs;
- repository contents or blobs;
- downloaded patches or diffs;
- HTML pages;
- arbitrary raw URLs;
- remote references; or
- executable content.

## Diff And Patch Policy

GitHub pull request diffs and patches are attractive but risky.

GITHUB_API0 defers:

- pull request diff acquisition;
- patch acquisition;
- raw file or blob acquisition;
- repository contents API file reads; and
- release asset downloads.

RepoMap already has local code extraction. GitHub provider ingestion should
first focus on project activity metadata. Linking GitHub activity to local code
facts can come later after identity, retention, redaction, and provenance are
clear.

## Actions Policy

Actions summaries may be allowed in a later phase:

- workflow run metadata;
- job metadata;
- conclusion, status, and timestamps;
- workflow name; and
- branch or ref summary.

Deferred Actions data and operations:

- full logs;
- artifacts;
- cache;
- uploaded files;
- rerun, cancel, and dispatch mutations; and
- secrets.

## Rate Limits And Pagination

Future GitHub implementation must model:

- max requests per run;
- max requests per minute;
- max pages per endpoint;
- max items per endpoint;
- max total bytes;
- `per_page` cap;
- pagination policy;
- retry and backoff;
- rate-limit remaining, used, and reset metadata;
- secondary rate limit handling; and
- hard stop on unknown rate-limit state.

Default behavior:

- conservative limits;
- serial requests;
- no concurrency unless a later phase accepts it;
- no retries unless a later phase accepts them; and
- fail closed when rate-limit policy is absent.

GitHub REST API documentation describes pagination using response link
headers and rate-limit behavior with primary and secondary limits. Future
GitHub implementation must preserve those controls in policy and diagnostics
without leaking credentials or sensitive URLs.

## Redaction

GitHub API responses can contain sensitive content even for public
repositories.

Redact or avoid:

- tokens;
- secrets;
- authorization headers;
- cookies;
- private emails;
- private clone URLs;
- signed URLs;
- workflow log URLs with tokens;
- artifact download URLs;
- patch or diff contents unless a later ADR accepts them;
- issue or pull request body text if redaction policy says body minimization;
- comments if redaction policy says body minimization;
- user emails;
- private repository names unless explicitly authorized; and
- credential reference suffixes if considered sensitive.

Redaction failures must stop routing to graph extraction and record safe
diagnostics only.

## Public Repository Policy

Public repositories are easier to demo, but still require explicit policy.

Public repository defaults:

- `credential_mode = "none_public_readonly"` is allowed only for public
  repositories.
- GET only.
- Issue, pull request, release, and activity metadata are allowed only if the
  endpoint is explicitly allowlisted.
- Public does not mean safe to retain all text forever.
- Retention and redaction are still required.
- GitHub HTML scraping is prohibited.

## Private Repository Policy

Private repositories require:

- explicit consent;
- credential reference;
- credential mode;
- narrower endpoint allowlist;
- strict retention;
- strict redaction;
- no public readback of private names unless explicitly allowed;
- no secrets endpoints;
- no Actions logs or artifacts by default; and
- no unauthenticated mode.

Private repository policy must fail closed when consent, credential mode,
credential reference, repository visibility, endpoint allowlist, rate limits,
retention, or redaction are missing or ambiguous.

## Failure Model

Future GitHub implementation should distinguish:

- policy failure;
- missing consent;
- missing credential;
- private repository without explicit consent;
- endpoint not allowlisted;
- method not allowed;
- rate limit exceeded;
- secondary rate limit;
- GitHub `401`;
- GitHub `403`;
- GitHub `404`;
- GitHub `422`;
- GitHub abuse or rate-limit response;
- network error;
- parse error;
- redaction error; and
- retention or storage error.

Diagnostics must not include secrets, authorization headers, cookies, full
sensitive URLs, raw response bodies, credential reference suffixes when
sensitive, private key material, tokens, or session IDs.

## Illustrative Future CLI

Future phases may add commands like:

```sh
repomap-kg github plan --config github-source.toml --json
repomap-kg github acquire --config github-source.toml --json
repomap-kg storage github-summary --root-path <repo> --json
```

These commands are illustrative only. GITHUB_API0 adds no commands.

## Illustrative Future Config

This TOML example is illustrative only and is not implemented in GITHUB_API0:

```toml
[source]
source_id = "github-public-repomap"
source_type = "api.rest"
api_source_class = "api.github.repository"
provider_name = "GitHub"
provider_product = "GitHub REST API"
policy_status = "allowed_with_limits"
owner = "lair001"
repository = "repo-map"
repository_visibility = "public"
read_only = true
mutation_allowed = false
credential_mode = "none_public_readonly"

[consent]
consent_ref = "local_consent_ref:github-public-repomap-readonly-2026-07"
authorized_operations = ["read"]
authorized_data_classes = ["repository_metadata", "issues", "pull_requests", "releases"]
revoked = false
mutation_allowed = false

[limits]
max_requests_per_run = 50
max_requests_per_minute = 10
max_pages_per_endpoint = 2
max_items_per_endpoint = 100
max_bytes_per_run = 10485760
max_concurrent_requests = 1

[retention]
policy = "local_user_controlled"
raw_response_retention = "minimized"
redacted_response_retention = "retain"

[redaction]
profile = "strict"
sensitivity = "public_metadata"

[[endpoints]]
name = "repository"
method = "GET"
path = "/repos/{owner}/{repo}"
purpose = "Export repository metadata"
response_type = "application/json"
max_page_size = 1
pagination = "none"
downstream_route = "config"

[[endpoints]]
name = "issues"
method = "GET"
path = "/repos/{owner}/{repo}/issues"
purpose = "Export issue metadata"
response_type = "application/json"
max_page_size = 100
pagination = "page"
downstream_route = "config"
```

## Recommended Future Implementation Approach

GITHUB_API1 should probably reuse generic API1 machinery where possible instead
of creating a parallel provider stack.

Possible approach:

- GitHub-specific config validation wrapper;
- endpoint allowlist expands into API1-style request plan;
- fixture or mock transport first;
- optional real transport only after tests and explicit policy;
- artifacts under `.repomap/api-runs/...`;
- readback via API2-like summary first; and
- GitHub-specific canonical graph deferred.

## Future GITHUB_API1 Tests

GITHUB_API0 requires future tests for:

- config required;
- policy absent fails closed;
- blocked policy fails closed;
- private repository without explicit consent fails closed;
- missing credential for private repository fails closed;
- public unauthenticated read-only allowed only with explicit public visibility;
- unsupported source class fails closed;
- non-GitHub provider fails closed;
- unsupported method fails closed;
- non-allowlisted endpoint fails closed;
- endpoint outside configured owner/repository fails closed;
- owner/repository path injection blocked;
- URL scheme in path blocked;
- credential values not read;
- credentials absent from logs, manifests, readback, and explain output;
- rate-limit policy required;
- retention policy required;
- redaction policy required;
- pagination bounded;
- request plan deterministic;
- artifact path under `.repomap/api-runs/...`;
- no mutation endpoints;
- no webhooks or schedulers;
- no HTML scraping;
- no real network before validation; and
- no provider namespaces unless later accepted.

## Rejected Alternatives

Rejected in GITHUB_API0:

- implementing GitHub API acquisition;
- using GitHub GraphQL first;
- using OAuth first;
- requiring GitHub App authentication first;
- scraping GitHub HTML;
- fetching arbitrary `raw.githubusercontent.com` URLs;
- repository cloning;
- downloading pull request patches or diffs first;
- downloading workflow logs first;
- downloading release assets first;
- webhook registration;
- scheduler or polling behavior;
- write endpoints;
- mutating issues, pull requests, labels, comments, or workflows;
- storing tokens in configs, manifests, readback, or explain output;
- adding `github.*` canonical namespaces;
- hiding GitHub acquisition inside BULK; and
- treating public repository data as automatically safe without policy.

## Proposed Phases

- GITHUB_API1: read-only GitHub provider fixture/mock acquisition skeleton.
- GITHUB_API2: optional real read-only GitHub REST acquisition for public
  repositories, if policy and tests are strong enough.
- GITHUB_API3: GitHub readback summary.
- GITHUB_GRAPH0: GraphQL ADR only, if ever needed.
- GITHUB_ACTIONS_LOG0: Actions logs ADR only, if ever needed.
- GITHUB_DIFF0: pull request diff/patch ADR only, if ever needed.
- GITHUB_CANON0: GitHub canonical graph identity ADR only, if implementation
  evidence supports it.

## Consequences

GITHUB_API0 makes GitHub provider work possible without weakening RepoMap's
documented API, source-ingestion, BULK, storage, readback, and canonical graph
boundaries.

The cost is that GitHub remains unimplemented. Future phases must first prove
policy, consent, credential reference safety, endpoint allowlisting, rate-limit
handling, retention, redaction, artifact safety, and read-only behavior before
real GitHub acquisition lands.

## Acceptance

GITHUB_API0 is accepted only if it is internally consistent,
provider-specific but implementation-free, read-only by default,
explicit-policy-gated, credential-safe, retention-aware, mutation-disabled,
scheduler-free, network-free, and does not weaken API, BULK, source-ingestion,
storage, readback, or canonical graph boundaries.
