# ADR 0018: Local Documents Graph Model

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap can now graph local Markdown, JSON/TOML configuration, plist/XML,
generic XML, HTML, CSS, RSS/Atom/JSON Feed artifacts, saved-page/static
artifact imports, and local WARC archives. The next mainstream use case is a
private, local knowledge graph for a configured documents folder.

Documents folders are high-value and high-risk. They often contain tax records,
medical records, banking statements, legal documents, employment or client
data, resumes, journals, credentials, backup configuration, account IDs, and
private correspondence. A documents graph must therefore be local, private,
user-controlled, redaction-aware, and deliberately closed in scope.

DOCS0 defines a local document-ingestion model without opening the
PDF/DOCX/XLSX/native-office parser surface. It accepts a small open and
text-oriented supported document set, defines conversion policy for mainstream
formats, and sets implementation boundaries for DOCS1 and DOCS2.

## Decision

RepoMap will model local document graphing as explicit local folder or artifact
analysis.

The future documents pipeline is:

```text
document source config
-> document folder policy validation
-> local document discovery
-> document manifest / evidence records
-> route supported files to document extractors
-> canonicalize observations
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

DOCS0 accepts this closed set for native RepoMap document extraction:

- `txt`
- `csv`
- `tsv`
- `tex`
- `latex`
- `odt`
- `ods`
- `ott`
- `ots`

Markdown remains governed by ADR 0008. Folder-level document ingestion may
route `.md` files through the existing Markdown extractor, but DOCS0 does not
redefine Markdown graph identity.

RepoMap will not implement native DOCS-track support for:

- PDF
- DOCX
- XLSX
- RTF
- Pages
- Numbers
- Keynote
- email/mailbox formats
- chat/message exports
- photo libraries
- browser profiles
- password-manager vaults
- OCR/image text extraction

Mainstream formats should be converted outside RepoMap into the supported set
when needed. RepoMap then ingests the converted local artifact under the same
document folder policy.

## Scope

In scope:

- local documents folder architecture;
- closed supported document format set;
- external conversion policy for mainstream formats;
- privacy and redaction posture;
- document source types and folder policy;
- future raw observation concepts;
- future canonical namespace policy;
- TXT, CSV, TSV, TeX, LaTeX, ODF, and ODF template extraction boundaries;
- fixtures and test requirements for DOCS1 and DOCS2; and
- future phase planning.

Out of scope:

- implementing document extraction;
- folder ingestion code;
- OCR;
- PDF extraction;
- DOCX/XLSX extraction;
- Pages/Numbers extraction;
- RTF extraction;
- cloud connectors;
- email, message, browser-profile, photo-library, or password-vault crawling;
- MCP tools;
- storage migrations;
- changes to Markdown extraction;
- changes to ARCHIVE, WARC, feed, storage, or public readback behavior;
- Phase F migration; and
- YAML work.

## Product Posture

DOCS must be boring, local, and explicit.

Requirements:

- local only;
- no upload;
- no cloud connector;
- no training use;
- no automatic indexing outside configured roots;
- no hidden or system folders by default;
- no default home-directory or `~/Documents` scan;
- no email, message, browser-profile, photo-library, or password-vault
  crawling;
- no secrets in canonical keys;
- no full document bodies in canonical metadata;
- read-only MCP only if a later ADR accepts it; and
- the user explicitly chooses each root path.

## Source Types

DOCS0 reuses the ADR 0014 and ADR 0016 source-ingestion model.

Existing source types that apply:

- `local.directory`
- `local.file`
- `manual.import`
- `static_artifact`

DOCS0 also proposes future conceptual source types:

- `document.collection` for an explicitly configured local document tree; and
- `document.file` for one explicitly configured local document.

These are source-policy concepts, not accepted canonical graph namespaces in
DOCS0. DOCS0 does not implement source-type storage.

## Supported Formats And Phases

Recommended implementation phases:

DOCS1:

- TXT
- CSV
- TSV
- TeX
- LaTeX

DOCS2:

- ODT
- ODS
- OTT
- OTS

DOCS3, optional:

- folder-source polish and readback examples if DOCS1/DOCS2 reveal a need for
  clearer document collection workflows.

The closed supported set should remain closed. PDF, DOCX, XLSX, Pages, Numbers,
and similar native formats require a separate later ADR to reopen the decision.

## Conversion Policy

PDF, DOCX, XLSX, Pages, Numbers, RTF, and similar mainstream formats are not
native supported formats in DOCS.

Users may convert externally to supported formats:

- DOCX -> ODT or TXT
- XLSX -> ODS, CSV, or TSV
- PDF -> ODT, TXT, CSV, or TSV when external conversion quality is acceptable
- Pages -> ODT or TXT by export or external conversion
- Numbers -> ODS, CSV, or TSV by export or external conversion

Conversion is external to RepoMap. Quality depends on the converter and source
document, especially for PDF. Converted artifacts are treated as local imports.
Conversion provenance may be stored as safe metadata if supplied.

RepoMap does not perform DRM bypass, password cracking, OCR, cloud document
access, or native office conversion in DOCS1. RepoMap should not invoke
LibreOffice, Pandoc, or other converters unless a later ADR accepts optional
local conversion helpers.

## Raw Observation Concepts

DOCS0 proposes these future raw observation kinds:

- `doc.text_document`
- `doc.text_section`
- `doc.table_document`
- `doc.table_sheet`
- `doc.table_row`
- `doc.table_column`
- `doc.latex_document`
- `doc.latex_section`
- `doc.latex_command`
- `doc.odf_document`
- `doc.odf_text`
- `doc.odf_sheet`
- `doc.odf_style`
- `doc.reference`
- `doc.parse_error`

Observation principles:

- observations include source file path and line/span or structural evidence
  where practical;
- full document bodies are not serialized into raw metadata;
- full row or cell values are not serialized into canonical metadata;
- parse errors remain raw/evidence-only;
- extractor confidence is conservative; and
- redaction happens before raw observation serialization.

Existing Markdown raw observations and `doc.page`, `doc.section`, `doc.adr`,
and `doc.skill` canonical namespaces remain governed by ADR 0008.

## Canonical Namespace Policy

DOCS0 keeps DOCS formats separate from Markdown document semantics.

Recommendation:

- use `document.*` for DOCS-track formats; and
- keep existing `doc.*` namespaces for Markdown, ADRs, and skills.

Possible future namespaces:

- `document.file:<encoded-file-key>`
- `document.section:<encoded-file-key>:<encoded-section-pointer>`
- `document.table:<encoded-file-key>:<encoded-table-pointer>`
- `document.sheet:<encoded-file-key>:<encoded-sheet-pointer>`
- `document.column:<encoded-file-key>:<encoded-column-pointer>`
- `document.latex_command:<encoded-file-key>:<encoded-command-pointer>`
- `odf.document:<encoded-file-key>`
- `odf.part:<encoded-file-key>:<encoded-odf-part>`
- `odf.sheet:<encoded-file-key>:<encoded-sheet-pointer>`

DOCS1 should accept only the namespaces it actually needs. DOCS0 does not add
storage migrations.

Canonical keys must not include:

- full document body text;
- secret values;
- row or cell values;
- timestamps or current time;
- absolute machine paths;
- extractor versions;
- parser object IDs;
- line numbers; or
- model-generated labels.

## Edge Vocabulary

DOCS0 adds no edge kind.

Use existing edge kinds:

- `defines` for file-to-document, document-to-section, document-to-sheet/table,
  and document-to-column structural facts; and
- `references` for local file paths, URLs, citations, includes, LaTeX inputs,
  image paths, ODF package relationships, and similar syntactic references.

Markdown `links_to` remains Markdown-only unless a later ADR explicitly changes
that decision.

## Privacy And Redaction

Documents may contain highly sensitive personal, professional, legal, medical,
and financial data. DOCS implementations must treat document ingestion as a
privacy-sensitive local import.

Requirements:

- local-only operation;
- explicit root path;
- hidden and system folders ignored by default;
- default excludes for sensitive directories;
- no full bodies in canonical metadata;
- safe short summaries only when explicitly allowed by policy;
- redaction before raw observation serialization;
- no secret values in canonical keys;
- no secret values in raw metadata, canonical metadata, edge metadata, golden
  fixtures, readback, or explain output;
- full content belongs to local artifacts or evidence under policy, not
  canonical graph metadata.

DOCS reuses ADR 0010 secret-prone markers:

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

DOCS also accepts document-oriented redaction markers:

- `ssn`
- `social_security`
- `tax_id`
- `account_number`
- `routing_number`
- `iban`
- `credit_card`
- `medical_record`
- `patient_id`

DOCS1 may refine these markers, but it should start from this expanded set.

## Default Excludes

Future document folder ingestion should exclude by default:

- hidden files and directories;
- `.git`, `.hg`, and `.svn`;
- `node_modules`;
- build, cache, and temp directories;
- browser profiles and caches;
- mail stores;
- Messages and chat exports unless explicitly configured;
- Photos and photo libraries;
- password manager directories and vaults;
- `.ssh`;
- `.gnupg`;
- cloud-provider internal metadata directories;
- OS and system folders; and
- private key, certificate, credential, token, or secret pattern files unless
  explicitly fixture-tested with redaction.

## Folder Policy

A future documents source config should include:

- `source_id`;
- root path;
- include patterns;
- exclude patterns;
- allowed extensions;
- max files;
- max total bytes;
- max file bytes;
- hidden file policy;
- symlink policy;
- retention policy;
- summary policy;
- redaction policy; and
- review notes.

No implementation should automatically scan `~/Documents` or a home directory
without explicit source configuration.

Suggested TOML shape:

```toml
[source]
id = "example-document-collection"
type = "document.collection"
display_name = "Example Document Collection"

