# Operator-local refresh output contract

PR26-STAGING-CONTRACT1 Decision A retains the existing legacy refresh contract.
Refresh result/status payloads are **not safe to share**: `public-dev` denotes
the configured privacy mode, not a shareable serialization API. Physical roots
and the independent `config_path` may disclose operator-local locations.

| Field/surface | Legacy `public-dev` | Explicit multiple bindings | Four private modes |
| --- | --- | --- | --- |
| Refresh result/status `root_path_display`, `root_path_expanded` | Existing physical configured locations | Existing empty root fields | `[private-root]` |
| Refresh repository display | Configured repository name | `[multi-source]` | Existing configured display contract |
| Top-level refresh `config_path` | Config location | Config location | Config location; root redaction does not redact it |
| Preflight root display | Existing physical root | `[multi-source]` | Existing private-root redaction |
| Graph-file records | Source-relative path and canonical identity | Binding-qualified identity and source-relative path | Existing access/privacy rules |

The supported private modes are `private-ops`, `private-memory`, `private-config`
and `sensitive-local`. Existing public-safe projections and credential filters
keep their own non-disclosure contracts. No new field or mode exposes paths.

Configuration ownership is `ops.config`/`config_graphs`/`config_records`; the
refresh owners are `ops.refresh_graphs._result_from_graph` and
`_status_from_graph`, `ops.reports._status_from_graph`,
`refresh_result_to_jsonable`, `refresh_status_to_jsonable`, and the record
serializers in `ops.report_records`. Preflight and refresh have distinct root
display owners. `ops.graph_files` and `graph_file_records` separately own
source-relative readback. A whole-report path assertion cannot replace those
record-level identity assertions.

The Q6-083 integration owner is
`src/test/int/python/repomap_kg/ops/multi_source_refresh_guard.int.test.py::test_legacy_one_source_publication_and_readback_qualifies_keys_with_source_relative_path`.
It asserts fixture-derived physical/config locations while preserving successful
publication, `file:root/modules/default.nix`, source-relative
`modules/default.nix`, binding alias/ID and candidate provenance. Its sibling
multi-binding path non-disclosure assertions remain intact. The pure
`report_boundaries.unit.test.py` owner characterizes all supported modes and
config-path independence; `config_redaction.unit.test.py`,
`multi_source_config.unit.test.py` and `multi_source_refresh_guard.unit.test.py`
retain the adjacent guards.

A distinct explicitly selected shareable projection remains deferred product
work. This phase implements, activates and starts no new projection or output
API. The original decision proposal and prior Q6-083 ledger remain historical;
the implemented contract correction still requires later hosted execution.
