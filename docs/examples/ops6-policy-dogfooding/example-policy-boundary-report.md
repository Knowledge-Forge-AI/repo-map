# MCP-OPS6 Example Policy Boundary Report

This example is public-safe. It uses fake fixtures under
`src/test/fixtures/ops_policy/` and does not include real private policy
content. The graph id in the command below is the fake identity defined by
that synthetic fixture, not a reference to any real graph.

## Command

```sh
repomap-kg ops policy-dogfood \
  --repo-map-home src/test/fixtures/ops_policy/repo_map_home \
  --graph codex-vc \
  --json
```

## Summary

- Graph: `codex-vc`
- Privacy: `private-ops`
- Graph root checked: `false`
- Server-memory read: `true`, through the read-only bridge
- AGENTS.md edited: `false`
- Server-memory mutated: `false`
- Destructive DB actions: `false`

## Policy Buckets

- Durable operational rules: fake memory-boundary policy cards.
- Private local preferences: fake machine-local path/config notes.
- Ephemeral task state: fake temporary task note cards.
- Generated graph evidence: configured graph metadata and exclusions.
- Secrets/sensitive facts: fake token marker redacted before output.

## Suggested AGENTS.md Refinements

The report suggests public-safe rule categories only:

- server-memory is a compact card catalog, not the policy library;
- RepoMap graph evidence is generated readback, not hand-authored policy;
- private roots require explicit user approval before reading or editing;
- secrets and private machine-specific facts stay out of public AGENTS.md;
- destructive DB lifecycle actions stay in local administrative CLI flows; and
- server-memory runtime JSONL is excluded from folder-tree graph ingestion.

## Leakage Checks

The example report must not contain:

- raw server-memory JSONL;
- raw full policy docs;
- fake secret values;
- real private paths;
- raw database credentials; or
- unbounded source text.

## Next Private-Local Step

A later explicitly approved private-local run may execute the same command
against a real configured local graph and server-memory bridge, then propose
guidance refinements in that private environment, outside the public RepoMap
repository.
