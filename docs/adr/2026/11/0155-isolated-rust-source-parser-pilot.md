# ADR 0155: Isolated Rust source-parser pilot

## Status

Accepted for implementation under `REPOMAP-CLOE-RUST-PILOT1`, following the
operator's class A selection (final W6 Rust-pilot packet V3, 2026-11-05),
independent design review and the parent's F1–F8 corrections below. Native
checks follow D8 only after their source and artifact gates. This accepts the
design; dependency adoption, platform qualification, W6 and release acceptance
remain open. No native execution was used to accept this ADR.

## Date

2026-11-05

## Context

[ADR 0050](../08/0050-extractor-dependency-and-capability-architecture.md)
sets the dependency, effect and capability rules.
[ADR 0154](0154-extractor-capability-receipt-foundation.md) implemented the
dependency-free foundation: closed vocabularies, receipts, bounded storage, a
witness with no positive path and canonical refusal of Rust claims.
[ADR 0071](../09/0071-post-promotion-local-server-cloud-architecture.md)
requires a bounded Rust pilot feeding retained Python semantics.

Class A authorizes exactly `tree-sitter==0.26.0` and
`tree-sitter-rust==0.24.2`, no extras, as four exact manylinux wheels. The
binding wheels are `cp313-cp313` and the grammar wheels are `cp39-abi3`, for
`aarch64` and `x86_64`. Together they are 1,642,452 bytes. The parent has made
four of the six permitted transfers into private custody. It verified digests,
sizes, `RECORD` and the closed archive members of each without extraction,
import or installation.

The inert inspection found:

- no selected mandatory runtime dependency, entry point or `.pth` file;
- for each extension, an ELF matching its machine, a non-executable stack,
  RELRO and `DT_NEEDED` of only `libc.so.6` and `libpthread.so.0`;
- MIT texts for the binding and the grammar;
- an additional MIT notice on the vendored Tree-sitter C core (submodule
  commit `7f534862c3ec939c3a6ee147f7600ef5c1bf900f`), which the wheels do not
  carry; and Unicode/ICU headers in that declared core, whose full upstream
  Unicode notice is retained as supplemental data. Retaining the complete
  notice does not assert that its dictionary/conversion components are in
  these wheels, or establish source-to-wheel reproduction.

All four PyPI provenance requests returned 404. There is no verified publisher
attestation and no source-to-wheel reproduction; an artifact digest is not
publisher authenticity.

Upstream py-tree-sitter issue 472 and pull request 473 record a real 0.26.0
defect. The `Point.row` and `Point.column` getters return borrowed references.
For rows or columns above 256 (non-immortal integers) this corrupts the
allocator and can crash later. The fix (466) is not in the selected release,
and versions may not change or be patched. Windows issue 469 (LLP64 pointer
width) does not apply to this Linux-only profile, and is not a Windows claim.

Current source facts that constrain routing:

- `graph/discovery.py` classifies `.rs` as `unknown`. Its `file` observation
  carries `metadata.language`, which ADR 0154's claim guard refuses when it
  asserts Rust.
- `canonicalization/main.py` (728 lines) and
  `artifacts/_bundle_stream_parse.py` (398 lines) are length-constrained owners
  and must not grow.
- `storage/staged_rows.build_staged_rows` recanonicalizes the observations it
  is given. `_run_staged_full_refresh_admitted` already accepts prepared rows.
- SQLite Local publication (`storage/sqlite_local/publisher.publish_generation`)
  requires a portable-worker publication receipt. Local refresh reaches it
  only through the portable worker.
- The portable worker route
  (`coordinator/_portable_semantic_adapter.py`) runs legacy discovery and
  `build_staged_rows` inside the worker.
- The existing SDK image is `repomap-test-sandbox:py313-go125-docker294-v1`
  from `tools/test_sandbox/Dockerfile`, Python 3.13.12 on Debian trixie (recipe
  `24ddf31d…`). The `d12-native-amd64` job's `prepare` step records its exact
  image ID, and `seal` records `result` and `qualified`.
- CI120's only independent failure was an HTTP 504 during native AMD SDK APT
  preparation. Native sealing is unqualified. Actual application starts are
  31, and no start 32 or campaign allocation exists.

## Decision

### D1 — Ownership is ADR 0050 D6 shape 4, interpreted narrowly

The component is a RepoMap-owned helper distributed as Python source, run by
the container's fixed interpreter. It runs against a separately frozen
container-side runtime closure of exactly the two third-party packages. This
is the explicit shape-4 interpretation V3 records:

