# CLOE bounded operator resource reports

## Decision and phase

Accepted parent selection within W7 under the operator's roadmap-continuation
instruction, after CI126 and independent design review. Canonical phase
`REPOMAP-CLOE-RESOURCE-REPORT1` comprises three connected epics: bounded report
files and offline inspection; explicit single-operation CLI attachment; and
lexical query/revoke views with connected fault-custody proof. ADR0165 owns the
new CLI contract. ADR0159's internal-only implementation stays historical.

This is descriptive reporting. It adds no work limit, default enforcement,
dependency, schema, graph vocabulary, MCP field, worker protocol, telemetry
service or installed-state change. Full W7 and v0.1.0 remain open.

## File and domain contract

The file is `cloe-resource-view-v1` canonical compact UTF-8 JSON, sorted object
keys, no unnecessary escaping, and exactly one LF. Preserve the existing
8192-byte payload, 24-metric and 16-limit bounds. The file bound is 8193 bytes.
There are seven top-level fields: schema, operation, backend, outcome,
instrumentation, metrics and limits. No identities, source paths, query text,
bodies, provenance, environment, error text or arbitrary fields are retained.

Decode with a bounded regular-file descriptor read. Reject duplicate object
keys at every level, nonfinite values, floats, bool counts, missing/extra keys,
wrong shapes, unknown closed values, duplicate slots, invalid operation/backend/
outcome pairs and invalid per-operation metric/unit/basis or limit/unit/
enforcement combinations. Share explicit slot tables with producers. Validate
encoding too; a manually constructed object is not permission to bypass domain
checks. Require byte equality with canonical re-encoding plus LF. Whitespace,
alternate ordering/escaping, BOM, CRLF, -0 and multiple documents refuse.

Integer parsing and canonical rendering must be bounded by the file bytes and
independent of the interpreter's configurable decimal conversion limit, without
changing process globals. Chunked decimal conversion is acceptable. Preserve
all counts that fit the existing payload bound; do not introduce a numeric
work-policy ceiling. Reject excessive depth or decoding failures with a closed
path-free category. Human rendering must not multiply a huge integer's width
across every row; keep output bounded using individual rows or compact fallback.

Validation proves format and domain validity, not producer authenticity,
measurement truth, qualification, publication or transaction success. No
signature or identity binding is inferred from this identity-free file. Once
this vocabulary is public, later vocabulary growth requires a schema bump.

## Destination custody

Only an explicit option writes a report. The parent directory must already
exist, be owned by the effective user and private (no group/other permissions).
Resolve ancestor aliases once; refuse a final parent-component symlink. Hold a
non-inheritable directory descriptor and verify identity. No mkdir, overwrite,
recursive cleanup, rename-over-target fallback or host-wide cleanup is used.
The early target absence check is only a non-reserving fast-fail. Refuse unsafe
targets without following them. New files are regular, effective-user-owned,
and mode0600; apply fchmod so an unusual umask does not create unreadable output.

Create the exclusive temporary file only after the subject returns normally
or its existing handler converts a failure to an exit code. Perform bounded
full writes, file fsync, same-directory atomic hard-link no-clobber installation,
temp unlink and directory fsync. EEXIST is the authoritative target-race refusal.
Never fall back to overwrite-capable rename. Keep a complete installed file
after post-install failures; do not remove the destination. Report delivery
failure truthfully if temp unlink or fsync fails. Readers accept regular private
files with one or more links, because transient/failed temp cleanup can leave a
second link; they do not follow symlinks or accept FIFO/device/directory input.

Cleanup compares owned temporary identity and never intentionally removes a
foreign replacement. This is not isolation from a malicious same-UID process
racing between identity checks and unlink. Likewise, held descriptors prevent
path retargeting but do not promise that a renamed parent remains reachable at
the original display path: verify the selected parent identity before install;
refuse a disappeared/retargeted parent. External same-UID rename/mount races
after verification remain a documented limit. POSIX fsync is not macOS
F_FULLFSYNC or a guarantee against every filesystem/hardware power failure.

### Source and runtime separation

After existing request/authorization refusals and existing config resolution,
but before DB/source work, opt-in destination admission rejects a report
destination within any configured source root or managed home/store/runtime
directory. Include all configured bindings, not only a selected binding. Honor
explicit portable-store and source-root overrides. Compare normalized and
canonical paths, including alias overlap. Do not create a temp before capture
and do not add implicit discovery exclusions.

ONLY with the option selected, custody admission may perform metadata-only
`resolve(strict=False)` checks on configured roots and destination ancestry.
Unresolvable/looped/permission-denied paths refuse attachment before the
subject starts. Missing roots do not require body reads. This additional
output-safety metadata IO is explicit; default query/context behavior remains
source-blind. No discovery, source body read, extra SQL or fresh work ledger is
performed to manufacture report values. Scope the safety claim to admission
under stable configured roots; do not promise hostile same-UID mount isolation.

## CLI and result custody

