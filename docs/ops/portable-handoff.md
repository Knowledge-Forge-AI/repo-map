# Optional portable source handoff v1

`tools/portable_handoff.py` is a standard-library local utility for explicitly
selected context. JSON is the round-trip record; deterministic Markdown is a
readable view of the same fields. Plain prose and ordinary navigation remain
available when this helper or a handoff is missing, stale, broken or over budget.
There is no tool registration, graph dependency, service or persistent memory.

The caller authors findings/inferences, selects references and reviews privacy.
The helper does not summarize logs, crawl source, generate conclusions, or execute
next checks. Omit credentials, raw payloads, private source IDs, environment and
host checkout roots before supplying content. Structural validation is not a
secret scanner: free text and opaque identities require caller privacy review.
Already sanitized graph values remain as supplied. Historical prose examples are
information-design context, not inputs to a general Markdown parser.

## Record contract

All object fields below are exact; unknown fields and duplicate JSON keys fail
locally with `HandoffError`. Version is the integer `1`. Lists retain caller order;
JSON object keys sort deterministically and UTF-8 JSON ends with one LF.

| Top-level field | Meaning |
| --- | --- |
| `version` | Integer `1`; other versions are unsupported |
| `task` | Short caller question/task |
| `references` | Selected source records, each with a unique evidence `id` |
| `findings` | `{id, kind, text, evidence_ids}`; kind is `finding` or `inference`, IDs link to references |
| `questions` | Unresolved caller-authored strings |
| `next_checks` | Inert caller-authored strings, including pasted command-like text |
| `negative_searches` | `{surface, scope, query, outcome, complete, has_more}`; strings plus Boolean completeness fields |

Every reference requires:

- `id`, `repository_identity`: opaque caller-selected identities, not host roots.
- `root: {key, origin}`: an explicit source/root key; origin is `caller_mapping`
  or `stored_binding`. A local mapping key is not a stored graph binding ID.
- `source_relative_path`: POSIX relative path, with no absolute/tilde path, URI,
  backslash, control character, empty/dot/parent component. `root/` is literal;
  it is never stripped or decoded from a key/module.
- `range`: `null` for path-only, or `[start, end]`, positive inclusive 1-based
  integers. A stored null range remains null even when a local excerpt is read.
- `origin`: `native`, `locator`, `historical` or `unknown`.
- `selection`: `direct`, `ambiguous`, `historical` or `unknown`; this describes
  caller selection context, not proof of current bytes or authored findings.

Optional reference fields:

- `provenance`: only supplied origin facts: `canonical_key`, `graph_id`,
  `binding_id`, `revision`, `run_id`, `publication_relation`, `freshness`,
  `ambiguity`, `has_more`, `evidence_role`, `location_scope`. Text/null is allowed;
  `run_id` additionally accepts nonnegative integers; `has_more` is Boolean.
  These preserve original publication/history, separate from local observations.
- `assertions`: caller strings, such as an externally asserted `verified=true`.
  They never bypass local checking. A bare `verified` field is unsupported.
- `recorded_content: {domain, range, sha256, origin}`: lowercase SHA-256,
  `domain="file"` with `range=null`, or `domain="range"` with an explicit range.
  Origin is `local_read` or `external`. Even an asserted `local_read` origin is
  historical input until an actual recheck; no serialized flag grants authority.

Native-only records omit graph/publication/binding provenance entirely. Ambiguous,
truncated, historical and unknown references remain representable. Preserve each
selected alternative separately and record omitted alternatives with `has_more`;
do not drop contrary evidence to fit a budget. A complete node no-match applies
only to its recorded surface and scope, never to arbitrary source-text absence.

For a selected compact `repomap_node_locations` reply, preserve the header's
`repository_identity`; use the chosen location's `source_relative_path` and exact
nullable `start_line`/`end_line`, and resolve its `binding` index into the header's
`bindings`. That supplied `binding_id` becomes `root.key` with `stored_binding`
origin. Copy header `canonical_key`, `graph.graph_id`, `freshness`, `ambiguity`,
`has_more`, `location_scope`, and row `run_id`, `publication_relation`,
`evidence_role` into provenance, together with the supplied `binding_id`.
Do not derive missing facts. Select `direct` only when appropriate; incomplete
provenance is retained for review but cannot authorize an automatic local recheck.
The maintained routed fixture demonstrates this mapping with an actual reply.

## Pure operations and limits

`export(record) -> str`, `load(str | bytes) -> dict`, and `render(record) -> str`
perform no source/graph/network/process I/O. The caller owns any input/output file.
JSON load is not verification. Markdown backslash-escapes significant punctuation,
escapes HTML delimiters, retains text lines and renders nested objects as nested
fields. Paths and ordinary punctuation remain readable in the raw file. Headings,
links, fences and pasted commands remain data; next checks are never executed.

The UTF-8 input **and canonical exported JSON** must fit 65,536 bytes. Each list
holds at most 32 items; each text value at most 4,096 Unicode code points, except
reference/finding IDs, repository identities and root keys at most 128. There is
no token budget. Over-limit records raise a reduction-needed error without
dropping entries, links or uncertainty. The caller chooses a smaller record.

## Explicit importing-caller recheck

