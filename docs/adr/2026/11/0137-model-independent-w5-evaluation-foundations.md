# ADR 0137: Model-independent W5 evaluation foundations

## Status

Accepted for REPOMAP-CLOE-SEMANTIC-FOUNDATION1 under the operator's approved
W5 roadmap and renewed instruction to continue on 2026-11-02. This decision
admits dependency-free evaluator code and disposable existing-fixture proof.
It does not itself authorize model/runtime execution; ADR0136 separately records
the accepted conditional route-A authority.

## Date

2026-11-02

## Context and authority

CI106 qualifies staging a300dc82d317ecde5646e4e90717b5eaa4aee8db. The next
approved roadmap segment is W5: optional vectors, measured fusion and the named
JSONB workload disposition. ADR0071 separately reserves inference/vector
generation; the operator's exact-dependency policy also reserves new runtime
selection. The separate route-A choice is governed by ADR0136. No model, wheel,
installation, inference, new corpus or held-out evaluation is authorized by
this decision.

ADR0136's model-dependent milestone remains a separate authority from this
foundation. Its broad implementation boundary does not prevent independently
authorized, dependency-free evaluator work under the existing roadmap. This
phase makes that distinction explicit rather than treating a continuation
instruction as approval of a model or dependency through ADR0137.

## Decision

Implement three connected foundations within the existing evaluator/test seams:

1. Canonical-node-v1 metadata bytes/digest and source-provenance validation.
   Use exactly canonical_key, kind and display_name with sorted compact UTF-8
   JSON, unescaped Unicode and invalid-string refusal. Recompute digest from
   independently accepted public-node fields; never certify an imported digest
   merely by hashing another untrusted copy of the same fields. Retain the
   existing 500-record ceiling, publication/snapshot and binding privacy gates.
2. File-level reciprocal-rank fusion and grading over explicit admitted arm
   observations. Verify actual read-back publication and complete receipt/vector
   identity; caller envelope metadata or a boolean 'trusted' flag is not proof.
   Preserve refusals, unavailable/failed/incomplete states, coverage gaps,
   generation boundaries and original node/span grading. Use exact rational
   contributions with k=60, collapse by binding/snapshot/source-relative-path,
   order each arm by best raw rank then tuple bytes, and use ordinal ranks.
   The output is an evaluator-owned versioned result, not a new product query
   mode, CLI/MCP payload, graph edge or automatic fallback.
3. A disposable named node-evidence JSONB experiment against the actual existing
   relational owner. Use existing public fixture publications only. Compare the
   same canonical-key/publication request, identity/provenance, current/historical
   semantics, ordering, caps, malformed-state behavior and refusal outcomes.
   Only after equality collect actual plans, timings/buffers/rows, preparation,
   index/build/update cost and footprint for no-index/jsonb_ops/jsonb_path_ops
   candidates. Use the existing binding/snapshot metadata containment facet,
   with source-relative-path equality declared before measurement. Retaining
   relational storage and no extra index is a valid disposition.

Experiment-local projections/indexes live only in disposable databases, are
removed at cleanup and are never adopted. Do not preload only the requested
answer or omit projection construction/refresh cost to manufacture a faster
query. Report the small fixture scale and missing selectivity/cardinality
ladder. No synthetic multiplier or new corpus is admitted.

The [foundation contract](../../../specs/cloe-w5-foundations-v1.md) supplies
bounded interfaces, evidence and implementation scope. ADR0136 and its
semantic-evidence specification remain the separate model-dependent authority;
this narrower accepted contract controls conflicts in the foundation phase.

## Boundaries and rollback

No changes to product CLI/MCP/schema, core package metadata, dependencies,
lockfiles, runner defaults, profiles, workflows or debt ceilings. No source
builds, application/SDK/optional-image builds, production extension admission,
private operational database, host IPC, source-body embeddings or private data.
All actual PostgreSQL work uses the canonical containerized disposable harness.
Tests may use existing public-safe precomputed vector mechanics; they do not
establish learned relevance. Do not run model inference or generate learned
vectors under an integration-test label.

Keep new Python owners clean under existing profiles and at most 400 physical
lines. Any necessary zero-debt inventory admission is parent-owned, separately
verified and cannot weaken a profile or historical authority.

The phase uses exact scoped unit and canonical containerized integration
selectors with --no-coverage, independent dispatcher review and fresh resulting
proof. Complete local suites, project coverage, image builds and remote CI are
not part of its local proof. Absent required cached infrastructure is a reported
boundary; it does not authorize rematerialization. Native AMD start 23 remains
spent. No 24th build or automatic retry is granted by this decision.

Rollback removes only new evaluator owners and invocation-owned disposable
objects. Canonical publication and maintained product behavior stay authoritative.
This phase may end as a reviewed local foundation checkpoint; full learned
vector/fusion usefulness, held-out criteria and public qualification remain
separate. Do not publish it as W5 completion or create a docs-only campaign.

## Subsequent separate operator authority

The operator subsequently accepted the bounded exact BGE/ONNX path in ADR0136
on 2026-11-02. References above to the pending selection describe this
foundation decision's original boundary. They do not revoke ADR0136 or grant
its authority through this model-independent ADR. Actual model proof belongs
to that separate accepted scope; optional source materialization and native
AMD application start24 remain unallocated.

## Subsequent bounded runtime and campaign

ADR0077's existing disposable pgvector materialization authority remains separate
from this model-independent decision. ADR0136 Route A supplies the exact isolated
model/runtime route; its public operational exit records the retained calibration
and capability gaps. ADR0138 separately allocates the fresh CI107/AMD24 campaign.
None of these observations closes production admission or full W5 qualification.
