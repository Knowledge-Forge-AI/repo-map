# ADR 0039: Synchronous And Asynchronous Execution Architecture

## Status

Accepted with phased implementation and explicit review triggers.

## Date

2026-07-13

## Context

RepoMap's first-release implementation is primarily synchronous. Repository
discovery, extraction, canonicalization, PostgreSQL publication, CLI lifecycle
operations, MCP standard-input dispatch, and configured multi-graph refresh all
execute through synchronous call chains. The local HTTP MCP adapter permits
concurrent request threads, and bounded helper threads isolate subprocess
streams, but there is no application-wide asynchronous execution model.

That architecture has useful properties. A forced-full refresh has one clear
owner, prepares one complete graph, and publishes one authoritative transaction.
Lifecycle operations are inspectable and CLI-owned. Failures roll back without
partial graph visibility. Tests and dogfood evidence cover deterministic output,
bounded errors, source protection, privacy, and exact database isolation.

The same architecture does not by itself provide a durable continuously
synchronized repository-backed graph mode. Filesystem watching, polling,
debounce, job coalescing, cancellation, progress, retry, backpressure, crash
recovery, multiple repositories, and laptop sleep or daemon restart require a
persistent coordination model. The strategic question is therefore broader
than whether functions should use `async def` or which PostgreSQL connector is
fastest.

GO22 and GO23 are the principal scale case study. GO22 corrected catastrophic
client memory amplification by lazily adapting storage rows and streaming
bounded SQL chunks with backpressure. It retained one `BEGIN`/`COMMIT` boundary
and no partial publication. Supported repositories then completed within the
first-release envelope, while a massive repository remained limited by millions
of deterministic row-oriented PostgreSQL operations. GO23 correctly classified
that remaining work as set-based, `COPY`, staging, batching, or incremental
storage architecture. Adding an event loop would not correct the write shape.

GO13 likewise found that caching extracted Go observations did not materially
improve full refresh because RepoMap still deserialized the complete observation
set, rebuilt the complete canonical graph, and wrote a complete run. A correct
incremental design requires language-neutral generations, invalidation,
delete/rename handling, dependency closure, evidence ownership, reconciliation,
rollback, retention, and deterministic full-refresh equivalence.

ADR 0038 therefore remains correct for the present: forced-full refresh is the
only supported first-release mode, lifecycle remains CLI-owned, MCP remains
read-only, and high-scale and incremental storage remain separate evidence-gated
decisions. ADR 0039 decides the longer-term execution and coordination target
without changing those present contracts.

## Decision

RepoMap selects a combined **hybrid coordinator and durable queued-job
architecture**.

The decision has two time horizons:

```text
Present architecture:
remain synchronous for the first release

Long-term target architecture:
use one persistent Python asynchronous coordinator with durable queued jobs
and bounded synchronous workers
```

This is Outcome H refined by Outcome Q. It is not an async-first rewrite and it
does not create two independent implementations of graph semantics.

The governing decisions are:

- **Present execution architecture:** keep current synchronous forced-full
  execution and current public behavior.
- **Long-term execution architecture:** introduce a persistent Python
  coordinator whose asynchronous work is scheduling, waiting, supervision,
  read-side multiplexing, and progress delivery.
- **Synchronous public mode:** retain the synchronous CLI as the primary
  operator interface and eventual submit/status/cancel/wait facade.
- **Asynchronous public mode:** expose a language-neutral durable job protocol
  to trusted local clients; do not create a second graph-semantic API.
- **Internal semantic implementation count:** one. Existing synchronous domain
  operations remain the initial worker implementation.
- **Coordinator language:** Python.
- **PostgreSQL default connector:** synchronous Psycopg 3 for current adapted
  readback; a bounded Psycopg asynchronous pool is the first long-term control
  for coordinator-owned queries.
- **PostgreSQL fallback connector:** retain `psql` for lifecycle, migrations,
  refresh publication, compatibility, operational recovery, and comparison
  until narrower accepted phases prove a safe replacement.
- **Optional comparison connector:** `asyncpg` may be benchmarked only after a
  fair pooled Psycopg asynchronous control exists; it is not selected as a
  production dependency.
- **Repository-watch architecture:** watcher events are hints feeding a durable
  queue; polling and periodic full reconciliation remain authoritative.
- **Job persistence:** use a coordinator-owned machine-local PostgreSQL control
  database with durable job state. Do not store the queue in graph product
  tables and do not add an external broker.
- **Delivery semantics:** at-least-once claim and execution with idempotency,
  leases, source-generation checks, and one mutating owner per graph.
- **Cross-language boundary:** retain the existing versioned JSON/JSONL
  subprocess boundary for approved helpers. Do not add a Go or Rust coordinator,
  extension ABI, gRPC service, or binary framing without a separate measured
  decision.
- **Migration timing:** no production execution change occurs in ASYNC0.
  Implementation begins with a language-neutral job contract and synthetic
  failure model in ASYNC1.

## Candidate Model Assessment

| Model | Conclusion |
| --- | --- |
| Model S, synchronous architecture | Retain for the first release; reject as the complete long-term target because it lacks durable coordination and recovery for continuous multi-repository mode. |
| Model A, async-first Python architecture | Reject now; a broad async conversion would not accelerate CPU-bound semantics or row-oriented PostgreSQL execution and would expand migration risk. |
| Model H, hybrid Python architecture | Select for long-term coordination; async owns waiting and supervision while bounded synchronous workers preserve one semantic implementation. |
| Model G, Go asynchronous/concurrent coordinator | Defer; technically credible, but Python model duplication, worker protocol, packaging, and parity costs lack measured justification. |
| Model R, Rust coordinator or storage engine | Defer; technically credible, but a third production language and native boundary lack a demonstrated hotspot. |
| Model Q, queued job architecture | Select as the durable execution model under Model H; queued versus request-bound execution is the primary product distinction. |

## Present Execution Architecture

Recommendation: Retain.

The first release remains synchronous because current evidence supports its
correctness and supported envelope. In particular:

- repository discovery and extraction remain deterministic synchronous
  operations;
- canonicalization remains one deterministic semantic implementation;
- forced-full refresh prepares the complete result and publishes it through one
  authoritative transaction;
