# CLOE W5 semantic evidence design v1

Status: accepted implementation contract under ADR0136 and the explicit operator A generator selection.
This document specifies a bounded experimental milestone, not production
extension admission or a claim that W5 is complete.

## Existing owners and boundaries

`storage/semantic_candidates.py` and its import/readback/SQL/seed owners retain
pgvector 0.8.7, exact cosine, 500 imported node/source records, explicit rebuild
and profile selection, publication/portable-receipt fences and the separate
enrichment principal. `server/investigation_read_store.py` owns the optional
PostgreSQL seam. SQLite reports explicit unavailability. Neither MCP nor an
ordinary reader acquires source text, inference authority or enrichment writes.

W3 lexical projection is derived from accepted captured material and has its
own privacy, owner, generation and publication fences. W4 context is bounded
metadata plus optional structural freshness; this milestone must not retrofit
source excerpts or embedding calls into that reader.

The proposed generator/evaluator extends these owners. It must not build a
second graph authority or duplicate the existing publication state machine.

## Representation and generator contracts

Preserve `canonical-node-v1` unchanged: encode exactly canonical_key, kind and
display_name as UTF-8 JSON with sorted keys, compact separators and unescaped
Unicode. Recompute the digest over those actual bytes from accepted public
nodes, and bind graph/repository, accepted receipt, source binding/revision,
captured snapshot and canonical identity. Record exact model/revision/file
hashes, generator version, dimensions, cosine metric, L2 normalization,
tokenizer/pooling/query policy, privacy and partial coverage in the immutable
profile/rebuild artifact. The first milestone uses the existing optional schema
and 500 node/source cap. It does not add a captured-body representation/table.
The reference byte encoding is:

```python
json.dumps(
    {"canonical_key": key, "kind": kind, "display_name": name},
    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
).encode("utf-8")
```

Require actual string fields and refuse unencodable values, including lone
surrogates. This is a new generator owner to implement; no existing helper is
claimed. No current checkout source text, model-generated summary or unrelated
canonical node can replace the accepted metadata.

Eligibility follows declared binding privacy, even when fixture bytes are
publicly stored in Git. Exclude private-only and withheld evidence. A node
requires eligible accepted public-binding evidence and representation bytes
verified against that public evidence; exclude mixed-provenance representations
whose public eligibility cannot be proved. Refuse a query targeting a denied
binding before inference. Vector/fused arms preserve the privacy refusal and
must not return candidates from another binding or disguise refusal as an
unavailable arm. The fixture mailbox binding remains a refusal case. Existing
asserted-digest imports cannot be relabeled as independently verified generator output without this proof.

Embedding body chunks, changing representation bytes, increasing the row cap
or creating persistent/admitted optional storage objects requires a later
accepted contract. Experiment-local HNSW/GIN indexes and JSONB projections are
permitted only in disposable databases, are removed at cleanup, and are never
adopted into a production or ordinary application schema by this milestone.
This bounded metadata representation may prove inadequate for task utility;
report that result rather than broadening input silently.

The generator receives an explicit regular-file manifest and a fixed artifact
directory. Validate the entire bounded input before starting inference. Use
exclusive output creation, an invocation-owned temporary directory and atomic
complete-result publication; retain a bounded failure receipt when output is
writable. Failed or partial generation cannot become a complete rebuild.
Output is inert JSON with finite vectors, strict integers, exact dimensions,
unit-norm tolerance and complete model/input identity. No pickle, executable
model code, arbitrary plugin loading or caller-selected executable is accepted.

For the proposed BGE candidate, tokenization uses only the pinned tokenizer
file. The wrapper must verify model input/output types and actual pooling
behavior, apply the declared query instruction, and expose truncation and
coverage rather than silently dropping text. The 512-token limit is not a
license to treat truncated input as a complete long document. Version every
such policy; record actual inputs without storing unnecessary body copies in
diagnostic logs.

## Acquisition and containment

The operator packet binds the exact model revision, advertised model hash and
twenty-package dependency metadata closure. After approval, fetch only those
artifacts and required small config/tokenizer/license files from their primary
immutable locations. Verify bytes, regular-file/archive boundaries, notices,
target tags and complete runtime closure before installing or importing them.
No cache hit substitutes for hash verification. Unknown license, unsupported
platform, missing artifact, incompatible graph or unresolved security finding
refuses execution. Do not select another model/package version automatically.
This applies to the new generator closure; inherited unmodified Debian findings
remain informational under ADR0105 and do not independently block the pipeline.

