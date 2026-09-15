# RepoMap Documentation Reference Policy

## Purpose

This policy defines how RepoMap public-facing documentation refers to
development history when private development, private review control, and
published source may use different Git histories.

The policy makes semantic records durable across history curation. It prevents
public documentation from depending on private Git objects while preserving
exact commit identity where it is useful for trusted private review.

## Scope

This policy applies to tracked public-facing documentation in:

- `README.md`;
- `AGENTS.md`;
- `CONTRIBUTING.md`;
- `COMMERCIAL-LICENSE.md`;
- `CLA.md`;
- `SECURITY.md`;
- all tracked files under `docs/**`.

These are the currently tracked root documentation and governance files
relevant to development-history references. If another root document is added
later, the scanner scope must be updated explicitly rather than inferred from
untracked files.

This policy does not govern private manager/worker messages or review reports
stored in the private control plane, except to define what must not be copied
into public-facing documentation.

## Repository Trust Model

RepoMap uses or plans four distinct repository roles.

### Private Development Repository

[`lair001/repo-map_dev`](https://github.com/lair001/repo-map_dev) is the
private development repository and the authoritative source-development
history.

Its commits may be rewritten, curated, or omitted when accepted source is
published. A commit that exists only in this repository is not a durable public
identity.

### Private Control Repository

[`lair001/repo-map_ctrl`](https://github.com/lair001/repo-map_ctrl) is the
private manager/worker communication and review-control repository.

It is the planned durable home for private task bindings, review reports, and
other control-plane records that need exact private commit identity. Detailed
control-repository layout and migration remain separate operational work.

### Future Public RepoMap Repository

A future public RepoMap repository may be created from curated accepted
development state. Its Git history may differ from `repo-map_dev`.

The public repository's published source, public releases, and public tags or
commits may become exact public source identities. No private-to-public commit
mapping archive is currently required.

### Apache-2.0 Historical Repository

[`lair001/repo-map_apache-2.0-final`](https://github.com/lair001/repo-map_apache-2.0-final)
is the durable repository identity for the final Apache-2.0 RepoMap source
state.

Until the repository is actually public, documentation must describe it as
preserved or intended for publication. Once public, it is the historical
Apache-2.0 source reference. Current and future RepoMap development uses the
later licensing model recorded by ADR 0006.

## Authoritative Public Development Record

RepoMap's authoritative public development record is semantic and
source-backed. It consists of:

- phase and task IDs;
- public releases and change history in `CHANGELOG.md` and `docs/releases/`;
- accepted ADRs under `docs/adr/`;
- roadmap entries that record planning and phase sequence;
- contributor standards that define durable development policy;
- source, tests, and public releases published in the public repository;
- separately preserved historical repository identities where applicable.

Private development commits, internal status archives (`docs/status/`, withheld
from public releases), and private control-plane reports are supporting
evidence, not public record identifiers.

## Public Semantic Reference Hierarchy

Public-facing documentation should use the narrowest durable semantic reference
that makes the statement unambiguous.

### 1. Phase ID

Use a phase ID alone when:

- the surrounding section already links or names the phase's status document;
- the phase is unambiguous in the same document;
- the statement only needs sequence or ownership, not an audit trail.

Example:

```text
PSYCOPG7 established the opt-in summary driver boundary.
```

### 2. Phase ID Plus Release or Change Record

Use a phase ID plus release/change path when:

- one phase follows, approves, evaluates, or completes another;
- the reference crosses documents;
- a reader needs durable evidence or release context.

Preferred example:

```text
V001-FIX12, recorded in CHANGELOG.md and docs/releases/v0.0.1.md
```

(Internal status documents under `docs/status/` are withheld from the public repository.)

Do not write:

```text
PSYCOPG7, approved in commit <sha>
```

### 3. ADR Path

Use an ADR path when the reference identifies an accepted architectural,
storage, extraction, privacy, licensing, CLI, MCP, or other durable design
decision.

A phase status document may be cited alongside an ADR when both decision and
implementation evidence matter.

### 4. Roadmap Entry

Use a roadmap entry for planning, sequencing, deferred work, risk, or
recommended next-phase claims. A roadmap entry is not a substitute for an ADR
when an architectural decision requires acceptance.

### 5. Repository URL

Use a repository URL when the referenced identity is a separately preserved
source repository, historical archive, or distinct public project.

Repository references must state whether the repository is private, planned
for publication, or public. Documentation must not claim public availability
before it exists.

### 6. Public Release Tag Or Public Commit

A public release tag or public commit may be used only when exact public source
identity is materially necessary, for example for release reproducibility,
security response, provenance, or a legal source boundary.

Such a reference must:

- identify the public repository;
- resolve in a repository that is already public;
- explain why semantic phase, status, ADR, roadmap, or repository identity is
  insufficient;
- avoid any private `repo-map_dev` commit or private-to-public mapping.

The Apache-2.0 historical source is a special case governed by its repository
policy below; its public documentation uses the repository identity, not an old
tag or private commit.

### 7. Descriptive Prose

Use concise descriptive prose when no separate durable record exists. The
description must identify the behavior or decision rather than inventing a
history identifier.

## Public And Private History Boundary

Public-facing documentation must not contain or depend on private-development
commit SHAs.

In particular:

- a private SHA must not be used to say that one phase followed, approved, or
  completed another;
- a public reader must not need access to `repo-map_dev` to understand or
  verify a development-history statement;
- private base and result commits must not be copied from manager/worker tasks
  or reports into public documentation;
- private patch metadata must not be turned into a public history archive;
- the future public repository may use a curated history without weakening the
  phase, status, ADR, or roadmap record.

Phase IDs, status paths, ADR paths, roadmap records, and repository identities
are the cross-history references.

## Apache-2.0 Historical Repository Policy

Public-facing references to the final Apache-2.0 RepoMap source state must use:

```text
https://github.com/lair001/repo-map_apache-2.0-final
```

The reference policy is:

- use the repository identity;
- do not use the former private-development tag;
- do not use a private-development commit SHA;
- do not claim the repository is public until it is actually public;
- once public, treat it as the historical Apache-2.0 source reference;
- state that current and future RepoMap development uses its later licensing
  model where that distinction matters.

No tag or commit SHA is required for the Apache-2.0 reference.

## Legitimate Hash And Identifier Boundary

The private-history prohibition is not a ban on hexadecimal strings.

Legitimate values include:

- SHA-256 and other content digests;
- artifact checksums;
- package integrity hashes;
- payload and identity hashes;
- public cryptographic signatures;
- example fixture hashes;
- GUID components;
- migration, schema, database, backup, runtime, or domain-specific identifiers.

Documentation should label these values by function, such as `sha256`,
`payload_hash`, `identity_metadata_hash`, `checksum`, `GUID`, or
`artifact_id`, when the context would otherwise be ambiguous.

Length alone does not establish Git identity. A 40-character value is not
automatically a commit, and a 7-character hexadecimal-looking token may be a
phase-name substring or domain value.

## Future Documentation Scanner Contract

DOC-SHA2 defines the scanner contract but does not implement it.

### Tracked-File Scope

The scanner should inspect only tracked files in the public-facing scope:

```text
README.md
AGENTS.md
CONTRIBUTING.md
COMMERCIAL-LICENSE.md
CLA.md
docs/**
```

It should obtain the file set from Git so untracked files are never inspected.

### Candidate Discovery

The scanner should:

- detect likely 7-to-40-character Git SHA references;
- inspect bounded context for terms such as `commit`, `SHA`, `hash`,
  `approved`, `base commit`, `result commit`, `predecessor`,
  `accepted`, and `completed`;
- recognize references that span adjacent lines;
- optionally use Git object resolution when running inside `repo-map_dev`;
- distinguish resolved commits from content hashes and identifiers;
- treat an unresolved value with strong Git context as suspicious rather than
  silently accepting it;
- classify public release identities separately from private-development
  references.

The scanner must not depend solely on a hexadecimal regular expression.

### Diagnostics

For each rejected or review-required candidate, diagnostics should emit:

- repository-relative file path;
- line number;
- candidate;
- bounded, public-safe context;
- classification or reason;
- recommended semantic replacement.

Diagnostics must not include absolute local paths, untracked content, secrets,
private graph data, raw private source, or unrelated neighboring text.

### Gate Behavior

A future CI gate should fail for:

- a private-development SHA in public-facing documentation;
- a likely Git SHA with strong commit context and no approved public identity;
- an Apache historical reference that uses the old tag or a private SHA;
- a stale, unused, malformed, or overbroad policy entry if a public-identity
  registry is later introduced.

The gate should provide the preferred phase, status, ADR, roadmap, repository,
or descriptive replacement where it can do so deterministically.

### False-Positive Handling

The scanner must avoid rejecting:

- labeled SHA-256 or other cryptographic digests;
- package integrity and artifact checksum values;
- payload and identity hashes;
- cryptographic signatures;
- public-safe fixture hashes;
- GUID components;
- domain-specific hexadecimal identifiers;
- numeric byte limits;
- hexadecimal-looking phase-name substrings such as CANON-FACADE identifiers.

Useful signals include field labels, surrounding prose, token length and shape,
known fixture locations, and optional Git resolution. No single signal is
sufficient in every case.

### Safety And Determinism

The scanner should:

- use deterministic public-safe fixtures in tests;
- produce stable ordering and bounded output;
- avoid network access and URL following;
- avoid inspecting unrelated repositories;
- avoid private graph or runtime state;
- avoid automatic documentation rewrites;
- avoid emitting raw private content.

Scanner implementation, tests, workflow integration, and CI rollout require a
separate accepted phase.

## Exception Policy

There is no ordinary exception for a private-development SHA in public-facing
documentation, and no exception registry is currently needed.

A materially necessary exact public source identity is not a private-history
exception. It must satisfy the public release requirements above.

If a future policy revision introduces an exact public-identity registry, each
entry must include:

- exact documentation path;
- exact value;
- explicit reason;
- semantic public anchor;
- review owner;
- expiration date or objective review condition when appropriate.

The scanner must fail stale, unused, malformed, or expired entries.

The policy forbids:

- whole-file exemptions;
- directory-wide exemptions;
- broad regular-expression exemptions;
- undocumented inline suppression;
- exceptions for commits that resolve only in `repo-map_dev`.

## Private git-show-report Policy

`git-show-report` output is a private review artifact.

Private reports may retain:

- exact private base and result commit SHAs;
- commit metadata;
- changed paths;
- numstat;
- full patch;
- phase or task ID;
- status-document path;
- result and final gate;
- verification claims.

Exact commit identity is useful and expected for trusted manager/worker and
ChatGPT review. It is unnecessary in public development documentation.

The planned control-repository location is:

```text
reports/git-show/YYYY-mm/<phase-or-task-id>.report.txt
```

under `lair001/repo-map_ctrl`. This path is a recommended organizational
boundary, not a finalized control-repository schema. Establishing the
repository layout and moving existing private reports require a separate
control-repository setup phase.

Private reports must not be committed under `docs/` or copied into any public
repository. If a public explanation is needed, write a new semantic status,
ADR, roadmap, release, or security record and review it independently. Do not
publish the private patch report, even as a routine sanitized mirror.

## Manager And Worker Commit Bindings

Private control tasks and reports may bind work to:

- target repository;
- exact base commit;
- exact result commit;
- phase or task ID;
- status-document path;
- verification state.

These exact identities stay in the private development and control planes.
Public status documents preserve the phase, behavior, decision, and
verification result without copying the private commit binding.

## Public git-show Archive Decision

A public `docs/git-show/` archive is not required.

Reasons:

- status documents provide phase-level durable history;
- ADRs provide architectural decisions;
- roadmap entries provide planning and sequence;
- the public repository's source history will show published code;
- private patches may contain sensitive data;
- sanitized patch publication creates unnecessary redaction complexity;
- private reports remain available in the trusted control plane.

## DOC-SHA3 Cleanup Boundary

DOC-SHA3 should be a final docs-only cleanup phase that:

- rewrites the DOC-SHA0 status document to remove copied raw private commit
  SHAs;
- preserves inventory counts, categories, affected phase IDs, status paths, and
  replacement conclusions;
- replaces raw SHA tables with phase/status-document mappings;
- records that Apache references use
  `lair001/repo-map_apache-2.0-final`;
- performs a final scan of all tracked public-facing documentation;
- verifies that no prohibited private-history SHA remains.

DOC-SHA3 must not modify private `git-show-report` contents merely because
public documentation is scrubbed. Moving or reorganizing private reports
requires a separately authorized `repo-map_ctrl` phase.

## Policy Summary

- Semantic references are the public default.
- Private-development SHAs are prohibited in public-facing documentation.
- Legitimate cryptographic and domain hashes remain allowed.
- The Apache-2.0 source state uses its dedicated historical repository identity.
- Exact private commit identity remains available in private review reports.
- No public git-show archive or private-to-public commit map is required.