- The helper is RepoMap source. Nothing is built, and no binary is committed.
  The native closure is third-party prebuilt bytes, frozen by an exact
  committed component lock (filenames, URLs, SHA-256, sizes, closed member
  manifests and modes). It is never committed and never built.
- It is not shape 2 or 3. There is no `project.dependencies` or
  `project.optional-dependencies` entry, host resolver, host import, host
  extra or new core metadata, and no generic plugin or registry loader.
  Core RepoMap imports and runs with both native packages absent.
- *Acquisition* is installation-time preparation, outside indexing. It creates
  a host-side **prepared profile** of the exact verified wheel bytes for one
  architecture. The run freezes that profile before the first container
  exists.
- *Offline unpack* is invocation-boundary construction. A fixed stdlib
  unpacker unpacks the prepared bytes into a per-container runtime prefix. It
  is not dependency acquisition, version resolution or a package-manager
  operation. No pip, installer hook, `setup.py`, compiler, resolver, network or
  lookup runs during indexing. Missing bytes refuse; they are never
  reacquired.
- Provenance is recorded on its own axis: `python-distribution` for the native
  closure. The helper's identity is the digest of the bytes the parent
  injected and read back.

This fits shape 4 as interpreted without a broader D6 amendment. An
install-during-indexing exception, a host extra or a committed binary would
be outside A.

### D2 — Routing: an explicit, parent-run pilot path; default output unchanged

The default classification is unchanged. `.rs` stays `unknown` in
`LANGUAGE_BY_EXTENSION`, and every legacy and default `file` observation stays
byte-identical. Changing it to `rust` would have no benefit: ADR 0154's guard
would refuse the file observation in every ordinary graph and silently drop
Rust inventory. It would also invite routing that requires Docker for
ordinary Local indexing. No CLI flag, configuration schema or MCP behavior
changes.

Rust parsing happens only through an explicit internal pilot API in the
parent process, `extractors/rust_pilot/pilot.py`:

1. Legacy discovery and extraction run unchanged on the repository.
2. The pilot selection rule `rust-pilot-selection-v1` picks inputs from that
   exact inventory. A selected input is a discovered path ending in `.rs`
   (case-sensitive) that the parent can open as a regular, non-symlink file
   under the root through descriptor-relative no-follow IO, whose content
   SHA-256 equals the discovery `content_hash`.
3. The live controller (D4–D7) parses each selected file in its own fresh
   container. It validates the output and builds Rust raw observations.
4. The witnessed canonicalizer combines the unchanged legacy
   canonicalization result with Rust canonical rows. It pulls the Rust rows
   from the live run, never from a caller (D4).
5. Generic staged family rows and the existing parent-run PostgreSQL direct
   staged publication carry the result. Readback uses the existing canonical
   readback.

Selection is a stdlib `file.classification` fact, owned by the parent
(`pure-python`, `selected-input`). It is distinct from the native
`syntax.tree` and `syntax.error_tolerant` facts, and neither implies the
other. Selection and pilot profile identity enter the direct publication's
distinct `eg1:` extractor and `kg1:` canonicalizer generations. The
specification fixes their domain-separated derivation; pilot and default
generation identities cannot be reused for one another.

When the prepared profile or component is missing, the run records one
run-level `dependency_unavailable` outcome. It creates no container, emits no
Rust raw observation or canonical claim, and leaves legacy output unchanged.

Unsupported in this pilot:

- **Portable worker.** The worker never imports the pilot. In worker bundles,
  the parent bundle validator refuses `rust.*` raw kinds, `rust.*` canonical
  nodes and any edge with a `rust.*` endpoint. There is no worker-parent
  channel, contract amendment or delegated privilege.
- **Multi-source composition.**
- **SQLite Local publication.** A parent-run Local receipt class does not
  exist. Inventing one is outside A, and the pilot does not need it.

### D3 — Capability and custody bindings come from live parent state only

A Rust canonical claim requires all eight ADR 0154 `REQUIRED_BINDINGS`. The
live controller recomputes each one for each file in this process:

| Binding | Recomputed from |
|---|---|
| admitted profile | the frozen prepared profile; exact lock digests; full readback equality of the installed tree |
| selected source bytes | bytes the parent read itself; equal to discovery `content_hash`; stable stat |
| active run nonce | 32 random bytes held only by the open run; per-file invocation nonce echoed exactly |
| clean exit | the parse exec's exit status is 0 and the container was alive until settlement |
| strict protocol | strict frame decoding (D6) |
| input-matching ranges | every range, name, line and nesting relation rechecked against the retained bytes |
| resource outcome | no time, output, diagnostic, memory or PID bound event |
| proven cleanup | every exact container absent after settlement; process() finishes component-attributed residue checks before admission, recomputed before publication |

These cannot authorize a claim: a caller boolean, a verifier callback, a
deserialized receipt, a digest, a dataclass, a copied or pickled token, or
helper metadata such as its `hello` frame.

There is no module-level registry or trust cache. Witness state lives in the
open run object and becomes inert when the run closes.

Trust limits:

- The in-process parent and its RepoMap source are trusted. A malicious
  monkeypatching parent can forge anything, and this design makes no claim
  against it.
- Same-UID host processes and anyone with Docker daemon access are trusted
  equivalently.

### D4 — Offline imports refuse Rust semantics; retention is audit only

The ADR 0154 guard in `canonicalize_observations` gains one closed reason,
`rust_raw_kind`. It refuses the pilot's three raw kinds (D5) as well as Rust
language assertions. This covers:

- offline raw JSONL;
- direct observation publication;
- `prepare_canonical_load`;
- replay of stored raw rows;
- portable bundles, refused at parent validation.

Only the witnessed canonicalizer admits the Rust kinds, and only while its
run is open. Every other observation keeps legacy behavior, including the
Markdown `rust` fence and HTML `lang` exceptions.

Receipts, run reports and stored raw Rust rows are sanitized audit evidence.
There is no signing key, trust store, implicit replay or automatic
re-execution. A receipt never selects a helper, image, command or profile.

### D5 — A small, syntactic Rust graph vocabulary

There is no SQL schema change or migration. Graph key version 1 stays, and
the new namespaces are additive entries in `_SEGMENT_COUNTS`.

Three raw kinds (schema 1):

- `rust.parse` — one per attempted file;
- `rust.item` — one per extracted item;
- `rust.unsupported` — one per bounded construct class per scope.

Seven namespaces:

- `rust.source_file` — one segment, the file key;
- `rust.module`, `rust.function`, `rust.type`, `rust.trait`, `rust.impl` and
  `rust.macro` — two segments, the file key and a syntactic pointer.

Edges use only existing kinds: the file `contains` its `rust.source_file`,
which `defines` top-level items, and a module, trait or impl `contains` its
members. PostgreSQL `canonical_edges` enforces a closed edge-kind `CHECK`, so a
new edge kind would need a migration. Node kinds have no such constraint.
Builders live in a new `graph/rust_keys.py` because `graph/keys.py` (855
lines) must not grow.

Keys are unique by construction. Same-named siblings receive `@k` suffixes,
and the node is marked as a bounded ambiguity rather than resolved.

The extractor observes, and never evaluates or infers:

- macros, which are never expanded;
- `cfg` and other attributes, recorded only as observed syntax, never as
  active build facts;
- build scripts and procedural macros, which never run;
- types, symbols, paths and `use` targets, which are never resolved;
- `mod x;`, recorded without resolving any file.

Function bodies are not descended; their local syntax is intentionally
unobserved, not counted without traversal. Item-level `const`, `static`, `use`,
extern crates and foreign blocks are counted as unsupported. Item-position
macro invocations mark the scope's member list as macro-incomplete.

The gating map sets the minimum achieved capability per claim kind:

| Claim | Complete tree | Partial tree |
|---|---|---|
| `rust.source_file`, file `contains` edge | `file.classification` + `syntax.tree` | `file.classification` + `syntax.error_tolerant` |
| Items, `defines` and `contains` edges | `syntax.tree` | `syntax.error_tolerant`, usable scope only |

Any unmapped claim kind is refused, as is anything needing `resolution.*`,
`build.condition` or `metadata.package`.

A partial tree's usable scope is an item with no error or missing node in its
subtree, directly under the root or under a usable container's body. Usable
scopes never imply a complete tree. Completeness is declared on every parse.

### D6 — Bounded byte protocol and fixed helper closure

The parent sends a header frame, then exactly N input bytes, with
N ≤ 1 MiB. The helper:

- returns integer-only frames: kind tags from a closed table, byte ranges,
  name ranges, parent indices and flags;