- one graph cannot have two mutating refresh owners;
- lifecycle and destructive operations remain explicit CLI compositions;
- MCP remains read-only and receives no job-control or lifecycle tools;
- database, graph, baseline, and backup state do not change merely because ADR
  0039 accepts a long-term coordinator; and
- current package metadata and dependencies remain unchanged.

Async syntax is not a present performance remedy. Python documents that
`asyncio.to_thread()` normally makes blocking I/O non-blocking but generally
does not accelerate CPU-bound Python work under the GIL. RepoMap's extraction,
canonicalization, JSON transformation, sorting, evidence linking, and SQL row
adaptation require algorithmic, process, native-helper, or database-shape
decisions when they become bottlenecks.

## Long-Term Target Architecture

Recommendation: Adopt through bounded phases.

One persistent machine-local Python service will coordinate repository-backed
graphs. Its asynchronous layer owns:

- filesystem watcher and polling inputs;
- debounce and event coalescing;
- durable job submission and claiming;
- per-graph serialization and bounded cross-graph concurrency;
- worker subprocess creation, monitoring, cancellation, and cleanup;
- PostgreSQL control-plane queries and notification waiting;
- progress, heartbeat, timeout, and stuck-job detection;
- retry and poisoned-job policy;
- client status streams; and
- startup, sleep/wake, and periodic reconciliation.

Existing synchronous operations initially run as bounded subprocess workers.
This preserves process isolation, current transaction ownership, existing tests,
and one semantic implementation. The coordinator must never call a blocking
worker directly on its event-loop thread. CPU-bound Python parallelism, if
later justified, uses processes or approved native helpers rather than
unbounded threads.

Python `TaskGroup` or an equivalent structured-concurrency boundary will own
related coordinator tasks. Failure of one child must have an explicit policy:
cancel its sibling group, isolate the failed graph, or record an independent job
failure. Detached fire-and-forget tasks are not an accepted ownership model.

## Sync And Async Public Modes

RepoMap will not maintain two independent sync and async implementations.

The synchronous CLI remains useful for shell automation, operator ergonomics,
bounded one-shot commands, and environments without a running coordinator. For
coordinator-backed work it becomes a client facade:

```text
CLI request
→ submit or inspect durable job
→ optionally wait and stream bounded progress
→ return stable result and exit status
```

The asynchronous public contract is the durable job protocol, not an alternative
set of extraction, canonicalization, or storage functions. Trusted clients may
submit, inspect, wait for, and cancel jobs. They do not select arbitrary
executables or PostgreSQL commands.

An embedded direct mode may continue for explicitly supported one-shot
operations, but it must invoke the same semantic worker entrypoint and result
contract. It must not become a parallel implementation with different error,
transaction, privacy, lifecycle, or compatibility behavior.

Nested event-loop concerns are confined to client adapters. Library callers and
notebooks must not be instructed to call `asyncio.run()` from an already running
loop. A future Python API must expose either explicit awaitable client methods or
the synchronous facade, with ownership documented.

## Durable Job And Queue Model

The durable queue is the material architectural change. Async I/O is the
coordinator implementation technique.

The target uses a dedicated machine-local PostgreSQL control database owned by
the coordinator. It is not a shared graph database, does not change canonical
graph identity, and does not hold graph product nodes or edges. Its authorization
must be added to the exact operations policy before implementation.

The durable job model must include at least:

- stable job ID and graph ID;
- operation kind and versioned request schema;
- idempotency and coalescing key;
- source generation and configuration generation;
- priority and deterministic enqueue order;
- state, attempt count, retry class, and next eligible time;
- lease owner, lease expiry, and heartbeat;
- cancellation request and cancellation acknowledgement;
- current phase and bounded progress counters;
- bounded sanitized diagnostic and terminal result;
- created, started, completed, and retention timestamps; and
- worker and protocol versions needed for compatibility decisions.

Workers claim jobs transactionally. PostgreSQL `FOR UPDATE SKIP LOCKED` is an
accepted candidate for bounded multiple-consumer claiming because PostgreSQL
explicitly identifies queue-like tables as a valid use. It does not make other
control-plane reads intentionally inconsistent.

`LISTEN`/`NOTIFY` may wake idle coordinators after durable rows commit. It is not
the queue, is not an exactly-once delivery mechanism, and cannot replace startup
inspection or polling. PostgreSQL documents an initial listener race and advises
committing `LISTEN`, inspecting current state, and then using notifications for
later changes. Durable state therefore always precedes the notification.

Delivery is at least once. Exactly-once execution is rejected as an unsupported
claim across coordinator crashes, worker crashes, PostgreSQL restarts, and
publication uncertainty. Safety comes from idempotency, graph locks, lease
recovery, source-generation validation, transaction rollback, and terminal
result reconciliation.

## Repository-Backed Continuous Graph Mode

Repository-backed continuous mode treats the configured source as the desired
state and the graph as a reconciled projection.

The accepted event flow is:

```text
filesystem event, Git-state observation, config change, poll, or timer
→ sanitize and classify hint
→ debounce and coalesce per graph
→ persist reconciliation job
→ acquire graph mutation ownership
→ capture source/config/extractor generation
→ execute synchronous worker
→ verify generation before publication
→ commit one authoritative graph or discard stale work
→ record result and schedule follow-up reconciliation when needed
```

Filesystem notifications are optimization hints. They are not a source ledger
and they do not authorize file-level incremental graph mutation. The current
`notify` documentation warns that large watches may fail to receive all events;
editors and platforms also report changes differently. The `watchfiles` Python
package provides cross-platform notifications and debounce through Rust
`notify`, while its async API waits on the watcher through a thread. That makes
it a future dependency candidate, not evidence that the entire worker pipeline
should become asynchronous.

Continuous mode must handle:

- create, modify, rename, delete, and directory replacement;
- branch checkout, reset, worktree changes, and repository disappearance;
- watcher overflow, lost events, event duplication, and event reorder;
- polling-only filesystems and explicit polling fallback;
- periodic complete source reconciliation;
- extractor, schema, canonicalizer, and configuration invalidation;
- multiple repositories and bounded global resource use;
- laptop sleep/wake and service restart;
- stale queued work and source mutation during extraction; and
- full-refresh fallback whenever incremental equivalence is uncertain.

