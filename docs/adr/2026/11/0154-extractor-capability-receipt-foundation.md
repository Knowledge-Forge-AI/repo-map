# ADR 0154: Dependency-free extractor capability and receipt foundation

## Status

Accepted for the dependency-free foundation of roadmap W6 only. Parser
dependencies, native execution, Rust graph vocabulary and workflow changes
remain pending a separate operator selection and resulting implementation ADR.

## Date

2026-11-05

## Context

ADR 0050 defines extractor adoption prerequisites but did not implement them.
The accepted v0.1.0 roadmap permits W6 to overlap search once naming and
development custody are stable. The operator directed roadmap progress after
CI120's sole independent failure was an HTTP 504 during native SDK preparation.
This does not turn that failed candidate into a qualified native platform.

REPOMAP-CLOE-RUST-FOUNDATION1 establishes the common prerequisite for either
parser decision. It implements contracts and refusal behavior with standard
library facilities and existing dependencies. It does not select a parser.

## Decision

### Closed capabilities, effects and lifecycle

Use ADR 0050's exact cap-v1 vocabulary and five effect dimensions. Validate
closed values, exact primitive types, bounded collections and explicit schema
versions at serialization boundaries. A declaration, availability check,
selection, exercise and achieved capability are separate facts. No capability
implies another; absent legacy evidence means undeclared or unavailable,
never an achieved empty-effect or fully contained run.

Effects reported by an extractor are declarations. Actual effect enforcement
and parent observation are distinct prerequisites. A syntactically valid
receipt, digest, dataclass, nonce or registry membership cannot establish them.

### Explicit legacy membership

Create a closed, source-owned registry of the existing extraction dispatch
entrypoints and their actual implementation owners. Resolve aliases from
source without importing target repositories. Registry data never supplies
an executable module, command or plugin loader from serialized input.

Membership traces to ADR0050's acceptance on 2026-08-12, rather than the date
of this foundation. All 26 named identities occur in that acceptance source;
current owner and alias mappings have separate source-resolution tests.
Later reviewed decompositions and ADR0123's namespace projection preserve
identity; current presence alone is not grandfathering authority.

Legacy membership records continuity only. It grants no new dependency,
capability, containment or native-code exception. A new owner cannot gain
legacy admission through a prefix, directory wildcard, extractor string or
copy of a legacy record. Current source identity may change through reviewed
bug fixes; do not freeze source hashes as an unmaintainable baseline.

### Receipt schema and bounded local storage

Define a versioned, public-safe receipt representation with distinct declared
and observed fields, source/profile/run identity, bounded outcome and cleanup
facts, and explicit partial/refused/unavailable states. Canonical JSON bytes
have an external digest; a receipt never signs or authenticates itself.

Decode strictly: reject unknown schema fields, duplicate JSON keys,
non-finite numbers, booleans where integers are required, invalid digest
forms, excess bytes, excess depth or collection bounds and invalid lifecycle
transitions. Diagnostics use categorical codes, not raw source or payloads.

Store and read receipts through bounded, no-follow, descriptor-relative IO
with fixed single-component names, exclusive creation, regular-file and
stable-stat checks. Existing files, symlinks, traversal, concurrent mutation
or incomplete write/cleanup are refusals. Do not overwrite or delete another
owner's data. A valid stored receipt is audit evidence, not runtime admission.
Require directories owned by the effective user with no group/other access,
including descriptors supplied directly to each IO operation. Trust that
owner and privileged host processes; no atomic conditional unlink or hostile
same-user filesystem sandbox is claimed.
The directory creator must also guarantee no additional ACL grants: mode-bit
admission does not inspect ACLs. Operational IO faults can propagate
`OSError`; future runtime consumers must sanitize them before exposing
diagnostics. Typed policy and codec refusals remain categorical.

### Parent witness and canonicalization boundary

Introduce a narrow internal observation-batch contract separating raw
observations from live parent verification state. Deserialization cannot
create that state. Do not add a raw top-level field or change raw schema 1.
Existing legacy extraction and canonicalization retain their behavior.

The dependency-free foundation has no qualified native runtime observer.
Consequently it refuses future Rust/parser capability claims, including
claims disguised as ordinary file observations or forged receipt metadata,
without accepting an injectable callback, boolean or caller-constructed token
as proof. Any future positive path requires the separate reviewed controller
that recomputes source/profile/run/output/range/outcome/cleanup bindings from
actual observations. Contract fixtures and doubles prove only logic.