- never sends text, names or line numbers;
- makes one `Parser.parse(bytes)` call per fresh container;
- walks the tree with a single `TreeCursor`;
- uses no `Point`, `Range`, start or end point, `Query`/`QueryCursor`, edit,
  logger, read or progress callback, included ranges, parent walks or
  point-based descendants.

The parent derives UTF-8 names and line numbers from the retained bytes in
Python. A source guard enforces the API list.

Outer attributes are preceding siblings, associated with the following
declaration across comment extras. Their separately validated ranges precede
that declaration within the same scope. Comments are trivia, not unsupported
syntax. Attribute overflow is explicit truncation, never silent completeness.

This is API avoidance for a known defect, not a memory-safety proof. Native
cases above 256 lines and columns remain required evidence.

The helper's source closure is fixed RepoMap package source:

- setup writer;
- install readback;
- runtime probe;
- parse helper;
- containment probes.

Interpreter, ABI, glibc, kernel, locale and encoding are observed, not pinned.
Retained reports project only closed string values and bounded numeric facts;
the complete probe object, kernel release and native kind/field maps are bound
by digests rather than copied as free-form diagnostic text. Recipe identity is not bitwise APT reproducibility or a
kernel pin. Nothing about the helper, image or command is selected from
`PATH`, environment variables or serialized data.

Docker is a declared parent host privilege. The parent uses the inherited
Docker configuration and context. No container receives a host socket, or a
bind of any artifact, target, home or other host path.

### D7 — Construction under drop-all capabilities and a read-only root

Each file gets one fresh exact container, built from the prepared SDK image ID
with `--pull never`. Its settings:

- network `none`;
- read-only root;
- `--cap-drop ALL`;
- `no-new-privileges`;
- no mounts or volumes;
- 512 MiB memory with swap equal;
- 32 PIDs;
- non-root PID 1 with a self-expiring lifetime;
- `--rm`, plus explicit settlement.

Two tmpfs mounts:

- **Runtime prefix**, executable, `nosuid`, root-owned. Loading the extension
  `.so` files requires an executable mount; this design does not claim that a
  `noexec` `.so` can load.
- **Data scratch**, `noexec`, owned by the parser UID.

Principals:

- **Setup.** A trusted setup-only exec runs as container UID 0 with no
  capabilities. It receives only verified artifact and helper bytes, over
  bounded stdin, before any target byte exists. It verifies them, writes the
  closed member set through no-follow descriptor traversal with exclusive
  creation, and seals everything root-owned: directories `0555`, files `0444`
  and extensions `0555`. It then exits. No root exec runs after sealing.
- **Parser.** A separate non-root exec. Principal changes are made by the
  runtime's `exec --user`; no process calls `setuid`, so dropped `CAP_SETUID`
  is never needed.

Before any target byte is sent, the parent:

- reads back every installed byte, mode, owner and link count, and compares
  them with its own in-memory extraction of the verified wheels, the closed
  `RECORD` set and the helper closure;
- inspects the container configuration;
- checks the container's credentials and mounts.

Budgets:

| Phase | Bound |
|---|---|
| Construction | 30 s, readback ≤ 8 MiB |
| Parse | 1 MiB input, 4 MiB output, 64 KiB diagnostics, 5 s wall |
| Settlement | 15 s |

Every deadline and cleanup acts on the exact container ID and ends with proven
absence. Killing the Docker client alone is insufficient. There is no broad
prune, no image commit or build, and no volume or reused file state. The
specification defines bounded stdio sequencing so that no pipe can deadlock.
AutoRemove may race explicit removal; only successful exact-ID absence
observation determines cleanup, never an advisory removal exit alone.

A crash is a recorded defect and is never retried. The exact container is
settled before the next file. Unproven absence halts the run and refuses all
of that run's Rust claims.

### D8 — Native import and adoption order is non-circular

1. This ADR is accepted, and the inert artifact gates close (G1–G3 in the
   specification).
2. Source and fake protocol tests are implemented. Unit and containerized
   integration owners are updated with no native import.
3. Independent review of the source and the mechanism.
4. **First native import: ARM execution 1.** It runs on the existing Docker
   Desktop native `linux/aarch64` guest with the retained SDK image `575e0004…`.
   In-run preflight comes first: inspection, readback, credential and mount
   probes, interpreter/ABI/glibc observation, the grammar pairing probe and
   negative containment probes. Target fixtures follow in the same execution.
   No earlier runtime success is demanded.
5. **ARM execution 2,** only after a finding, its correction and a fresh
   source review. It is the last ARM execution.
