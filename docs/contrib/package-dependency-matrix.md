# RepoMap Package Dependency Matrix

This document defines the allowed dependency direction for committed Python
production modules. It applies to static imports at module and function scope,
dynamic module loading, compatibility facades, and subprocess module targets.

## Target Direction

Dependencies point left in the matrix. A module may depend on its own layer
only when that relationship remains acyclic and represents one cohesive
responsibility.

| Consumer layer | Shared domain contracts | Extraction and canonicalization | Storage contracts and implementation | Operations | Platform adapters | Presentation |
| --- | --- | --- | --- | --- | --- | --- |
| Shared domain contracts | Allowed | Forbidden | Forbidden | Forbidden | Forbidden | Forbidden |
| Extraction and canonicalization | Allowed | Acyclic only | Forbidden | Forbidden | Forbidden | Forbidden |
| Storage contracts and implementation | Allowed | Allowed | Acyclic only | Forbidden | Forbidden | Forbidden |
| Operations | Allowed | Allowed | Allowed | Acyclic only | Forbidden | Forbidden |
| Platform adapters | Allowed | Allowed | Allowed | Allowed | Acyclic only | Forbidden |
| Presentation | Allowed | Allowed | Allowed | Allowed | Allowed | Acyclic only |

Layer meanings:

- shared domain contracts include graph keys, observation records, authority
  records, diagnostics, policy values, and other IO-free value contracts;
- extraction and canonicalization include static discovery routing, format and
  language extractors, canonical graph construction, and source interpretation;
- storage includes SQL, persistence records, readback, staged publication, and
  database transport contracts;
- operations include configured ingestion, refresh, baseline, drift, and
  lifecycle orchestration that combines lower layers;
- platform adapters include coordinator, runtime, service packaging, process,
  container, and operating-system integration; and
- presentation includes CLI, HTTP, MCP, and user-facing formatting or schema
  adapters.

An outward layer may expose a narrow lower-layer contract without taking
ownership of that contract. A lower layer must not import presentation,
platform, or operations behavior to format output, discover ambient runtime
state, launch processes, or resolve configuration.

## Compatibility Facades

A compatibility facade may re-export names from the same or a lower layer. It
must not contain domain decisions, construct a reverse dependency, or hide an
import cycle through function-local or dynamic loading. Existing public and
de facto import identities remain supported until a separately accepted
consumer inventory authorizes retirement.

Dynamic imports and `sys.modules` aliases are dependency edges. They require
the same direction as static imports and must be covered by an explicit
compatibility test. Moving an import into a function does not make a reverse
dependency acceptable.

## Production And Test Support

Test support may import production code. Production code must not import test
support, name test-support subprocess modules, or add test directories to a
runtime search path. No exceptions remain.

## Strongly Connected Component Guard

ARCH1D established a standard-library AST guard over all committed
`repomap_kg` production modules. The guard includes imports at every lexical
scope. It fails if any component appears or production references test
support.

ARCH1D removed the two-module storage telemetry component by extracting neutral
event records below connection wrapping and private-pipe transport. ARCH1E
removed the two-module graph discovery/extractor-routing component by extracting
the shared file record below both modules. ARCH1F removes the coordinator
protocol/launch/refresh component by separating protocol core, refresh errors,
worker environment, and outward compatibility facades. ARCH1G removes the
CLI/server/MCP component by moving shared canonical filter validation below
both presentation adapters. ARCH1H removes the operations/runtime component by
placing configuration loading below the runtime adapter and keeping status
readback in the public operations facade. ARCH1I removes the final
extractor-configuration component by placing format, value, reference,
observation, profile, and structure contracts below the generic registry and
format implementations. ARCH1J removes the production-owned synthetic-worker
fixture boundary by moving the fixture target, support path, mode allowlist,
and fixture-selecting coordinator factory into test support.

The static SCC allowlist is empty and the committed production import graph is
a DAG. The production/test-support exception allowlist is also empty, so
`ARCH0-LAYER-001` is resolved.

## ARCH1D Telemetry Consumer Inventory

The combined `storage.backend_telemetry` facade remains the production import
surface used by staged publication, refresh orchestration, the backend
observer, and CLI wiring. Existing tests also import the connection wrapper and
event transport modules directly; those module paths, exported class objects,
factory functions, and patch targets remain unchanged.

No telemetry consumer uses dynamic import, a subprocess module target, or test
support. The new `storage.backend_telemetry_contracts` module owns only the
error, event enum, frozen event record, and event constructor. Connection
wrapping and event transport both depend on it; the event transport depends on
the connection wrapper for its inherited-pipe factories, and the
connection wrapper no longer imports transport behavior.

## ARCH1E Discovery Consumer Inventory

Production callers import classification, discovery, exclusion defaults, and
`FileInfo` from `graph.discovery`; that module remains the compatibility and
orchestration surface. Operations ingestion modules are the only production
callers that import `FileInfo` directly. Existing tests import the discovery
orchestrator, import extractor adapters directly for facade checks, and patch
`graph.discovery.classify_path`. Those paths and object identities remain
unchanged.