At worker start, the source and effective configuration receive stable
generations. Before publication, the worker or coordinator proves that the
generation still represents the intended source. If it does not, the prepared
result is not published and a replacement reconciliation is queued. This extends
LOCAL's operation-scoped source evidence without requiring exclusive ownership
of a developer's checkout.

## Coordinator Language

Recommendation: Python.

### Python

Python already owns RepoMap orchestration, configuration, graph models,
canonicalization, storage contracts, tests, packaging, and operator diagnostics.
`asyncio` supplies structured tasks, subprocess supervision, timeouts,
cancellation, streams, and local servers. Psycopg supplies synchronous and
asynchronous PostgreSQL APIs. Python therefore minimizes duplicated models and
lets the coordinator reuse existing public-safe tests and result contracts.

Costs are explicit: the GIL limits CPU-bound thread parallelism; cancellation
must cross process and transaction boundaries; exception groups require bounded
translation; type safety is weaker than Go or Rust; and a persistent Python
service needs disciplined task ownership and operator diagnostics.

### Go

Go has strong coordinator primitives: goroutines, channels, `context`
cancellation, worker pools, subprocess control, filesystem watchers, static
binary deployment, and `pgx`. RepoMap also has an approved Go parser helper.

Go is not selected because it would need to duplicate or remote the Python-owned
configuration, job, graph, result, privacy, and error models. It would add a
Python-worker protocol to nearly every orchestration path and expand release
packaging. Existing Go code proves that versioned persistent helpers are viable;
it does not prove that Go should own the control plane.

### Rust

Tokio, `tokio-postgres`, the synchronous `postgres` crate, and Rust filesystem
watching can support a safe and efficient coordinator. Rust could be valuable
for a future measured storage or parser hotspot.

Rust is not selected because RepoMap has no current Rust production boundary,
and a third implementation language would add build, packaging, model, protocol,
debugging, and contributor costs before a measured need exists. Theoretical
throughput is not sufficient evidence.

### Split Responsibility

The accepted split is Python coordination plus independently approved worker
helpers. Language-neutral versioned messages cross process boundaries. No
language other than Python owns job semantics, graph locking, publication
policy, or operator-facing error translation without a later ADR.

## Concurrency Granularity

| Layer | Classification | Reason and required guard |
| --- | --- | --- |
| across independent graphs | safe with a bounded global worker limit | dedicated databases isolate mutation; CPU, memory, and PostgreSQL capacity still require backpressure |
| across repositories mapped to independent graphs | safe with a bounded design | preserve one graph owner and source-generation checks |
| across files | safe only after deterministic process/helper merge tests | Python threads do not solve CPU work; output order and evidence ownership must remain stable |
| across extractor families | safe only after bounded design | families may share file/evidence identities and diagnostics |
| extraction and canonicalization overlap | unsafe under current full-run contracts | canonicalization consumes the complete normalized observation set |
| within canonicalization | requires a separate deterministic partition/merge design | canonical identity, evidence linking, sorting, and diagnostics are globally related |
| graph preparation versus storage | unsafe for one publication under current invariants | one source generation and one authoritative transaction own the run |
| storage row families | unlikely to help under current SQL shape | preserve dependency order and transaction failure attribution |
| storage database batches | requires set-based, pipeline, `COPY`, or staging architecture | async scheduling alone does not remove row-oriented server work |
| independent read queries | safe on separate pooled connections | operations on one connection serialize and share session/transaction state |
| MCP requests | safe with bounded read-only concurrency | keep pagination, privacy, and connector limits; never share unsafe cursors |
| background jobs | safe with leases, graph locks, and global backpressure | at-least-once execution requires idempotency and recovery |

## CPU-Bound And Database-Bound Work

Async I/O improves coordinator responsiveness while waiting. It does not by
itself accelerate:

- Python parsing, extraction, hashing, sorting, and evidence linking;
- canonical node and edge construction;
- JSON encoding, decoding, and Python object construction;
- SQL row adaptation and generation;
- compression or backup inspection; or
- PostgreSQL execution of millions of deterministic row operations.

Candidate remedies remain workload-specific:

- algorithmic reductions and bounded streaming;
- process workers for independent CPU partitions;
- existing or separately approved Go helpers for parsing hotspots;
- batched parameter execution and prepared statements;
- libpq pipeline mode where result ordering and recovery remain explicit;
- `COPY` into staging tables followed by set-based validation and publication;
- retention controls; and
- a separately accepted language-neutral incremental model.

PostgreSQL pipeline mode can reduce client/server round trips but adds queue and
error-recovery complexity, can consume more memory, and does not permit `COPY`
while the connection is in pipeline mode. It is an ingestion experiment, not a
synonym for asynchronous architecture.

## PostgreSQL Connector Capability Matrix

| Candidate | Language and mode | Protocol | COPY and batching | Pooling and concurrency | Cancellation, transactions, notifications, and adaptation |
| --- | --- | --- | --- | --- | --- |
| Psycopg 3 synchronous | Python, synchronous | libpq extended/simple protocol | sync `COPY`, prepared statements, and sync pipeline support | optional bounded sync pool; one connection serializes operations | libpq cancellation; explicit transactions; `LISTEN`/`NOTIFY`; mature Python type adaptation and SQLSTATE errors |
| Psycopg 3 asynchronous | Python, asyncio | libpq nonblocking APIs | async `COPY`, prepared statements, and async pipeline support | `AsyncConnectionPool`; tasks on one connection still serialize and share session/transaction state | async cancellation and notifications; transaction and adapter model closest to current implementation |
| asyncpg | Python, asyncio | native PostgreSQL binary protocol | COPY APIs, prepared statements, cursors, and native pooling | asyncio-native pool; connections reset on release | cancellation and transactions supported; PostgreSQL-specific records, codecs, exceptions, and pool semantics require a new adapter boundary |
| pgx | Go, concurrent | native PostgreSQL protocol | `COPY`, batches, prepared statements, and PostgreSQL-specific features | `pgxpool`; individual connections are not general concurrent-use objects | `context` cancellation, explicit transactions, `LISTEN`/`NOTIFY`, Go type mapping and errors |
| tokio-postgres | Rust, asynchronous | native PostgreSQL protocol | COPY streams and prepared statements; concurrent polling can pipeline independent requests | pooling supplied by ecosystem crates rather than the core client | future/task cancellation requires careful query/connection handling; transactions, notifications, typed conversion, and Rust errors |
| postgres crate | Rust, synchronous | synchronous facade over rust-postgres protocol stack | synchronous COPY and prepared statements | external pool required | synchronous transactions and typed conversion; boundary cost dominates unless it owns a larger worker operation |
| `psql` subprocess | external PostgreSQL client, synchronous process | libpq through official CLI | current migrations, lifecycle, refresh SQL streaming, and native `\\copy`/COPY-capable operations | process-level concurrency only; no reusable application pool | signal/process cancellation, transaction scripts, text/JSON decoding, bounded stderr translation |

