# ADR 0050: Extractor Dependency And Capability Architecture

## Status

Accepted. Docs-only. This ADR decides architecture; it authorizes no
implementation, no dependency adoption, and no schema change.

## Date

2026-08-12

## Context

RepoMap extracts facts from polyglot repositories and stores them as raw
observations that a canonicalizer turns into graph claims. Today the extraction
tier carries **zero** parser, grammar, or resolver dependency. `pyproject.toml`
declares only `psycopg[binary]` and `typing-extensions` at runtime. Every
language family — shell, Bash, Bats, awk, zsh, zunit, PowerShell, Ruby,
JavaScript, CSS, HTML, Markdown, YAML, Nix — is extracted by RepoMap-owned
conservative scanners, with two exceptions: Python uses the standard-library
`ast` module, and Go uses a RepoMap-built helper executable that links only Go's
own standard library.

That position is honest but bounded. Regex-and-heuristic scanners cannot make
resolution-grade claims, cannot recover from partial syntax in a principled way,
and accumulate maintenance cost per dialect. The obvious response is to adopt
parser libraries. The obvious response is also dangerous: a parser that resolves
more can also read more, execute more, reach the network, fail unpredictably on
untrusted input, bind incompatible native artifacts, and — most corrosively —
allow the graph to appear more confident than the evidence supports.

RepoMap has already been bitten by the shape of this problem in a narrow form.
`docs/extraction/go-extraction-design.md` worked the runtime-resolution and
protocol questions carefully for exactly one language, and still concluded that
"the exact wheel/Nix/source-checkout publication mechanism is not accepted."
RepoMap therefore has a strong precedent for *how a helper behaves* and no
accepted precedent at all for *how a dependency is distributed*.

Three further facts frame this decision:

- `docs/contrib/dependency-standards.md` forbids introducing parser or runtime
  dependencies in static extraction phases without explicit phase allowance, and
  lists license, packaging, footprint, and transitive risk as review criteria.
  It grants no automatic admission to any dependency or license family.
- `docs/contrib/coding-standards.md` states without qualification that RepoMap
  extraction does not execute target repository code, scripts, profiles, tests,
  package managers, generated command strings, or repo-local tools.
- PERF-BASE1 (status 00721) produced no accepted extraction performance
  baseline. RepoMap therefore holds **no measured fact** about extraction
  throughput, parser cost, or install cost against which a dependency could be
  justified on performance grounds.

This ADR answers the general question rather than a product question. It must
remain useful if every library named in it is renamed, relicensed, abandoned, or
replaced.

## Problem Statement

How may RepoMap introduce parser, resolver, toolchain, or evaluation
dependencies while preserving deterministic and offline extraction, honest graph
claims, bounded installation cost, portability, security, and reproducible
capability semantics across languages?

### What would prove this ADR wrong

This ADR is wrong if any of the following is demonstrated:

- A conforming extraction run produces two different observation sets from
  identical repository bytes, identical profile, and identical declared
  dependency closure, without a recorded nonconformance.
- A canonical claim of a given kind is produced by a run that never achieved the
  capability that claim requires, and the pipeline accepted it.
- A capability declaration is accepted as an observation of what an extractor
  actually did, rather than as an expectation the acceptance boundary must test.
- The capability model orders two genuinely incomparable positions, or forces a
  language into a rank it does not occupy.
- The architecture is usable only for Python, or requires a single parser
  technology to be adopted uniformly across all languages.
- Removing every optional extractor dependency leaves RepoMap unable to run, or
  leaves the graph silently claiming what it can no longer support.

## Definitions

**Extractor dependency.** Any artifact outside RepoMap's own Python source that
participates in producing observations: a Python distribution, a compiled
grammar, a shared library, a RepoMap-built helper executable, or an
operator-supplied external toolchain. The Python standard library is a
dependency for the purpose of capability declaration and dialect scope, and is
exempt from the adoption gate in D7.

**Effect vector.** A tuple of five closed, independently valued dimensions
describing what an extractor invocation may do. Defined in D2.

**Provenance axis.** Where an extractor artifact came from. A separate axis, not
an effect, and never a substitute for one.

**Semantic capability.** A named element of the closed vocabulary in D4
describing what an extractor invocation can determine about source. Capabilities
form a set, never a ladder.

**Capability lifecycle state.** One of *installed*, *admitted*, *attempted*,
*exercised*, *achieved*, as defined in D5. These are distinct facts about
distinct subjects and may not be collapsed.

**Language-dialect.** A language together with the dialect and version scope an
extractor actually accepts — for example `bash`, `zsh`, `awk/posix`,
`python/cpython-3.12+`, not "shell" or "Python".

**Extraction attempt.** One invocation of one extractor against one selected
input at one pipeline stage. The unit of outcome accounting in D12.

**Extractor run receipt.** A run-scoped record with two disjoint parts: a
*declared* part carrying producer expectations, and an *observed* part carrying
facts a boundary witnessed. Defined in D10.

**Dependency-minimal profile.** The configuration in which no optional extractor
dependency is installed and no operator-supplied external toolchain is
available.

## Scope And Non-Scope

