# ADR 0034: Operational Policy Dogfooding

## Status

Accepted.

## Date

2026-07-02

## Context

ADR 0031 defined a permanent local RepoMap MCP operations model. ADR 0032
corrected that model toward an isolated containerized runtime and
`REPOMAP_HOME` TOML config folder. ADR 0033 defined backup-first database
lifecycle rules.

RepoMap now has:

- unified local operations config under `REPOMAP_HOME`;
- configured graph registry status and refresh commands;
- read-only MCP graph readback;
- a read-only server-memory JSONL bridge;
- graph `exclude_paths` enforcement; and
- local runtime database lifecycle guardrails.

The user eventually wants local graphs for `repo-map`, `codex-vc`,
`codex-memories`, and `flakes`, then wants RepoMap and server-memory evidence
to improve Codex operational policy boundaries. That future private workflow
must not leak private policy material into the public RepoMap repository.

## Decision

MCP-OPS6 establishes a public-safe dogfooding method and readback helper for
operational policy boundary analysis.

RepoMap will use:

- configured graph metadata and stored graph evidence as generated evidence;
- server-memory as a read-only card catalog;
- bounded classification buckets for policy candidates; and
- redacted report-only AGENTS.md suggestions.

MCP-OPS6 does not read real private roots, does not edit the user's real
`AGENTS.md`, does not mutate server-memory, and does not run private graph
refreshes. Public examples and tests use fake fixture content only.

## Policy Boundary Buckets

Dogfooding reports classify bounded evidence into these buckets:

1. Durable operational rules
   - Stable, generally applicable, low-secrecy rules.
   - Possible candidates for `AGENTS.md` or repo-local policy docs.
2. Private local preferences and machine-specific paths
   - Private configuration, local paths, and user-machine choices.
   - Belong in ignored `*.rpl.toml`, private docs, or server-memory cards.
3. Ephemeral task state
   - Temporary reminders, session notes, and current task state.
   - Belong in chat/session state or bounded server-memory entries.
4. Generated graph evidence
   - RepoMap-produced facts from configured graph roots and storage.
   - Should not be copied into policy docs unless a durable rule is extracted.
5. Secrets and sensitive operational facts
   - Credentials, tokens, database URLs, private keys, auth headers, cookies,
     and secret-bearing local data.
   - Never belong in public policy docs or ordinary readback output.

## server-memory Role

server-memory remains the compact card catalog. It may point to docs, skills,
policies, project notes, and local paths, but RepoMap treats it as read-only in
this phase.

Dogfooding reports may summarize server-memory counts and bounded labels. They
must not emit raw JSONL lines, full private policy text, or secret-like values.

## RepoMap Graph Role

RepoMap graph evidence is generated evidence over configured sources. It helps
find files, nodes, relationships, diagnostics, and stale or noisy areas.

Graph evidence does not replace server-memory and does not become user-authored
policy. For folder-tree-backed `codex-vc` graphs, server-memory runtime files
remain excluded from normal graph ingestion:

```toml
exclude_paths = [
  ".git",
  ".serena",
  ".venv",
  "__pycache__",
  "mcp/server-memory/memory.jsonl",
  "mcp/server-memory/serena",
]
```

The JSONL card catalog is handled through the server-memory bridge instead.

## AGENTS.md Refinement Model

MCP-OPS6 may produce report-only suggested AGENTS.md rules, such as:

- when to use server-memory as a card catalog;
- when to use RepoMap graph readback;
- when to ask before reading private roots;
- how to keep private local paths out of public commits;
- how to keep destructive DB lifecycle work out of ordinary MCP tools; and
- how to treat generated graph evidence as evidence, not hand-authored policy.

MCP-OPS6 must not edit the user's real private `AGENTS.md`. A later private
local phase may propose and apply real codex-vc edits only after explicit user
approval.

## Readback Helper

MCP-OPS6 adds a bounded local command:

```sh
repomap-kg ops policy-dogfood --repo-map-home <fixture-home> --graph codex-vc --json
```

The command:

- loads the configured TOML config home;
- requires an explicit graph id;
- reads server-memory only through the existing read-only bridge and only when
  the graph is enabled and MCP-visible;
- does not read graph roots;
- does not run discovery or refresh;
- does not mutate files;
- does not write storage rows;
- does not invoke database lifecycle commands; and
- emits bounded JSON or compact table output.

## Privacy And Redaction

Dogfooding output must not include:

- raw server-memory JSONL;
- raw full policy files;
- raw secrets or credentials;
- credentialed URLs;
- environment variable values;
- private keys;
- database URLs;
- raw source contents;
- unbounded snippets; or
- private root directory listings.

Public examples use placeholder paths such as `/path/to/codex-vc` and fake
secret markers only for redaction tests.

## Fixtures

MCP-OPS6 fixtures live under:

```text
src/test/fixtures/ops_policy/
```

They contain:

- fake codex-vc policy material;
- fake server-memory JSONL cards;
- a fake `REPOMAP_HOME` config home; and
- server-memory exclusion examples.

They must not contain real private policy content, real server-memory data, real
secrets, or real machine-specific path contents.

## Rejected Alternatives

### Read the user's real codex-vc tree in MCP-OPS6

Rejected. This phase must be public-safe and must not inspect private roots.

### Mutate server-memory to add policy links

Rejected. The MCP-OPS5 bridge is read-only, and server-memory remains the card
catalog unless a later phase explicitly changes that boundary.

### Automatically edit AGENTS.md

Rejected. MCP-OPS6 produces report-only suggestions. Real private policy edits
need a later explicit local phase.

### Treat graph evidence as policy truth

Rejected. RepoMap evidence is generated evidence. Policy remains user-authored.

## Consequences

RepoMap now has a repeatable, testable way to dogfood operational policy
boundaries without private leakage. Later private-local work can run the same
method against user-approved local graphs and server-memory data, then propose
specific private `AGENTS.md` improvements outside the public RepoMap repository.
