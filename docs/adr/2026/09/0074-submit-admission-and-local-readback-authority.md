# ADR 0074: Submit admission and local readback authority

## Status

Implementation candidate for REPOMAP-PRODUCT1-REFRESH-ADMISSION-READBACK-FIX1.
Product step 2 and ADR 0072/0073 acceptance remain pending.

## Date

2026-09-27

## Context

QUAL8 observed a refresh caller return unavailable before a job appeared later.
Configured generation resolution precedes durable submission. The ordinary
five-second RPC timeout cannot define admission authority. A table-lock wait
inside durable submission can also outlive a check made before that call.
Host readback currently relies on ambient libpq credentials rather than the
setup-owned read/status role.

## Decision

Authenticated version-1 submit payloads contain exactly `request` and
`admission_deadline` (absolute Unix seconds). The deadline is finite numeric,
non-boolean and at most 300 seconds in the future. Expired valid authority
returns `admission_timeout`; malformed authority returns `invalid_request`.
Other operations reject this field. Deadlines are never durable request data.

The client admission budget is `min(coordinator wait budget, 300 seconds)`.
The 300-second ceiling limits resource occupancy, comfortably exceeds the
observed approximately 83-second scan, and is not a performance target. Ordinary
RPCs retain their five-second default. Connection, send, and response consume
one monotonic budget, with at most one additional second for terminal response
transport. Admission is separate from the existing post-submit wait budget;
total duration can include both budgets and bounded response slack.

Server admission checks wall-clock expiration and a non-extending monotonic
budget before and after resolution, at the submission callback, after database
lock acquisition, and before transaction completion. Transaction-local lock and
statement timeouts bound database waits by remaining admission time. Expiration
rolls back; no job, attempt or publication may survive an expired admission.
The final pre-commit check admits commit/response completion; transport slack
does not authorize additional resolution or lock waiting.

Only a server-returned admission refusal maps to `coordinator_submit_timeout`.
It definitively refuses this attempt; an earlier successful same-key request
may still exist. Other transport loss remains uncertain and never automatically
resubmits. Successful replay returns the same durable identity.

Eligible setup-default native local homes project readback to
`repomap_read_status`, even with ambient `REPOMAP_PG_PASSWORD` or `PGPASSWORD`.
These ambient admin credentials do not override least privilege. Reuse the
owner-private no-follow runtime env reader, require exactly one bounded role
secret, and never generate, chmod, rewrite, export or serialize that secret.

Explicit literal/file credentials and custom configured environment references
retain authority. Resolving those configured credentials in readback is an
intentional correction to the prior ambient-libpq behavior, required by B4.
Custom/nonlocal configs never read runtime role secrets. Container role behavior
and internal endpoints remain unchanged. Credentials are passed only in memory
to Psycopg or in a private child environment to psql.

Canonical `storage edges` and `storage explain-canonical-edge` gain explicit
`--repo-map-home` and graph selection. Without local-home selection, existing
explicit connection defaults remain the default mode. Conflicting home and
connection flags refuse. Both families reuse the same readback authority helper.
Graph-selected queries pass the resolved `repo1:<graph-id>` identity, with the
existing MCP root fallback (`graph:<graph-id>` for explicit bindings, expanded
source root otherwise), so refresh-published rows remain addressable.

## Scope and verification

Only admission and host readback are changed. No background admission, direct
fallback, grant expansion, maintained-source refresh, MCP redesign or successor
product work is authorized. Required evidence includes delayed successful submit,
expired resolution and contended-lock rollback, stable replay, all five host
readbacks without password exports, denied role writes, and Product1 4+4.

## Rejected alternatives

Globally raising RPC timeouts leaves late admission possible. A Python check
alone cannot bound database lock waiting. Admin fallback violates least privilege;
mutating secret loading violates read-only command semantics.
