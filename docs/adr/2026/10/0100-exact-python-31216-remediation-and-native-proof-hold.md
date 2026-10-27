# ADR 0100: Exact Python 3.12.16 remediation and native-proof hold

## Status and date

Accepted bounded Route A before implementation, 2026-10-27. The operator
selected "A: Python code fix + bounded proof (Recommended)" against decision
SHA-256 `97e620c5e9882a70ac4abc4fad217851047f6f95967dca7744c8a65f7f8b66a9`. Independent review identified F1–F4;
the binding parent amendments were included in the selected packet. Approval
authorizes implementation and scoped evidence, not P3/image/native-platform
acceptance, an application build or public staging publication.

## Context

The current Python 3.12.15 pin predates the Python 3.12.16 SSL security fix.
CI72's application build and five diagnostic scenarios passed, but P3 security,
byte/licence/provenance and comparison requirements remain. The later docs-only
CI73 publication failed its spent run-72 grant without remediating the runtime.
Renumbering that grant would not fix P3. All four application starts remain spent.

## Decision

Adopt only the already inspected Python 3.12.16 slim-Trixie index
`sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e`.
ARM child/config are
`sha256:0ced713d9b8336172d981d8f25f2422b6782bdad019fda4cb653c6ee187430de` /
`sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3`.
Keep index, platform manifest, config, package and final-byte identities distinct.
No substitute digest, distribution, Python series, dependency or SDK is selected.
Preserve dynamic C Psycopg 3.3.6 and distribution-owned shared libpq.

Update the pin/version, payload and expected identity/source/recipe metadata,
connected test owners and current notices/as-built records. Preserve complete
module/ELF/ownership/removal guards and every coverage/debt ceiling. Historical
records remain historical. No system grant, ordinal, workflow trigger, P3
acceptance predicate or runner acquisition policy is changed.

The ARM import/exclusion baseline must come from the approved real native ARM
component proof. Before that observation, any prepared expected data is a
candidate, not a recorded native pass. Use the existing explicit exclusion-
mapping test seam when needed to prove the actual observed entry without
inventing prior facts. A later literal adoption must match that sealed result.
AMD byte/OCI metadata may be recorded, but its new native import baseline is
unobserved and admission must refuse. Keep the old sealed AMD observation as
historical evidence; never transfer ARM or old imports to the new index.

## Execution limits and proof owners

Fresh maxima: three scoped unit executions (one regression RED, one combined
affected-owner GREEN and a conditional correcting repeat); two scoped
containerized integration executions and two changed-owner static profiles,
first one and a repeat only after failure/correction. Cumulative ceilings are
unit16/integration13/static17/RED2; old exact diagnostic1 remains spent.
Declare exact paths/nodes before execution through tools/run_tests.py with
--no-coverage. Include all directly affected identity/payload/image-route and
expected-evidence unit owners in the combined GREEN. Add dedicated d12_python31216
unit and integration owners. SDK-ELF synthetic evidence cannot substitute for
the actual Python input and its native imports/exclusion/retained payload.

One normal native-ARM digest-pinned pull of that exact input is permitted;
verify child/config against retained manifests and blob digests. No retry,
hand-assembled archive load or emulation. Permit exactly one offline managed
dependency-only runtime-cache materialization through the existing manager,
inside the reused cached SDK, from retained hash-bound wheels/prerequisites.
It is distinct from application assembly; uncertain start consumes its slot.
Missing retained inputs or cached SDK stops the phase. All real probes occur
within the two scoped integration invocations, with exact owned cleanup.
Source review precedes scoped execution; independent resulting-state review
and fresh parent verification precede acceptance of this partial code change.

## Boundaries and consequences

No fifth application start, SDK rebuild, complete local suite, coverage, new
runtime deployment, infrastructure, pgvector/D15 admission, main/tag/history
mutation or publication follows. Preserve predecessor private source/HEAD/index;
only this accepted ADR and a new primary Exit are added there. Source changes
remain in the public candidate checkout as a local, unqualified continuation.

This correction is partial. Trixie glibc findings and all other P3 stops remain.
No operator risk disposition is inferred. Missing candidate identity, licences,
provenance, ABI or cleanup evidence cannot be waived. Later staging requires
supported corrections or explicit applicable per-finding dispositions,
complete candidate evidence and native AMD proof, and a fresh separately
granted application start/event. Keep the existing grant spent and unchanged.

## Alternatives and rollback

Retaining the hold or separately designing supported replacement bases remain
operator choices. Replacing only a version string, transplanting old native
baselines, relaxing a guard or publishing another knowingly red docs milestone
does not satisfy this decision. Reject source reversibly with a forward change;
do not rewrite public history or accept an affected predecessor as a safe runtime.


## Approved recovery amendment, 2026-10-27

After the first integration refusal, the operator selected
"A: Approve bounded recovery (Recommended)" against recovery decision SHA-256
`721179bfb7bd5bb6ab7b2f36c9701469c6065ad84785fdf0a4303805caa6055f`
and frozen execution binding SHA-256
`01d3f191869b229e95d17ebd91f6afe84cc3a14a9ff9dcd1fadfad43c0f4f9e8`.
This extended only the exact Python-pull ceiling from one to two and expressly
included four unchanged frozen harness prerequisite pulls, one command each.
It used the existing conditional integration slot 2/2 with the exact ARM
config/image override. Zero further dependency-cache materializations, SDK or
application builds were permitted. Unit/static limits and all other holds
remained unchanged. The earlier online cache materialization remains an
unaccepted deviation; its unsatisfied offline condition was not waived.

The recovery passed its native ARM component and adopted the actual 77 imports
literally. The final scoped unit cohort passed 292 tests and scoped static
passed all ten checks; see the [companion record](../../../../tools/ci/nav47-python31216.md).
The native proof matched retained manifest/config bytes to observed Engine ID
and rootfs diff IDs. It did not freshly observe registry manifests or compressed
layer blob digests; the original blob/provenance requirement remains unclosed.
The adopted literal was checked against the retained observation by scoped
unit evidence and independent source review, without another native execution.
Full phase, offline-cache/dynamic-Psycopg, native-AMD, P3/image acceptance and
publication remain held. No additional retry or execution authority follows.