New offline commands are `cloe ops resource-report check --input FILE` and
`cloe ops resource-report show --input FILE [--json]`. They have no home/config
arguments, run before product dispatch, and open no config, DB, source or worker.
Their process-level claim is the existing guarded forbidden-module/event
boundary, not a claim that the large CLI module has minimal imports.

Add `--resource-report FILE` only to single-operation Local/Server refresh,
lexical-build, lexical-query, lexical-revoke and context-pack. Refuse coordinator
refresh explicitly; do not add a root-global flag, refresh-enabled aggregate,
context-select, vector, Rust or MCP exposure. Existing cheap refusals precede
destination admission. No report is promised for a pre-request/config/refusal
path before an eligible owner is admitted.

An invocation owns one session and at most one admitted destination, including
the repeated SQLite dispatcher seam. Keep ownership explicit in the call/
Namespace; no global/thread-local state. Forward observer kwargs only with the
option selected. No-option stdout, JSON, stderr, exit codes and Python/mock
seams stay unchanged.

Delivery runs after stdout and the operation exit code are fixed, outside the
SQLite, lexical and Server subject catch blocks. Ordinary delivery/report/
cleanup errors yield a fixed path-free stderr warning and preserve the subject
result and exit. Existing caught failures keep their original diagnostic first.
Uncaught exceptions, KeyboardInterrupt and SystemExit produce no sidecar and
retain exact original exception custody; secondary cleanup cannot replace them.
A delivery-only interrupt may propagate after cleanup, outside publication
handlers: stdout may already state a committed result while the process exit
reflects the interrupt. Never relabel a committed publication as rolled back.

## Context and Local imports

Project only the actual returned context packet and available owner ledger.
No extra query or fresh ledger is allowed. Early refused/unavailable packets
constructed from a fresh placeholder ledger produce no sidecar. Budget-error
paths retain not-reached semantics if represented. A guessed early backend
must never become a measured report backend. Keep context projection in a
Local-safe module, separate from PostgreSQL staging imports. Package __init__
imports count toward the guarded Local boundary. Local help/report/check and
refresh/context remain free of Psycopg, Docker, parsers and enrichment imports.

## Lexical query and revoke

Add PostgreSQL-only lexical_query and lexical_revoke operation values and
optional resource_observer=None service wrappers. Preserve the old unobserved
path. Explicit per-operation slots, limits and outcome tables must cover normal,
degraded, unbegun and unfinished observers without KeyError or subject changes.

Query reports parent elapsed/CPU, returned hit/omission counts and existing
query controls. Preserve available and not_run as distinct closed outcomes;
available is not a claim of complete scope. Project the service envelope, not
the CLI's possibly budget-relabeled/stripped presentation. Immediate envelope
returns can prove timeout applicability false; SQL-path applicability stays
unknown unless the existing owner boundary actually proves it. No scanned-row
or byte estimate, query/hit/provenance copy, new SQL or source read is added.

Revoke reports returned aggregate effect counts after actual completion. Dry
run has a distinct preview outcome and unavailable effect metrics; its candidate
counts are not measured purges. With purge_rows=False, literal effect zeros
mean not_selected, not measured work. Repository-resolution misses may record
truthful zero-generation/no-work facts without exposing identity; unknown or
ambiguous effects remain unavailable. Negative rowcounts are invalid_owner_value.
The existing revoke timeout is an owner constant, not configured. Confirmation,
transaction, purge and dry-run behavior stays unchanged.

## Precise sealing correction

In _source_sealing_io._open_anchored transfer the current directory variable
to the opened child before closing the previous descriptor. An injected old-FD
close failure must retain its original exception and close the child, without
re-closing an old possibly reused number. This proves Python ownership under
the injected failure, not recovery from all possible kernel close states.
No capture limit, body/digest/metadata rule or broader rollback policy changes.

## Verification and completion

Use exact canonical scoped unit and containerized integration selectors with
--no-coverage. Test strict decoding/domain matrices and producer round trips,
no-clobber/temp/partial-write/fsync/close/identity races, original exception
precedence, context early paths, absent-option byte equality, all observer
outcomes and the sealing regression. Connected proof must use real files,
SQLite and core PostgreSQL, plus observed CLI children through existing shared
measurement registration. Prove actual graph/publication identity, no source
report ingestion, no inherited destination FD and useful first-use workflows.
Direct child SIGINT tests use the existing ACK/readiness protocol only.

No complete local unit/int/smoke/staging/system/combined suite, local coverage,
application/SDK build, new dependency/acquisition class, native parser/model
command, live graph/home or installed/release qualification is selected. Do
not weaken quality roots, debt ceilings, coverage denominator or hard85/85 and
80/80 gates. Desired87/82 margins remain pending hosted measurement. Admit new
owners cleanly and update real unit and integration owners together.

The parent verifies the integrated candidate and owns independent final review,
source pins and any later campaign. Aim for a meaningful batched milestone;
record actual LOC rather than padding a forecast. This design allocates no
build, wheel transfer or public campaign. A separate exact-source final grant
may select one CI127 after audited CI126 consumption37/6/16. Public main stays
unchanged. No automatic successor, release, tag or deployment follows.
