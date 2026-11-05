# CLOE extractor capability foundation v1

Phase: `REPOMAP-CLOE-RUST-FOUNDATION1`. Decision:
[ADR 0154](../adr/2026/11/0154-extractor-capability-receipt-foundation.md),
implementing prerequisites from
[ADR 0050](../adr/2026/08/0050-extractor-dependency-and-capability-architecture.md).
Exit record: [cloe-rust-foundation1-exit.md](../../tools/ci/cloe-rust-foundation1-exit.md).

This contract is dependency-free and common to every W6 parser decision. It
selects no parser, adds no Rust raw kind, graph key namespace or `.rs`
classification, and has no positive native-admission path.

## Owners

| Module | Contract |
|---|---|
| `extractors/contracts/vocabulary.py` | Closed cap-v1, effect, provenance, lifecycle and reserved metadata names; strict primitive validators |
| `extractors/contracts/legacy_registry.py` | Closed legacy baseline v1: dispatch entrypoints and exact raw-observation emitters |
| `extractors/contracts/receipt_schema.py` | Receipt fields, state coherence and transitions |
| `extractors/contracts/receipt_codec.py` | Canonical bytes, external digest, strict decoding and digest-named storage |
| `extractors/contracts/bounded_io.py` | Descriptor-relative no-follow regular-file IO |
| `extractors/contracts/witness.py` | Observation batch and the non-constructible parent witness |
| `canonicalization/claim_guard.py` | Pre-dispatch refusal of raw capability claims |

`canonicalization/dispatch.py` records refusals once per call, and
`canonicalize_observations` dispatches only unrefused observations while keeping
original raw ordinals.

## Vocabularies

Capability vocabulary `cap-v1` is exactly ADR 0050 D4's nine names. Sets are
sorted, unique lists; no capability implies another. The five effect dimensions
and their values are exactly ADR 0050 D2, with provenance on a separate axis.
`declares_extraction_admissible_shape` reports only whether a *declared* vector
lies inside D3; it is never admission because D7 enforcement and parent
witnessing do not exist here.

The lifecycle facts `installed` (environment), `admitted` (run), `attempted`,
`exercised` and `achieved` (attempt) live in different fields. Missing evidence
is `undeclared` or `unavailable`. Validators accept exact `str` and `int` only:
string subclasses, `bool` integers, floats and bytes are refused.

## Legacy baseline v1

`cloe-legacy-extractor-baseline-v1` records the 25 distinct entrypoints
called by `graph.discovery.extract_observations_from_repository_files` (26 call
sites; the config adapter is called from two branches): the S1 file inventory
observation, two S2 indexes that emit no observations, 20 S3 file adapters and
two S4 post-passes. The Go repository post-pass is the only
`subprocess` boundary. Each entry names its defining module, implementation,
dispatch selectors and the static import-closure upper bound of extractor names
it can emit.

The owner map lists, for 26 extractor names, the exact modules whose
`RawObservation(...)` constructions emit them. Module constants, import aliases,
`_extractor_name()` helpers that `getattr` a fixed constant and caller-supplied
helper parameters are resolved; the shared secret-like builder is attributed
its callers' names. Any other `extractor=` form, such as an attribute value, and
any construction without an explicit `extractor=` keyword, including a `**`
splat, fails the source-resolution owner instead of being skipped. Three
source-ingestion names are included so the map covers every product emitter,
but they have no discovery entrypoint.

Lookups are exact. A prefix, package wildcard, unknown name, string or copied
record is refused; only the registry's own record object passes
`require_registered_entrypoint`. Identity is module and symbol names, never
source hashes, so reviewed bug fixes need no registry edit. The registry holds
strings only and never imports or loads code. Every legacy member has an
undeclared capability set and undeclared/unavailable lifecycle facts; continuity
is not capability, containment or a native-code exception.

The baseline identities trace to ADR0050's acceptance on 2026-08-12; current
namespace and source-owner moves do not expand that historical membership.

## Receipt v1

Schema `cloe-extractor-run-receipt-v1`, vocabulary `cap-v1`. Top-level fields:
`state`, `producer`, `consumer_boundary`, `run_id`, `source_sha256`,
`declared`, `observed`, `refusal`. All fields are required; absent values are
explicit `null`.

- `declared`: stage, language-dialect, optional exact runtime identity,
  capabilities, effect vector, provenance, invocation mode, optional dependency
  digest and profile digest.
- `observed`: installed and admitted facts, optional artifact digest and
  invocation mode, at most 64 attempts, resource-bound events, optional exit
  status, cleanup fact and verification fact.
- Attempt: input digest, closed D12 outcome, exercised and achieved sets and
  declared completeness (`complete`, `partial`, `truncated`, `none`).

Inputs are identified only by digest, never by path or content. The
verification vocabulary is `unverified` or `refused`: serialized data cannot
represent parent verification success.

States are `declared`, `incomplete`, `complete`, `refused` and `unavailable`.
Allowed transitions are `declared` to any other state and `incomplete` to
`incomplete` or `complete`; the remaining states are terminal. A transition may
not rewrite identity or declarations, and observed facts only accumulate:
`installed` and `admitted` are fixed; artifact digest, invocation mode, exit
status and a cleanup fact other than `unknown` are set once; resource events
form a superset; attempts are only appended; and `refused` verification is
sticky. Incomplete cleanup therefore cannot later become a `complete` receipt. Coherence
rules: achieved is a subset of exercised, exercised a subset of declared;
achievement requires a `succeeded` outcome; `syntax.tree` requires a complete
tree; `syntax.error_tolerant` requires declared completeness; attempts require
admission; admission requires installation; `refused` and `unavailable` have no
admission or attempts; `unavailable` means the dependency was unavailable;
`complete` requires an exit status and proven or not-applicable cleanup.

