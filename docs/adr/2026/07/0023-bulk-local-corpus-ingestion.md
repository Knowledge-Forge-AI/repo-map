# ADR 0023: Bulk Local Corpus Ingestion

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap can now graph many local file families safely:

- source code;
- configuration files;
- Markdown and structured documents;
- saved-page and static artifact directories;
- local WARC payloads;
- feeds;
- JavaScript assets;
- `.eml` single-message files; and
- `.mbox` mailbox archive files.

The next useful ingestion step is not provider APIs. It is safe bulk ingestion
of local corpora the user already possesses on disk. Examples include email
export folders, local MBOX export folders, document corpora, source-code
corpora, saved-page bundles, generated test reports, coverage reports, static
documentation exports, archive-like export folders, and future local artifact
dumps produced by API phases.

Bulk ingestion has a different risk profile from single-file extraction. It
can traverse large directory trees, touch sensitive files by accident, amplify
redaction mistakes, and make provenance hard to reason about. BULK0 therefore
defines a local, explicit, policy-gated orchestration layer over already
supported static extractors.

The product story is:

RepoMap can safely import a local corpus directory or local corpus manifest and
route supported files through existing static extractors, producing
deterministic graph facts with clear provenance. It does not connect to
providers, fetch remote resources, crawl the web, execute content, mutate source
files, or infer runtime behavior.

## Decision

RepoMap will model BULK as local corpus orchestration over already-supported
local extractors.

The future BULK pipeline is:

```text
explicit local corpus config / manifest
-> validate source policy and root constraints
-> enumerate local files deterministically
-> classify supported files
-> apply limits and exclusions
-> route each eligible file to existing extractors
-> attach corpus/run/file provenance metadata
-> write deterministic manifest/run summary
-> load observations through existing storage path
-> expose through existing readback and future read-only summaries
```

BULK0 is architecture only. It does not implement ingestion, add CLI commands,
add discovery routing, add canonicalization code, add fixtures, add tests, add
MCP tools, add storage migrations, add provider APIs, or change existing
extractor/readback behavior.

## Scope

In scope:

- bulk local corpus architecture;
- explicit source policy and root constraints;
- corpus-kind metadata;
- deterministic traversal and manifest requirements;
- safe file classification and extractor routing policy;
- provenance metadata for routed observations;
- limit, exclusion, symlink, hidden-file, and failure behavior;
- redaction and privacy posture;
- email-export, document, source-code, saved-page, report, WARC, feed, and
  mixed-corpus boundaries;
- future CLI shape as illustrative non-implementation guidance;
- future BULK1 test requirements; and
- future phase planning.

Out of scope:

- implementing BULK ingestion;
- adding CLI commands;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding MCP tools;
- adding storage migrations;
- adding provider APIs;
- changing MAIL, EML, MBOX, ARCHIVE, WARC, DOCS, YAML, RUBY, JS, HTML, CSS,
  feed, storage, or public readback behavior;
- provider acquisition;
- API acquisition;
- web crawling;
- archive decompression; and
- Phase F migration.

## Product Posture

BULK must remain local, explicit, deterministic, privacy-preserving,
non-mutating, and acquisition-free.

Requirements:

- local files only;
- explicit roots only;
- explicit config or manifest required;
- no provider APIs;
- no Gmail API;
- no IMAP;
- no SMTP;
- no Microsoft Graph;
- no OAuth;
- no credential prompts;
- no mailbox mutation;
- no file mutation except RepoMap-owned output directories;
- no sending, forwarding, deleting, archiving, labeling, or marking mail;
- no URL fetching;
- no web crawling;
- no scraping;
- no remote image loading;
- no tracking pixel fetching;
- no source-map fetching;
- no attachment execution;
- no macro execution;
- no OCR unless a later ADR accepts it;
- no HTML rendering;
- no JavaScript execution;
- no shell command execution;
- no archive decompression unless explicitly accepted by a later phase and
  bounded;
- no arbitrary home-directory scan;
- no automatic `~/Documents`, `~/Downloads`, or mail-client profile scan; and
- no MCP write, import, or run tools in BULK0.