## Connector Governance Matrix

| Candidate | Current version/support evidence as of 2026-07-13 | License, dependencies, and packaging | RepoMap evidence and integration cost | Decision, fallback, and removal effect |
| --- | --- | --- | --- | --- |
| Psycopg 3 synchronous | repository requires Python 3.12+ and Psycopg `>=3.2,<4`; benchmark used Python 3.13.12 and Psycopg 3.2.12 against the PostgreSQL 16 test image | LGPL-3.0; current binary extra supplies native wheels; cross-platform wheel policy already accepted | production adapted readback and parity tests exist; lowest integration and rollback cost | remain default; rollback is selected `psql`; removal would affect CLI, MCP, tests, and container packaging broadly |
| Psycopg 3 asynchronous | same Psycopg major and adapter family; current official API includes async connections, pools, COPY, pipelines, cancellation, and notifications | LGPL-3.0; a pool pilot would require explicit evaluation of the `psycopg_pool` distribution/extra | no RepoMap async parity or pool benchmark yet; closest migration path | first async control only after ASYNC job boundary; fallback is synchronous Psycopg/`psql`; no adoption in ASYNC0 |
| asyncpg 0.31.0 | upstream release 0.31.0 dated 2025-11-24; upstream documents Python 3.9+ and PostgreSQL 9.5 through 18 | Apache-2.0; native/Cython implementation with platform wheels; optional authentication dependency | no installed dependency or RepoMap benchmark; supporting two Python stacks doubles adapters, errors, pool policy, parity tests, and security updates | optional comparison after pooled Psycopg async control; not default; removal is cheap only before production configuration exists |
| pgx v5 | current upstream v5 supports Go 1.25+ and PostgreSQL 14+ under its rolling support policy | MIT; Go module and pure-Go PostgreSQL stack; cross-platform static deployment | capable but requires a persistent Go service or worker protocol and duplicates Python-owned models | no pilot now; reconsider only if coordinator or storage work becomes Go-owned through measured evidence |
| tokio-postgres 0.7.18 | release 0.7.18 dated 2026-06-12; current line requires Rust 1.85; the inspected upstream docs do not publish a bounded server-version matrix, so PostgreSQL compatibility must be proven against RepoMap's supported test envelope | MIT OR Apache-2.0; Tokio and protocol/TLS ecosystem dependencies; native Rust build and packaging | no Rust production boundary; highest new-language and cross-language cost | no pilot now; reconsider only for a measured Rust-owned component |
| postgres 0.19.14 | release 0.19.14 dated 2026-06-12, tracking tokio-postgres 0.7.18 | MIT OR Apache-2.0; synchronous Rust facade plus the same build ecosystem | a synchronous Rust connector alone offers no proven benefit over Psycopg after Python/Rust transfer cost | reject as a current alternative; a future stock control must batch a meaningful worker operation |
| `psql` 17.10 control | benchmark host client 17.10; repository disposable runtime uses `postgres:16-alpine` | PostgreSQL license; official external binary/container dependency | broad current lifecycle and mutation coverage; process startup is slower for small reads but behavior is an operational oracle | retain fallback and operational escape hatch; retirement requires parity for migrations, COPY/streaming, lifecycle, errors, smoke, and recovery |

Surface and rollback effects are explicit:

- Psycopg sync is already exercised by CLI and MCP readback, connector selector,
  parity, integration, and container smoke tests. Its rollback path is the
  selected `psql` fallback.
- Psycopg async would initially affect only the coordinator control/read side.
  It requires new pool, cancellation, notification, CLI-client, integration,
  failure, and smoke coverage; graph workers remain on the current transport
  until separately migrated.
- asyncpg would affect the same coordinator surfaces and additionally require a
  second type-codec, exception, transaction, pool-reset, packaging, and
  dependency test matrix. Rollback must preserve the Psycopg implementation and
  avoid persisted connector-specific job semantics.
- pgx would require a Go service or worker protocol, Go integration and smoke
  packaging, CLI error translation, and explicit proof that MCP remains
  read-only. Rollback must leave no Go-owned persistent job or graph contract.
- tokio-postgres or the synchronous Rust postgres crate would require equivalent
  Rust build, protocol, integration, cancellation, TLS, CLI translation, and
  smoke coverage. Rollback must not strand Rust-specific persisted state.
- `psql` affects CLI lifecycle, migrations, refresh publication, integration,
  smoke, and operator recovery. It has no MCP execution surface; its removal
  cost remains high until every accepted role has another tested owner.

Upstream asyncpg reports a substantial benchmark advantage over Psycopg on its
own driver benchmark. That claim is useful for candidate selection but is not
transferable to RepoMap's query shapes, adaptation, connection lifecycle,
transaction ownership, or end-to-end refresh. RepoMap requires its own pooled,
warm, parity-checked control before drawing a production conclusion.

## Connector Decisions

### Synchronous Connector

Recommendation: Keep one production default.

Synchronous Psycopg 3 remains the default adapted readback connector. No second
synchronous Python, Go, or Rust connector is justified. `psql` remains the
official fallback and the current mutation/lifecycle transport, not a competing
general-purpose application connector.

### Asynchronous Connector

Recommendation: Psycopg asynchronous pool first; comparison only after control.