In scope: the capability model; the effect and provenance model; the extraction
admission boundary; dependency ownership shapes; the adoption gate; licensing
and supply-chain review obligations; determinism and input closure; the receipt
model and its binding to raw observation schema v1; pipeline stages and per-stage
capability rules; fallback semantics; canonical claim gating; process isolation;
cross-file resolution ownership; the plugin question; performance evidence
policy; migration; and per-language-dialect mappings.

Out of scope: adopting any dependency; selecting any parser for any language;
measuring anything; changing `pyproject.toml`, lockfiles, or any vendored
artifact; changing the raw observation schema or canonical storage; implementing
receipts, resolvers, or admission checks; defining a dynamic-analysis or
runtime-evidence workflow; and modifying ADR 0048 or ADR 0049.

This ADR does not define a target-code-execution workflow. It excludes one from
extraction and leaves the question of whether RepoMap should ever have such a
workflow entirely unaddressed.

## Evidence Hierarchy

ADR 0049 governs. This ADR adds no evidence authority and creates no exception
to it. Three of its rules are load-bearing here and are restated, not extended:

- An expectation may reject an observation but never becomes one (ADR 0049 D1).
  A capability declaration is an expectation.
- Semantic verification belongs at every acceptance boundary, per consumer and
  per claim, and a generic consumer that cannot dispatch a declared semantic
  class fails closed (ADR 0049 D2).
- Claim-scoped candidate identity is repository content, environment, and
  runner or profile together, with the dependency set frozen before execution
  (ADR 0049 D6).

This ADR deliberately rests on very few external facts, because ADR 0049 forbids
a durable claim from depending solely on a phase-private packet, and phase
XDEP0's research packet is not committed.

Exactly one class of external fact is load-bearing: that certain toolchains
separate parsing from evaluation at the level of a named package or command-line
mode. The specific artifacts relied on are the `syntax`, `shell`, and `interp`
package split in `mvdan.cc/sh`; the `go/parser` and `go/ast` split from
`go/types` and `go/packages` in the Go standard library; and the `--parse` mode
of `nix-instantiate` as distinct from `--eval`, `nix eval`, and `nix flake show`.
These were read from the projects' own published documentation on 2026-08-12,
they are checkable by any reader against those upstream sources, and each is used
only to show that the same tool can present different effect vectors in different
modes — the argument in D2.

No other external fact is used to justify a decision. Statements about library
maturity, design quality, portability, binding availability, and licensing are
**not** asserted here as verified conclusions; where XDEP0's survey formed a view
it is marked as a hypothesis or recorded as "no qualified candidate identified,"
per D16. All such facts must be re-verified from primary sources at adoption
time under D7 and D8 rather than carried forward from this document.

## Decision

### D1 — Capability is two orthogonal vectors, and neither is ordered

**[invariant]** An extractor invocation is described by an *effect vector* (D2)
and a *semantic capability set* (D4). These are independent: what an extractor
is permitted to do and what it can determine are different questions, and
neither determines the other.

**[invariant]** RepoMap declares **no total order** over effect vectors, and no
order at all over semantic capabilities. An ordinal "capability tier" or "safety
level" is rejected as a modelling primitive.

The reason is that ordinal ranks assert strict supersets that do not hold. An
in-process pure-Python parser reading the whole repository is not obviously
safer than a subprocess helper confined to one file. An operator-supplied
external toolchain is not obviously more privileged than a RepoMap-built helper.
Target-code evaluation and network reach are incomparable harms, not successive
degrees of one harm. Likewise a parser with error-tolerant recovery is not
thereby stronger than one with local symbol resolution; they answer different
questions.

A derived risk band or presentation ordering may exist for operator ergonomics.
It is a projection, never an authority, and no admission decision may be made
from it.

### D2 — The effect vector is a closed vocabulary of five dimensions

**[invariant]** Every extractor invocation has exactly one value in each
dimension. The vocabularies are closed; an unrecognized value is a
nonconformance, not a new state.

**[invariant]** The effect vector covers the whole process descendant tree of an
invocation, not the first process in it. When RepoMap invokes a helper that in
turn invokes an operator-supplied external tool, the effect vector describes what
the entire tree may do, and the RepoMap-owned invocation layer is responsible for
constraining it. A supervising process does not launder the effects of what it
launches.

**[invariant]** Explicit declaration is required of every invocation that uses a
dependency adopted under D7. Extractors whose vector is fixed by construction are
covered by the legacy baseline in D17 rather than by per-invocation declaration.

| Dimension | Values |
| --- | --- |
| `target_code_evaluated` | `none`, `evaluated` |
| `execution_boundary` | `pure-python`, `in-process-native`, `subprocess` |
| `filesystem_read_scope` | `selected-input`, `repository`, `beyond-repository` |
| `filesystem_write_scope` | `none`, `scratch`, `repository`, `beyond-repository` |
| `network` | `none`, `any` |

**[invariant]** The effect vector describes an *invocation mode*, not a tool. The
same dependency may present different effect vectors in different modes, and each
mode is admitted or refused separately. This is not a hypothetical refinement:
`mvdan.cc/sh` separates parsing, expansion, and interpretation into different
packages; Go separates `go/parser` from `go/types` and `go/packages`; and
`nix-instantiate --parse` parses while `nix eval`, `nix flake show`, and
`nix-instantiate --eval` evaluate and may fetch flake inputs over the network. A
model that classified safety at the level of "the tool" would be wrong about all
three.