6. **AMD:** one gating command in the next separately granted substantial
   public campaign (D10).

### D9 — A pre-declared qualification window

Before any native execution, the qualification window is declared and frozen:

- an exact manifest: candidate, component lock, profile, helper closure
  digests, fixtures, golds and scenarios;
- one-use attempt identities;
- the fixtures and golds themselves, which are original public sources frozen
  before any tuning;
- an exhaustive false-positive sample of every emitted item claim;
- correctness and bounded cost accounting.

The scenario matrix is fixed in the specification. Three evidence tiers stay
distinct:

- **Fake protocol tests:** logic only.
- **Native component evidence:** this runtime, image and platform.
- **Full product acceptance:** not claimed.

The manifest declares per-platform scenario subsets. ARM has both inert CPU
pairs available for cross-CPU refusal. AMD uses only its two permitted
transfers, so its wrong-platform checks cannot demand ARM wheel bytes.

### D10 — Exact AMD gate

The existing `d12-native-amd64` job of
`.github/workflows/repomap-release-qualification.yml` gains exactly two steps
after the current D12 seal and upload. Its projection
`tools/ci/d12_native_amd64_job.yml` and the native workflow contract change
with it. `qualification_native_contracts.py` remains at its 400-line ceiling;
a new small Rust contract owner enforces the added steps. The existing D12
upload assertion identifies exactly its own upload, while the new owner
rejects missing, extra, reordered or weakened Rust steps. The AMD tool and
its import closure require no installed project/database dependencies.

1. **The Rust component command** runs under `always()`. It first validates
   the sealed D12 evidence (`result` passed, `qualified` true) and the exact
   prepared SDK image ID. On failure it writes `rust-pilot-qualification.json` with
   `result: prerequisite-refused` and `qualified: false`, exits nonzero, and performs no download, construction or parse.
2. **A separate artifact upload,** also under `always()`, with
   `if-no-files-found: error`.

Constraints on the change:

- no `continue-on-error`;
- no new job, runner, image or SDK owner;
- no trigger, permission, timeout, population or retry change.

The component's own refusal or failure fails the job. Missing report bytes
cannot qualify Rust. A job ending before the command classifies Rust as
unavailable, never passed. D12 and Rust reports stay separate. The two
remaining exact `x86_64` transfers and one component allocation are
preserved. No application start 32 or public grant is created.

### D11 — Implementation stays bounded inside existing owners

New modules:

- live under `extractors/rust_pilot/` (host) and its `guest/` package (stdlib
  text, injected and never imported on the host);
- have at most 400 lines each;
- enter retention and type ownership clean, with no new test dependency,
  suppression, core metadata, lock or runner policy.

Narrow existing edits:

- the claim guard;
- the key namespace table;
- the bundle validator;
- a new prepared-rows staging entry;
- a third-party notice record;
- the D10 workflow steps.

Every debt ceiling, baseline and length policy is preserved.
`canonicalization/main.py` and `_bundle_stream_parse.py` do not grow. The
specification lists every owner and exact selector.

The run finalizes component-attributed image/volume/container residue checks
before canonicalization or publication. Global Docker deltas are recorded
separately: unrelated shared-daemon activity does not become pilot ownership
or deletion authority. Closed command journaling, fixed image and mount
inspection, labels and exact IDs establish zero pilot-attributable image or
volume creation and zero surviving owned containers. A missing or ambiguous
owned observation refuses admission; a global empty delta alone cannot
establish it.

### D12 — Disable and reversal

The pilot is off unless a caller invokes the pilot API with a prepared
profile. To disable it:

- remove the prepared profile; nothing is acquired; or
- stop calling the pilot API.

Neither path leaves legacy output changed. No positive witness means no Rust
claims. Earlier pilot publications are ordinary generations, superseded by
the next default publication.

The pilot does not claim:

- production use;
- full W6;
- container-free Local Rust;
- v0.1.0 acceptance;
- any measured comparison against the unexecuted `syn` or rust-analyzer
  candidates.

It compares only its executed candidate with the actual file-only incumbent.
ADR 0071's broader comparison remains open.

### D13 — Resulting-source review corrections before native execution

The first runtime source review requires these implementation corrections;
none spends a native attempt or changes the approved dependency class:

- The public controller and pilot facade accept no runner, verifier, clock or
  sleep callback. Trusted test support may replace a module-private boundary
  factory; its stand-in evidence remains T1. A complete positive controller
  path must be exercised before native execution, including actual protocol
  IO, probe, residue, admission and PostgreSQL publication/readback.