`recheck(record, selected_ids, roots, source_check=None)` returns observations in
original reference order, only for selected IDs. `roots` is an external mapping
from `(repository_identity, root_origin, root_key)` to an absolute `Path`. It is never
serialized. Equal key strings with `caller_mapping` and `stored_binding` origins
occupy distinct mapping entries; no fallback between origins occurs.
The optional callback receives `(reference, inspected_text)`; it belongs to the
importing caller. Callbacks and serialized narrative are never interchangeable.

Only caller-selected direct references are read. Historical/unknown origins,
non-direct selections, truncated alternatives, non-accepted publication relations/scopes,
non-direct evidence roles or known non-single ambiguity produce `not_checked`.
Locator records additionally require all five explicit provenance facts:
`has_more=false`, `ambiguity="single_stored_location"`,
`location_scope="accepted_run"`, `publication_relation="accepted_run"`, and
`evidence_role="direct"`. Missing/null facts remain portable but are not selected
as current direct evidence. Native-only references require no graph provenance.
This is a selection guard, not a truth certificate for a caller's classification.
Invalid/unmapped roots, missing files and escaping symlinks affect individual
entries only. Resolution stays under the caller's root; no URI fetch, root
inference, moved-file search, refresh, repair or retry occurs. Ordinary personal
laptop files are assumed stable during a read; this is not a concurrent hostile
filesystem sandbox.

Reads keep the consumer's 65,536-byte file limit and 80-line selection limit.
UTF-8 decoding is strict, with no newline normalization; line selection uses
`str.splitlines(keepends=True)`, preserving CRLF/LF and any final unterminated line.
Range hashes cover the UTF-8 encoding of exactly those inclusive selected lines.
File hashes cover all bounded original bytes, independently of the predicate's
excerpt. A digest is compared only against its declared file/range domain.

A path-only reference inspects at most lines 1–80; `inspected_range` records the
actual excerpt separately from the null original range. Without a recorded digest,
the returned `content` hashes the whole bounded file for path-only references,
including bytes after line 80; ranged references hash their exact range. If a
recorded digest exists, `content` uses its explicit domain/range. Whole-file hash
equality is only byte equality of that bounded file. Neither digest nor a passed
predicate certifies a semantic claim, graph freshness or whole checkout revision.

| Outcome | Exact local meaning |
| --- | --- |
| `observed` | Actual permitted read; no recorded digest to compare |
| `matching` | Actual digest equals recorded digest in its declared domain |
| `changed` | Actual digest differs, or a recorded range no longer exists (`recorded_range_missing`); no digest or predicate is reported for an absent range |
| `missing` | Referenced file was absent under an existing caller root |
| `unmapped` | No caller mapping for this identity/origin/key, or its root is absent (`missing_root`) |
| `out_of_bound` | File exceeds bytes, selection exceeds 80 lines, or an unrecorded selection exceeds the file |
| `not_checked` | Uncertain reference, invalid mapping, unsafe/unreadable/non-UTF-8 source |

`source_check: true` appears only after an actual callback invocation passes.
`predicate` reports `passed`, `failed` or `error`; absence means no callback ran.
Callback exceptions are bounded locally without leaking their messages. Checks
never rewrite the original record or discard independent matching entries. Every
result carries the inert `next_action="native_search_or_review"`; nothing runs it.
To retain an observed digest, explicitly copy its `content` into a reference's
`recorded_content` and export a new caller-selected record.

## Small native-only example

This callable works under `python -I -S`: supply explicit absolute `repo_root`
and `workspace` Paths. The selected file must already exist. The helper is loaded
by filename, with no dependency on the current directory or package import path:

```python
import runpy
from pathlib import Path

def portable_example(repo_root: Path, workspace: Path) -> tuple[str, str, list]:
    api = runpy.run_path(str(repo_root / "tools/portable_handoff.py"))
    record = {
        "version": 1, "task": "Review normalization",
        "references": [{
            "id": "E1", "repository_identity": "repo1:example",
            "root": {"key": "source", "origin": "caller_mapping"},
            "source_relative_path": "src/normalize.py", "range": [2, 3],
            "origin": "native", "selection": "direct",
        }],
        "findings": [{"id": "F1", "kind": "inference", "text": "Review caller constraints.",
                      "evidence_ids": ["E1"]}],
        "questions": ["Are empty values allowed?"],
        "next_checks": ["Inspect selected caller tests."], "negative_searches": [],
    }
    encoded = api["export"](record)
    restored = api["load"](encoded)
    markdown = api["render"](restored)
    checks = api["recheck"](restored, ["E1"],
                           {("repo1:example", "caller_mapping", "source"): workspace},
                           lambda reference, text: "return" in text)
    return encoded, markdown, checks
```

A different caller supplies a different workspace under the same repository/root
triple. No serialized host root, graph ID or callback is needed. A known location
can also feed the existing `source_navigation_consumer.navigate` handoff path:
explicitly supply its legacy `binding_id` mapping slot and nullable start/end from
the reference. For native evidence that slot is a caller-local alias, not an
assertion of a stored graph binding. This utility requires no consumer adapter;
old/default calls and `source_text_paths` behavior remain unchanged.

The maintained `portable_handoff.unit.test.py` exercises the same record through
JSON/load/Markdown, relocation, zero-graph checks, changed/missing sources and
independent valid references. Its narrative/native source and manifests are
synthetic; the routed Markdown locator uses existing real static extraction,
canonicalization, SQLite publication and callable dispatch. Fixture source is
never executed. These checks demonstrate behavior, not an isolated agent trial,
token/time savings or causal navigation benefit.