When coordinator-owned PostgreSQL concurrency is implemented, the first pilot
uses a bounded Psycopg `AsyncConnectionPool` because it preserves the accepted
adapter and error family. The pilot must configure minimum and maximum size,
acquisition timeout, maximum waiters, lifetime, idle reset, startup/open, and
shutdown/close explicitly.

One connection is never treated as parallel query execution. Psycopg documents
that cursors on a connection serialize access and share session and transaction
state. Independent concurrent queries require independently acquired pooled
connections.

`asyncpg` is evaluated only if pooled Psycopg evidence leaves a material
coordinator bottleneck. Adoption requires query/result parity, type-codec and
error translation, cancellation, transaction, notification, pool reset,
packaging, security-update, and rollback evidence. Multiple production async
connectors are not accepted.

Go `pgx` and Rust `tokio-postgres` do not own PostgreSQL work unless a later
decision first selects a Go- or Rust-owned component large enough to justify the
boundary.

## Controlled Benchmark Evidence

ASYNC0 ran the existing public-safe connector comparator:

```sh
python3 tools/compare_pg_connectors.py \
  --iterations 5 \
  --pg-container-port 55433 \
  --json
```

Environment and method:

- Python 3.13.12;
- Psycopg 3.2.12;
- host `psql` 17.10;
- disposable `postgres:16-alpine` test runtime;
- repository migrations and the synthetic
  `psycopg-adapted-family-parity` fixture;
- seven adapted readback operations;
- two independent runs of five iterations per connector and operation; and
- payload parity required before timing rows were accepted.

Results:

- all seven operations had payload parity;
- `psql` medians ranged from approximately 54 to 61 milliseconds across both
  runs;
- synchronous Psycopg medians ranged from approximately 5 to 10 milliseconds;
- Psycopg first-operation cold maxima varied between approximately 68 and 114
  milliseconds; and
- payload sizes ranged from 174 to 1,331 bytes.

This benchmark supports the existing small-read choice: avoiding a new process
for each adapted query materially reduces latency. It does not measure a warm
pool, concurrent connections, writes, prepared-statement reuse, pipeline mode,
COPY, async scheduling, cancellation latency, client or server CPU, peak memory,
repository extraction, or full refresh. It therefore does not prove that
asynchronous Psycopg, asyncpg, Go, or Rust will improve RepoMap end to end.

No asyncpg benchmark was run because asyncpg is not a project dependency.
ASYNC0 does not alter dependencies merely to manufacture candidate evidence.

## Cross-Language Boundaries

Go and Rust were not serious coordinator candidates after the repository and
ownership audit, so ASYNC0 does not claim an unrun cross-language benchmark.

The accepted existing boundary is a persistent subprocess with versioned JSONL
messages where a non-Python helper owns a cohesive operation. It provides
process isolation, bounded diagnostics, explicit startup failure, and a
language-neutral testable schema. Its fixed startup and serialization costs are
amortized only when the helper remains persistent or handles meaningful batches.

Alternative boundaries remain unselected:

| Boundary | ASYNC0 conclusion |
| --- | --- |
| one subprocess per request with JSONL | simple but fixed startup dominates small work |
| persistent JSONL worker | accepted existing pattern for cohesive helpers |
| binary framing | deferred; no measured JSON serialization bottleneck |
| local socket or stdio RPC | suitable for the coordinator client protocol after ASYNC1 defines framing, versioning, cancellation, and bounds |
| HTTP or gRPC | rejected for the initial local service; unnecessary dependency and attack surface |
| PyO3, C ABI, or cgo | rejected without a measured in-process hotspot and packaging study |
| shared files or spool | unsuitable as the primary job protocol without atomic ownership, cleanup, privacy, and version contracts |
| shared memory | rejected; complexity and crash cleanup exceed current evidence |

Before Go or Rust becomes a serious coordinator, connector, or storage
candidate, a public synthetic benchmark must separate fixed call overhead,
serialization, Python object construction, database time, and worker time for:

- one small request;
- 100 records;
- 10,000 records;
- a representative large canonical batch;
- streaming records; and
- cancellation during transfer.

It must also record startup, batching, copying, memory, crash containment,
schema compatibility, packaging, and error propagation. Until then the boundary
cost is unknown, not negligible.

## PostgreSQL Correctness Constraints

Every coordinator, queue, connector, and concurrency phase must preserve:

- one authoritative latest graph;
- no partial publication;
- transaction rollback on failure and cancellation;
- deterministic canonical nodes, edges, evidence, and ordering;
- exact evidence and run ownership;
- dedicated graph isolation;
- source and configuration generation consistency;
- stored/preflight baseline and drift compatibility;
- bounded cancellation and diagnostics;
- retry safety and idempotency;
- static non-executing extraction; and
- path, credential, source, graph, and operational privacy.

Parallel publication, shared graph transactions, or partial latest-run
visibility require a separate ADR. Queue implementation does not authorize them.

## Cancellation And Progress

Cancellation is cooperative first and forceful only at a bounded process
boundary:

```text
client cancellation request
→ durable cancel_requested state
→ coordinator cancels waits and signals worker
→ worker cancels active PostgreSQL operation where supported
→ transaction rolls back
→ worker performs bounded cleanup
→ coordinator terminates the process group after the grace limit if needed
→ terminal cancelled or failed result is persisted
```

Cancellation after database statements begin never publishes a partial graph.
If commit outcome is uncertain after a connection loss, the coordinator inspects
authoritative run state before retrying. It must not assume either success or
rollback.

Progress is phase-oriented and bounded. Workers report current phase, completed
units, optional known total, heartbeat, and sanitized diagnostic category.
Progress is not raw stdout, a source excerpt, an unbounded SQL message, or a
guaranteed percentage when the total is unknown.

Timeouts belong to orchestration policy and are named per operation class.
Heartbeat expiry marks a job reclaimable only after worker/process ownership and
publication state are reconciled.

## Service And Process Topology

The target topology is:

```text
synchronous CLI or trusted local controller
                │
                ▼
permission-restricted local coordinator protocol
                │
                ├── durable PostgreSQL control database
                ├── watcher and polling adapters
                ├── bounded read connection pool
                └── bounded synchronous worker subprocesses
                            │
                            └── dedicated graph databases
```