- The network invariant is Docker network `none` with no usable external
  interface. Besides loopback, only the known fallback names `tunl0` and
  `ip6tnl0` may be present, and only with the UP flag clear and no IPv4 or IPv6
  address. Missing or ambiguous observations and every other interface refuse.
  Their presence on this guest is unverified; no such observation is claimed.
  Network-none, dropped capabilities and negative connection probes remain.
- Construction has one 30-second deadline across all client calls. One
  15-second settlement deadline per container starts at the first bound event
  or normal settlement entry and covers nested kill, removal, observation and
  client/thread reaping. An exception in the kill action cannot skip client
  cleanup. Reader/writer failures never become clean IO; diagnostics retain
  only the count and hash of bytes actually observed, with categorical errors.
- The five-second parse cap covers the entire Docker exec, including startup
  and import. This is a tighter upper bound than timing only input-to-exit.
  Successful probe parsing receives its own audit receipt. Qualification-only
  containment containers receive separate component execution records and do
  not invent extractor capabilities.
- Retained Python validates parent depth≤256, closed container-parent kinds
  and ordered disjoint sibling ranges before constructing pointers. Pointers
  have a4096-byte cap and each file's retained raw semantic output a16MiB cap.
  The parent refuses all of that file's Rust claims on a bound, records an
  `output_bound` attributed to retained semantics, and preserves legacy output.
  These bounds prevent a small native frame stream from expanding unboundedly
  through repeated ancestor paths. They do not enlarge native IO budgets.
- Per-file cost records retain construction/readback/parse/settlement times,
  installed/readback/output bytes and guest-reported memory peak when
  available. Unavailable counters are null with a reason, never fabricated
  zero. Journal-derived zero image/build/pull/volume facts are labelled as
  derived and cross-checked against owned resources; timings remain measured.
  Construction includes readback; reports label that nesting explicitly.
  Container and parse counters count attempted create and fixed parse-exec
  commands, respectively; their explicit scopes do not assert successful
  native entry or successful parsing. Successful admission is proved separately.
- Archive member permission bits are checked against `wheel_mode` by both
  host and guest before installation, in addition to the complete wheel hash.
  A public audit accessor returns deep inert copies only. Graph consumers
  still require the exact live controller and fresh binding verification;
  mutation digests guard exposed result content but confer no authority.
- Package notice bytes remain unchanged. The existing application packaging
  adapter copies only its four Psycopg notice files to the Psycopg-specific
  image documentation path, while the distribution includes the three Rust
  notice/provenance additions. Update its exact resource tests. No SDK recipe,
  base, dependency or image execution changes; application-build authority
  and the next public campaign remain separate.
- The existing D12 evidence validator reaches runtime configuration/storage
  through its Dockerfile renderer import. Move that pure renderer and its two
  formatting helpers to a leaf module, retaining the `runtime.commands` API
  and byte-identical rendered recipe. The D12 recipe owner imports the leaf.
  This necessary import-boundary correction adds no image, SDK or dependency
  authority. Qualifier closure records cover its actual host initialization
  and explicit qualification call roots; a runtime import guard refuses any
  database, publication or native-parser host import throughout qualification.
  Candidate binding also compares the exact manifest, source, fixture, SDK
  recipe and incumbent bytes with regular blobs in the current candidate
  commit. A matching HEAD name alone cannot qualify uncommitted inputs.
- The retained dynamic-boundary declaration is a closed audit declaration,
  never a host import or project dependency. It binds only `parse_helper.py`
  and `runtime_probe.py`, their literal (`tree_sitter`, `tree_sitter_rust`)
  tuple, and fixed component-lock/source identities. Aliases, selector
  rebinding, mutation and extra import sites refuse. It emits no project edge
  and establishes no native qualification.
- The four held wheels contain explicit directory entries even though the
  component lock lists regular files only. Host and guest admit a directory
  entry only when its slash-terminated name is a unique exact proper parent of
  a locked regular member, its mode is exactly ZIP directory `0755`, its
  external attributes are not a symlink or special type, its uncompressed
  payload is empty, and its encryption/compression flags are admitted. Such
  entries are archive metadata only: they are not locked members and never
  participate in `RECORD`; parent directory creation remains derived from
  verified regular members.

