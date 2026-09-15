# ADR 0001: Graph Identity Model

## Status

Accepted

## Date

2026-06-29

## Context

RepoMap has two related but different responsibilities:

- preserve what deterministic extractors actually observed; and
- expose a durable repository knowledge graph that users can query across
  languages, tools, and indexing runs.

The initial implementation maps each raw observation into a graph-shaped source
node, optional target node, edge, and evidence record. That shape is useful for
early storage and readback, but it does not by itself define the long-term
domain graph. A source line such as `nix build .#checks` is an observation
event. The durable graph fact is that a repository file or script calls the
`nix` tool, with evidence pointing back to the line where that was observed.

This ADR defines the long-term distinction between raw observations, evidence
records, canonical nodes, and edges.

## Decision

RepoMap will treat raw observations as the extractor interchange and audit log,
evidence records as provenance, canonical nodes as domain entities, and edges as
domain relationships between canonical nodes.

Observation-derived source nodes, such as the current
`node:<path>:<kind>:<source_id>` rows, are temporary normalization and storage
artifacts. They are not the long-term domain graph identity model unless the
observed thing is itself a durable domain entity. Public graph queries should
move toward canonical nodes such as `file:bin/tool`, `tool:nix`, `env:PATH`,
`python.module:repomap_kg.cli`, and `nix.app:repo-map#tool`, with evidence
records attached to edges and, when useful, to nodes.

The current observation-derived nodes may remain internally while RepoMap is
building out storage and query surfaces. They should not become the vocabulary
that downstream users must depend on. As canonical graph modeling matures,
normalization should collapse multiple observations of the same domain entity
into one canonical node and attach one or more evidence records to the node or
edge that they support.

## Terms

### Raw Observations

Raw observations are extractor output. They are stored as JSONL and preserve the
fact that an extractor saw something in a repository file at a particular time
and with a particular confidence.

Raw observations are:

- appendable fixture and debugging records;
- extractor-specific enough to preserve parser details;
- suitable for replay into newer normalizers; and
- not themselves the canonical graph API.

Stable fields such as `kind`, `source_id`, `path`, `start_line`, `end_line`,
`name`, `target`, `confidence`, `extractor`, and `metadata` describe the
observation event and enough detail to normalize it.

### Evidence Records

Evidence records are provenance. They answer "why does RepoMap believe this
node or edge exists?"

Evidence records should preserve:

- repository file path;
- line range or other source span when available;
- extractor name and version;
- raw source identity;
- optional excerpt or structured parser metadata; and
- confidence inherited from or calibrated from the raw observation.

Evidence records are not domain entities. They can support many graph facts
over time, and a graph fact can have multiple evidence records.

### Canonical Nodes

Canonical nodes are durable domain entities in the repository knowledge graph.
They should have stable keys based on what the entity is, not on which
observation first discovered it.

Examples include:

- `file:bin/tool`
- `tool:nix`
- `env:PATH`
- `python.module:repomap_kg.cli`
- `nix.app:repo-map#tool`

Canonical node identity should survive extractor implementation changes when
the represented domain entity is the same.

### Edges

Edges are durable domain relationships between canonical nodes. Edges carry a
relationship kind, confidence, optional relationship metadata, and references to
supporting evidence records.

Edge identity should be based on source node, relationship kind, target node,
and any relationship-disambiguating metadata. It should not depend on a raw
observation `source_id` except as evidence metadata.

## Consequences

- Raw observation schemas can evolve independently from the canonical graph
  vocabulary.
- Query commands should prefer canonical nodes and relationships in their
  public output.
- Storage may keep observation-derived nodes during early implementation, but
  those nodes are staging details.
- The same canonical edge may be supported by multiple observations from
  different extractors or different lines.
- Confidence belongs on edges and can be summarized from the evidence that
  supports them.
- Evidence remains available for explainability even when graph identity is
  canonicalized.

## Examples

The examples below use illustrative canonical keys and relationship names. The
exact key grammar may be refined, but the separation of raw observation,
evidence, canonical nodes, and edges is the accepted model.

### File `bin/tool` Executes `tool:nix`

Source:

```sh
nix build .#checks
```

Raw observation:

```json
{"schema_version":1,"kind":"shell.command","path":"bin/tool","start_line":12,"end_line":12,"name":"nix build","target":"tool:nix","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"bin/tool#call:12:nix-build","metadata":{"argv":["nix","build",".#checks"],"command":"nix","raw":"nix build .#checks"}}
```

Evidence record:

- key: `evidence:bin/tool:12-12:repo-shell:bin/tool#call:12:nix-build`
- path: `bin/tool`
- span: line 12
- extractor: `repo-shell`

Canonical nodes:

- `file:bin/tool`
- `tool:nix`

Canonical edge:

- `file:bin/tool --executes--> tool:nix`
- confidence: `heuristic`
- evidence: line 12 in `bin/tool`

The current implementation may also store an interim source node such as
`node:bin/tool:shell.command:bin/tool#call:12:nix-build`. That node represents
the observation event, not the long-term domain identity.

### Shell Script Sources `lib/common.sh`

Source:

```sh
source ../lib/common.sh
```

Raw observation:

```json
{"schema_version":1,"kind":"shell.source","path":"scripts/build.sh","start_line":3,"end_line":3,"name":"source ../lib/common.sh","target":"file:lib/common.sh","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#source:3:lib/common.sh","metadata":{"argv":["source","../lib/common.sh"],"source":"../lib/common.sh","resolved_path":"lib/common.sh","raw":"source ../lib/common.sh"}}
```

