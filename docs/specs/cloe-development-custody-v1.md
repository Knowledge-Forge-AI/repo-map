# CLOE development custody and reconciliation

## Baseline and decision boundary

The continuing public implementation starts from preview v0.0.3 at
`5ad00d162ad8a04430874275246a53227578c533` and subsequent reviewed staging
changes. [CI93 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40958119302)
qualifies staging `433a2edf89284f71f10996d20c88bcf3e311c9de`; it does not qualify
its successors. The local configuration migration checkpoint `f9df2cf` adds
guarded apply, rollback and finalize under [ADR 0114](../adr/2026/10/0114-cloe-config-migration-apply-recovery.md),
with scoped proof and independent review. Its hosted qualification remains pending.

REPOMAP-CLOE-CUSTODY1 records a reviewed W0 reconciliation audit and restores
existing test contracts. It does not claim wholesale private-line reintegration
or authorize the broad package/import/default-home cutover.
REPOMAP-CLOE-RUNNER-RECOVERY1 subsequently completes the required bounded W0
source-recovery disposition under [ADR 0115](../adr/2026/10/0115-bounded-runner-failure-diagnostics.md).
W0 is locally reconciled for continuing development from this public candidate;
private experiments and historical material remain preserved under their owners.

The protected development checkout remains intact, including uncommitted and
untracked work. No reset, mirror, deletion or mechanical adoption is used.
Exact path identities and private diffs are retained outside the public tree;
public documentation does not reproduce private operational material.

## Dispositions

| Responsibility | Disposition |
|---|---|
| Product runtime assembly | Keep the public successor's Python 3.12.16/Trixie pins, linker-cache repair, package probes and native architecture contracts. Do not regress to the private precursor's earlier pins or missing runtime cleanup. |
| Historical release identities | Keep historical payload and package records distinct from current candidate records in `runtime/release_manifest.py`; neither historical record grants a new build or image acceptance. |
| Extracted D12 probes | Preserve the maintained `d12_image_probes`, `d12_recipe`, `d12_system_evidence` and `d12_candidate_assessment` owners. Packaging, dynamic linkage, archive integrity, row/schema parity, extension/index restrictions and replication-slot assertions remain explicit. |
| Hosted contracts | Keep the current public workflow and SHA-bound grants. Topology enforcement remains in the pre-review check catalog. Private split-workflow topology is retained privately. |
| Command-contract characterization | Restore specific cross-job-leakage assertions and invalid dependency variants against the projected public workflow, plus loop refusal and quoted-keyword acceptance using its native runner command. |
| Extension restore characterization | Require a nonempty observed ICU collation version as well as equality with the actual version. |
| Current product description | Describe implemented SQLite Local and PostgreSQL, with bounded host-native MCP acceptance; managed Cloud remains a target. |
| Private runner failure evidence | Integrate typed first-error retention, guarded cleanup and safe discovery diagnostics under ADR0115. Preserve the precursor's arbitrary-text capture prototype without adopting it. |
| Retrieval utility prototypes | Preserve for W2 evaluation design and W5 comparison. Synthetic fixture consistency is not measured product usefulness, held-out quality or live cost evidence. |
| Optional pgvector companions | Preserve for W5 tooling/admission work. No production pgvector admission or usefulness follows from these prototypes. |
| Private status, design and operational evidence | Preserve in place. Public companion notes and accepted ADRs retain their own scope; historical operational prose is not copied into the public namespace. |

The audit found no private-only product source module. That absence alone does
not prove semantic inclusion: runtime differences were reviewed, moved helpers
were inspected, and meaningful test/harness differences were recorded separately.
The historical and candidate D12 records retain different ownership and hash
domains. The informational treatment of inherited Debian findings follows
[ADR 0105](../adr/2026/10/0105-debian-stable-slim-maintenance-and-ci-responsibility.md).

## W0 source-recovery disposition

The private precursor contains a coherent failure-evidence family spanning
`runner_failure_evidence.py`, `runner_integration_execution.py`,
`runner_staging_discovery.py` and its child, plus corresponding test owners.
Its useful behavior includes bounded redacted discovery diagnostics, retention
of the primary error across secondary reporting/cleanup failures, and an honest
failure record when collection never established a population partition.

The public runner already rejects unsuccessful execution and requires report
export after success. Its missing diagnostic enhancements must not be described
as a demonstrated false-green defect. However, loss of the primary cause during
secondary failures is a real recovery/analysis limitation. The next W0 source
slice must review and integrate those enhancements under the existing privacy
and fail-closed contracts, with an ADR before changing report interfaces.

Preserve the strict successful qualification schema, exact M/A populations,
coverage floors, admission, no-retry rules and owned cleanup. A diagnostic failure
record must never fabricate a partition, counts, coverage or successful execution.
Optional pgvector profile propagation and companion-specific interpretation
remain separately owned where they affect the deferred W5 work.

The bounded source slice now preserves actual candidate/discovery failures across
later report and cleanup exceptions, with invocation-bound typed diagnostics.
Real canonical CLI and child-process cases prove unestablished population
reporting and owned process cleanup; positive qualification contracts stay strict.
Its local checkpoint passes 78 scoped unit and three containerized integration
cases, clean static enforcement and independent native source review. Python
project coverage is disabled for scoped runs; the canonical runner's fixed Go
helper component checks retain their own component coverage output.

This closes the named mandatory W0 source-recovery follow-up locally. It does not
claim blanket private-line reintegration, execution of preserved experiments or
hosted successor qualification. W1's coordinated installed-distribution, import,
resource, command and home ownership decision remains separate; configuration
filename conversion alone does not settle it.

## Qualification and publication

Local scoped proof establishes the edited boundaries only. This audit does not
request a complete local suite, coverage, an application/SDK build or live
operation. Public CI remains batched around useful roadmap milestones.

README is part of the release build context. Its corrected wording changes that
context even though runtime behavior is unchanged. The eventual publication must
freeze the final candidate afresh and obtain any required fresh build allocation.
Spent grants remain spent; no existing campaign is rearmed. Until that occurs,
the local successor is not accepted for hosted qualification or promotion.
