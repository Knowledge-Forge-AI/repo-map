# STR-PUB5 Hosted Pipeline Owners

Status: executable owners added or extended; intentionally unexecuted locally
under TEST-ISO2 and hosted-CI state `EXHAUSTED`.

## Staging Gate

The changed-boundary owner is
`src/test/int/python/repomap_kg/storage/str_pub5_portable_publication.int.test.py`.
It starts disposable PostgreSQL, applies the real Liquibase closure, passes a
current seven-family `stage-unassigned-v1` bundle through
`run_staged_portable_refresh`, executes direct one-source `refresh_graph` through
the supervised worker and publisher into PostgreSQL, reconciles portable
`commit_unknown` state to matching success, and queries the committed final
receipt. It is not a callable, dictionary-only, `hasattr`, or documentation
placeholder.

The complete hosted matrix composes that owner with existing executable owners:

| Contract | Executable hosted owner |
|---|---|
| real managed one-source/multi-source worker, negotiation, cancellation, malformed/corrupt/semantic-invalid bundles, stage-smuggling, replay/conflict, authority denial, exact cleanup | `src/test/int/python/repomap_kg/artifacts/seam_pipeline.int.test.py` |
| direct/coordinator staged route, seven-family load, prior-state preservation, load/merge/receipt rollback | `src/test/int/python/repomap_kg/storage/scale8_staged_ingestion.int.test.py` and `scale3_staging_merge.int.test.py` |
| direct one-source portable refresh into disposable PostgreSQL | `src/test/int/python/repomap_kg/storage/str_pub5_portable_publication.int.test.py` |
| final portable receipt constraints and legacy compatibility | `src/test/int/python/repomap_kg/storage/publication_receipt_constraints.int.test.py` and `str_pub5_portable_publication.int.test.py` |
| `commit_unknown` matching success, proved absence, conflict/quarantine, replay fencing | `src/test/int/python/repomap_kg/storage/scale5_publication_fencing.int.test.py`, `scale15_terminal_adversarial.int.test.py`, and `str_pub5_portable_publication.int.test.py` |
| cancellation/connection settlement and prior-publication preservation | `src/test/int/python/repomap_kg/storage/test_cov5d_observer_cancellation.int.test.py` and `scale28_fix5_observer_cancellation_postgresql.int.test.py` |
| stage expiration, quarantine, and exact cleanup | `src/test/int/python/repomap_kg/storage/scale6_staging_cleanup.int.test.py` |
| sole mutating-owner exclusion | `src/test/int/python/repomap_kg/storage/arch1c_publication_exclusion.int.test.py` |

The STR-PUB5 unit cohort separately owns parent sealing, no credential/root
delegation, shared route selection, no legacy fallback, complete validator
matrices, publisher stage substitution, final receipt parsing/redaction, retention
classes, and no production selection of an unvalidated bundle.

## Main System Gate

`tools/system/scenario.py` executes the assembled coordinator route, interrupts and
restarts the coordinator, waits for authoritative success, and queries the exact
graph publication receipt. It now requires `portable-worker-v1` plus manifest,
extraction-receipt, bundle, and candidate identities before continuing to CLI and
read-only MCP determinism checks. This owner is real assembled-product evidence and
must not be run locally for STR-PUB5.

## Pending Classification

These owners remain pending the hosted Staging and Main System gates. Their presence
does not qualify deployment, branch publication, promotion, main-source-policy, or
the separately required PYLEN-SCALE14-FIX1 branch-hygiene correction.