Evidence record:

- key: `evidence:scripts/build.sh:3-3:repo-shell:scripts/build.sh#source:3:lib/common.sh`
- path: `scripts/build.sh`
- span: line 3

Canonical nodes:

- `file:scripts/build.sh`
- `file:lib/common.sh`

Canonical edge:

- `file:scripts/build.sh --sources--> file:lib/common.sh`
- confidence: `heuristic`
- evidence: line 3 in `scripts/build.sh`

### Shell Reads `PATH`

Source:

```sh
echo "$PATH"
```

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","path":"scripts/build.sh","start_line":8,"end_line":8,"name":"PATH","target":"env:PATH","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#env-read:8:PATH","metadata":{"operation":"read","variable":"PATH","raw":"echo \"$PATH\""}}
```

Evidence record:

- key: `evidence:scripts/build.sh:8-8:repo-shell:scripts/build.sh#env-read:8:PATH`
- path: `scripts/build.sh`
- span: line 8

Canonical nodes:

- `file:scripts/build.sh`
- `env:PATH`

Canonical edge:

- `file:scripts/build.sh --reads_env--> env:PATH`
- confidence: `heuristic`
- evidence: line 8 in `scripts/build.sh`

### Shell Writes `FOO`

Source:

```sh
FOO=bar
```

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","path":"scripts/build.sh","start_line":9,"end_line":9,"name":"FOO","target":"env:FOO","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#env-write:9:FOO","metadata":{"operation":"write","variable":"FOO","value":"bar","scope":"shell","raw":"FOO=bar"}}
```

Evidence record:

- key: `evidence:scripts/build.sh:9-9:repo-shell:scripts/build.sh#env-write:9:FOO`
- path: `scripts/build.sh`
- span: line 9

Canonical nodes:

- `file:scripts/build.sh`
- `env:FOO`

Canonical edge:

- `file:scripts/build.sh --writes_env--> env:FOO`
- metadata: `{"scope":"shell","value":"bar"}`
- confidence: `heuristic`
- evidence: line 9 in `scripts/build.sh`

The variable value is edge or evidence metadata. It is not part of the
canonical `env:FOO` node identity.

### Python Module Imports Another Module

Source:

```python
from repomap_kg import storage
```

Raw observation:

```json
{"schema_version":1,"kind":"python.import","path":"src/main/python/repomap_kg/cli.py","start_line":32,"end_line":32,"name":"repomap_kg.storage","target":"python.module:repomap_kg.storage","confidence":"extracted","extractor":"repo-python","extractor_version":"0.1.0","source_id":"src/main/python/repomap_kg/cli.py#import:32:repomap_kg.storage","metadata":{"imported_name":"storage","module":"repomap_kg.storage","syntax":"from_import"}}
```

Evidence record:

- key: `evidence:src/main/python/repomap_kg/cli.py:32-32:repo-python:src/main/python/repomap_kg/cli.py#import:32:repomap_kg.storage`
- path: `src/main/python/repomap_kg/cli.py`
- span: line 32

Canonical nodes:

- `python.module:repomap_kg.cli`
- `python.module:repomap_kg.storage`
- optionally, `file:src/main/python/repomap_kg/cli.py`

Canonical edges:

- `python.module:repomap_kg.cli --imports--> python.module:repomap_kg.storage`
- `file:src/main/python/repomap_kg/cli.py --defines--> python.module:repomap_kg.cli`
- confidence: `extracted`
- evidence: line 32 in `src/main/python/repomap_kg/cli.py`

### Nix App Exposes a Script

Source:

```nix
apps.aarch64-darwin.tool = {
  type = "app";
  program = "${self}/bin/tool";
};
```

Raw observation:

```json
{"schema_version":1,"kind":"nix.app","path":"flake.nix","start_line":20,"end_line":23,"name":"tool","target":"file:bin/tool","confidence":"extracted","extractor":"repo-nix","extractor_version":"0.1.0","source_id":"flake.nix#app:aarch64-darwin:tool","metadata":{"system":"aarch64-darwin","app":"tool","type":"app","program":"bin/tool"}}
```

Evidence record:

- key: `evidence:flake.nix:20-23:repo-nix:flake.nix#app:aarch64-darwin:tool`
- path: `flake.nix`
- span: lines 20 through 23

Canonical nodes:

- `nix.app:repo-map#aarch64-darwin:tool`
- `file:bin/tool`

Canonical edge:

- `nix.app:repo-map#aarch64-darwin:tool --exposes_script--> file:bin/tool`
- confidence: `extracted`
- evidence: lines 20 through 23 in `flake.nix`

If the exposed script is also executable and invokes tools, separate facts such
as `file:bin/tool --executes--> tool:nix` should be represented as separate
edges with their own evidence.

## Implementation Notes

Near-term storage can continue to use the current normalized rows:

- source node from raw observation identity;
- target node from `target`;
- edge from source node to target node; and
- evidence from file and line range.

Future canonicalization work should add or migrate toward:

- stable domain node key builders per extractor family;
- edge builders that connect canonical domain nodes;
- evidence-to-edge linkage that permits many evidence records per canonical
  edge;
- query output that distinguishes canonical graph facts from observation
  events; and
- compatibility views only where early storage/query commands need the existing
  observation-derived shape.