**[invariant]** Provenance — `python-stdlib`, `python-distribution`,
`repomap-built-helper`, `operator-supplied-external` — is recorded on a separate
axis. Provenance never substitutes for an effect value, and a trusted provenance
never relaxes an effect requirement.

### D3 — The extraction admission boundary is fixed and not operator-tunable

**[invariant]** An invocation is admissible for extraction only if:

- `target_code_evaluated` is `none`;
- `network` is `none`;
- `filesystem_write_scope` is `none` or `scratch`; and
- `filesystem_read_scope` is `selected-input` or `repository`.

**[invariant]** These are not defaults. There is no profile setting, flag,
environment variable, or operator opt-in that admits target-code evaluation or
network access into extraction. `docs/contrib/coding-standards.md` states the
non-execution boundary without qualification, and this ADR declines to weaken it
by introducing an opt-in that would make non-default indexing a lawful exception.

**[invariant]** An extractor that can only produce a given capability by
evaluating target code cannot produce that capability in RepoMap. The correct
outcome is a recorded unsupported result, not a quiet evaluation.

Consequence for Nix, stated plainly because the current spec says otherwise:
`nix flake show` and `nix eval` are inadmissible for extraction at every
setting. `nix-instantiate --parse` is admissible in principle, subject to D7.

### D4 — Semantic capabilities are a closed, versioned, unordered vocabulary

**[invariant]** Capability vocabulary version 1:

| Capability | Meaning |
| --- | --- |
| `file.classification` | The input's language-dialect and role were determined |
| `lexical.structure` | Tokens, comments, strings, and line ranges were recovered |
| `syntax.tree` | A complete syntax tree conforming to the dialect grammar was produced |
| `syntax.error_tolerant` | A partial tree with located errors was produced from non-conforming input |
| `resolution.include_local` | Include/import targets were resolved to repository-local paths |
| `resolution.symbol_local` | Symbol references were resolved to repository-local declarations |
| `resolution.type` | Static types of expressions were determined |
| `metadata.package` | Package, module, or workspace metadata was read from project files |
| `build.condition` | Build constraints or conditional compilation were interpreted |

**[invariant]** Every capability names a *source semantic result*, never a
mechanism. "An external toolchain assisted" is not a capability, because it says
how the work was done rather than what was determined about the source; that
fact belongs to the provenance axis and the invocation record. Two extractors
that achieve `resolution.type` have achieved the same thing regardless of what
helped them.

**[invariant]** No capability implies any other. `syntax.error_tolerant` does not
imply `syntax.tree`; a recovered partial tree is not a conforming one.
`resolution.symbol_local` does not imply `resolution.type`. Each capability is
declared and achieved independently.

**[invariant]** The vocabulary is versioned. Adding, removing, or redefining a
capability is a vocabulary version change and requires an ADR. Consumers that
encounter an unrecognized capability name fail closed for the affected claims
(ADR 0049 D2).

**[invariant]** A capability is meaningless without scope. Every declaration
binds the capability to a language-dialect. "Supports Python" is not a
declaration.

**[invariant]** Where the accepted grammar is defined by a runtime rather than by
a specification the extractor implements, the declaration binds to that exact
runtime identity — implementation and version of the interpreter or toolchain in
the running process — and not to a version range. An open-ended range such as
"3.12 or later" would assert acceptance of grammars that do not yet exist. What
the runtime actually accepted for a given input is an *achieved* fact per D5,
reported per attempt, not derived from the declared range.

### D5 — Five capability lifecycle states, never collapsed

**[invariant]** These are distinct facts and must not be conflated:

| State | Subject | Meaning |
| --- | --- | --- |
| *installed* | environment | The artifact is present and loadable |
| *admitted* | run | The invocation mode passed D3 and the run may use it |
| *attempted* | attempt | The extractor was invoked against this input |
| *exercised* | attempt | The capability's code path actually ran |
| *achieved* | attempt | The capability produced a usable result for this input |

**[invariant]** *Achieved* is an attempt-scoped fact. A run-scoped capability set
is an **upper bound only** and may never be read as a per-observation claim.

This closes a real hazard: a run that parses two hundred files successfully and
falls back on eight would, under a run-wide capability set, attach an apparently
strong capability to all two hundred and eight. Capability that gates a claim is
always the *achieved* capability of the attempt that produced it.

### D6 — Ownership shapes are enumerated, and the dependency-minimal profile is guaranteed

**[invariant]** Admissible ownership shapes:

1. Python standard library.
2. Core Python runtime dependency (`project.dependencies`).
3. Optional Python extra, per language family (`project.optional-dependencies`).
4. RepoMap-built helper executable, installed beside the distribution.
5. Operator-supplied external toolchain, resolved by explicit absolute path.
6. Vendored source or grammar committed to the repository.

**[invariant]** Shape 2 is refused for any language-specific parser or resolver.
A parser that only some users need does not belong in the core dependency set.

**[invariant]** Shape 5 never searches ambient `PATH`, and shape 4 never runs a
build tool at extraction time or ships a committed binary. These are not new
rules; `docs/extraction/go-extraction-design.md` already rejects `go run` at
extraction time, ambient `PATH` search, and committed binaries. This ADR
generalizes them from Go to every dependency.