Use the existing verified native-ARM SDK image with an invocation-owned tmpfs
dependency overlay, network disabled, no Docker socket, no host home/config,
no private data, read-only model/input mounts and bounded output. Offline
library settings are supplementary; the disabled container network is the
execution boundary. Do not modify the SDK recipe, core dependencies, package
metadata, test-runner defaults or application image for this component proof.
Record resource identity privately and prove exact cleanup. Bind the actual
cached SDK identity and Python ABI before installation; the source SDK recipe
uses Python 3.13, separately from the Python 3.12 application/release runtime.
An absent verified SDK is a stop condition. Rematerializing even the unchanged
recipe would be a build and is excluded. If the approved container cannot
support the closure, report that boundary instead of building a substitute
image. Inspect all twenty dependencies, including idle network-client/native
packages; a minimal undeclared --no-deps subset is not an authorized substitute.
Native AMD/other-platform support is not inferred.

## Fusion experiment

Compare status quo separate results, exact vector candidates and a rank-based
fusion candidate; do not add raw lexical and cosine scores as comparable units.
A predeclared reciprocal-rank candidate may use `sum(1/(60+rank))`, with rank
starting at 1, one contribution per arm and deterministic byte tie-breaks.
This constant is an experiment setting, not an adopted relevance optimum.

Both arms must use the identical accepted publication, selected bindings,
captured snapshots, selected material and privacy scope. This first fusion
comparison is file-level. Map vector candidates through their actual accepted
node/source evidence; map lexical chunks through their accepted captured
locators. Refuse unverifiable or withheld identities rather than matching
untrusted display/path strings. Deduplicate each arm by the complete
(binding_id, snapshot_id, source_relative_path) tuple, retaining its best raw
rank and bounded supporting canonical/chunk identities. Rank contributions use
deterministic one-based ranks after that file-level collapse. Break fused-score
ties by UTF-8 bytes of that full tuple. Each collapsed arm orders by best raw
rank, then the tuple bytes, assigning ordinal rather than dense ranks. Never
count two duplicate rows from one arm as independent support.

Vector file identity comes from verified evidence metadata binding/snapshot/
source_relative_path, with complete bounded evidence enumeration or explicit
truncation; do not split display paths or let evidence_limit silently erase
files. Derive lexical snapshots from the admitted generation snapshot vector.
For grading, drop the snapshot field only after verifying equality with the
task publication snapshot for that binding. Preserve binding/path identity.
Score and label this file-level experiment separately from node-identity metrics and historical graders; preserve raw observations.

Exact-identity lookup remains a distinct unchanged mode. A file-level fusion
result makes no exact-symbol or canonical-relationship claim. Similarity never
writes canonical edges. Inputs without an eligible canonical-node representation
remain explicit coverage gaps in this first vector arm.

Record requested/effective modes, match surfaces, profile/generator identities,
arm ranks and contributions, exclusions, refusal, truncation and provenance.
An unavailable arm makes the requested fused experiment unavailable unless the
caller explicitly requests a separately disclosed fallback. A fallback result
cannot count as execution of the missing arm. Preserve bounded candidate,
statement, storage-work and serialized-byte limits; output caps do not imply
bounded underlying work. A future public CLI/result schema requires its own
accepted versioned contract; this first comparison is evaluator-owned.

## Experimental evidence

Declare the attempt before execution, binding source, input, task manifest,
model/runtime artifacts, policy, arms, repetition count and calibration-only
selection. Archive source/input dependencies before queries. Run actual native
comparators, current graph/context, current PostgreSQL lexical, exact vector,
disposable HNSW and the fused candidate only where their capabilities apply.
Unsupported cells remain visible and cannot disappear through vacuous filters.
Predeclare arm applicability by task mode, comparability stratum and intended
match surface. Metadata-only vectors are not a captured-body comparator; keep
inapplicable body-stratum cells visible as unsupported/not comparable. Each
fixture generation needs its own receipt-bound rebuild and paired observations
before any later publication invalidates that rebuild.

The existing exact query deliberately materializes distances and cannot prove
HNSW use. Implement a separate evaluator-owned ordered cosine-distance/LIMIT
path with the same publication, profile, source and privacy fences. Freeze
ef_search and iterative-scan settings before queries. Retain actual EXPLAIN
proof of index scanning; if the planner chooses a sequential scan, record the
HNSW arm as not executed. Report filter-induced short results as truncation,
not absence. Any forced planner setting must be disclosed and cannot prove
acceleration at this small scale.

Use the existing approved public calibration task IDs without relabeling or
success-driven resampling. Keep all held-out tasks inaccessible to selection
and execution. Freeze one current baseline across arms, retaining old attempts
as immutable history rather than repinning them to new code. Resolve the
existing comparator-output and PostgreSQL absent-answer comparability issues
before accepting future scientific criteria.

