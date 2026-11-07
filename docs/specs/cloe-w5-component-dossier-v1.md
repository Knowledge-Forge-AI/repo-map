# W5 component correspondence dossier v1

ADR0148 defines the accepted tools-only reader, two-generation dossier and separately gated functional provenance proof. Build a dossier from explicit canonical journals, ResultV2 files, original pairedV2 bytes and optional complete raw model directories. Existing report and product interfaces remain unchanged.

The output binds canonical members, original report bytes and verified raw component correspondence with strict unknown/null handling. It carries no model vectors, task text, principal, SQL, admission scope or execution authority. A missing raw bundle stays unknown; a supplied invalid bundle refuses. The structural check command validates only the dossier itself. No inference, archived code, database or network is executed by these tools.

Epics A/B are implemented and independently reviewed. Scoped unit, containerized artifact/CLI integration, retention and original optional15 replay evidence pass. Final milestone proof and publication remain pending. Scientific criteria, held-out evaluation, calibration comparability and production admission remain reserved. Epic C passed independent source review and one separately allocated corrected functional diagnostic; complete raw journal and ResultV2 bindings establish six actual ANN index-use/cleanup observations across three repetitions with synthetic vectors only. No learned attempt16 is authorized.

The repository tool requires absolute paths and refuses relative paths with a public-safe exit3. Run it with the existing repository import roots:

```sh
PYTHONPATH=tools:src/main/python:src/test/support/python \
  python3 tools/retrieval_semantic_component_dossier.py check \
  --input /work/evidence/component-dossier.json
```

The build subcommand takes --journal-1, --journal-2, --result-1, --result-2, --paired-report and --output. Optional --model-1 and --model-2 select complete raw model directories. Omitting a model keeps correspondence unknown; supplying a partial or invalid directory refuses. Existing outputs are never overwritten. Check performs structural validation only and does not reopen original artifacts or live stores.