**[invariant]** **Dependency-minimal profile guarantee.** RepoMap remains fully
installable, runnable, and useful with zero optional extractor dependencies and
zero external toolchains present. This holds today by construction, because no
extractor requires an optional dependency and the one helper-backed extractor
fails with a bounded diagnostic rather than degrading the run.

**[invariant]** The second half of the guarantee — that a degraded run records
the reduced capability rather than silently retaining claims it can no longer
support — is **not realizable today**, because no receipt binding exists (D10)
and D13 gating is unimplemented. It is therefore an adoption precondition, not a
present property: the first optional extractor dependency may not be adopted
until a degraded run can record its reduced capability. Stating it as a current
guarantee would be exactly the declaration-as-observation error this ADR forbids.

**[invariant]** "Useful" in the minimal profile means the graph is still built
from every language RepoMap extracts today, at the capability those extractors
have today. It does not mean capability-equivalent to a dependency-backed run.

**[invariant]** RepoMap never downloads, installs, builds, or fetches an
extractor dependency during indexing. Dependency acquisition belongs to
installation, is performed by the operator or the packaging process, and is
frozen before a run begins (ADR 0049 D6).

### D7 — Every non-stdlib extractor dependency passes an adoption gate, and the incumbent wins ties

**[invariant]** Adoption of any dependency under D6 shapes **2 through 6**
requires a durable adoption record. The gate is not escaped by proposing a
dependency as core rather than optional, nor by arguing that a dependency is not
language-specific. Only the Python standard library is exempt.

The record contains:

1. the incumbent baseline — what RepoMap-owned code achieves today, honestly
   stated;
2. the specific capability benefit, expressed as capabilities from D4 bound to
   language-dialects;
3. the effect vector and invocation mode to be admitted under D3;
4. alternatives considered, including remaining dependency-free;
5. licensing and supply-chain review per D8;
6. installation and runtime footprint: artifact size, build requirement,
   toolchain requirement, transitive closure, and the supported platform matrix
   including the platforms where the artifact is *not* available;
7. artifact provenance binding — source repository, release identity, and hash;
8. qualification evidence per ADR 0049, including the predeclared window;
9. the fallback path and the deterministic rollback to the dependency-minimal
   profile.

**[invariant]** **Enforcement precedes admission.** A declared effect vector is
not sufficient to admit a dependency. Admission under D3 requires that the
invocation's compliance be either mechanically enforced by the environment the
run constructs, or witnessed by the acceptance boundary. Where neither is
available for a given dimension, the dependency is not admitted — the correct
outcome is refusal, not adoption with an unverified declaration.

This is the ADR's tightest coupling and the easiest one to lose: D3 fixes a
boundary, D9 concedes that RepoMap cannot yet enforce every dimension, and D10
concedes that some execution facts cannot yet be witnessed. Without this rule
those three would compose into a boundary that binds nothing, because any
dependency could be admitted on its own say-so. Building the enforcement
mechanism is therefore a prerequisite to the first adoption, not a parallel
improvement.

**[invariant]** **Default disposition.** If the adoption record is incomplete, or
the evidence does not establish the claimed capability benefit, the incumbent
dependency-free implementation wins. Insufficient evidence is a refusal, not a
deferral to judgment. This is what makes per-language ownership a decision
rather than an open-ended framework.

**[invariant]** The decision owner is the accepted phase that proposes the
adoption; the acceptance boundary is a RepoMap ADR. No dependency is adopted by
landing code that imports it.

### D8 — Licensing is reviewed, never presumed from family

**[invariant]** No license family is automatically admissible. RepoMap is
AGPL-3.0-or-later; that makes inbound compatibility a real question and outbound
distribution obligations a real cost.

**[invariant]** Every proposed extractor dependency requires a documented
compatibility review covering: the primary license text as published by the
project, not a summary or registry classifier field; notice and attribution
obligations; the provenance and license of any bundled or generated grammar,
which is frequently distinct from the tool's own license; the linking or
combination form; the license of the transitive closure; and the effect on
RepoMap's distributed artifacts.

**[invariant]** Copyleft, dual-licensed, unclear, absent, and
custom-license dependencies require additional review. The absence of that
category does not imply permissive dependencies are pre-approved; every
dependency is reviewed.

**[invariant]** Where primary license text was not read, the adoption record says
so. An unverified license position is recorded as uncertainty, never as a
conclusion. This ADR asserts no legal conclusion about any specific library.

### D9 — Determinism requires a closed input identity and an enforced environment

**[invariant]** Extraction is deterministic when the closed input identity is
fixed. That identity extends ADR 0049 D6's three components with the
extraction-specific closure:

- selected file bytes **and** every companion file the run may read, including
  project metadata such as `pyproject.toml`, `go.mod`, and manifest files;
- the file inventory and its selection profile, since inventory membership
  changes index construction;
- profile and option values;
- RepoMap extractor code version;
- the dependency closure — not merely a top-level version string, but the
  loaded artifact and its shared-library and grammar closure;
- platform, architecture, and libc family;
- locale and character-encoding settings;
- working directory and any path input that reaches an extractor;
- resource bounds, since a timeout that fires changes the output;
- and the deterministic processing and emission order.

**[invariant]** An absolute path plus a version string does not identify an
executable's shared libraries and does not constrain its behavior. Offline and
non-mutating behavior are enforced by the process environment the run
constructs, not by a flag the extractor sets and not by a declaration in a
receipt. Where RepoMap cannot yet enforce, it says so and treats the claim as
unverified rather than proven.

