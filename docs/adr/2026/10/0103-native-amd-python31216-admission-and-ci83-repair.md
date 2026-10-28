# ADR 0103: Native AMD Python 3.12.16 admission and CI83 repair

## Status

Accepted for bounded source remediation under the maintainer's request to fix
CI83 and publish another public staging candidate. Implementation and fresh
scoped verification follow this decision. Image and P3 acceptance remain held.

## Date

2026-10-27

## Context

CI83 ran on staging b856bac943e59aebe419c009f4f2331cb99ba4c3, merge
43304df9dc6222940ba69433f6737f192b5980bf, run 40612206734 attempt 1.
It retained a successful native AMD component observation while the legacy
preflight refused the un-enrolled default. Unit and integration consumers also
still expected a held AMD entry or the former Python 3.12.15 config. A capacity
fixture patched shared standard-library modules, and a host-proof fixture paired
the real spent build grant with a later candidate. These are repairable defects.

The independent Claude source-admission checkpoint accepted the actual native
observation under conditions C1–C6. Its work reviewer independently inspected
source consumers but could not access the private evidence directory; actual
artifact inspection was performed by the external primary reviewer and parent.
That access limitation is retained rather than described as two artifact reviews.
The parent subsequently fetched and hashed the raw Git merge object and verified
its tree and both parents. Source implementation receives the complete compact
sealed record in its review input so that evidence access can be checked again.

## Decision

Enroll exactly the independently observed AMD 3.12.16 default. Write its 77-name
import tuple as a separate literal, never alias an ARM or historical tuple.
The SHA-256 of names joined by one space is
049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b.
The exact entry uses:

- index sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e;
- manifest sha256:6d2b0577e6d1632f077331de8e4780535f54839d163ded7abb4b7dd37b5d37ac;
- config sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28;
- sole removal /usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so;
- file SHA-256 4505ea29e626d11865106c975d7bed84d472bc6a4c0f2aedd670c6a3ecf233a8,
  size 62448, ELF machine 62, missing only libtcl8.6.so and libtk8.6.so.

The evidence has 1721 raw entries and 1720 trimmed entries, 77 successful imports,
81 retained ELF files, 21 owned library targets, no modified survivors and exact
container cleanup with zero application-build delta. The sealed record SHA-256 is
7ffc378494cb4f8d8556c03279bd957f4e2eec801fed51ade50c6578f9e95122.
Its payload-source SHA-256 is 821f35e81496639659e54736e7de58d964f2107a4287158d782d12046d41b1a8.
The OCI input envelope remains byte-identical, SHA-256
9781988ca058dcee40e7818be04843aedfdaec43fd5ab5fb1816fdb4a7fd2ce1.

Only the AMD literal, default map and explanatory comments may change in the
payload module. All functions, frozen Tk specifications and embedded probe
programs remain AST-identical to b856bac. Thus the native observation continues
to vouch for the trimming algorithm. ADR 0102 and the historical CI83 record
remain unchanged, including CI83's then-held default state.

Host validators compare each configured default against the entry independently
derived from raw native facts, and compare inner flags against that host state.
Missing, None, malformed and foreign defaults refuse distinctly. Default metadata
must not bootstrap its own evidence. The linker-cache integration mechanism uses
the enrolled entry for the native daemon; it must not derive a fallback from its
own observation. All three cache/missing-SONAME phases and the prohibition on
interpreter creation while libpython is moved remain. That mechanism proves
linkage behavior, not an OCI config identity. Standalone ARM proofs remain
ARM-only and retain an early AMD refusal and amd64_qualified=false.

Repair every affected consumer and preserve authentic refusal coverage using
explicit isolated doubles. Keep the original CI83 failing test population and
assertions. Positive host-proof fixtures use coherent temporary grants and
candidates rather than the production spent grant. Capacity fixtures isolate
module dependencies and prove real file I/O and shared stdlib state survive.
Python/pytest version drift is observed correlation; no dependency policy change
is inferred or authorized. Refresh candidate context only after final source.

## Exact scanner false-positive classification

Pinned Betterleaks 1.8.1 reproduces four generic-api-key matches in the unchanged
public OCI metadata. Each is the public OpenPGP fingerprint in GPG_KEY used by
the image's receive/verify commands, not a credential. Preserve the input bytes.
Add an explicit tools/ci/betterleaks.toml configuration and pass it explicitly
from the existing scanner command. Extend all upstream defaults; preserve all
417 resolved rules, their rule filters, the prefilter, and the upstream global
filter. Add only the conjunction of exact generic rule, exact metadata path,
exact public fingerprint and immediate GPG_ match context. No blanket path
exclusion, disabled rule, baseline increase, encoding or online validation.
The copied upstream global filter retains its MIT source attribution.

Native pinned-scanner canaries must reject a synthetic unissued credential in
the same file, the fingerprint outside that path, the fingerprint outside GPG
context, and a changed value in the same context. The unchanged metadata must
scan clean. This classification accepts no credential and changes no debt or
coverage ceiling. A pre-implementation private prototype passed those canaries;
fresh resulting-source checks remain required.

## Scope and non-scope

The maintainer authorizes actual repairs, independent source review, ordinary
scoped unit and containerized integration proof, static checks, and one ordinary
staging push with its automatic public CI campaign. New dispatches are sequential
claude_only; active dispatches must not be interrupted. Debian Trixie, dynamic
Psycopg and the finite glibc disposition remain. No new dependency, lock, SDK
policy, workflow topology, main promotion, tag or PR state change is authorized.

Future AMD application builds would use the enrolled trimming default; this is
disclosed but not exercised. The four consumed application starts remain spent.
The real CI72 build grant is immutable and its candidate mismatch still refuses.
There is no fifth application build, grant rearm, image admission or P3 acceptance.
Ordinary managed dependency-runtime setup needed by scoped integration is
separately accounted; it is not an application build. No complete local suite,
local coverage, AMD emulation or SDK build is authorized.

## Required evidence and alternatives

Use exact affected unit owners, including closure, host proof and capacity,
all default/observer/provenance consumers, grant/admission/system consumers and
scanner command/config contracts. Use native ARM container selectors covering
the full linkage mechanism, payload contract and affected standalone proofs.
Preserve all negative cases and grant refusals. Run changed-source static,
retention, topology/history/export/privacy checks and the exact pinned scanner.
Hosted CI owns whole-population coverage; prior CI83 measured unit 88.0/87.6 and
integration 90.2/82.3, meeting hard gates plus two points but with failed tests,
so those figures do not qualify the repaired candidate.

Rejected: another docs-only publication, historical import transfer, circular
fallback admission, rearming the spent grant, and weakening scanner gates.
If fresh evidence finds another defect, correct it within the same bounded
remediation before publication. Record exact results and remaining hosted holds
in the phase exit and commit.