[policy]
status = "allowed"
max_artifact_bytes = 104857600
max_file_count = 5000
max_file_bytes = 1048576
hidden_files = false
symlink_policy = "do_not_follow"
retention_policy = "retain-local-path-and-hash"
summary_policy = "metadata-only"
requires_manual_review = false

[documents]
path = "documents"
allowed_extensions = ["txt", "csv", "tsv", "tex", "latex"]
include = ["**/*"]
exclude = ["**/.git/**", "**/.ssh/**", "**/.gnupg/**"]
```

## TXT Policy

TXT extraction should remain simple:

- emit a document node;
- optionally emit sections from conservative heading patterns;
- record line, paragraph, and byte counts;
- create `references` edges for conservative URLs and repo-local path-like
  strings;
- include safe short summaries only under size and redaction limits; and
- never put the full body in canonical metadata.

## CSV And TSV Policy

CSV/TSV extraction should focus on table structure:

- delimiter;
- header row detection when conservative;
- column nodes or column metadata;
- row count;
- column count;
- per-column type summaries;
- no cell values in canonical keys;
- no full row or cell bodies in canonical metadata;
- redaction for secret-prone column names and values; and
- optional sample values only if policy explicitly allows them and redaction is
  applied first.

## TeX And LaTeX Policy

TeX/LaTeX extraction is static only:

- document node;
- sections and subsections;
- labels;
- refs and cites;
- `\include` and `\input` file references;
- bibliography file references;
- graphics references such as `\includegraphics`;
- package names as metadata;
- commands and environments as metadata or optional nodes;
- no compilation;
- no shell escape;
- no package fetching; and
- no resolving external bibliography beyond local reference edges.

## ODF Policy

ODT, ODS, OTT, and OTS are ZIP packages containing XML. ODF extraction should
parse only local package bytes under strict package limits.

Rules:

- apply ZIP bomb and decompression limits;
- do not execute macros or scripts;
- do not fetch external links or images;
- parse safe package parts such as `content.xml`, `meta.xml`, `styles.xml`,
  and manifest entries;
- treat OTT and OTS as ODT/ODS-like templates with template metadata;
- use ODT paragraphs, headings, and tables as structure;
- use ODS sheets, tables, rows, and columns as structure;
- never put cell or body values in canonical keys;
- apply redaction to text, cells, and metadata; and
- represent external package relationships as `references` edges only.

## MCP Direction

DOCS0 adds no MCP tools.

Future read-only MCP tools may inspect already-indexed document graph facts
only. MCP import, indexing, write, or folder-scanning tools require a later ADR.
MCP should not expose full document bodies by default.

## DOCS1 Fixtures

DOCS1 should add:

```text
src/test/fixtures/discovery/docs_text_table_basic/
```

Fixture files:

- `notes.txt`
- `data.csv`
- `data.tsv`
- `paper.tex`
- `chapter.tex`
- `secret-notes.txt` or equivalent redaction cases

Coverage:

- text sections/headings;
- URLs and local file references;
- CSV/TSV headers;
- CSV/TSV type summaries;
- LaTeX section, ref, cite, label, input, includegraphics, and bibliography
  behavior;
- secret redaction; and
- unsupported binary/doc files skipped if present.

## DOCS2 Fixtures

DOCS2 should add:

```text
src/test/fixtures/discovery/docs_odf_basic/
```

Fixture files:

- small ODT;
- small ODS;
- optional OTT;
- optional OTS;
- package with external link or image reference;
- redaction case; and
- malformed or zip-limit case if feasible.

## Required DOCS1 Tests

DOCS1 implementation should test:

- TXT extraction;
- CSV extraction;
- TSV extraction;
- TeX/LaTeX extraction;
- URL and local reference detection;
- LaTeX include/input/reference behavior;
- CSV/TSV row and column counts;
- redaction;
- no full body or cell values in canonical metadata;
- no compilation;
- no external fetching; and
- no PDF/DOCX/XLSX ingestion.

## Required DOCS2 Tests

DOCS2 implementation should test:

- ODF package safety;
- ODT structure extraction;
- ODS sheet/table extraction;
- template metadata for OTT/OTS when implemented;
- external reference detection without fetching;
- ZIP/decompression limits;
- macro/script omission;
- redaction; and
- no full body or cell values in canonical metadata.

## Rejected Alternatives

Rejected:

- native PDF, DOCX, or XLSX support in DOCS;
- Pages or Numbers support;
- OCR;
- automatic scanning of `~/Documents`;
- cloud drive connectors;
- email, photo, message, browser-profile, or password-vault indexing;
- invoking external converters automatically;
- storing full document bodies in canonical metadata;
- semantic embeddings or vector search in DOCS0;
- MCP read/write import tools in DOCS0; and
- reopening Phase F as part of document ingestion.

## Proposed Phases

Recommended next phases:

- DOCS1: TXT/CSV/TSV/TeX/LaTeX extraction.
- DOCS2: ODT/ODS/OTT/OTS extraction.
- DOCS3: optional folder-source polish/readback if needed.
- YAML0 after DOCS is complete enough to return to core configuration work.