The coordinator is one local scheduler, not one daemon per graph. Graph locks
and the worker limit prevent unbounded process and database concurrency.
Lifecycle/destructive operations remain outside daemon authority. An initial
service uses a permission-restricted local transport and does not listen on a
public network interface. Cross-platform transport details are decided in the
ASYNC1 protocol design without changing the authorization model.

No external message broker is introduced. An in-memory queue alone is
insufficient because it loses cancellation, retry, progress, and pending work
across restart. A filesystem queue is not selected because atomic claiming,
queries, retention, migrations, privacy, and crash recovery would reproduce a
database poorly.

## Failure Model

The target architecture handles failures as follows:

| Failure | Required behavior |
| --- | --- |
| worker crash | lease remains durable; reconcile publication state; retry only when safe |
| coordinator crash | workers are terminated or adopted only through an explicit protocol; expired leases are reclaimed after restart reconciliation |
| PostgreSQL restart or network loss | preserve durable intent where committed; classify transient failure; inspect uncertain publication before retry |
| laptop sleep/wake | expire stale timing assumptions, reconnect watchers and pools, then perform reconciliation |
| watcher overflow or missed event | enqueue full reconciliation; never infer completeness from the event stream |
| duplicate or reordered event | coalesce by graph and desired generation; jobs remain idempotent |
| repository deletion | record an explicit unavailable/tombstone condition; do not silently erase the last good graph without a separate policy |
| branch switch or force reset | invalidate older source generations and enqueue reconciliation |
| source mutation during extraction | reject stale publication and enqueue the newer generation |
| stale queued work | supersede before execution when a newer coalescing generation covers it |
| cancellation after SQL begins | cancel where possible, roll back, clean up, and inspect uncertain commit state |
| schema, extractor, or canonicalizer upgrade | invalidate incompatible jobs and require version-aware full reconciliation |
| poisoned job | bounded retry followed by quarantine with sanitized operator status |
| repeatedly failing repository | apply backoff and pause automatic work without blocking other graphs |

## Security And Privacy

A persistent daemon has a larger authority duration and attack surface than a
short-lived command. The following boundaries are mandatory:

- the service is machine-local and its transport is permission-restricted;
- requests select configured graph IDs and approved operation kinds, never
  arbitrary roots, executables, SQL, or connection strings;
- the coordinator does not possess or expose destructive lifecycle authority;
- workers receive the minimum graph-scoped capability needed for one job;
- exact internal routing may use private paths, but public CLI, MCP, status, and
  diagnostics retain ADR 0038 path-free presentation;
- job metadata, progress, and errors contain no source excerpts, raw
  observations, credentials, connection strings, backup receipts, or private
  topology;
- temporary files use private permissions, bounded lifetime, and deterministic
  cleanup;
- pool reset and connection reuse must prevent session-state leakage between
  jobs;
- logs remain bounded and separated from machine-readable result streams; and
- MCP remains read-only and gains no submit, cancel, refresh, lifecycle, or
  PostgreSQL execution surface through this ADR.

Authentication beyond local operating-system permissions, multi-user tenancy,
remote control, and lifecycle approval require separate architecture decisions.

## Migration Plan

The migration is incremental and parity-gated:

1. **ASYNC1 — durable job contract and coordinator boundary design.** Define the
   language-neutral request/result schemas, state machine, PostgreSQL control
   topology, leases, idempotency, coalescing, source generations, progress,
   cancellation, retention, local transport, and synthetic failure plan. Add no
   production daemon.
2. **ASYNC2 — durable queue and synthetic coordinator pilot.** Implement the
   control schema and a Python coordinator against synthetic no-op/failure
   workers; prove claim, lease, retry, cancellation, restart, and privacy
   behavior.
3. **ASYNC3 — synchronous worker adapter.** Wrap one existing non-destructive
   operation through the versioned worker protocol and prove direct/coordinator
   parity, bounded process control, and no duplicated semantics.
4. **ASYNC4 — refresh job pilot.** Add graph-scoped refresh submission,
   progress, cancellation, one-owner locking, rollback, uncertain-commit
   inspection, and synchronous CLI facade behind an explicit non-default pilot.
5. **ASYNC5 — repository reconciliation pilot.** Add polling first, then an
   evaluated watcher dependency if justified; prove debounce, coalescing,
   overflow recovery, sleep/wake, branch/reset, delete/rename, and full fallback.
6. **ASYNC6 — asynchronous PostgreSQL control.** Compare bounded Psycopg sync
   and async pools for coordinator read/control work. Evaluate asyncpg only if
   the fair Psycopg control leaves material measured headroom.
7. **ASYNC7 — adoption and compatibility evaluation.** Run multi-graph failure,
   privacy, performance, packaging, CLI, MCP read-only, container, and direct-
   mode parity gates before making coordinator-backed execution a default.
8. **ASYNC-CLOSE — epic closure.** Reconcile accepted behavior, remaining
   deferrals, operational evidence, and review triggers.

High-scale set-based storage and transactional incremental graph storage remain
separate architecture families. They may supply workers to this coordinator but
must not be smuggled into the ASYNC phases as implementation details.

## Relationship To Existing ADRs

