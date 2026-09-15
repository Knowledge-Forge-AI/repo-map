# ADR 0022: Static Email Graph Model

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap can now graph local code, configuration, documents, saved artifacts,
archives, WARC payloads, feeds, and frontend/static assets without executing
them or fetching remote resources.

Email is the next useful local document source because many users can export
mail as files they already possess. Common portable shapes include single
`.eml` message files and local MBOX mailbox archives. RepoMap should first
understand these local artifacts before any bulk corpus or provider API
acquisition work.

Email files are highly sensitive. They may contain private correspondence,
names, addresses, phone numbers, account records, one-time codes, reset links,
medical or financial details, secrets, tracking links, attachment names, and
provider-specific metadata. They also commonly contain HTML, remote images,
tracking pixels, JavaScript-like content, and attachments. MAIL0 therefore
defines email graphing as static local file analysis only.

The product story is:

RepoMap can build a local, deterministic graph from email export files the user
already possesses: `.eml` files and MBOX/mailbox archives. It does not connect
to mail providers, fetch remote images, download attachments, click links,
execute content, mutate mailboxes, or call Gmail, IMAP, SMTP, Microsoft Graph,
or other provider APIs.

## Decision

RepoMap will model EML and MBOX support as static local email file analysis.

The future email pipeline is:

