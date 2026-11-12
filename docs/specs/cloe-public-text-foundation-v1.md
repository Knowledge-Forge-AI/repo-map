# Public-text foundation contract

Status: model-independent source accepted after conforming independent review
and exact scoped proof (142 unit, four containerized integration cases).
Calibration/runtime/report/publication remain pending. Date: 2026-11-11.
Phase: `REPOMAP-CLOE-PUBLIC-TEXT1`.

## 1. Accepted scope and remaining authority

The operator selected captured-public-text input on the exact existing
mixed-v1/BGE/ONNX path and explicitly permitted document-only generation 2.
The task-side preflight verified all 24 retained task digests and found four
fixed generation-1 ranked queries surviving declared body policy, zero in
generation 2. Declaration 1 remains stopped. The entirely unspent allocation
stays two workers, one study materialization and no retry.

This first implementation epic is model-independent: admission, accepted raw
capture/span correspondence, deterministic descriptors/model text and census.
It adds no production behavior, profile, schema, CLI/MCP, dependency, lock,
runner, image build, model execution, vector storage or scientific acceptance.
The overall [declaration and later epic proposals](cloe-public-text-calibration-implementation-v1.md)
do not make their unaccepted sealing/report details prerequisites for this
independent foundation. Later epics need their own technical acceptance.

## 2. Preserved boundaries

All old v1 functions, decisions and worker protocols remain byte-unchanged.
No file under src/main/python changes. Source selection comes from accepted
publication/capture/evidence owners; no task, filename, descriptor claim or
serialized code reference can authorize body access. MCP remains read-only.
Public report/log objects expose hashes, offsets, counts and closed reasons,
never raw captured text, private paths, endpoints or runtime identifiers.
No fixture body, query, gold, catalog or held-out record is changed.

## 3. Exact foundation ownership

| New owner | Responsibility |
|---|---|
| `tools/retrieval_public_text_contracts.py` | closed descriptor/reason/decision contracts and strict public-safe serialization |
| `tools/retrieval_public_text_excerpt.py` | exact line/byte/UTF-8 bounds and fixed model-text encoder |
| `tools/retrieval_public_text_admission.py` | unchanged base/v1 decisions plus supplemental per-arm body policy |
| `tools/retrieval_public_text_capture.py` | unchanged global projection membership and exact delegated-read accounting/raw capture |
| `tools/retrieval_public_text_descriptors.py` | current accepted publication, capture, span and descriptor recomputation |
| `tools/retrieval_public_text_census.py` | frozen task-side/runtime applicability and bounded preparation ledger |
| `src/test/support/python/repomap_test_support/w5_public_text_readback.py` | companion SQLite/PostgreSQL span adapters; old reader functions unchanged |

Keep each module within existing file-length/quality policy, no exemptions,
suppression or debt growth. A natural helper split inside this responsibility
may be proposed before source ownership freezes; never add a framework or
duplicate maintained artifact/projection logic. Product modules import none
of these tools/support owners.

## 4. Model-free task census and runtime revalidation

The pre-implementation task-side census is complete: all 24 selected task
objects match their retained ASCII-escaped canonical JSON digests; only selected calibration objects were
decoded, and no gold/question value influenced selection. Its necessary
ranked-mode counts are 4/0 for generations 1/2. The pure declared-policy check
using the maintained factory and `_policy_denial(..., body=True)` confirmed
that all four generation-1 queries survive core/companion body-policy checks.
It read no fixture body or model and opened no database. This closes the
task-side floor for declaration 2; it is not live publication admission.

The implemented census repeats checks against the actual current accepted
publication before any generation preparation: exact task id/digest/mode,
binding scope, unchanged incumbent and v1 query decisions, supplemental
public-text body policy and closed applicability. No questions or golds are
selection criteria. Fresh publication, complete artifact/span correspondence,
document eligibility and remaining caps are checked before reservation.

## 5. Admission

### 5.1 Query arm wrapper

`admit_public_text_query(task, *, policy, publication_pin, observed_backend,
frozen_policy_digest, post_publication_pin)`:

1. Call unchanged `admit_w5_task` with identical arguments. Its serialized
   decision is the v1/incumbent decision, byte-for-byte unchanged.