**[invariant]** Where the closure cannot be established, the conservative
whole-candidate default of ADR 0049 D6 applies.

### D10 — The receipt separates declaration from observation, and binds to schema v1 through metadata

**[invariant]** An extractor run receipt has two disjoint parts.

*Declared* (expectations, produced by the extractor or its adapter): requested
and admitted capability set with dialect scope; the intended invocation mode and
effect vector; profile and options; declared dependency identity.

*Observed* (facts a boundary witnessed): the artifact identity actually loaded or
executed; the invocation mode actually used; per-attempt outcomes and achieved
capability; resource-bound events; exit status; and the acceptance boundary's
verification result.

**[invariant]** The declared part is never promoted to the observed part. A
receipt is not authoritative for what an extractor did merely because the
extractor said so (ADR 0049 D1).

**[invariant]** Each receipt names its producer and the consumer boundary that
verified it. A consumer that cannot verify a receipt it requires fails closed for
the claims that depend on it.

**[invariant]** **Schema binding.** Raw observation schema v1 has no receipt
reference field, and `RawObservation.from_dict` silently discards unknown
top-level keys. A receipt reference is therefore carried inside extractor-owned
`metadata` under a versioned key, or not at all. Promoting it to a top-level
field is a schema version change owned by a future phase.

**[invariant]** Until that binding lands in an accepted phase, **no
receipt-linked observation contract exists.** Nothing in this ADR may be read as
establishing one, and no consumer may assume a receipt reference is present.

**[invariant]** Receipts are run-scoped, not observation-scoped. Repeating full
dependency, platform, and capability metadata on every observation is refused;
the reference is the observation-side cost.

**[invariant]** Observed execution facts that RepoMap cannot currently witness —
that no network syscall occurred, that no prohibited API was called — are
declared unverified. This ADR states the requirement; the enforcement mechanism
is deferred.

### D11 — Five graph-construction stages, with capability rules per stage

**[invariant]** Graph construction has five stages. *Extraction* is S1 through
S4 and produces raw observations; canonicalization is S5 and is a separate
consumer, as the extractor strategy and the raw observation contract already
describe. The admission boundary in D3 governs S1 through S4.

| Stage | Name | Reads | Produces |
| --- | --- | --- | --- |
| S1 | Inventory and classification | Repository tree, profile | File inventory, language-dialect assignment |
| S2 | Index preparation | Inventory, project metadata files | Cross-file indexes |
| S3 | Per-file extraction | One selected file | Raw observations |
| S4 | Raw post-passes | Raw observations, inventory | Raw observations |
| S5 | Canonicalization | Raw observations | Canonical nodes, edges, evidence |

This is the pipeline as it exists. `PythonModuleIndex` and the Markdown anchor
index are built from the path inventory before any per-file parsing, and the
package-root logic reads `pyproject.toml` — so S2 is a real stage that consumes
repository configuration bytes and is not derived from parse evidence. The
Go repository-context pass and the CSS/HTML selector matcher both consume raw
observations and emit raw observations after the per-file loop — so S4 is a real
stage and is not canonicalization.

**[invariant]** S4 does not **inherit** capability from its inputs, and it does
not **confer** capability on them. A post-pass is its own attempt with its own
declared effect vector, its own verifier, and its own achieved-capability record.

**[invariant]** A post-pass **may** achieve a capability its inputs did not have.
This is not a loophole; it is how cross-file resolution legitimately works. A
correlation over per-file observations, none of which resolved anything, can
establish `resolution.include_local` from the combination — RepoMap already does
this by matching import observations against a separately built module index.
What is forbidden is the reverse move: attributing the post-pass's achieved
capability back to the per-file observations it consumed, or letting a
correlation assert a capability its own algorithm does not support.

**[invariant]** S2 and S4 own cross-file resolution. A per-file extractor at S3
never claims a cross-file resolution capability. S5 owns canonical identity and
never introduces new evidence.

**[invariant]** Ambiguity is preserved, not resolved by convenience. Duplicate
symbols, ambiguous imports, multiple workspace roots, generated files, and
build-variant alternatives are recorded as bounded ambiguity. Picking one
arbitrarily is a false claim, not a resolution.

### D12 — Attempts are transactional, fallback is declared, and outcomes are bounded

**[invariant]** An extraction attempt is transactional per input per stage. A
failed attempt's partial observations are either discarded, or retained under a
distinct failed-or-partial marker that S5 may never merge into a stronger claim.
Partial output from a failed strong parser is never silently unioned with output
from a successful weak parser.

**[invariant]** Fallback order is declared in advance and is deterministic.
Fallback is permitted only for these declared failure classes:

1. the dependency is unavailable in this environment;
2. the language-dialect is not accepted by this extractor;
3. the input exceeds a declared resource bound;
4. the artifact or invocation mode is inadmissible under D3; and
5. **bounded parse failure** — the parser ran correctly and rejected the input as
   non-conforming to its grammar.

Class 5 is the ordinary case and must not be conflated with class 2. A strict
parser meeting a syntax error in one file is not evidence that the dialect is
unsupported; it is evidence about that file. Falling back to a conservative
scanner for that input is correct, and the recorded outcome names the file, not
the dialect.