## Canonical bytes and decoding

Canonical bytes are `json.dumps` with sorted keys, `(",", ":")` separators,
ASCII escapes, no NaN and no trailing newline, at most 65,536 bytes. The digest
is the external SHA-256 of those bytes and never appears inside the receipt.
Decoding refuses, with a categorical code only: non-bytes, oversized input,
non-ASCII bytes, nesting deeper than 6 (measured before parsing), invalid JSON,
duplicate keys, NaN or infinity, any float, integers longer than 20 digits,
missing or unknown fields at every level, wrong schema or vocabulary, invalid
types, tokens, digests or lifecycle states, a mismatched expected digest and any
encoding that is not byte-identical to the canonical form.

## Bounded storage

Callers own a private directory descriptor. Each IO operation checks that it
is a directory owned by the effective user with no group/other access. Names
are one component matching
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}` without `..`. Writes use
`O_CREAT|O_EXCL|O_NOFOLLOW` with mode `0600`, write fully, `fsync`, then read
back through the same descriptor-relative path and require identical bytes and
the created inode. Reads use `O_NOFOLLOW|O_NONBLOCK` and refuse symlinks,
non-regular files, hard-linked files, files above the limit (hard cap 1 MiB) and
any change of device, inode, size, timestamps or link count during the read or
of the directory entry afterwards. Failed writes remove only the exact created
inode; if the entry no longer names it, nothing is deleted and the code is
`cleanup_incomplete`. Receipts are stored as `receipt-<sha256>.json`; loading
verifies the digest. A stored receipt is audit evidence, not admission.

## Witness and canonical refusal

`ParentWitness` cannot be constructed, copied or pickled.
`refuse_capability_admission` ignores its argument and always returns
`native_observer_unavailable` with the eight bindings a future controller must
recompute from actual observations. `ObservationBatch` carries raw schema-1
observations unchanged with origin `legacy-discovery` or `offline-raw`; there is
no witnessed origin.
Batch construction accepts bounded exact lists or tuples, checking type and
length before copying; it does not consume an arbitrary iterable first.

Before family dispatch, canonicalization refuses an observation of any kind
whose top-level metadata contains a reserved capability-claim name
(`capability_vocabulary`, `declared_capabilities`, `admitted_capabilities`,
`exercised_capabilities`, `achieved_capabilities`, `effect_vector`,
`parent_witness`, `capability_witness`), any `extractor_receipt*` name
(including the receipt reference `extractor_receipt_ref_v1`), or a `language`,
`dialect` or `language_dialect` value asserting Rust. A refused observation
produces no node, edge or evidence and is excluded from the shared Go context.
One warning diagnostic, category `extractor_capability_claim_refused`, carries
its ordinal, path, field `metadata` and a reason code; metadata values are never
echoed. When several claims apply, the reason is the receipt reference first,
then capability metadata, then the Rust assertion. Raw JSONL stays readable and unmodified for audit.

The Rust assertion is not applied to `markdown.code_fence` and
`html.document`, the legacy kinds whose `language` describes embedded content
(a fence info word or an HTML `lang` attribute) rather than the observed source.
A Markdown `rust` fence therefore keeps its legacy page evidence. Reserved
metadata names are still refused on those kinds.

Everything else keeps its legacy behavior. Discovery still classifies `.rs` as
`unknown` (or by its legacy shebang quirk), unsupported kinds such as
`rust.function` keep `unsupported_raw_observation_kind`, raw decoding is not
tightened and raw extractor strings remain unauthenticated. A forgery shaped
exactly like legacy output can therefore obtain only legacy-strength claims,
as any raw JSONL could before this phase; no capability-gated claim exists.

## What would make this contract wrong

- A raw observation, receipt, digest, nonce, callback, boolean or constructed
  object causes canonical admission of a parser or Rust capability claim.
- A product module emits a legacy extractor name without being in the owner map
  and the source-resolution owner does not fail.
- Legacy discovery or canonicalization output changes for input carrying no
  reserved metadata name or Rust language assertion, including a Markdown
  `rust` code fence.
- A receipt transition changes or erases an earlier observed fact.
- A receipt that decodes successfully re-encodes to different bytes, or two
  distinct receipts share canonical bytes.
- Bounded storage deletes, follows or overwrites an entry it did not create.
- A lifecycle fact is derived from another, or legacy membership reads as an
  achieved capability.

## Limitations

The entry check and `unlink` in owned cleanup are separate system calls.
Private directory admission checks POSIX ownership and mode bits. The trusted
directory creator must ensure no additional ACL grants; ACL inspection is not
implemented. The owning principal and privileged host processes remain
trusted. Operational filesystem faults can propagate `OSError`; future native
controllers must sanitize them before exposing diagnostics. No hostile
same-user filesystem
sandbox or atomic conditional unlink is claimed. Observable substitution
is refused. Extractor-name and dispatch closure is proven by static source
resolution in the unit owner, not by execution of every extractor. Receipts are
not authenticated and the foundation has no native observer, helper, parser,
confinement or cleanup witness; those require a separately approved parser class
and resulting ADR.