Record relevance, recall, empty/absent-answer behavior, identity correctness,
output bytes, latency distribution, actual queries/rows/statements, preparation,
inference/import/index build cost, footprint and failed attempts. Report ANN
recall against exact cosine separately from task usefulness. No production
HNSW adoption, superiority, generalization or fixed savings follows from this
small public-fixture calibration. Derive file-level relevance from the unchanged
labels with a declared per-file maximum-gain projection, retaining node-level
metrics separately; this is a new calibration report, not a replacement of old
grading or accepted criteria. A future held-out protocol and acceptance
criteria remain an operator decision.

## Named JSONB workload protocol

Retain the existing named query: node-evidence expansion by publication and
canonical key. Freeze repository/publication/binding filters, selected keys,
expected evidence rows, and ordering. Compare the incumbent relational joins
with a disposable JSONB projection only if it can represent exactly the same
accepted row set. Identity, required relationships and constraints remain
relational. Never benchmark a less strict query as an equivalent replacement.

The predeclared facet is containment over the existing evidence metadata
binding_id and snapshot_id strings, with an explicitly declared optional
source_relative_path equality. It introduces no new semantic labels. Compare
no index, jsonb_ops and jsonb_path_ops using identical accepted rows and
provenance predicates; freeze each predicate before measurement. Save actual
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, planning/execution observations,
rows, buffers, storage, construction/update cost and failures. Use only
cardinalities and selectivity variation actually present in existing approved
public fixtures/publications. Do not generate a synthetic multiplier
or acquire a new corpus for this milestone. Report the tiny scale and any
missing ladder as explicit limitations. Use fixed warm/cold descriptions and
repetitions; report variance and limits without inventing storage hardware or
production-scale claims.

The disposition may retain relational joins and no additional JSONB machinery.
No production index or schema change follows from a faster disposable query.
Any adoption requires a separately reviewed workload-specific decision.

## Proposed proof owners and milestone exit

Create exact unit owners for input/artifact validation, representation digests,
generator lifecycle, fusion identity/order/absence and report accounting.
Create canonical containerized integration owners for actual PostgreSQL
publication/privilege boundaries, semantic/fusion retrieval and JSONB equality/
plans. Select the existing optional pgvector profile only for its exact owners;
keep ordinary core tests independent. Bind real learned artifact/component
receipts to the integration inputs without relabeling synthetic vectors.

The isolated generator component proof must use the actual approved model and
closure, native CPU execution, network isolation and terminal cleanup. Unit
replacements and precomputed fixture values cannot substitute for it. Ordinary
source tests remain scoped with `--no-coverage`. Keep clean retained-Python
admission, zero cycles, privacy, file-length and every debt ceiling.

Publish once after the connected milestone, fresh scoped proof, independent
review, exact-commit report and a fresh native build/campaign binding. The
current 23rd AMD start is spent; this design grants no 24th start or workflow
change. Core CI qualification and optional-capability evidence stay distinct.
An unmet production/quality gate must remain explicit; neither a green core
run nor this design closes W5's full release requirement.


## Current implementation admission

The operator selected exact BGE/ONNX route A. The inspected ARM artifact bank
contains the full twenty-wheel closure and pinned model/config files. Native
target and document-only maintained-kernel execution passed offline in the
unchanged SDK. These receipts do not establish calibration usefulness, actual
PostgreSQL/HNSW execution or public qualification.

The maintained protocol separates current-store public input admission,
byte-only artifact verification, fixed CPU execution and whole-journal response
validation. Every selected output must match request, source, publication,
representation, artifact and controller-admission identities. Failed, missing,
extra, malformed or truncated output cannot become a complete import. Preserve
scope exclusions and unsupported/refused tasks independently of generation
completion. Use fixed sequential one-record inference microbatches within the
existing memory bound; do not allocate one 500-record transformer batch.

ADR0077's existing disposable pgvector0.8.7 test-profile authority is separate
from Route A's exact isolated model/runtime closure. It admits no application,
SDK, dependency/lockfile, runner or production change. The retained paired
calibration is described in the public operational exit; generation2 has only
document inference and explicit unsupported query cells. The fresh CI107/AMD24
allocation is separately bound by ADR0138 and remains conditional on final
proof and independent review. Full W5 and hosted qualification remain open.

## Bounded milestone result

The [operational exit](../../tools/ci/cloe-semantic1-exit.md) records actual
two-generation public calibration and the named equality-first JSONB workload.
Baseline file grading and hybrid fusion use the same strict publication scope
and run-alias validation. Unresolved baseline provenance remains a measured
coverage gap; span grading alone does not establish file-level comparability.
Shared campaign cleanup belongs only to the last retained generation.
The JSONB disposition retains relational joins at the observed tiny-fixture
scale. No production index/schema or quality-superiority decision follows.
ADR0138 separately bounds one successor staging campaign; this specification
does not itself grant a build or workflow change.
