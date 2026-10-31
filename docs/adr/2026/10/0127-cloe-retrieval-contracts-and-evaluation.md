# ADR 0127: CLOE retrieval contracts and evaluation baseline

## Status and authority

Accepted by the parent under the operator's approved W2 roadmap scope, after
independent design and planning review and parent disposition of the clean
ownership-admission conflict. The earlier implementation dispatch continued
past a blocking checkpoint; its output is retained partial work and is not an
acceptance result. A fresh reviewed continuation owns resulting-state proof.
Phase exit remains NOT ACCEPTED pending exact successor hosted qualification.

Phase: REPOMAP-CLOE-RETRIEVAL1. Date: 2026-10-30.

The operator requests continuing the accepted CLOE roadmap after CI100 passed.
This instantiates W2: query/corpus/privacy contracts and an executable evaluation
baseline before tuning. It adds no dependency, database migration or public
CLI/MCP surface. The three units below belong to this one canonical phase.

CI100 attempt1 qualifies staging 970d7dc9f6b895a210953e38bccb54cc839ccf75,
merge ac9e1857d6b44ba4dca2723ea2746ebfdd1e039f. All nine jobs and retained
same-attempt staging/system contracts pass. Unit coverage is88.1/87.7 and measured
integration90.1/82.2. Seventeen actual native AMD application starts remain spent.
No successor qualification or new build allocation follows from that result.

## Decision

Deliver three connected units under the
[W2 specification](../../../specs/cloe-retrieval-evaluation-v1.md):

1. Internal query-mode envelopes and a bounded captured-input projection reference.
   Preserve the six roadmap intentions, existing literal behavior, source-blind
   MCP and current backend capability differences. Direct locator handoff is an
   auxiliary workflow, not a seventh query mode.
2. A public-safe mixed corpus and frozen36-task instrument, with24 calibration
   and12 held-out tasks, adapter-independent gold locators and explicit exposure.
3. Real native-tool and current-graph baseline adapters, the in-memory projection
   reference, grading, accounting and a reproducible developer harness. Run only
   calibration in W2; choose and freeze numeric criteria from observed results
   before later tuning or held-out execution.

Use maintained capture, artifact validation, publication and read-store seams.
Graph observations contain selected structural metadata, not complete file bodies.
Portable stores can contain raw bytes, including email and metadata-only material;
possession of those bytes is not permission to project or disclose them.

PublicationBundle explicitly represents candidate material. A receipt or digest
alone does not establish database acceptance. The pure reference checks input
correspondence against a mandatory trusted-caller marker; the benchmark obtains
that marker from the real accepted store. It does not establish a production
query-pinning or generation-retention capability. W3 must integrate those.

Keep artifact PrivacyClassification and graph/binding policy labels separate.
Do not invent a total ordering among private policy categories or infer body
authorization from public-dev or inherit. The W2 reference admits only explicitly
authorized public fixture code/prose. It refuses unresolved/private scopes,
metadata-only/ephemeral retention, email bodies and feed bodies before reading
their blob contents. This bounds an experimental reference; it changes no
existing production capture, ingestion or search policy. Metadata remains usable.
Private/format-specific body support and indexed-text exposure remain W3 design
obligations. No weaker replacement for existing feed redaction is introduced.

SQLite Local remains complete and useful without PostgreSQL or enrichment.
W3 owns PostgreSQL native FTS. This decision adds no SQLite FTS5 or SQLite
body-search release prerequisite; that experiment remains separately justified.
W4 owns intent-aware context; W5 owns optional vectors/fusion and JSONB disposition.

## Alternatives

- Metadata-only search mislabeled as body search: rejected because it misses
  uncaptured prose and changes information-exposure claims.
- Live workspace reads inside existing read stores: rejected because mutable
  bytes cannot be attributed to an earlier accepted publication.
- Database indexing before the baseline: deferred to W3 to keep this instrument
  useful before search tuning.
- A Python scanner described as equivalent to native search: rejected as the
  competent-tool comparison. Such a scanner may be an explicitly named reference.

## Evidence, ownership and boundaries

Keep only reusable contracts/projection in common_lore_index.retrieval; evaluation
code belongs to tools and test support. New Python owners are cleanly admitted
under existing quality policy. Preserve every old historical authority and
numerical debt/tool ceiling. Permit one guarded baseline transition only for
new common_lore_index.retrieval modules: update the ownership digest and append
clean retained/T1-future selection rows. Every old ownership and selection row,
Ruff/mypy finding, migration-import edge, file-length ceiling, analyzer version,
rule and schema remains identical. New files stay within400 lines with no new
length allowance. Bind the transition to this ADR and the phase exit in one
append-only scope record. Candidate generation is not enforcement; the complete
retained static check must pass afterward. No baseline genesis/reset or unrelated
debt absorption is permitted.
Use one public exit tools/ci/cloe-retrieval1-exit.md, following the existing public
milestone surface; do not copy or modify protected private status history.

Require scoped unit and real containerized integration owners, --no-coverage,
actual native command execution, actual SQLite/PostgreSQL publication/readback,
privacy canaries, drift/refusal tests, complete retained static enforcement and
independent resulting-state review. Complete local suites and Python project
coverage remain unselected. Each new Python file targets350 lines and stays
within400; applicable repository profiles remain authoritative.

No live home/service/client mutation, external acquisition, new dependency,
application/SDK image build, package publication, repository rename, main
promotion, tag or remote trigger is granted by this design. The parent owns
commits, exact-commit reports and eventual separately bound staging publication.
Rollback removes the new reference/harness and its clean admission records;
there is no database or user-data migration to undo.

## Admission and observation clarification

Retained calibration uses a persistent experiment directory. Atomically create
one attempt directory per identifier; a previous start, including a failed start,
refuses reuse within that experiment. Persist the declaration and matching source
bytes before queries. Verify the actual runtime profile, frozen inputs and full
execution-source closure before admission. A different output filename must not
permit replay of the same attempt. Writes of declarations and final reports are
exclusive. Ordinary integration runs identify themselves as functional checks,
write only to temporary experiment directories and cannot qualify retained data.

Journal every repetition, including failures and observed costs. Preserve partial
observations on cancellation or exceptions. Divergent repetitions make the task
and retained attempt fail; a successful last repetition cannot erase earlier
failures. Unknown costs remain null. Proposed criteria use retained observations
from the matching declaration, with no fixed quality assertions in routine tests.

Paging retains only the requested result page while counting skipped matches.
Large offsets do not authorize retaining all preceding hits. Traverse files in
the declared canonical order before selecting the page. This implements the
existing bounded-reference contract without adding an indexed search backend.

Wire parsing preserves input types through validation. It must not coerce a
string into caller consent/completeness, a boolean or fraction into a rank,
or a number into a source identity. Scores must be finite. A post-measurement
contract correction requires a new retained attempt with its own source closure.

Publisher validation is mandatory for every projection, including trusted-caller
inputs. Manifest, bundle and extraction-receipt references and owned spool storage
are required; missing material refuses instead of bypassing streaming validation.
Bind stored parsed identities and the validated descriptor to the supplied inputs.
Comparator exposure groups remain separate. Seed-heavy graph tasks do not justify
a general graph-quality floor, and setup body-byte counters do not claim total
validator/store I/O. Frozen task and gold bytes remain unchanged.