Whole-file attribute-overflow truncation, root item depth1 and empty-statement
trivia are accepted bounded interpretations. A truncated stream cannot prove
attribute absence or complete container membership: attribute flags describe
only retained observations, `conditional` is null when unobserved under
truncation, and container member lists remain truncated unless a more specific
error or macro incompleteness is observed. T1 stand-in/gold agreement is
protocol consistency, not an independent native oracle. The original golds
remain frozen; any changed source/gold needs a newly declared window, and all
windows share the same original two-ARM budget.

### D14 — Refusal and audit consistency clarification

A journaled create that yields no usable container ID does not prove absence.
The controller halts immediately, records cleanup as incomplete and admits no
Rust claims; an empty owned-ID list cannot supply a cleanup proof. A missing or
unexecutable Docker client records a run refusal before any container work.

Receipt `observed.admitted` records runtime profile/effect admission before an
attempt. It does not assert a successful parse or positive semantic admission;
the receipt's attempt outcome and achieved capabilities remain separate, and
serialized verification stays `unverified` or `refused`. The synthetic run-level
probe uses `<run_id>.probe.0`, while selected-file and run-refusal receipts use
`<run_id>.<seq>`. This distinct audit namespace prevents probe/source identity
confusion and carries no graph authority.

The cost-observation command shares the settlement deadline and may trigger
container termination when it cannot settle. A resulting `crashed` record
reports failed clean-exit/liveness evidence; it does not establish that the
parser itself caused the crash. The component refuses positive claims either
way. A cleanup failure preserves the primary operation's closed error and
known evidence and any existing explicit cause, with the cleanup failure
recorded separately by a fixed note. Unidentified-create cleanup remains
incomplete at context exit, even with no owned ID. Ordinary settlement
exceptions cannot erase the primary error or prove absence. A pre-parse
contract refusal remains `inadmissible`, rather than inventing a crash.
Per-file settlement timing includes cost/liveness observation from the first
settlement entry through exact cleanup. Prepared staged rows and publication
use the same single resolved stage ID.

The admitted interface set stays closed. Additional inactive kernel fallback
interfaces are not accepted speculatively. Their presence can refuse the
bounded native gate; changing that rule requires a finding, source correction
and fresh review before the second allocated ARM command. This is an explicit
availability limit, not evidence that native confinement has passed.

### D15 — Whole-command qualification closure

Source admission requires known, nonnegative integer and cross-checked aggregate
counters across source, containment and every preflight role. Builds, pulls,
images and volumes must each be zero. Unknown totals remain unknown diagnostic
evidence and refuse qualification; no role is silently omitted.

Missing-profile and wrong-CPU refusals retain their original controller audit,
including unobservable resource fields. A separate read-only observer snapshots
images, volumes and the exact run label before and after the refusal. Only an
empty or exact version-only controller journal, exact observer query journal,
zero controller creates/parses and equal empty-owned-label resource snapshots
prove the scenario's zero effects. Scenario totals include the observer's
commands and name this cross-check. No unknown raw audit value is rewritten or
credited without the independent observation.

One monotonic 20-minute work deadline covers acquisition, preparation, native
preflights, negative probes, source containers and comparisons. It is shared,
never reset by a nested phase, and checked between phases and owned containers.
Expiry refuses qualification and new work. Existing bounded cleanup remains
mandatory; a deadline cannot justify abandoning an owned container or extending
its separate 15-second settlement cap. Per-operation caps are unchanged. This is a cooperative work
window, not an OS hard wall: an already active bounded operation may finish
after expiry, followed by exact settlement. No new phase, container, exec or
transfer begins after an observed expiry, and qualification always refuses.

Temporary wheel bytes, including corrupt-profile copies, belong only to the
separate private work directory outside every uploaded report root. Refuse
an overlapping path before any artifact write. A hard termination must not
make selected or mutated wheel bytes eligible for the always-upload step.

Cleanup preserves a primary RuntimeGap or ContractError's closed code and known
evidence; unexpected primaries use a fixed category, never their message. A
failure's source-only counters and files are labelled as such rather than
presented as whole-command totals. Structured refusal reports use the actual
`rust-pilot-qualification.json` result/reason contract; the separate intent file
records an attempted command, never successful native execution.

The fixed cost-only settlement observation remains available under its existing
settlement end after work expiry; setup/probe/parse execs do not. SDK inspections
share the same cutoff. An expired source attempt settles and retains its audit,
then terminates the run without later refusal rows. Final aggregate accounting
is followed by another deadline check before any success credit.