**[invariant]** An internal crash of an admitted dependency on conforming input
is a defect and is recorded as one. It is not a fallback trigger, because
treating crashes as routine hides the defect. The distinction from class 5 is
whether the parser reached a decision: a rejection is a result, a crash is not.

**[invariant]** A fallback reduces capability only when the resulting output
records the capability actually achieved and no existing observation or edge is
reinterpreted as stronger evidence. This is the rule the phase set out to
falsify; it survives, with the correction that "records the capability" means
*achieved* capability per D5, not a run-wide set.

**[invariant]** **Outcome cardinality.** At most one terminal outcome is recorded
per (selected input, extractor, stage). Diagnostics are bounded in length and
count and are redacted before emission. Repetitive repository-wide conditions —
notably "dependency not installed" — are recorded once as a run-level fact, not
once per file.

**[invariant]** Error-tolerant parsing declares completeness: whether the tree is
complete, partial, or truncated, and where recovery occurred. An error-tolerant
result without that declaration is not usable for claim gating.

### D13 — Canonical claims are gated on achieved capability, and the gate fails closed

**[invariant]** The canonicalizer owns an explicit mapping from each canonical
claim kind and edge kind to the minimum *achieved* capability set that permits
it. A claim whose kind is not in the mapping is refused, not admitted by default.

**[invariant]** Confidence and capability are different axes and neither implies
the other. `confidence=extracted` asserts that a fact was read from source rather
than guessed. It asserts nothing about resolution, and specifically does not
imply `resolution.symbol_local` or `resolution.type`. An extractor may be highly
confident about a low-capability fact, and a high-capability extractor may still
emit `heuristic` facts.

**[invariant]** Raising an extractor's capability never retroactively
strengthens claims made by earlier runs at lower capability.

Two current-state notes, recorded because they bound what this decision can
assume. First, the raw schema has no capability field at all; capability is
currently unrepresented rather than misrepresented, and this ADR does not assert
that existing code conflates the two. Second, `docs/contrib/coding-standards.md`
names six confidence values including `dynamic` and `unsupported`, while
`VALID_CONFIDENCES` admits only four; those two values would raise a validation
error today. That divergence is recorded here and left to its owner.

### D14 — Out-of-process is the default, and in-process native code requires a recorded variance

**[default]** An extractor whose `execution_boundary` is `in-process-native` or
`subprocess` runs out of process under a RepoMap-owned invocation boundary, with
bounded input size, wall-clock timeout, memory bound, and a bounded diagnostic
channel. That boundary is a RepoMap-built helper when RepoMap owns the
executable, and a RepoMap-owned supervising layer when the executable is an
operator-supplied external tool. In both cases the bounds apply to the whole
descendant process tree, per D2.

**[invariant]** A pure-Python extractor, including one built on the standard
library `ast` module, is not required to run out of process. The reason is not
cost: it is that out-of-process isolation exists to contain native memory-unsafe
failure, and a pure-Python extractor has no such failure mode. A Python
exception is already a bounded, catchable per-file outcome under D12, and
unbounded allocation is addressed by input bounds rather than by process
separation. Symmetry with native extractors is not a safety argument.

Any claim that subprocess isolation is *expensive* for the stdlib parser is an
`[unmeasured assumption]` under D16 and is not relied on here.

**[invariant]** Running native code in process is a **variance**, not a
case-by-case judgment. It requires a recorded decision naming: the crash and
memory-safety evidence relied on; the input size and structure bounds enforced
before the call; the supported platform matrix; the behavior when the artifact is
missing or ABI-incompatible; and the deterministic rollback. Without that record,
the default binds.

Rationale: a segmentation fault or unbounded allocation inside an in-process
native parser takes down the whole indexing run and loses every observation
already produced. Out of process, it is a bounded per-file failure under D12.

### D15 — No public third-party extractor plugin API

**[invariant]** XDEP0 does not introduce a public plugin API for third-party
extractors. Dependencies varying per language is not a reason to build a plugin
system; it is a reason to have a registry.

The blocking reason is capability honesty. Every rule in this ADR depends on an
acceptance boundary that can test a producer's declaration and refuse it. RepoMap
cannot verify an arbitrary third-party producer's effect vector, cannot subject
it to D7 or D8, and cannot bound its behavior under D3. A plugin API would make
the graph's honesty a function of code RepoMap never reviewed.

**[invariant]** Internal restructuring of the hardcoded per-language dispatch
into a RepoMap-owned registry with declared capabilities is the admissible
direction, subject to a future accepted phase. A registry whose entries are all
RepoMap-owned is not a plugin API. This ADR authorizes no such work; it only
records that the plugin prohibition is not an argument against the registry.

Revisiting requires a verifiable declaration mechanism, an ownership model for
third-party capability claims, and a fail-closed default for unverified
producers.

### D16 — Performance evidence is labelled, and unmeasured claims cannot justify adoption

**[invariant]** Every performance statement in RepoMap architecture documents
carries one of four labels: `[architecture decision]`, `[measured fact]`,
`[pilot hypothesis]`, `[unmeasured assumption]`.

**[invariant]** No dependency is adopted on the basis of a `[pilot hypothesis]`
or `[unmeasured assumption]` about performance. Performance benefit is
`[measured fact]` or it is not a reason.