No production discovery consumer uses dynamic import, a subprocess module
target, or test support. Package-structure tests use dynamic import only to
verify the committed compatibility surfaces. The new
`graph.discovery_records` module owns only `FileInfo` and its unchanged raw
observation and metadata projections. Discovery orchestration and extractor
routing both depend on it; extractor routing no longer imports discovery even
under `TYPE_CHECKING`.

## ARCH1F Coordinator Consumer Inventory

`coordinator.protocol` remains the public compatibility surface for protocol
constants, errors, records, sessions, encoding, decoding, stderr retention,
generic supervised launch, and refresh launch. Protocol behavior now lives in
`coordinator._protocol_core`, which has no dependency on worker launch or
refresh adapters. The public generic launch wrapper retains the established
`coordinator.protocol.launch_managed_process` patch seam.

`coordinator.refresh_adapter` now owns refresh capability IO and refresh-worker
launch. `coordinator._worker_launch` continues to export the identical
`run_refresh_worker` object for compatibility while owning only a generic
immutable worker launch specification and supervised launch operation.
Refresh execution and the adapter share only the neutral error classes in
`coordinator._refresh_contracts`; execution no longer imports the adapter.

Production callers continue to import coordinator protocol and refresh
contracts from their established public modules. Tests retain direct imports
from the public protocol, refresh adapter, and worker-launch modules. The
public `protocol.subprocess.Popen` and
`protocol.launch_managed_process` patch targets remain effective. No dynamic
production import or new subprocess module target was introduced.

The synthetic-worker module, test-support search path, mode allowlist, and
fixture-selecting coordinator factory now live outside production in
`repomap_test_support`.

## ARCH1G CLI And Server Consumer Inventory

`storage.canonical_filters` now owns canonical node, edge, and neighborhood
filter validation. Both `cli.main` and `server.mcp_core` import the same
function objects. The CLI main module and dynamically populated
`repomap_kg.cli` package facade therefore preserve their established exports,
and the CLI storage command adapters continue to bind those objects from the
commands module supplied by dispatch.

The former reverse dependency was limited to `server.mcp_core` importing three
validators from `cli.main`. MCP core now imports their neutral storage-facing
owner. CLI dispatch continues to load `server.mcp.serve_stdio` at the outward
presentation boundary, and CLI main continues to use the HTTP and
server-memory adapters. With no server-to-CLI edge, those dependencies are no
longer cyclic.

No test or production caller patches the three validators. No dynamic
production import or subprocess target names them. The CLI package facade's
existing dynamic import of `cli.main` remains covered by identity tests, and no
CLI, MCP, JSON, table, storage-query, lifecycle, or error contract changes.

## ARCH1H Operations And Runtime Consumer Inventory

`ops.config_loading` now owns operations configuration loading, merging,
validation, and construction below runtime adapters. `runtime.plan` and
`runtime.local` import that owner directly. The public `ops.config` module
continues to expose the identical loading, record, helper, projection, and
storage utility objects while retaining status SQL and readback orchestration.

`ops.report_records` now imports diagnostic and redaction contracts from their
lower helper owner. Operational JSON readback retains its established runtime
container fallback, and `ops.config.execute_ops_json_readback` remains the
effective status-test patch target. Runtime lifecycle, container inspection,
root facades, JSON/table payloads, SQL, and error identities are unchanged. No
dynamic import or subprocess target was added.

## ARCH1I Extractor Configuration Consumer Inventory

`extractors.config.generic` remains the routing and compatibility facade for
structured configuration extraction. Neutral format, reference, value,
observation, profile, and structure contracts now sit below both that facade
and the format implementations. The XML, YAML, JavaScript, Python, Terraform,
OpenAPI, and infrastructure helpers no longer import the broad registry, even
at function scope.

The generic facade and the new contract owners expose identical constants,
exceptions, helpers, and observation functions. Existing YAML limit patch
targets remain effective through outward facade-to-owner synchronization. No parser,
limit, redaction, profile, routing, observation, dynamic import, or subprocess
contract changed.

## ARCH1J Synthetic Worker Consumer Inventory

`coordinator._worker_launch` owns `WorkerLaunchSpec` and generic supervised
execution. `coordinator.protocol` exposes the same specification class and a
patch-compatible `run_worker_spec` facade. Process supervision, protocol
framing, environment normalization, Windows containment, cancellation, and
the existing `protocol.launch_managed_process` patch target remain production
responsibilities.

`repomap_test_support.synthetic_worker_adapter` now owns the synthetic mode
allowlist, fixture module target, support search path, and coordinator factory
that selects a test fixture. Tests import that outward adapter directly. No
production module imports or names test support, no production factory selects
a fixture, and no dynamic production import or subprocess target was added.