The existing always() behavior remains explicit: cancellation after a positive
D12 prerequisite can still spend the one AMD component allocation and its two
transfers. It supplies no retry/refund. Campaign preparation must prove the
frozen checkpoint equals the unchanged main parent available in the depth-two
checkout; a moved main requires a fresh candidate binding, never weakened Git
checks. AMD Q11 negative scenarios remain unexecuted; positive architecture,
interpreter/ABI/glibc checks do not claim negative mismatch qualification.

## Resulting-source review disposition for bounded native proof

Independent review found no P1/P2 blocker. Its remaining findings are retained
as limitations of this pilot, without changing runtime code, caps or gates.
Source-controller command counters end at the audit snapshot; later read-only
witness/canonicalization queries and separate SDK-prerequisite queries are
excluded. Aggregate commands describe captured roles, not complete command
cost. They establish no performance or adoption claim. Zero builds/pulls and
exact attributable residue remain separately enforced.

The cooperative work window may overrun inside a read-only comparison phase.
Containment or preflight expiry can lose role diagnostics or report a generic
containment refusal. A pre-attempt deadline can appear as an effects refusal
in the inner audit while the enclosing command reports expiry. These limits
do not turn refusal or incomplete evidence into native credit. A final cutoff
check still precedes qualification, and exact settlement remains mandatory.

Global image and volume equality is an additional conservative availability
gate. Unrelated shared-daemon changes can refuse a spent attempt; use a quiet
daemon without stopping foreign work. No retry or refund is implied. Public
qualification exposes only the AMD command. ARM uses a parent-held private
wrapper over the same component implementation, not a public Local surface.

These dispositions permit the already approved bounded ARM proof only. Native
results, hosted qualification, campaign allocation, image acceptance and full
W6 completion remain separate gates. The specification records the remaining
same-user gold-binding and public synthetic-fixture upload limitations.

## Alternatives considered within class A

- **Warm per-run container.** Rejected: V3 requires fresh per-file containers
  with no shared process or scratch state.
- **Host-side unpack with a bind mount, or a derived image.** Rejected: no
  host bind, image build or commit is permitted.
- **Guest `pip install`.** Rejected: installer during indexing.
- **Helper-emitted names and points, or Tree-sitter queries.** Rejected: the
  `Point` defect, query churn, and trusting helper text.
- **In-process native parsing.** Rejected by ADR 0050 D14; no variance is
  recorded.
- **Defaulting `.rs` to `rust`.** Rejected under D2.
- **Generalizing `witness.ParentWitness` into a positive generic witness.**
  Rejected. The foundation refusal stays for legacy and offline origins, and
  the live pilot state is narrower.
- **Docker SDK for Python.** Rejected: it is not a core dependency. The CLI is
  the parent host tool.
- **SQLite Local publication.** Deferred: it needs a parent-run Local receipt
  class outside A.

## Consequences

RepoMap can produce honest, syntactic Rust structure with recorded
completeness. Default users, offline imports and the worker route are
unaffected.

The costs:

- per-file container overhead, recorded as measured cost, never a performance
  claim under ADR 0050 D16;
- Docker as a host prerequisite of the pilot path only.

Supply-chain trust is bounded to exact digests, without publisher
attestation. Parser compromise is contained by network `none`, a read-only
root, the sealed prefix and dropped capabilities. It is not prevented, and
the image's own tools (for example `gcc`) remain visible to a compromised
parser that cannot persist or exfiltrate.

### Scope outside A, stated concretely

Nothing indispensable to the pilot exceeds A. These would need new decisions:

- a parent-run SQLite Local publication receipt;
- portable-worker or multi-source Rust;
- a CLI or configuration surface;
- any timeout change if the AMD job envelope proves insufficient;
- a new or pulled image if the integration sandbox has no admitted Python
  image for the optional real-boundary integration owner. That owner's
  absence is a named gap, not a reason to create an image.

## What would make this decision wrong

- A Rust claim reaches storage without all eight live bindings, or after its
  run closed.
- An offline, raw or worker path admits Rust.
- Default or legacy output changes for any repository.
- The construction cannot run under drop-all capabilities and a read-only
  root without a capability or mount this ADR forbids.
- The prepared runtime is reacquired or resolved during indexing.
- A container, volume or image survives a run unreported.

## Specification

[CLOE Rust parser pilot v1](../../../specs/cloe-rust-parser-pilot-v1.md).