**[invariant]** As of 2026-08-12 RepoMap holds **no** `[measured fact]` about
extraction performance. PERF-BASE1 produced no accepted baseline. Any adoption
record claiming a performance benefit must first establish one.

**[invariant]** Speed is not quality. A parser that produces more claims faster,
at a higher false-positive rate, is worse for RepoMap than a slower parser with
honest bounds, because the graph's value is its trustworthiness. Accuracy
evidence is required independently of throughput evidence.

**[invariant]** Maturity, design quality, and portability judgments about
candidate libraries are subject to the same discipline. Version numbers,
packaging shape, and release cadence do not establish maturity. Where XDEP0's
survey found insufficient evidence, this ADR records "no qualified candidate
identified" rather than a ranking.

### D17 — Migration is additive, and absence of declaration is not a strong claim

**[invariant]** **Legacy baseline v1.** Every extractor present at the time this
ADR is accepted belongs to a single named, versioned baseline rather than to an
open-ended exception. The baseline is not an absence of an effect vector; it is a
vector known by construction, because these extractors are RepoMap-owned code
that evaluates no target code, opens no socket, writes nothing, and reads only
the selected input and repository-scoped companion files. The one helper-backed
extractor runs as a subprocess with an absolute-path resolver. Nothing in the
baseline was inferred from a declaration.

**[invariant]** The baseline is closed. Its membership is fixed at acceptance;
a new extractor does not join it, and a baseline extractor that adopts a
dependency leaves it and declares per D2. Naming the set is a prerequisite to
implementing D13.

**[invariant]** Baseline extractors keep exactly the claim kinds they produce
today and no stronger ones. Their semantic capability sets are undeclared, and an
undeclared capability set never reads as full capability. Capability declaration
is additive and may be adopted per extractor.

**[invariant]** No existing graph claim is strengthened by this ADR. No automatic
schema, storage, or data migration is authorized. Rollback is removing the
optional dependency, which returns the extractor to its declared
dependency-minimal path deterministically.

### D18 — Language-dialect mappings are per dialect, and unsupported is a valid answer

**[language-specific decision]** Mappings bind to language-dialects, not
families. Grouping `bash`, `zsh`, `bats`, `awk`, and `zunit` under "shell" hides
the fact that they need different answers; RepoMap's own extraction designs
already treat them separately.

The table below records the current position and the admissible direction. It
selects nothing; every entry marked as a candidate is subject to D7, and the
incumbent wins until an adoption record succeeds.

| Language-dialect | Current | Effect vector today | Admissible direction |
| --- | --- | --- | --- |
| `python`, bound to the running interpreter identity | stdlib `ast` | pure-python, selected-input | Incumbent adequate for `syntax.tree`. The accepted grammar is whatever the running CPython accepts — not a version range, and not a promise about future grammars. Per-input acceptance is an achieved fact, not a declared one. No qualified error-tolerant option identified. |
| `go` | RepoMap-built helper, Go stdlib only | subprocess, selected-input | Incumbent adequate. `resolution.type` would require `go/types`/`go/packages`, whose effect vector must be re-examined against D3 before any proposal. |
| `bash` | RepoMap scanner | pure-python | Parse-only modes of a shell-grammar library are the candidate direction. `mvdan.cc/sh` splits parse from expand from interpret, so only its parse mode could be admissible; it is a Go module, so shape 4 packaging would apply. Not selected. |
| `zsh` | RepoMap scanner | pure-python | **No qualified candidate identified.** zsh grammar coverage was not established by XDEP0's survey. |
| `awk/posix` | RepoMap scanner | pure-python | **No qualified candidate identified** among the shell-family candidates surveyed; awk is a separate grammar, not a bash dialect. |
| `bats`, `zunit` | RepoMap scanners | pure-python | Test-framework semantics layered over a host dialect. Any host-dialect parser adoption must state whether framework constructs survive it. |
| `powershell` | RepoMap scanner | pure-python | A static AST API exists in the PowerShell automation engine, which is an operator-supplied external runtime under shape 5. Effect vector of loading that engine is not established. Not selected. |
| `ruby` | RepoMap scanner | pure-python | Candidate parsers exist. XDEP0 identified no Python binding for any of them, so shape 4 or 6 packaging would apply and the packaging cost is the dominant question. Not selected; all maturity, error-tolerance, and dependency-footprint characterizations are `[pilot hypothesis]` pending primary-source review under D7 and D8. |
| `nix` | RepoMap scanner | pure-python | Only a pure static parse mode is admissible under D3. Evaluation modes are excluded at every setting. Tree-sitter grammar maturity was not established. |

**[future pilot requirement]** Any pilot must report, per language-dialect: the
capabilities actually achieved on a public-safe corpus; the false-positive rate
against a hand-checked sample; the effect vector observed, not declared; the
platform matrix including failures; and the dependency-minimal fallback
behavior.

## Alternatives Considered

### Rejected

**Remain dependency-free indefinitely.** Rejected as a permanent position,
accepted as the default under D7. The honest cost is maintenance effort and
limited dialect and error-recovery coverage — not a permanent inability to make
resolution-grade claims. RepoMap's own `PythonModuleIndex` already performs
bounded repository-local resolution with no third-party dependency, and
RepoMap-owned code can improve without adopting anything. This alternative is
understated by anyone who claims dependency-free means claim-free.