## Corpus Kinds

BULK corpus kinds are acquisition and provenance metadata only. They are not
canonical graph namespaces and do not imply provider-specific semantics.

Suggested corpus kinds:

- `generic_local_corpus`
- `email_export`
- `eml_export`
- `mbox_export`
- `document_corpus`
- `source_code_corpus`
- `saved_page_corpus`
- `static_artifact_corpus`
- `report_corpus`
- `warc_corpus`
- `feed_corpus`
- `mixed_corpus`

Corpus kinds must not create `gmail.*`, `imap.*`, `microsoft.*`, or other
provider-specific canonical namespaces.

## Supported Future Inputs

Future BULK phases may accept:

- an explicit local directory root;
- an explicit local manifest file;
- an explicit list of local files; and
- a RepoMap-owned source artifact directory from prior ARCHIVE, WARC, feed, or
  import phases.

Extensionless or ambiguous corpora require explicit config. BULK must not infer
mail-client profiles, browser profiles, backup roots, or home-directory trees
from ambient filesystem layout.

Future API phases may produce local artifact dumps that BULK can ingest after
API acquisition is complete. BULK itself does not acquire those dumps.

## File Routing

BULK should route only already-supported file types through existing extractors.
It must not introduce new extractor behavior.

Current route candidates include:

- `.eml`;
- `.mbox`;
- Markdown;
- JSON, JSONL, JSONC;
- TOML;
- YAML;
- XML, plist, HTML;
- CSS;
- JS, MJS, CJS, JSX, TS, MTS, CTS, TSX;
- TXT, CSV, TSV, TeX, LaTeX;
- ODT, ODS, OTT, OTS;
- Ruby;
- Python;
- Nix;
- shell;
- feed artifacts;
- WARC files only through the existing WARC import path; and
- saved-page/static artifact directories only through existing archive policy.

Unsupported files should be skipped or retained as safe file inventory metadata
only, depending on policy. BULK must not use this architecture to add PDF,
DOCX, XLSX, OCR, archive decompression, provider export parsing, or browser
profile parsing.

## Source Policy

BULK requires source policy before import. An absent policy fails closed.

Policy fields should include:

- `source_id`;
- `source_type`;
- `corpus_kind`;
- `root_path`;
- `allowed_paths`;
- `excluded_paths`;
- `allowed_extensions`;
- `max_files`;
- `max_total_bytes`;
- `max_file_bytes`;
- `max_depth`;
- `follow_symlinks`;
- `retention_policy`;
- `redaction_profile`;
- `sensitivity`;
- `provenance_label`;
- `policy_status`;
- `created_by`; and
- `created_at`.

`created_at` is policy metadata, not graph identity. It must not become a
canonical key component.

Allowed statuses:

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

Future implementations may map ADR 0014 statuses into these bulk statuses, but
the operational rule is simple: BULK proceeds only when policy is explicitly
allowed.

## Traversal Policy

Future BULK1 should:

- require an explicit root path;
- resolve the canonical local path before traversal;
- prevent root escaping;
- avoid broad home-directory scans;
- sort files deterministically;
- apply maximum depth;
- apply maximum file count;
- apply maximum total bytes;
- apply maximum per-file bytes;
- honor include and exclude patterns;
- never follow symlinks by default;
- follow symlinks only when policy explicitly allows it and root containment is
  rechecked after resolution;
- avoid hidden files and directories by default unless explicitly allowed;
- avoid dependency, vendor, cache, and build directories by default unless
  explicitly allowed;
- skip special device files, sockets, and pipes; and
- never execute files.

Default excluded directories:

- `.git`
- `.svn`
- `.hg`
- `node_modules`
- `vendor`
- `.venv`
- `venv`
- `.mypy_cache`
- `.pytest_cache`
- `.tox`
- `.gradle`
- `target`
- `build`
- `dist`
- `.next`
- `.nuxt`
- `.cache`
- `.Trash`
- mail-client profile directories unless explicitly selected

Default excluded file patterns:

- credential stores;
- browser profiles;
- password vaults;
- keychains;
- private keys;
- SSH keys;
- OS credential caches;
- binary executables;
- huge media files; and
- unknown archives unless a future phase accepts bounded archive handling.

## Manifest Model

BULK runs should produce deterministic manifests:

- corpus manifest;
- run manifest;
- file inventory;
- skipped-file report;
- extractor routing report;
- diagnostics report;
- redaction and safety summary;
- checksums for files when permitted; and
- stable run ID.

Manifest metadata should include:

- `bulk_run_id`;
- `source_id`;
- `source_type`;
- `corpus_kind`;
- `root_path_summary`;
- `started_at`;
- `completed_at`;
- `file_count_seen`;
- `file_count_included`;
- `file_count_skipped`;
- `total_bytes_seen`;
- `total_bytes_included`;
- `limit_hit`;
- `limit_reason`;
- `extractor_counts`;
- `diagnostic_counts`;
- `redaction_counts`;
- `manifest_sha256`.

Manifest timestamps are run metadata, not canonical graph identity. Public
readback should prefer stable summaries and hashes over machine-specific paths.

Manifests must not include:

- raw sensitive file contents;
- raw email bodies;
- raw full email addresses;
- raw subjects;
- attachment bodies;
- secret values; or
- full absolute machine paths in public readback.

## Provenance Metadata

BULK-routed observations should preserve safe provenance metadata:

- `source_id`;
- `source_type`;
- `corpus_kind`;
- `bulk_run_id`;
- `bulk_manifest_id`;
- `bulk_relative_path`;
- `bulk_file_sha256`;
- `bulk_file_byte_count`;
- `bulk_extractor_route`;
- `bulk_policy_status`;
- `bulk_retention_policy`;
- `bulk_sensitivity`; and
- `bulk_skipped_reason` when applicable.

Provenance metadata must not weaken extractor-level redaction. If downstream
extractors redact a value, BULK must not reintroduce that value in manifests,
summaries, evidence metadata, edge metadata, or readback surfaces.

## Canonical Graph Policy

BULK0 does not accept bulk-specific canonical domain namespaces.

Preferred behavior:

- corpus, run, and manifest facts remain raw/provenance metadata;
- file facts use existing `file:*` nodes;
- extracted facts use the existing canonical namespaces from routed extractors,
  such as `email.*`, `document.*`, `js.*`, `ruby.*`, `config.*`, `html.*`,
  `css.*`, `warc.*`, `feed.*`, and source-language namespaces.

Possible future namespaces only if implementation evidence proves they are
needed:

- `bulk.corpus:<encoded-source-id-or-manifest-key>`
- `bulk.run:<encoded-run-id>`

Recommendation: defer `bulk.*` canonical namespaces until provenance metadata
has proved insufficient.

## Edge Vocabulary

BULK0 adds no new edge kinds.

Future BULK implementations should use existing edge kinds only:

- `defines`
- `references`

Routed extractors keep their existing canonicalization behavior. BULK should
attach provenance to observations and evidence rather than inventing corpus
edges.

## Redaction And Privacy

BULK must preserve extractor-level redaction and add corpus-level safety.

Requirements:

- no raw body text in bulk summaries;
- no raw email addresses in bulk summaries;
- no raw subjects in bulk summaries;
- no attachment bodies;
- no secret values;
- no credentials;
- no browser or session cookies;
- no tracking URLs with identifiers;
- no full absolute machine paths in public readback;
- no raw file contents in manifests; and
- no raw attachment filenames unless an extractor already sanitized or redacted
  them.

BULK must treat corpus summaries as public readback surfaces. They should report
counts, routes, diagnostics, redaction totals, and safe relative-path summaries,
not sensitive content.

## Email Export Posture

For email exports, BULK should:

- route `.eml` files to MAIL1 behavior;
- route `.mbox` files to MAIL2 behavior;
- preserve `email_export`, `eml_export`, or `mbox_export` corpus kind metadata;
- apply strict file, byte, message, and depth limits by default;
- avoid opening attachments;
- avoid body indexing;
- avoid body URL extraction;
- avoid provider semantics;
- avoid Gmail Takeout or provider labels unless a later ADR accepts safe local
  provider-export metadata; and