| ADR | Relationship | ADR 0039 conclusion |
| --- | --- | --- |
| ADR 0001, durable graph model | prerequisite and reaffirmed | queued work must preserve stable canonical identity, provenance, and authoritative graph publication |
| ADR 0002, canonical keys and vocabulary | prerequisite and unaffected | concurrency cannot change canonical keys, edge kinds, or deterministic ordering |
| ADR 0003, canonicalization and storage transition | prerequisite and reaffirmed | one canonicalization model remains authoritative; worker placement does not change product semantics |
| ADR 0005, additive canonical storage | prerequisite and refined | queued publication preserves raw/canonical evidence ownership; no storage schema changes occur in ASYNC0 |
| ADR 0007, canonical readback and explanation | reaffirmed | read concurrency must preserve bounded deterministic canonical results |
| ADR 0009, public query migration | unaffected | ADR 0039 does not change canonical defaults or remaining compatibility contracts |
| ADR 0014, source ingestion | prerequisite and refined | asynchronous coordination remains separate from static acquisition/extraction and never authorizes target-code execution |
| ADR 0023, bulk local corpus ingestion | separate deferred decision | continuous coordination does not imply massive-repository or incremental support |
| ADR 0031, permanent local MCP operations | prerequisite and refined | the long-term local service direction gains a durable coordinator target; MCP remains read-only |
| ADR 0032, containerized local runtime and config home | prerequisite and refined | a coordinator/control database must remain machine-local and explicitly configured without changing config-home privacy |
| ADR 0033, backup-first database lifecycle | prerequisite and reaffirmed | destructive lifecycle remains CLI-owned and outside daemon authority |
| ADR 0034, operational-policy dogfood | prerequisite and reaffirmed | future pilots require protected sources, bounded public evidence, and exact graph scope |
| ADR 0035, dependency evaluation | prerequisite and reaffirmed | no dependency is added in ASYNC0; watcher, pool, or connector additions require explicit benefit, license, security, packaging, rollback, and test evidence |
| ADR 0036, package-tree architecture | separate decision | coordinator packages must respect domain boundaries but ADR 0039 does not move packages |
| ADR 0037, Psycopg candidate | refined | synchronous Psycopg remains default; Psycopg async pool becomes the first future control, while asyncpg remains evidence-gated |
| ADR 0038, local operations and canonical readback | prerequisite, reaffirmed, and refined | first-release forced-full, CLI lifecycle, read-only MCP, dedicated graph databases, privacy, and bounds remain; ADR 0039 adds only the long-term coordinator and control-plane target |

No earlier ADR requires a reciprocal edit. ADR 0039 does not supersede the
first-release contracts in ADR 0038.

## Consequences

Benefits include:

- a clear distinction between present synchronous correctness and long-term
  asynchronous coordination;
- one semantic implementation instead of duplicated sync and async behavior;
- durable recovery across daemon restart, worker crash, and laptop sleep;
- bounded concurrency and backpressure across independent graphs;
- explicit cancellation, progress, heartbeat, retry, and poisoned-job policy;
- a credible repository-backed continuous synchronization path;
- preservation of current deterministic publication and rollback guarantees;
- reuse of existing Python models, tests, adapters, and operator diagnostics;
- continued CLI ergonomics and read-only MCP safety; and
- evidence-gated connector and cross-language choices.

Costs include:

- a new persistent service and machine-local control database;
- another database lifecycle, migration, retention, backup-policy, and
  authorization surface;
- more complex failure, lease, cancellation, and uncertain-commit handling;
- a longer-running authority boundary and larger local attack surface;
- worker subprocess and serialization overhead;
- sync facade, coordinator protocol, and direct-mode parity testing;
- pool sizing and PostgreSQL capacity management;
- watcher platform variation and mandatory reconciliation;
- no immediate speedup for CPU-bound canonicalization or row-oriented writes;
- deferred asyncpg, Go, Rust, high-scale, and incremental decisions; and
- a multi-phase migration before continuous mode can become a supported default.

## Alternatives Considered

### Remain Synchronous Now And Long Term

Focused processes, threads, and polling could keep the implementation simple.
This was rejected as the long-term target because durable multi-repository job
state, responsive cancellation, progress, recovery, and client multiplexing are
first-class product requirements for continuous mode. Synchronous workers remain
valid inside the selected architecture.

### Defer The Long-Term Decision

Deferral would avoid committing before continuous-mode demand. It was rejected
because repository-backed synchronization is already an explicit strategic
driver and the evidence is sufficient to select coordination boundaries without
selecting speculative worker optimizations.

### Async-First Python Rewrite

Converting storage, extraction, canonicalization, CLI, and MCP internals to
async-first code could produce a uniform syntax. It was rejected because most
domain work is CPU-bound or deliberately serialized, transaction correctness is
already proven, and a rewrite would broaden parity and cancellation risk without
addressing GO22's write-shape evidence.

### Two Independent Sync And Async Implementations

Independent implementations might optimize each interface. They were rejected
because semantic drift, doubled tests, duplicated bug fixes, connector parity,
and lifecycle/error-contract divergence outweigh the benefit.

### Async Core With A Blocking Runner Everywhere

One async domain core could serve both modes. It was rejected for the initial
migration because it forces proven synchronous domain operations through an
event-loop contract, complicates embedded/nested-loop use, and does not solve
CPU or database work. The selected coordinator keeps async at the waiting and
supervision boundary.

### Go Coordinator

Go provides strong concurrency, cancellation, PostgreSQL, watcher, and static
deployment support. It was rejected because the dominant integration cost is
duplicating or remotely controlling Python-owned RepoMap models, not goroutine
capability. Reconsideration requires a measured boundary and a cohesive Go-owned
component.

### Rust Coordinator Or Storage Engine

Rust and Tokio provide high performance and memory safety. They were rejected
because no current Rust production boundary or measured hotspot justifies a
third language, native build pipeline, protocol duplication, and operational
debugging cost.

### asyncpg As Immediate Default

asyncpg is a credible asyncio-native PostgreSQL driver. It was rejected as an
immediate default because RepoMap has no async connector architecture or fair
pooled control, and a second Python PostgreSQL stack would double adapters,
error translation, parity, packaging, and security maintenance.

### Go Or Rust Synchronous Connector

`pgx` or the Rust `postgres` crate could move PostgreSQL work out of Python. The
alternative was rejected because a connector-only process or extension adds
transfer and packaging cost without evidence that synchronous Psycopg is the
bottleneck.

### `psql`-Only Architecture

The official client is reliable for migrations, lifecycle, streaming mutation,
and recovery. It was rejected as the only application connector because process
startup dominates small adapted reads and current Psycopg parity is proven.

### In-Memory Queue

An in-memory queue is easy to implement but loses pending work, cancellation,
retry, and progress on restart. It was rejected for supported continuous mode.

### Filesystem Queue

A filesystem spool would avoid a control database. It was rejected because
atomic claiming, queries, retention, migrations, privacy, leases, and recovery
would recreate a database with weaker tools.

### External Broker

Redis, NATS, RabbitMQ, or another broker could provide queue features. They were
rejected because the machine-local first target already requires PostgreSQL and
does not demonstrate broker scale, distribution, or availability needs.

### Watcher Events As Incremental Truth