```text
local .eml file or local mbox archive
-> safe email/MIME parse using stdlib or bounded parser
-> raw email observations
-> canonicalize observations
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

Email graphing is file analysis, not mailbox acquisition or mail client
automation. Future MAIL phases must not connect to providers, fetch remote
resources, render HTML, execute JavaScript, execute attachments, mutate
mailboxes, or send mail.

MAIL0 accepts conservative generic `email.*` graph identity for local mailboxes,
messages, participants, MIME parts, attachment stubs, and thread hints if later
implementation tests prove them useful. MAIL0 explicitly rejects provider
namespaces such as `gmail.*`, `imap.*`, `smtp.*`, `outlook.*`,
`microsoft.*`, and `exchange.*`.

## Scope

In scope:

- static local email graph model design;
- `.eml` and MBOX input policy for future MAIL phases;
- safe parser policy;
- raw email observation vocabulary;
- conservative canonical namespace policy;
- message, address, subject, body, attachment, and thread identity policy;
- MIME structure policy;
- local-only reference policy;
- privacy and redaction policy;
- fixture and test requirements for MAIL1 and MAIL2; and
- future phase planning.

Out of scope:

- implementing EML parsing;
- implementing MBOX parsing;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding MCP tools;
- adding storage migrations;
- changing HTML, CSS, ARCHIVE, WARC, DOCS, YAML, RUBY, JS, storage, or public
  readback behavior;
- adding Gmail, IMAP, SMTP, Microsoft Graph, or provider API behavior; and
- Phase F migration.

## Product Posture

Email graphing must remain static, local, deterministic, privacy-preserving, and
non-mutating.

Requirements:

- local files only;
- no Gmail API;
- no IMAP;
- no SMTP;
- no Microsoft Graph;
- no provider login;
- no OAuth;
- no mailbox mutation;
- no sending;
- no forwarding;
- no deleting;
- no archiving;
- no label mutation;
- no marking read or unread;
- no remote image loading;
- no tracking pixel fetching;
- no link crawling;
- no attachment execution;
- no macro execution;
- no OCR;
- no HTML rendering;
- no JavaScript execution;
- no external asset retrieval;
- no automatic attachment text extraction unless a later ADR accepts safe local
  attachment handling; and
- no API acquisition until API0 or later.

## Supported Files

Future MAIL phases may support:

- `.eml`
- `.mbox`
- `.mailbox` only if explicitly documented as MBOX-like; and
- extensionless MBOX files only when selected explicitly by config or a future
  bulk policy, not through broad default discovery.

Recommended phase split:

- MAIL1: EML extraction.
- MAIL2: MBOX extraction.
- MAIL3: email readback polish.
- BULK0/BULK1: safe bulk local corpus ingestion, including large email export
  folders.
- API0: documented API ingestion architecture ADR only.

Gmail, IMAP, SMTP, Microsoft Graph, and other provider phases are future work
and must not be included in MAIL0.

## Parser Policy

MAIL1 and MAIL2 should use Python stdlib `email` and `mailbox` modules where
practical, or another bounded local parser only if a future implementation
phase justifies it.

Parser requirements:

- parse local bytes only;
- do not connect to providers;
- do not fetch links;
- do not load remote images;
- do not fetch `Content-Location` or `cid:` references;
- do not execute HTML, JavaScript, macros, scripts, attachments, or active
  content;
- enforce maximum file bytes;
- enforce maximum message count for MBOX;
- enforce maximum MIME part count per message;
- enforce maximum header bytes;
- enforce maximum body snippet bytes if snippets are accepted at all;
- preserve parse diagnostics;
- gracefully handle malformed messages; and
- treat body and attachment content as sensitive by default.

## Structure Goals

Future implementation should detect conservative local email structure:

- message file or mailbox observation;
- message identity from valid `Message-ID`;
- fallback structural message identity when `Message-ID` is absent or invalid;
- `Date` header as parsed timestamp metadata when valid;
- `From`, `To`, `Cc`, `Bcc`, `Reply-To`, `Sender`, and `Return-Path`;
- `Subject` with redaction and truncation policy;
- `In-Reply-To` and `References` thread hints;
- MIME part tree structure;
- `Content-Type`;
- `Content-Disposition`;
- attachment presence;
- attachment filename metadata only after redaction or sanitization;
- attachment size metadata when available;
- text/plain part metadata;
- text/html part metadata;
- local `cid:` references as internal message references only;
- URLs in safe metadata only if redacted and not fetched;
- mailing list headers if present; and
- provider/export headers as raw metadata only when safe.

MAIL phases must not attempt:

- full conversation reconstruction;
- provider label or folder semantics beyond local mbox/file path hints;
- mail account synchronization;
- spam or phishing classification;
- sender identity verification;
- DKIM, SPF, or DMARC validation;
- contact enrichment;
- address book lookup;
- link expansion;
- attachment parsing;
- attachment OCR;
- HTML rendering;
- remote image loading;
- tracking pixel detection by fetching;
- important-email inference;
- sentiment analysis;
- LLM summarization; or
- body indexing beyond explicitly accepted safe snippets or metadata.

## Raw Observations

Future email raw observations may include:

- `email.mailbox`
- `email.message`
- `email.header`
- `email.address`
- `email.part`
- `email.attachment_stub`
- `email.thread_hint`
- `email.reference`
- `email.parse_error`

Optional observations, if useful and still small:

- `email.list_header`
- `email.body_summary_stub`

MAIL1 and MAIL2 should start with message, mailbox, header, address, thread,
MIME, and attachment-stub observations. Body content should remain
raw/evidence-first and heavily bounded or redacted if included at all. Attachment
content is deferred.

Suggested safe metadata fields:

- `format`: `eml` or `mbox`;
- `mailbox_path`;
- `message_id`;
- `message_id_hash`;
- `date`;
- `date_parse_status`;
- `subject_present`;
- `subject_preview`;
- `subject_hash`;
- `from_count`;
- `to_count`;
- `cc_count`;
- `bcc_count`;
- `reply_to_count`;
- `sender_count`;
- `address_role`;
- `address_display_name_redacted`;
- `address_domain`;
- `address_hash`;
- `mime_type`;
- `content_type`;
- `content_disposition`;
- `part_index`;
- `part_path`;
- `part_depth`;
- `part_byte_count`;
- `attachment_count`;
- `attachment_filename_redacted`;
- `attachment_filename_hash`;
- `attachment_mime_type`;
- `attachment_byte_count`;
- `has_text_plain`;
- `has_text_html`;
- `has_attachments`;
- `has_remote_references`;
- `thread_hint_kind`;
- `redacted`;
- `redaction_reason`; and
- `identity_strength`.

## Canonical Namespaces

MAIL0 accepts conservative generic email namespaces for future implementation if
tests prove them useful:

- `email.mailbox:<encoded-file-key>`
- `email.message:<encoded-message-identity>`
- `email.address:<encoded-address-hash-or-domain-scoped-key>`
- `email.part:<encoded-message-key>:<encoded-part-path>`
- `email.attachment_stub:<encoded-message-key>:<encoded-attachment-pointer>`
- `email.thread_hint:<encoded-message-key>:<encoded-thread-pointer>`

`email.mailbox:*` represents the local archive container. `email.message:*`
represents a parsed message identity. `email.address:*` represents a redacted or
hashed participant identity, not a public contact record.

Deferred or rejected namespaces:

- `gmail.*`
- `imap.*`
- `smtp.*`
- `outlook.*`
- `microsoft.*`
- `exchange.*`
- attachment content namespaces;
- body content namespaces unless a later ADR accepts a strict safe snippet
  model.

## Canonical Key Rules

Canonical keys must not include:

- raw subject text;
- raw body text;
- raw HTML;
- attachment content;
- attachment filenames without sanitization or hashing;
- full email addresses unless explicitly hashed or domain-only;
- display names;
- secrets;
- auth tokens;
- cookies;
- tracking URLs;
- remote image URLs with credentials;
- parser object IDs;
- line numbers;
- current time;
- absolute machine paths;
- model-generated labels;
- provider account names; or
- provider-specific mutable IDs.

## Message Identity

Message identity must be deterministic and privacy-preserving.

Preferred identity:

1. Valid `Message-ID`, normalized and hashed or encoded safely.
2. Source file or mailbox context when needed to avoid collisions.
3. Fallback structural identity when `Message-ID` is absent or invalid.

Fallback structural identity may use:

- file key or mailbox key;
- MBOX ordinal;
- stable header hash; and
- safe body hash only if body hashing is accepted and the body value is never
  stored.

Message identity must not use line numbers alone, import timestamp, parser
object IDs, mutable provider IDs, model-generated summaries, or raw subject text
alone.

## Address Identity

Email addresses are sensitive.

MAIL0 accepts hashed full-address canonical identity only if future tests prove
that strict redaction prevents raw address leakage. A lower-risk implementation
may start with raw address observations and defer canonical `email.address:*`
nodes.

Rules:

- store address role when safe;
- store address domain when safe;
- hash or omit full local-part values;
- redact or omit display names;
- do not expose raw full email addresses in canonical keys, node metadata, edge
  metadata, fixtures, readback, or explain output.

## Subject Policy

Subjects can contain secrets, personal data, names, private events, and one-time
codes.

MAIL1 should prefer:

- `subject_present`;
- `subject_hash`; and
- a bounded, redacted, truncated `subject_preview` in raw metadata only if tests
  prove it safe.

Raw subject text must not appear in canonical keys. Unredacted subjects must not
appear in canonical metadata, edge metadata, golden fixtures, readback, or
explain output.

## Body Policy

Email bodies are high sensitivity. MAIL0 defers body text extraction and LLM
summarization.

MAIL1 and MAIL2 should record body part metadata first:

- body part exists;
- MIME type;
- byte count;
- charset;
- transfer encoding; and
- redaction status.

If a later ADR accepts snippets, snippets must be small, bounded, redacted,
raw/evidence-only, absent from canonical keys, absent from default readback, and
created without HTML rendering, remote asset loading, or link fetching.

## Attachment Policy

MAIL0 defines attachment stubs only.

Attachment stub metadata may include:

- redacted, sanitized, or hashed filename;
- MIME type;
- size;
- content disposition;
- part path;
- content-id presence; and
- inline versus attachment flag.

MAIL phases must not extract attachment text, execute attachments, open nested
archives, OCR images, parse PDFs, parse DOCX/XLSX, render images, fetch missing
attachments, decode macros, or store attachment bodies.

## Reference Model

MAIL1 and MAIL2 should emit `email.reference` only for conservative references.

Initial supported references should be header-first:

- `Message-ID`;
- `In-Reply-To`;
- `References`;
- list headers such as `List-Id`; and
- `List-Unsubscribe` as redacted URL or email reference metadata only.

Additional references may be accepted later if bounded and redacted:

- local `cid:` references within the same message;
- URLs in text/plain or text/html body parts as not-fetched references; and
- attachment filename or part references to attachment stubs.

Target behavior:

- referenced message IDs become `email.message:*` or
  `unknown:email-message:*`;
- local mailbox/file references become `file:*`;
- attachment stubs become `email.attachment_stub:*`;
- `cid:` references become internal message part or attachment-stub references
  where safe;
- URLs become `external.url:*` with `not_fetched=true` and redaction only if
  body URL extraction is accepted;
- unsupported or dynamic targets become `unknown:*`; and
- references are never fetched.

## Thread Model

Email threading is a hint, not an authoritative graph truth.

MAIL phases may emit `email.thread_hint` observations for:

- `In-Reply-To`;
- `References` chains;
- same `Message-ID` references; and
- normalized subject fallback only as weak metadata, not strong identity.

RepoMap must not claim exact Gmail, Outlook, or provider thread membership,
infer conversations from body quotes, use LLM clustering, or use
provider-specific thread IDs in generic email identity.

## Edge Vocabulary

Use existing edge kinds only:

- `defines`
- `references`

Expected structural edges:

- `file:* --defines--> email.message:*` for `.eml`;
- `file:* --defines--> email.mailbox:*` for MBOX;
- `email.mailbox:* --defines--> email.message:*`;
- `email.message:* --defines--> email.part:*`;
- `email.message:* --defines--> email.attachment_stub:*`; and
- `email.message:* --defines--> email.thread_hint:*`.

Expected reference edges:

- `email.message:* --references--> email.message:* | unknown:*` for
  `In-Reply-To` and `References`;
- `email.message:* --references--> email.address:*` if address nodes are
  accepted; and
- `email.part:* --references--> email.attachment_stub:* | external.url:* |
  unknown:*` only when safe and not fetched.

MAIL0 does not add new edge kinds.

## Redaction

Email files are privacy-sensitive. MAIL phases should reuse existing secret
markers from ADR 0010, YAML, Ruby, and JS:

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

MAIL phases should also treat these email and personal-data markers as
secret-prone:

- `one_time_code`
- `verification_code`
- `reset_code`
- `reset_link`
- `magic_link`
- `unsubscribe_token`
- `tracking_pixel`
- `auth_link`
- `invoice_number`
- `account_number`
- `ssn`
- `tax_id`
- `dob`
- `phone`
- `address`
- `medical`
- `prescription`
- `bank`
- `routing`
- `credit_card`
- `card_number`

Requirements:

- raw full email addresses must not appear in canonical keys;
- display names must not appear in canonical keys;
- raw subjects must not appear in canonical keys;
- body text must not appear in canonical keys;
- attachment contents must not appear in canonical keys or metadata;
- secret literal values must not appear in raw observation metadata;
- secret literal values must not appear in canonical node metadata;
- secret literal values must not appear in edge metadata;
- secret literal values must not appear in golden fixtures, CLI readback, or
  explain output;
- URL credentials and tracking parameters must be stripped or redacted; and
- message bodies and headers must be treated as sensitive by default.

## Fixtures For MAIL1 And MAIL2

Future fixtures should live under:

```text
src/test/fixtures/discovery/mail_basic/
src/test/fixtures/canonicalization/mail_basic/
```

Suggested fixtures:

- `single-message.eml`
- `thread-reply.eml`
- `multipart-alternative.eml`
- `attachment-stub.eml`
- `inline-cid.eml`
- `malformed.eml`
- `sample.mbox`
- `redaction.eml`
- `large-body.eml`

Use fake values only:

- `example.invalid`;
- `alice@example.invalid`;
- `bob@example.invalid`;
- fake `Message-ID` values; and
- fake secrets designed for redaction tests.

Do not include real email addresses, real names, non-reserved domains, real
tokens, private endpoints, real message bodies, or private correspondence.

## Required MAIL1 Tests

MAIL1 should cover:

- EML file discovery if accepted;
- safe parse of simple EML;
- header observations;
- address redaction/hash behavior;
- subject redaction/hash behavior;
- Message-ID identity;
- Date parse metadata;
- MIME part metadata;
- attachment stub metadata;
- `In-Reply-To` and `References` thread hints;
- malformed EML diagnostics;
- no remote asset fetching;
- no attachment extraction;
- no HTML rendering;
- no JavaScript execution;
- storage load/readback;
- explaining one email reference edge; and
- proving no raw secret values, raw full addresses, body text, or attachment
  content in readback/explain output.

## Required MAIL2 Tests

MAIL2 should cover:

- MBOX discovery if accepted;
- parsing multiple messages from a local MBOX;
- mailbox node defines message nodes;
- MBOX ordinal fallback identity;
- malformed message diagnostics;
- large mailbox limits;
- no provider/API behavior;
- no mailbox mutation; and
- storage load/readback.

## Security And Privacy Consequences

This decision makes privacy the primary email design constraint. The graph can
represent structure, provenance, participants, MIME shape, attachments, and
thread hints, but body text and attachment content remain deferred by default.

The model intentionally sacrifices some search richness to avoid exposing raw
addresses, raw subjects, message bodies, attachment bodies, tracking URLs, or
provider-specific mutable identifiers in canonical graph surfaces.

## Rejected Alternatives

Rejected:

- Gmail API in MAIL phases;
- IMAP or SMTP in MAIL phases;
- Microsoft Graph in MAIL phases;
- OAuth or provider login;
- provider synchronization;
- mailbox mutation;
- message sending;
- marking read or unread;
- deleting, archiving, or labeling;
- remote image loading;
- tracking pixel fetching;
- link crawling;
- attachment execution;
- attachment content extraction in MAIL1;
- OCR;
- HTML rendering;
- JavaScript execution;
- LLM summarization in the extractor;
- exact provider thread reconstruction;
- raw email addresses in canonical keys;
- body text in canonical keys; and
- attachment bodies in graph metadata.

## Proposed Phases

- MAIL1: EML extraction.
- MAIL2: MBOX extraction.
- MAIL3: email readback polish.
- BULK0: bulk local corpus ingestion architecture.
- BULK1: safe bulk local import implementation.
- API0: documented API ingestion architecture ADR only.
- Future provider phases only after API0, with separate explicit consent,
  credential, mutation, retention, and rate-limit models.

## Outcome

MAIL0 is accepted only as a static, local-only, privacy-preserving, and
non-mutating graph model. It does not implement extraction, acquisition,
provider APIs, storage migrations, MCP tools, public readback changes, or Phase
F work.