- never call provider APIs.

BULK is local export ingestion, not mailbox sync.

## Archive Handling

BULK0 is conservative about archives.

BULK1 should not implement arbitrary archive decompression. Saved-page and
static artifact directories should use ARCHIVE1-style policy. WARC files should
use WARC1-style policy. Arbitrary `.zip`, `.tar`, `.gz`, `.7z`, `.rar`, and
similar decompression is deferred.

If a future archive phase accepts decompression, it must include:

- bounded decompression;
- archive bomb protection;
- nested archive limits;
- extension allowlists;
- size limits;
- no execution;
- no password cracking; and
- no external resource retrieval.

## Failure Model

BULK should be resumable and fail-soft per file.

Rules:

- one bad file should not kill the whole corpus unless policy says fail-fast;
- skipped files and diagnostics are recorded;
- partial run manifests are preserved;
- run status remains deterministic;
- dry-run planning is supported before extraction; and
- strict mode can be added later if needed.

Failure diagnostics should distinguish policy blocks, traversal limits,
unsupported file types, extractor parse errors, redaction events, and storage
load failures.

## Future CLI Shape

BULK0 defines possible future commands but does not implement them.

Possible commands:

```sh
repomap-kg bulk plan --config bulk.toml --json
repomap-kg bulk import --config bulk.toml --repository-name <name> --root-path <repo> --json
repomap-kg storage bulk-summary --root-path <repo> --json
```

These are illustrative only. BULK0 adds no commands.

## Illustrative Config

This TOML is illustrative architecture text only. It is not implemented in
BULK0.

```toml
[source]
source_id = "local-email-export-2026-07"
source_type = "local.directory"
corpus_kind = "email_export"
policy_status = "allowed_with_limits"
root_path = "/path/to/export"

[limits]
max_files = 10000
max_total_bytes = 1073741824
max_file_bytes = 10485760
max_depth = 12
follow_symlinks = false

[include]
extensions = [".eml", ".mbox"]

[exclude]
directories = [".git", "node_modules", ".Trash"]

[retention]
policy = "local_user_controlled"
```

## Future BULK1 Tests

BULK1 should add tests for:

- config required;
- absent policy fails closed;
- blocked policy fails closed;
- unknown source type fails closed;
- explicit root required;
- root escaping blocked;
- symlink behavior;
- deterministic traversal order;
- max file count;
- max total bytes;
- max per-file bytes;
- max depth;
- exclusion patterns;
- hidden directory default exclusion;
- extractor routing to MAIL, DOCS, JS, and other existing extractors;
- dry-run manifest;
- import manifest;
- skipped-file report;
- redaction summary;
- email export folder with `.eml` and `.mbox`;
- no provider or API behavior;
- no external fetches;
- no archive decompression unless accepted;
- no mutation of source files; and
- storage load/readback if implementation includes load.

## Rejected Alternatives

Rejected:

- provider sync in BULK;
- Gmail API in BULK;
- IMAP or SMTP in BULK;
- Microsoft Graph in BULK;
- OAuth in BULK;
- web crawling;
- scraping;
- URL fetching;
- automatic home-directory scan;
- automatic browser or mail-client profile scan;
- recursive archive decompression by default;
- attachment extraction by default;
- body text indexing by default;
- LLM summarization during ingest;
- MCP write or import tools in BULK0;
- provider-specific namespaces in BULK0; and
- broad filesystem indexing without explicit policy.

## Proposed Phases

- BULK1: safe bulk local import implementation.
- BULK2: bulk readback polish if needed.
- API0: documented API ingestion architecture ADR only.
- Future provider acquisition phases only after API0, each with explicit
  consent, credentials, rate limits, retention, mutation, and provider-policy
  models.

## Acceptance Criteria

BULK0 is accepted only if internally consistent, local-only,
explicit-policy-gated, privacy-preserving, non-mutating, and acquisition-free.

BULK0 intentionally does not implement ingestion.