Offline raw JSONL remains readable for audit. Its metadata and any retained
sidecar cannot authorize canonical Rust claims. No new keys, signatures,
trust store, implicit replay or worker-parent channel is introduced.

## Scope and non-scope

The phase owns the contracts package, explicit legacy inventory, narrow
canonicalization refusal integration, unit and containerized integration
tests, retention ownership rows and current phase documentation. Use small
cohesive modules; preserve every existing retention debt ceiling and registry
authority. No broad canonicalization refactor or public CLI/MCP change.

This phase adds no parser installation or import, distribution extra,
dependency lock, helper execution, image or runtime build, package acquisition,
Rust graph key/raw kind, default `.rs` classification, workflow or runner
policy. It does not claim native platform qualification, container-free Local
Rust support, a measured parser comparison, W6 completion or v0.1.0 acceptance.
W5 held-out/scientific evaluations and production remain outside this slice.

## Required proof

Use exact scoped unit selectors for schema/type/lifecycle/registry and forged
claim rejection. Add containerized integration owners for real filesystem
round trips, no-follow/exclusive-write failures, bounded malformed receipts
and offline raw JSONL through the actual canonicalization refusal boundary.
No test may execute a target repository. Preserve legacy extraction output.

Run the retained-Python enforcement owner and source/export/file-length/privacy
checks on the resulting state. New owners enter clean cohorts immediately;
no historical baseline, debt ceiling or suppression is relaxed. Complete local
suites, local candidate coverage and builds are unselected. Scoped proof is
diagnostic and cannot replace hosted qualification.

## Implementation record

The exact contract is
[cloe-extractor-capability-foundation-v1.md](../../../specs/cloe-extractor-capability-foundation-v1.md).
Corrections made while implementing, within the scope above:

- The legacy registry covers the 25 distinct entrypoints the discovery
  dispatch calls (26 call sites: the config adapter is called from two
  branches), including the S1 file-inventory observation and the S2 Python
  module index that the source census did not list, and the exact emitters of all 26 product
  extractor names, including three source-ingestion names that have no
  discovery entrypoint. Membership is resolved from source and records names,
  never source hashes.
- The receipt reference is a reserved extractor-owned metadata name,
  `extractor_receipt_ref_v1`, together with a small reserved set of
  capability-claim names. Canonicalization refuses observations carrying them,
  or a Rust language/dialect assertion, before family dispatch with one
  categorical warning; no new raw field, kind, graph key or classification
  exists. The Rust assertion is not applied to the two legacy kinds whose
  `language` describes embedded content (`markdown.code_fence` info words and
  the `html.document` `lang` attribute), so a Markdown `rust` fence keeps its
  legacy evidence; reserved names are still refused on those kinds.
- Receipt transitions only accumulate observed facts: installation and
  admission are fixed, artifact digest, invocation mode, exit status and a
  known cleanup fact are set once, resource events and attempts only grow, and
  a `refused` verification fact is sticky.
- A serialized receipt cannot express verification success: its verification
  fact is only `unverified` or `refused`.
- Batch construction validates exact list/tuple type and length before
  materialization; arbitrary iterables cannot consume an unbounded input.
- Owned cleanup requires a private owned directory, checks the entry and then
  unlinks it. The same-user/privileged trust assumption remains explicit.
- The parent extends this slice to append the eight new retained selection
  rows. Clean additions require no restricted-scope authority record; the
  inherited scope registry stays byte-identical. Every predecessor row,
  numerical debt, ownership manifest, tool and length policy stays unchanged;
  clean admission still requires actual Ruff/mypy/cohort enforcement.

## Consequences and alternatives

Implementing the foundation first makes dependency adoption observable and
prevents metadata from becoming a trust bypass. Deferring it until after a
parser import would reverse ADR 0050's adoption order. Treating every old
extractor as already capability-qualified would invent evidence. A generic
plugin system or serialized command registry would add an unnecessary
execution surface and is rejected.

The next parser selection, if approved, must name exact artifacts, licensing,
delivery, confinement, observed runtime identity, cleanup, canonical graph
vocabulary and native component proof before parser execution. Publication
waits for a substantial reviewed milestone; this foundation alone does not
trigger a small mechanics-only CI campaign.