**Standardize on a single parser technology across all languages.** Rejected.
Grammar maturity, provenance, licensing, and freshness differ sharply per
language even within one ecosystem, and grammars pin incompatible core version
ranges against a moving core. A uniform answer would import the weakest grammar's
quality as RepoMap's floor.

**Prefer native or standard-library parsers wherever one exists.** Rejected as a
rule, retained as a preference inside D7. It is right for Python and Go and
silent for zsh, awk, and Nix, where no such parser is reachable from Python.

**Move all stronger analysis out of process, uniformly.** Rejected by D14.
Symmetry is not a safety argument; it would impose real cost on the stdlib `ast`
path for no benefit.

**Fixed ordinal capability tiers.** Rejected by D1. Ordinal ranks assert strict
supersets that do not hold across incomparable languages and incomparable harms.

**A public third-party extractor plugin architecture.** Rejected by D15.
Capability honesty requires a verifiable acceptance boundary that a third-party
producer cannot currently pass.

**Operator opt-in for evaluation-based extraction.** Rejected by D3. An opt-in
would make non-default indexing a lawful exception to the non-execution
boundary, which the accepted coding standard states without qualification.

### Accepted

**Orthogonal declared capabilities, with a separate closed effect vector.**
Accepted as D1, D2, and D4. This is the hybrid position — a safety model and a
semantic model — with the ordinal half of the usual hybrid removed. It supports
incomparable languages, which is the requirement an ordinal ladder fails.

**Hybrid per-language ownership under shared rules.** Accepted as D6 and D7,
with the correction that shared rules plus a default disposition make it a
decision. Without D7's default-to-incumbent rule it would be an invitation to
repeated ad hoc choice, which is the failure mode this ADR most needed to avoid.

## Consequences

Positive: RepoMap can adopt parser dependencies without weakening graph honesty,
because capability is declared, scoped, gated on achievement, and separated from
confidence. The dependency-minimal guarantee keeps the project installable
everywhere. The effect vector gives a vocabulary for safety that survives new
tools. The default-to-incumbent rule stops dependency adoption from being a
matter of enthusiasm.

Negative: the model is heavier than a tier number. Every adoption now costs an
adoption record, a licensing review, and qualification evidence. Capability
declarations must be maintained per language-dialect. The receipt model requires
a schema decision that has not been made, so the capability data has nowhere
durable to live yet, and D13's gating therefore cannot be enforced mechanically
until it does.

Neutral: no code changes. Every existing extractor stays conforming, and every
existing claim stays exactly as strong as it was.

## Migration And Adoption

No migration is performed by this ADR. The adoption order that follows from it,
should later phases be authorized, is:

1. name the closed legacy baseline membership (D17);
2. define the receipt schema binding (D10);
3. build the RepoMap-owned extractor registry with declared capabilities (D15);
4. implement the claim-kind-to-capability mapping and its fail-closed default
   (D13);
5. implement environment-level enforcement and boundary witnessing of the D3
   admission dimensions (D7, D9); and
6. then, and only then, consider any specific dependency through D7.

Steps 4 and 5 are both prerequisites, for different reasons. Adopting a
dependency before step 4 would produce stronger extraction with no way for the
graph to say what it actually knew. Adopting before step 5 would mean admitting
a dependency on its own declaration, which makes the D3 boundary decorative.
Neither ordering constraint is a preference.

## Refresh And Revisit Conditions

Revisit this ADR when: a capability in D4 proves insufficient to gate a real
claim kind; a language requires an effect dimension D2 does not express; the
non-execution boundary in `docs/contrib/coding-standards.md` changes; raw
observation schema v2 provides a receipt reference; a verifiable third-party
declaration mechanism makes D15 reconsiderable; or an accepted extraction
performance baseline exists, making performance a `[measured fact]` for the
first time.

Package, license, and API facts recorded here were verified on 2026-08-12 and
must be re-verified from primary sources at adoption time, not carried forward.

## Deferred Work

Identified, not authorized: naming the closed legacy baseline membership in D17;
the receipt schema binding and retention lifecycle; mechanical enforcement and
boundary witnessing of the D3 admission dimensions, which D7 makes a prerequisite
to any adoption; the claim-kind-to-capability mapping; the extractor
registry; a canonical serialization for the closed input identity in D9;
reconciling the six confidence values in `docs/contrib/coding-standards.md` with
the four in `VALID_CONFIDENCES`; reconciling `AGENTS.md`'s "by default"
non-execution phrasing with the unqualified rule in the routed coding standard;
the three inconsistent read-failure behaviors in `discovery_extractors.py`
(silent empty on decode failure, uncaught `OSError` for most extractors, recorded
`parse_error` observations for email and ODF); and any dynamic-analysis workflow,
which this ADR excludes rather than defers.

## Explicit Authorizations And Prohibitions

Authorized by this ADR: nothing beyond recording the decision and updating
`docs/specs/extractor-strategy.md` to conform.

Prohibited without a further accepted phase: installing, vendoring, or declaring
any parser, grammar, or resolver dependency; modifying `pyproject.toml` or
lockfiles; building a parser helper; implementing receipts, registries,
resolvers, or admission checks; changing the raw observation or canonical
schema; and introducing any extraction path that evaluates target code or
contacts the network.
