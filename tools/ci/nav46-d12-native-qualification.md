# REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED8 Exit: native D12 qualification checkpoint

This staging candidate carries the bounded PostgreSQL 16.15 image and Python
payload work described by [ADR 0087](../../docs/adr/2026/10/0087-d12-image-evidence-and-core-security-prerequisite.md),
[ADR 0089](../../docs/adr/2026/10/0089-d12-dynamic-psycopg-and-system-libpq.md),
[ADR 0090](../../docs/adr/2026/10/0090-d12-application-go-supported-toolchain.md),
[ADR 0091](../../docs/adr/2026/10/0091-d12-tls-p3-disposition-and-trixie-remediation.md),
and [ADR 0092](../../docs/adr/2026/10/0092-public-native-d12-qualification.md).

The dependency route is `psycopg[c]==3.3.6` and `psycopg-c==3.3.6`, dynamically
linked to the distro's system libpq. Bundled binary wheels, static linking and
pure-Python fallback are excluded. The application Go toolchain is pinned to
`golang:1.26.10-bookworm`; this checkpoint does not admit a new SDK base.

The public release-qualification workflow adds only `d12-native-amd64` in this
first checkpoint. It requires matching native host, daemon and SDK architecture,
and binds the checked-out merge, tree, parents, run and attempt. An ARM64 hosted
lane remains deferred. This checkpoint requests native evidence; it does not
establish two-platform qualification.

The existing `main-system-gate` retains its canonical runner. An early
`system-hold` guard refuses unresolved release prerequisites after candidate
binding and Python setup, before SDK or application-image work. Numeric libpq
and dynamic-package commitments remain unresolved, and application builds are
held at zero for this attempt. The original two-build human ceiling is not a
permission to consume it here. Native preflight or system refusal remains a
failed gate with evidence, rather than a waived or skipped qualification.

P3, image acceptance, incumbent comparison and coverage evidence remain subject
to their existing decisions and gates. The checkpoint does not claim P3 closure,
image acceptance, complete local suites, hosted success or coverage cushions.
The publication commit records exact scoped selectors and verification. Local
source checks do not establish native ABI or assembled-image qualification.

## Retained scope authority

The adopted `D12HOSTED6` projection introduces the clean
`repomap_kg.runtime.python_payload` helper in the existing `T1-future` /
`python_retained` ownership tier. This corrective `D12HOSTED8` record binds its
actual public before/after ownership and selection digests as one direct scope
transition. Its v2 source witness is the genuine public staging predecessor `a00e3c60c26e24153e8cf0923a1138459c5b545f` and that commit's ownership manifest. No new historical projection proof or history rewrite is introduced.
All 15 published authority records, incumbent selections, type entries,
projection proofs, debt findings and ceilings are preserved.
