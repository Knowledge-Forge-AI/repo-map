# Mixed-v1 Architecture and Snapshot Quorum Handoff

## Overview

The `RetrievalExecutionPipeline` in `core/pkg/pipeline.py` enforces deterministic
snapshot quorum handoff before any route target is dispatched. Every candidate
must carry a verified `cand1:` token and a matching `snapmanifest1:` seal.

## Failure Handling

When a snapshot vector diverges from the accepted store marker, the pipeline
raises `ERR_CLOE_MANIFEST_SEAL_MISMATCH_409: snapshot_vector!=accepted_vector`
and aborts the step without mutating state.
