# ADR 0064: Compact retained retention evidence

## Status

Accepted design for PR26-STAGING-FIX5-REVISE26; implementation remains subject
to focused verification and dispatcher-owned review and finalization.

## Date

2026-09-09

## Context

The hosted retention result occupied 5,077,574 bytes and aggregate evidence
occupied 5,718,594 bytes. Policy evaluation completed, but evidence exceeded
the existing 5 MiB aggregate limit. Repeated path, finding and cohort tables
dominate retention size. The live result remains necessary for policy evaluation.

## Decision

Keep the full live result and evaluation semantics. A dedicated retention
evidence compactor produces only the retained machine artifact after sanitization.
Keep the 200,000-byte per-log and 5 MiB aggregate limits unchanged.

Use a versioned complete projection and an explicitly incomplete failure
variant. Parse/bootstrap failures, including non-JSON output, cannot masquerade
as checked zero debt. Validate required fields, types, partitions, cohort and
regression identities, counts, and indexed-reference bounds before compaction.

Direct evidence retains status, classification, enforcement completeness,
census and eligibility/assignment/enforcement/residual counts; root counts,
closure and failure/unknown/policy states; checker/root finding counts; cohort
and admission counts; every admitted regression identity; candidate, inventory,
ratchet, governing-input, environment and immutable history identities; timings;
and bounded deterministic residual/blocker examples. Finding counts describe
records, not distinct paths. Root closure is independent of partial enforcement.
Unavailable per-root durations are `null`, never inferred as zero.

Every omitted collection retains its semantic element type, count, canonical
encoding version and SHA-256 commitment. A whole sanitized-source commitment
also covers source fields not individually projected. Commitments bind sanitized
evidence; existing source digests retain their original meaning.

Canonical encoding is UTF-8 JSON with sorted string mapping keys, compact
separators `(",", ":")`, `ensure_ascii=False`, JSON string escaping, and
`allow_nan=False`. Non-string mapping keys and unsupported values are rejected.
Declared sets normalize by canonical element bytes and count unique members;
mappings count entries; sequences retain order and duplicates and count elements.
Indexed finding/dependency catalogs are sequences and must never be reordered
independently of references. Mapping insertion order and set iteration order
must not influence commitments.

Sanitize diagnostic values and mapping keys before retention, rejecting key
collisions. Absolute scratch/tool-root paths must not survive in JSON or fallback
diagnostics. Verification checks the complete or incomplete schema, internal
consistency, aggregate retention status agreement, manifest membership, byte
sizes and hashes. Envelope verification establishes retained-byte integrity;
it does not reconstruct omitted collections.

## Scope and Non-Scope

This changes retained CI evidence only. ADR 0062/0063 history, same-run dependency
closure, immutable candidate validation, cohort ownership, hard admitted
regressions, zero credit for pending cohorts and enrollment rules remain intact.
There is no dependency addition, cap increase, opaque compression, product
architecture change or coverage-policy change.

## Required Verification

Focused tests cover nonmutation, canonical ordering, commitment sensitivity,
malformed source refusal, explicit regressions, sanitized keys and collisions,
both incomplete paths, schema/manifest tampering, aggregate-cap refusal and a
realistic result with at least 1,122 cohorts below 1 MiB. A normal aggregate
with 19 passing policies and one residual policy finding must finalize evidence.

## Alternatives and Consequences

Raising caps postpones duplication costs. Dropping the machine artifact removes
qualification evidence. Truncation without commitments loses accountability.
The compact projection instead trades detailed retained inspection for bounded
summaries and reproducible commitments; full live output remains available to
evaluation. Hosted qualification remains unknown until operator publication.