2. If that decision is not `ADMITTED`, the public-text arm inherits its state,
   reason and refusal code (global denial refuses every arm).
3. Otherwise, for each selected binding id in task order: if absent from
   `policy.bindings`, refuse with `public_text_binding_policy_missing` (the
   helper's `None` is not authority); else call `_policy_denial(policy,
   binding_id, body=True)`; the first non-`None` reason refuses the public-text
   arm with layer `public_text_body_precheck`. The missing-binding check is
   defensive and unreachable here: `admit_w5_task` already makes an
   undeclared or foreign binding `UNAVAILABLE`
   (`retrieval_evaluation_admission_w5.py:259-269, 286-304`), so step 2
   handles it. Its unit test calls the helper directly; the reachable
   missing-binding branch is in section 5.2. It is not counted toward branch
   recovery.
4. Applicability uses the complete unchanged v1 predicate: stratum exactly
   `metadata`, surface not `captured_text`, mode `ranked_discovery`, grading
   rule `ranked_positive` or `absent_answer`. Evaluate it in the same order as
   `_query_decision`: stratum/surface, mode, then rule. Preserve its unavailable
   reason for each failure. Task mode, stratum and surface are never relabelled.
5. Any fusion arm depending on the public-text arm inherits its refusal;
   incumbent fusion keeps the v1 decision.

The result is a new `PublicTextQueryDecision` carrying the unmodified v1
decision object plus the public-text state; the v1 object is never rebuilt.

Two v1 decision objects exist and both stay byte-identical: the evaluator's
`admit_w5_task` decision, and the learned-query `QueryInputDecision` that
`prepare_public_generation_input` builds through `inputs._query_decision`
(`retrieval_semantic_generator_inputs.py:131-153`, over
`pin.denied_bindings`). The v1 query records in the request come from the
second object, not from step 1. Byte-identity tests pin both.

### 5.2 Document pair admission (before any body read)

For each `(canonical_key, binding_id)` pair in the fresh v1
`RepresentationValidationReport.verified_entries` (so v1's observed-evidence,
withheld-path and mixed-provenance rules apply unchanged), in order:

1. binding present in `policy.bindings`, else `public_text_binding_policy_missing`;
2. `_policy_denial(policy, binding_id, body=True)` is `None`;
3. `evaluate_binding_exclusion(policy, manifest_binding)` is `None`;
4. select a span (section 6.2), require exact integer endpoints (not bool)
   both >=1, else `public_text_span_invalid`; then require start <= end, else
   `public_text_span_reversed`. These content-blind checks precede body reads;
5. validate the selected K/T/N/P metadata with the exact descriptor bounds,
   `validate_relative_path` and the same private markers, else
   `public_text_metadata_privacy_refused`;
6. require the selected path to be a manifest entry of that binding, else
   `public_text_artifact_not_in_manifest`;
7. `evaluate_artifact_pre_open(policy, binding, entry)` returns no reason.

A failure excludes only that pair with its closed reason, recorded before any
store open. v1 documents are never removed because a v2 pair is excluded.
Steps 1-7 read only policy, manifest and evidence-row metadata. Projection
membership (section 6.1) is the next admission step and the first body read.

## 6. Accepted readers and descriptors

### 6.1 Publication and artifact closure

The descriptor builder accepts a factory-issued `VerifiedPublicationPin` and
an injected trusted `PublicationReadbackAdapter`; tools never import test
support or access the pin's private adapter field. Call `pin.revalidate_current`,
then invoke the injected adapter once to capture an `AcceptedStoreReadback`.
Verify that exact captured object through unchanged
`verify_publication_provenance` using `readback_adapter=lambda: captured` and
its graph/repository/backend/publication/receipt plus the same policy. Compare
the resulting verified pin's complete `to_dict()` with the original pin's
`to_dict()`. This binds all reference fields, generations, candidate, snapshot
vector, receipt identity and policy, without requiring callable identity.
The captured object supplies `projection_inputs`; require it non-None.
Missing inputs make the whole v2 arm unavailable for that generation (gate 8;
no live-filesystem or alternate-backend fallback). Revalidate the original pin
after capture and around every later dependent read. Inject span-reader
callables separately, checking their returned row sets as section 6.2 requires.

Before the first read: `check_correspondence(projection_inputs)` (receipt,
manifest, bundle, three verified store references, canonical re-parse,
`PublisherBundleValidator`), `pin.revalidate_current()`, and
`policy.policy_digest() == pin.policy_digest`. The returned
`AcceptedPublicationReference.to_dict()` is captured whole. Every later
comparison uses all eleven fields, explicitly including `snapshot_manifest_id`
and `extraction_receipt_id`, which `matches_current()` omits.

**Projection membership (admission authority).** The bounded projection the
body policy authorizes is the one the maintained composer builds. The design
therefore does not recompose its steps. If section 5.2 admits at least one
pair in a pass, call unchanged `build_captured_text_projection(
projection_inputs, policy)` (`projection_build.py:168-349`) once for that pass.
That call performs correspondence, binding exclusion, pre-open, the
`(binding_id, source_relative_path)`-ordered file-count and aggregate-byte
budget over all manifest entries, `store.read` and `normalize_and_bound_text`.
It reads only entries its own pre-open policy admits. It is the maintained,
policy-authorized captured-text reader, so it adds no new body-read class.
Whether the matched captured-text controls reuse this same pass is an
implementation detail; that is not claimed here. If no pair is admitted, it is
not called and no body is read.

A pair is admitted only if its selected `(binding_id, source_relative_path)`
is a `ProjectedFileRecord` with `truncated == False`, its `accepted_reference`
equal on all eleven fields to the captured reference, and its
`original_content_digest` and `original_size_bytes` equal to the manifest
entry. Otherwise:

- `AGGREGATE_BUDGET_EXCEEDED` on a selected file stops the attempt (gate 5).
  Budget order never silently drops a selected document.
- `truncated` excludes the pair (`public_text_projection_truncated`). This is
  a fixed, content-blind rule frozen before any model work.
- Any other maintained exclusion (`INVALID_UTF8`, `NUL_BYTE_REJECTED`,
  `ARTIFACT_MISSING`, `ARTIFACT_CORRUPT` or a pre-open reason) excludes the pair
  as `public_text_projection_excluded:<maintained reason>`.

**Raw excerpt read.** Only for admitted pairs, read the raw bytes again
through `projection_inputs.store.read(entry.reference.with_store_version(None),
max_bytes=policy.max_input_artifact_bytes)`, once per distinct content digest
per pass. Independently require exact `bytes`, compare `len(raw)` with the manifest
entry size, and recompute SHA-256 against its content digest before any
excerpt use. A type/length/digest mismatch refuses as
`public_text_artifact_integrity_refused`. This holds for every store type,
including a store that incorrectly returns a prefix. For
`FileSystemArtifactStore` the underlying call (`_store_filesystem.py:313-324`,
`_read_path` 142-188) opens with `O_NOFOLLOW`, checks owner, mode, link count
and inode stability, reads the whole object, and verifies exact size and
SHA-256. It is complete-object verification, never a prefix.
`returned_payload_bytes` counts the projection pass and excerpt reads
separately, without claiming that a bad store's returned data was verified.
Independently verified excerpt-object bytes and selected excerpt bytes have
their own counters; failed reads never become verified work. Offsets always use the
original raw bytes, never normalized text or chunk digests. The record's
`raw_line_count` is kept for the line-convention cross-check in section 6.3.

### 6.2 Span reader and selection

The existing v1 reader owner is
`src/test/support/python/repomap_test_support/w5_semantic_store_support.py`:
`load_sqlite_accepted_nodes_and_evidence` (48-107) and
`load_postgres_accepted_nodes_and_evidence` (145-228). Both exist; the first
review's claim that only SQLite exists was incorrect. Their old functions
remain byte-unchanged. A new support owner `w5_public_text_readback.py` adds
backend-specific companion span reads, using the same config resolution,
repository/accepted-run predicates and connection boundary as those readers.

Span owners are `canonical_evidence.start_line/end_line` in SQLite and
`public.canonical_evidence.start_line/end_line` in PostgreSQL. Companion rows
carry canonical key, evidence key, link kind, run, graph-key version,
binding/snapshot/path and the two nullable integers. The exact row key is
`(canonical_key, evidence_key, link_kind, run_id, graph_key_version)`;
observed and inferred links to the same evidence remain distinct. Compare
the complete row-key set against the fresh v1 evidence read and require equal
path/metadata on each key. Missing/extra/duplicate keys or unequal metadata
refuse the entire public-text generation preparation before any body read;
they never drop one pair and continue. Old v1 decisions remain unchanged.
Only observed rows admitted by unchanged v1 validation select an excerpt.
Inferred-only, foreign, missing or invalid selected spans exclude the pair.

The learned study uses PostgreSQL publication pins from the beginning, in the
same single disposable cluster used for import and query. The existing
`make_postgres_readback_adapter(published)` supplies current receipt plus
`published.projection_inputs()` without a receipt override. Revalidate before
and after every dependent read. Compare all eleven reference fields within
that PostgreSQL publication, including manifest and extraction receipt IDs.
No SQLite-to-PostgreSQL reference equality or vector rebinding is attempted.
SQLite remains an independent core-integration adapter/control only.

Select only from the exact observed evidence rows already admitted for that
pair by v1 validation. `source_relative_path` comes from their verified
`metadata_json`, never the separate evidence `path` column. The companion
reader returns both unchanged so equality with the v1 row can be checked.
Do not filter NULL, reversed or out-of-file spans before selection. Use a
total sort key `(path_utf8, evidence_key_utf8, endpoint(start), endpoint(end))`,
where `endpoint(x)` is `(1, x)` for an exact integer (not bool), otherwise
`(0, 0)`. For valid rows this preserves the original numeric ordering; missing
or invalid endpoints never cause a Python comparison error. After selecting
the minimum, require exact integer endpoints, then validate the span.
Invalid chosen spans exclude the pair; never select a later favorable span.

A withheld/conflicting path fails v1 validation before selection. Any remaining
selected path outside the exact manifest binding/entry excludes the pair at
section 5.2 step 4; it is not filtered to select a different row. A companion
metadata mismatch, duplicate, missing or extra row refuses correspondence
before selection. Whole-file line-convention checks precede excerpt use.

### 6.3 Byte mapping (exact)

Let `B` be the verified raw bytes. Line 1 starts at offset 0. Each `0x0A` at
offset `i` ends its line inclusively; the next line starts at `i + 1`. Line
count `L = count(0x0A) + (1 if B and B[-1] != 0x0A else 0)`; an empty file has
zero lines and a terminal LF creates no extra line. A `0x0D` immediately
followed by `0x0A` is part of its line's terminator, so CRLF stays two bytes.

**Line-convention guard (whole file, before span checks).** Line conventions
differ. The maintained counter (`projection_text.py:20-24`, and the
normalization at line 84) treats a lone CR as a line break. Python
`str.splitlines` also breaks on VT, FF, U+001C-U+001E, U+0085, U+2028 and
U+2029. Extractor line numbers may follow any of these conventions. Exclude
the pair with `public_text_line_convention_mismatch` if either of these holds:

- the strictly decoded file contains a `0x0D` not immediately followed by
  `0x0A`, or any of U+000B, U+000C, U+001C, U+001D, U+001E, U+0085, U+2028 or
  U+2029;
- `L` differs from the `raw_line_count` of the file's `ProjectedFileRecord`.
  This is a defensive invariant; once the first condition is false, it cannot
  hold.

On the remaining files every convention above gives the same line numbers, so
the mapping does not depend on which convention the extractor used.

The pure excerpt helper first applies the same content-blind endpoint checks
as section 5.2 (exact integer and >=1, then start <= end). After those pass,
strictly decode the entire verified raw file; failure maps to
`public_text_excerpt_invalid_utf8` (X8 is the direct helper vector).
Then run the whole-file line-convention guard, then require `end_line <= L`,
else `public_text_span_out_of_file`. Integration normally observes the
maintained projection's earlier `INVALID_UTF8` exclusion for X8, not a
successful projection. No endpoint check waits for body bytes.
`span_start` is
line `start_line`'s first byte; `span_end` (exclusive) is one past the LF of
line `end_line`, or `len(B)` for a final line without LF. `cut_end = min(
span_end, span_start + 4096)`. Decode `B[span_start:cut_end]` strictly; if it
fails only with an incomplete sequence in the last three bytes and
`cut_end < span_end`, trim to the failure position (1-3 bytes) and decode
again. Any other decode failure excludes (`public_text_excerpt_invalid_utf8`).
A whitespace-only excerpt (`excerpt.strip() == ""`, Python Unicode whitespace)
excludes (`public_text_excerpt_blank`). An excerpt failing
`is_sanitized_public_string` with the run's private markers excludes
(`public_text_excerpt_privacy_refused`); text is never redacted and admitted.

The phase controller constructs one immutable, repr-suppressed private
marker scope from its trusted current run envelope: private home/login,
protected and contribution checkout roots, scratch root and known private
endpoints/runtime identifiers. Require a tuple of 1-128 exact nonempty,
non-whitespace-only strings, each <=4096 UTF-8 bytes and containing no Cc/Cs.
Refuse missing/invalid scope as `public_text_private_marker_scope_invalid`.
No empty/default fallback. Tests inject named synthetic canaries.

The controller freezes a private digest of the sorted unique markers and a
fresh random 256-bit `privacy_scope_id` (opaque hex with a version prefix).
Only that random ID appears in public descriptors/census. The marker values
AND digest stay in private immutable scope state and never in a public
serializer, repr, log or model record. The random ID commits no guessable
marker-derived data. Before recomputation require the same frozen scope ID
and private marker digest; do not recreate the scope or accept a serialized
public ID as authority. The stored marker digest is unkeyed. It is not a
capability against a caller that can recompute it. The bindings that count
are the fresh-owner check and the scope object identity, and caller-supplied
markers confer no native authority. Markers come from the trusted run envelope, never
from task questions, golds or captured text. The same markers are passed to
`_validate_representation_string` for K/T/N/P and excerpt sanitization.
Any K/T/N/P privacy or path failure refuses the pair as
`public_text_metadata_privacy_refused` before body access.

### 6.4 Model text (`cloe-public-text-model-text-v1`)

Exactly these keys in this order, serialized with `json.dumps(obj,
ensure_ascii=False, separators=(",", ":"), allow_nan=False)`:

```text
{"v":"canonical-node-public-text-v2","canonical_key":K,"kind":T,"display_name":N,"source_relative_path":P,"excerpt":E}
```

`K`, `T`, `N`, `P` pass unchanged `_validate_representation_string`. Then every
remaining character of Unicode category `Cc` (only U+007F-U+009F can survive
`json.dumps`) is replaced by `\u00xx` with lowercase hex. The result contains
no `Cc`/`Cs` character, so it satisfies both the worker request check
(`worker_protocol.py:174`) and the kernel check (`kernel_validation.py:174`).
Non-ASCII text stays literal UTF-8. Lone surrogates cannot arise from strict
decoding and are refused if supplied. The model text contains no digest,
offset, line number or binding id. `input_digest = "sha256:" +
sha256(model_text UTF-8)`; it is never equal to a v1 digest because the bytes
differ by construction (`"v"` key).

The kernel's unchanged query prefix, CLS pooling, normalization and 512-token
truncation apply. Token counts come only from the worker receipt.

### 6.5 Descriptor (`cloe-public-text-descriptor-v1`)

Strict frozen object; unknown or missing keys refuse. Fields: `schema`,
`representation_version`, `model_text_version`, `admission_policy_version`
(`cloe-public-text-admission-v1`); `graph_id`, `repository_identity`,
`backend`, `run_id`, `generation`, `receipt_identity`, `policy_digest`,
`privacy_scope_id`,
`accepted_reference` (all eleven fields), `publication_bundle_id`,
`snapshot_manifest_id`, `extraction_receipt_id`, `candidate_id`;
`source_binding_id`, `binding_revision`, `snapshot_id`; `canonical_key`,
`kind`, `display_name`, `v1_input_digest`; `evidence_key`,
`source_relative_path`, `start_line`, `end_line`; `artifact_content_digest`,
`artifact_size_bytes`, `artifact_privacy`; `span_start_byte`,
`span_end_byte`, `excerpt_end_byte`, `excerpt_bytes`, `excerpt_digest`,
`span_cut`, `utf8_tail_dropped_bytes` (0-3), `lf_count`, `crlf_count`,
`final_line_without_lf`; `model_text_bytes`, `input_digest`.
`descriptor_identity = digest_json(descriptor)` (sorted compact JSON).

### 6.6 Frozen test vectors

Unit owners assert these bytes literally. Expected digests are computed in the
test from the literal expected bytes with `hashlib`, never through the
encoder; this stage executed nothing, so no digest is precomputed here.

| Id | Raw bytes | Span | Expected |
|---|---|---|---|
| X1 | `a\nbc\nd\n` | 2-2 | bytes [2,5) `bc\n`; L=3 |
| X2 | `x\r\ny\r\n` | 1-2 | [0,6); crlf_count 2 |
| X3 | `p\nq` | 2-2 | [2,3) `q`; final_line_without_lf |
| X4 | `p\nq` | 3-3 | out_of_file |
| X5 | `p\n` | 2-2 | out_of_file (terminal LF adds no line) |
| X6 | 4095 x `a`, `C3 A9`, `\n` | 1-1 | excerpt 4095 bytes; cut; tail dropped 1 |
| X7 | 4094 x `a`, `F0 9F 98 80`, `\n` | 1-1 | excerpt 4094 bytes; tail dropped 2 |
| X8 | hex `61 FF 62 0A` | 1-1 | invalid_utf8 |
| X9 | hex `7F C2 9F 0A` | 1-1 | excerpt JSON `"\u007f\u009f\n"` |
| X10 | `p\nq` | 3-2 / 0-1 | reversed / invalid |
| X11 | empty | 1-1 | out_of_file |
| X12 | `\n` | 1-1 | blank |
| X13 | `def f():\n    return 1\n`, K=`py:mod.f`, T=`function`, N=`f`, P=`src/m.py` | 1-2 | `{"v":"canonical-node-public-text-v2","canonical_key":"py:mod.f","kind":"function","display_name":"f","source_relative_path":"src/m.py","excerpt":"def f():\n    return 1\n"}` |
| X14 | X13 with N=`café` | 1-2 | `café` literal UTF-8 (`63 61 66 C3 A9`) |
| X15 | `a\rb\n` | 2-2 and 1-1 | line_convention_mismatch (whole file; lone CR) |
| X16 | hex `61 C2 85 62 0A` | 1-1 | line_convention_mismatch (U+0085) |
| X17 | `a\r` | 1-1 | line_convention_mismatch (lone CR at end of file) |

In X17, `L` and `raw_line_count` are both 1. Only the first guard condition
catches it, so the vector pins that condition independently of the
cross-check.
The encoder unit test separately covers every `Cc` character from U+007F to
U+009F, including U+0085, by calling the encoder directly on strings. X16 shows
that U+0085 cannot reach the encoder through a span.

## 7. Read accounting and private data

For exact read accounting, the capture adapter delegates the maintained
projection's reads unchanged through a closed read-observation wrapper.
There is no raw-object cache in this foundation. Excerpts use the explicit
second complete-object `read` in section 6.1, once per distinct digest per
pass; raw bytes are discarded after deriving all descriptors for that object.
The wrapper never skips reads or changes global projection order or budget.
It delegates `get`, `read`, `verify` and `open_stream` with identical arguments,
return values and exceptions. It observes each method invocation separately.
`read` attempts and successfully returned payload bytes are counted,
separating the three metadata-reference digests from source-content digests.
`get` also returns complete verified bytes (it delegates to `read` in the
inner filesystem store). Count its attempts and successful returned payload
bytes exactly like `read`, under its own method name, without double-counting
the inner store's call. `verify` is opaque: internal reads cannot be counted
by this wrapper. `open_stream` returns the original
stream unwrapped: stream consumption, failed-read bytes and internal/device
I/O remain explicitly unknown, never zero. Such correspondence work is not
represented as fully measured total I/O. Record these measurement scopes and
unknowns alongside direct-read counters. A post-inference pass starts new
counters and recomputes everything. Raw capture is private, repr-suppressed,
and never appears in public report/log representations.

## 8. Exact proof owners

Use the canonical runner with `--no-coverage`. Initial unit selectors:

```text
src/test/unit/python/tools/retrieval_public_text_contracts.unit.test.py
src/test/unit/python/tools/retrieval_public_text_excerpt.unit.test.py
src/test/unit/python/tools/retrieval_public_text_admission.unit.test.py
src/test/unit/python/tools/retrieval_public_text_capture.unit.test.py
src/test/unit/python/tools/retrieval_public_text_descriptors.unit.test.py
src/test/unit/python/tools/retrieval_public_text_census.unit.test.py
```

Initial core containerized integration selectors:

```text
src/test/int/python/tools/retrieval_public_text_capture.int.test.py
src/test/int/python/tools/retrieval_public_text_census.int.test.py
```

The unit contract covers the literal X1-X17 vectors, strict types/unknown
fields/private-string refusal, unchanged v1 decisions and real supplemental
body-policy differences. Integration uses actual accepted capture/publication
objects, filesystem stores and disposable SQLite/core PostgreSQL: pre-read
denial, projection membership/budget refusal, actual full-content integrity,
span correspondence, publication/optional-ID advance, independent descriptor
recomputation and observed read work. No model/runtime/vector boundary is
mocked into an integration claim. Synthetic vectors are not used in this epic.

Private-name reuse is checked by observable equivalence and concrete behavior,
not an assertion merely pinning implementation order or import identity.
Changes to existing product owners are excluded; adjacent regression tests
must prove useful source/publication/artifact safety behavior. Exact selectors
and source snapshot are recorded for each run. No complete local suite,
smoke/staging/system run, local coverage or project dependency change is
authorized. Scoped source proof makes no hosted or whole-product claim.

## 9. Foundation acceptance and later gates

Before source work: conforming independent technical checkpoint plus parent
disposition for this exact foundation. Before closeout: paired scoped unit
and containerized integration evidence, proportional static/diff/link checks,
independent resulting-source review and protected-checkout preservation.
The later response/vector/report contracts remain proposed. No model slot is
reserved by foundation tests and no intermediate public CI is planned.


## 10. Foundation falsifiers

The design fails if delegated reads change maintained projection membership,
if get/read payload bytes are misclassified or opaque work becomes zero,
if a prefix is treated as complete-object verification, if either backend's
span rows differ from accepted v1 evidence, if line mapping disagrees with
the admitted convention, if an optional reference ID drifts undetected, or
if old v1 decisions change. Real paired scoped tests must challenge these
claims. No test result is implied by this design.


## 11. Resulting-source review dispositions

The ADR0182 evaluator-privacy closure is binding: before body access, K/T/N/P
meet the descriptor's nonblank, <=1024-character, Cc/Cs-free public string
bounds and the existing path/marker checks. Excerpt text independently refuses
ordinary credential assignments and credentialed HTTP URLs with a small local
stdlib predicate, then the maintained sanitizer; no redacted text is admitted.
The pure encoder remains capable of escaping excerpt C1 controls. No product
redactor, v1 validator, package, lockfile or runner policy is changed.

Each explicit raw reread has its own before/after publication fence; the
unchanged global projection pass retains its batch fence. Known census input/
admission/provenance errors return a closed census refusal. Generation2 proof
uses a genuinely advanced accepted publication and generation2 enumeration
task, with the old generation1 pin refused. SQL-span mismatch is pair-local
before the reread, but any recomputation change refuses the whole generation.

## Task identity compatibility

The retained task pin uses the existing ASCII-escaped canonical JSON scheme.
The unchanged v1 query decision uses UTF-8 JSON without ASCII escaping.
The existing Unicode task makes them differ. The census preserves the
original `task_sha256` for v1 and adds `retained_task_sha256` for the retained
manifest. It validates both independently. Original pins, task bytes,
decisions, questions and golds are unchanged. The selected loader verifies
the retained scheme; request correspondence binds both named maps. Metadata
preflight's 24 retained matches never meant equality between these schemes.

External readback callback exceptions refuse the entire preparation/census
under a closed code, with no raw callback error in public diagnostics. They
never become a pair-local favorable exclusion.