Directly applying file events could reduce latency. It was rejected because
events can be duplicated, reordered, coalesced, or missed and do not encode
extractor invalidation, dependency closure, or source snapshot consistency.

## Review Triggers

- **Present synchronous architecture:** review before changing the first-release
  default, or when a supported workload demonstrates that request-bound
  execution prevents a required user workflow.
- **Python coordinator:** review if ASYNC2–ASYNC4 show that Python coordinator
  CPU, memory, cancellation latency, packaging, or service reliability breaches
  an accepted budget after blocking work is isolated.
- **Control database topology:** review if the added database creates measured
  lifecycle burden, if multi-user tenancy appears, or if graph federation
  changes the authorization boundary.
- **Queue semantics:** review before distributed coordinators, remote workers,
  exactly-once claims, cross-machine leases, or an external broker.
- **Cross-graph concurrency:** review worker limits when PostgreSQL saturation,
  host memory, CPU, or backup/restore interference appears in two representative
  concurrent workloads.
- **Per-file or canonicalization concurrency:** review only after deterministic
  partition/merge equivalence and memory evidence exist.
- **Repository watcher:** review dependency selection after platform tests cover
  supported filesystems, large trees, overflow, editor patterns, sleep/wake,
  and polling fallback.
- **Psycopg async pool:** review after ASYNC6 measures pooled sync and async
  query latency, throughput, cancellation, waiters, memory, client/server CPU,
  and session reset under RepoMap query shapes.
- **asyncpg:** review only if that fair Psycopg control leaves a material
  release-relevant bottleneck and the second-stack maintenance cost is included.
- **Go coordinator or pgx:** review only if a cohesive Go-owned component and
  the required small/100/10,000/stream/cancel boundary benchmark demonstrate a
  material advantage.
- **Rust coordinator or connector:** review only if a measured hotspot remains
  after Python/Psycopg and storage-shape controls and can justify the third
  language and native packaging.
- **`psql` fallback:** review retirement only after migrations, lifecycle,
  refresh streaming/COPY, error handling, recovery, container smoke, and
  operator escape-hatch parity exist elsewhere.
- **High-scale storage:** review under ADR 0038's trigger when one supported
  repository is release-blocked or two representative repositories demonstrate
  the same material write bottleneck.
- **Incremental storage:** review only with a language-neutral transactional
  design preserving full-refresh equivalence, deletes, renames, invalidation,
  provenance, rollback, and full fallback.
- **Lifecycle MCP or remote service:** review only through authentication,
  authorization, approval, audit, exact-target, backup-first, and interruption
  architecture separate from ASYNC.

## Explicit Deferrals

- changing the first-release synchronous default;
- adding the coordinator, control database, queue schema, or local protocol;
- selecting or adding a watcher dependency;
- adopting Psycopg async pool or `asyncpg`;
- changing `psql` mutation, migration, or lifecycle ownership;
- set-based, staging, pipeline, or `COPY` ingestion redesign;
- transactional incremental graph storage;
- per-file or canonicalization parallelism;
- Go or Rust coordination, connectors, services, or extensions;
- binary framing, shared memory, gRPC, or an external broker;
- remote, multi-user, federated, or multi-tenant coordination;
- lifecycle or destructive MCP tools; and
- automatic graph deletion when a source repository disappears.

## Non-Goals

ASYNC0 does not:

- modify production source, tests, fixtures, schemas, or migrations;
- add dependencies or change package metadata;
- implement async functions, services, workers, queues, watchers, or pools;
- change CLI or MCP commands, output, visibility, or authorization;
- change graph identities, repository scopes, or database topology;
- run graph refresh, lifecycle, baseline, backup, restore, or destructive
  operations;
- benchmark or publish private repositories or graph data;
- claim that a microbenchmark predicts end-to-end refresh performance; or
- supersede high-scale, incremental, lifecycle, privacy, or canonical graph
  decisions owned by earlier ADRs.

## Primary Research Sources

Sources were inspected on 2026-07-13. Primary sources govern candidate
capabilities; RepoMap benchmarks and current source govern RepoMap conclusions.

- [Python 3.14 asyncio tasks, cancellation, TaskGroup, and thread
  offloading](https://docs.python.org/3/library/asyncio-task.html)
- [Python 3.14 asyncio subprocess APIs](https://docs.python.org/3/library/asyncio-subprocess.html)
- [Psycopg 3 concurrent and asynchronous operations](https://www.psycopg.org/psycopg3/docs/advanced/async.html)
- [Psycopg synchronous and asynchronous pool APIs](https://www.psycopg.org/psycopg3/docs/api/pool.html)
- [Psycopg COPY APIs](https://www.psycopg.org/psycopg3/docs/api/copy.html)
- [asyncpg documentation and release repository](https://github.com/MagicStack/asyncpg)
- [pgx v5 official repository](https://github.com/jackc/pgx)
- [rust-postgres releases](https://github.com/rust-postgres/rust-postgres/releases)
- [Go context cancellation](https://pkg.go.dev/context)
- [Tokio task spawning and ownership](https://tokio.rs/tokio/tutorial/spawning)
- [Tokio graceful shutdown](https://tokio.rs/tokio/topics/shutdown)
- [watchfiles architecture](https://watchfiles.helpmanual.io/)
- [Rust notify platform limitations](https://docs.rs/notify/latest/notify/)
- [PostgreSQL 18 `SELECT` locking and `SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html)
- [PostgreSQL 18 `LISTEN`](https://www.postgresql.org/docs/current/sql-listen.html)
- [PostgreSQL 18 `NOTIFY`](https://www.postgresql.org/docs/current/sql-notify.html)
- [PostgreSQL 18 pipeline mode](https://www.postgresql.org/docs/current/libpq-pipeline-mode.html)
- [PostgreSQL 18 `COPY`](https://www.postgresql.org/docs/current/sql-copy.html)

## Private-Data Boundary

This ADR contains no private roots, local graph database names, credentials,
connection strings, configuration values, backup identifiers or receipts, raw
MCP payloads, source excerpts, graph dumps, raw observations, benchmark payloads,
or private development commit hashes. Evidence is limited to repository-relative
public paths, synthetic fixture labels, public aggregate timings, semantic phase
identities, official sources, and architecture contracts.
