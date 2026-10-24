# PostgreSQL D12 Python Payload Decision Packet v1

Date: 2026-10-23. Phase: `REPOMAP-PRODUCT6-NAVIGATION45-D12DYNAMIC1`.
Status: **Route A; D4 amendment parent-accepted after independent review;
source [implemented](#implemented-contract-2026-10-23), NOT ACCEPTED.** This is a design amendment,
not image, platform, phase, P3 or coverage acceptance. The application hold
stays in force. See [ADR 0089](../adr/2026/10/0089-d12-dynamic-psycopg-and-system-libpq.md#d4-release-recipe-narrow-correction)
and [the D12 native qualification companion note](../../tools/ci/nav46-d12-native-qualification.md).

**Historical contract.** Everything below through the E2 result describes
the superseded Bookworm 3.12.13 base (index `d50fb761…`, 70,512-byte target,
78 imports). Under ADR 0091 route A the only live entry is the
[exact Trixie case](#exact-trixie-case-adr-0091-2026-10-23); the Bookworm
entry is never generalized to new bytes.

## Actual refusal and subsequent static identity

The parent's one admitted native linux/arm64 E1, under
`--d12-core-image-preflight`, `--no-coverage` and no ledger option, exited 1
at E-f on 2026-10-23. It is spent; no automatic retry is authorized.

| Fact | Evidence and limit |
| --- | --- |
| Source and recipe | `c6218750…`, `d6c1dfd3…`, 693 context files |
| Daemon | Engine 29.4.0/API 1.54, docker/overlay2, BuildKit v0.29.0; arm64 native; amd64 merely offered by the builder and classified emulated |
| Trust | Existing `gpg` listed PGDG primary `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`, no subkeys |
| libpq | PostgreSQL-base dpkg `libpq5` version `18.6-1.pgdg12+2`, not a loaded numeric ABI observation |
| Python closure | 83 ELF entries, 27 resolved dependency paths with 22 package owners; 79 lib-dynload names, 78 fresh-process imports under `LD_BIND_NOW=1` |
| Refusal | Only `_tkinter` did not import; only its `libtcl8.6.so` and `libtk8.6.so` were reported not found by ldd. Python exception text was not recorded |
| Application work | Candidate, product/build-profile, unmanaged build and unmanaged pull counts all 0; candidate ID null |
| Test runtime | Managed test-runtime materialization count 1, non-ledger; new managed cache images 0 |
| Cleanup | Server removed, containers at baseline, four resource and reference inventories identical; source, index, hold and spent Go record preserved |

The immutable exploration, cleanup and freeze reports have SHA-256
`30ffdf7fc283962f4268d0d687e37955c5216205b3d9de71dc267c1c00d21486`,
`a4ae421ca37b865d8319c7bf0f1c52465092dc7a618a9e2edc767ce8c0444166`
and `e7bc2a5754ea7b5853cbfeca82afb26c8824f556debfcc739b4d510913b6f901`.

Subsequent read-only inspection of the exact public OCI artifacts established
the module identity below without Docker, execution, a retry or an application
build. The accepted Python index is
`sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b`.
The arm64 child manifest is
`sha256:c18c7a910432dde3311fc54d02e5d5220f3ebe26fec43ff15745982863dd7b3b`;
its config `sha256:a0938838407c79b6ff4ea2635398c61b68a3bf58d9d71d0604ab7825086d506a`
equals the Python image ID in E1. Manifest, config and layer digests and
compressed sizes were checked. The regular target in layer 2 overrides earlier
contents; the later layer was scanned for replacement, ancestor links and
whiteouts. The exact target is ELF64 little-endian AArch64:

- Path: `/usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-aarch64-linux-gnu.so`.
- Size: **70,512 bytes**.
- SHA-256: `e6856022061704f2b95ea01c9c12b6fa6fee36d2527a8ad7d0f18d4bacd9519f`.

The retained package-status artifacts show no installed Tcl/Tk package in
either Python architecture. Only the arm64 config was matched to actual E1.
These are static facts; amd64 execution and native admission are absent.
The module's import failure remains the separate native E1 observation.
The supplier history excludes tkinter from its runtime-dependency scan; that
explains the retained broken bridge without granting project authority.
PostgreSQL-base Tcl/Tk presence is unobserved: E-h did not run.

E-g, E-h and E-i did not run; the matching-header `libssl-dev` issue remains
a forecast (superseded: [E2](#e2-component-result-2026-10-23) observed it). There is no serialized complete libpq file-hash inventory, loaded
final-image ABI, P2, P3 or coverage proof. Builder offers do not prove actual
`RUN --network=none` execution or same-building-daemon readiness.

## Authority and selected amendment

The original D4 listed recipe changes and named only build-tool removals.
It derived interpreter dependencies from installed Python-base owners and
required all final retained ELFs to resolve. It cannot derive Tcl/Tk from
that base. It also preserves the set of baseline-importable lib-dynload
modules. D5 and D6 are not the governing clause.

The prior packet incorrectly made route A an operator-reserved choice.
Independent review found no such reservation: D4 is parent-accepted design;
approved dynamic-route item 4 already covers generated runtime recipe and
release assertions. The parent selects **A**, subject to independent review
of this written amendment. No new dependency, pin or capability is selected.
Only adding a new Tcl/Tk dependency class requires separate operator approval.
The derived interpreter closure already restores incumbent interpreter needs;
the libpq-only bound must not be misquoted as prohibiting that accepted closure.

### A: exact unusable `_tkinter` exclusion

1. Inventory the full original Python-base `/usr/local` ELF payload before
   any trim, including path, hash, size, ldd and fresh-process import results.
   Retain original findings; never filter the raw report into a false pass.
2. Classify exactly the frozen arm64 target above, only for the accepted
   index, child/config and native architecture. Compare actual bytes before
   deletion. It must be the sole nonimporting lib-dynload name and sole
   unresolved ELF; its missing set must be exactly the Tcl/Tk pair. Refuse
   absent, symlink, duplicate, importing, changed hash/size/path/base/arch,
   malformed observation, extra failed module or other unresolved dependency.
   Unknown architecture has no exclusion. Do not infer an amd64 entry.
3. Remove that one regular file only in an owned staged Python payload,
   disposable inspection container or separately admitted python-runtime
   build stage. Never modify upstream images, host files or live runtime.
   No glob, directory pruning or unresolved-entry ignore. Record the exact
   exclusion with original identity, reason, baseline imports and retained
   closure. The final recipe must apply the same frozen check; no broad
   exemption may replace it.
4. After deletion, re-enumerate and check every physically retained ELF;
   all must resolve, with the existing ownership rule. Re-import every one
   of the 78 baseline-successful arm64 modules in fresh eager-binding
   processes. Prove the target absent and every other payload file preserved,
   apart from the independently approved build-tool cleanup. Retain notices.
5. Record the removed bridge in P2 as a payload change. Its file/spec
   availability and import exception can change. The observed Tk bridge was
   unusable already; GUI behavior is not newly promised. Absence of direct
   source references does not prove no transitive consumer uses it.

Deletion and an exact hash-bound exception are peer bounded alternatives:
both change the universal assertion's effective domain. Keeping the file
preserves bytes but requires a permanent named exception for a broken ELF.
The parent chooses deletion to keep the assertion literal for every shipped
ELF. Neither permits blanket ignores or unrelated stdlib pruning. Rollback
is keep the hold or revert this exclusion; no history rewrite.

### Implementation and proof sequence

No source implementation occurs in this docs-only checkpoint. After review
and explicit parent acceptance, freeze a bounded implementation assignment:

- A cohesive `runtime/python_payload.py` may own the exact immutable
  exclusion, validation and generated inspection/removal contract shared by
  recipe and exploration; `tools/d12_python_closure.py` may own observation
  and E-f classification extracted unchanged where possible from the 400-line
  `d12_dependency_preflight.py`. Product/support must never import tools.
  `release.py` (399 lines), `commands.py` and preflight remain within the
  existing 400-line ceiling; no packing or unrelated refactor.
- A live observation compares the statically frozen identity before trim.
  An additional measurement-only E1 is unnecessary for this known arm64
  byte identity. That changes the old two-source-change sequence on new
  static evidence, not on a fabricated hash. Full raw inventory and imports
  are still required in the admitted disposable container before removal.
- Cover the shared helper and E-f classifier with pure units; update named
  `arch7f_release_resources`, `d12_release_apt_custody`, `d12_inner_preflight`,
  `local_runtime` and `system_candidate_image` recipe owners as needed.
  Preserve and select the existing exploration/admission/owner/build guards.
  Any new Python owner gets an exact zero-debt retention record; old records,
  deferred owners and ceilings remain byte-identical.
- Negative tests cover every mismatch above, importing Tk, another failing
  module, another unresolved ELF, malformed ldd, retained resolution failure,
  lost baseline imports and unintended deletion. Restore narrow mutants to
  prove hash enforcement, unknown-entry refusal and retained closure checks.
- Only after the frozen resulting source has independent review and parent
  acceptance may the parent admit **one** exact canonical native arm64
  D12 exploration with `--no-coverage`, no ledger and zero application builds.
  Write its disposition before any later attempt. This document is not that
  execution admission. No complete suite, coverage or application build.

No package, Python dependency, signing key, pin, compiler policy, emulator,
builder, capacity change or deployment is added. Python/Psycopg/Go notices and
exact sources remain; this is not a license or security waiver.

### Implemented contract (2026-10-23)

`runtime/python_payload.py` (stdlib only) holds the frozen arm64 entry with
all 78 E1 import names and the program. The recipe copies it into
`python-runtime` before the trust copy, builder APT, downloads and context
copy, and runs `python -I -B`; E-f (`tools/d12_python_closure.py`) runs the
same bytes, applying the entry only natively on the frozen Python config. It
records the raw baseline, refuses on any check above, re-hashes and unlinks
one file, then re-proves tree, closure, owners and imports. amd64 always
refuses until its own static identity, native observation and reviewed D4
entry exist. The in-container machine check is no OCI-config or native proof.
On arm64 `import tkinter` now fails for want of `_tkinter`.

The implementation's independent review found an unrelated ownership-binding
effect. The parent restores the pre-entry ratchet binding and registry while
keeping this clean helper's selection and new exact rule. Inherited ownership
mismatches stay unresolved. This component's scoped tests do not qualify
global governance. The helper's own new ownership rule is also unbound by
the retained old digest; its clean scoped checks do not qualify that binding.
A later isolated public candidate needs its own exact
manifest binding and any required scope record. No source/test byte changes
in this correction and no E2 is admitted by this paragraph.

### E2 component result (2026-10-23)

The parent's one E2 ran this contract natively on arm64 config `a0938838…`:
program `f3d92f4f…` returned `trimmed` (exit 0). 83 ELF files and 1,721
entries before; only `_tkinter` failed; exactly `e6856022…` (70,512 bytes)
was removed; 82 ELF files and 1,720 entries remain, 78 imports pass, nothing
is unresolved, and the digest equals the expected `6d3af915…`. The original
ELF observations are serialized; the raw post-trim inventory is not, so the
preservation of the other entries rests on that count, the digest and the
same in-container checker. This is no final-image, amd64, P3 or coverage
proof. E2 then refused at E-g on the matching header; see
[ADR 0089](../adr/2026/10/0089-d12-dynamic-psycopg-and-system-libpq.md#e2-actual-header-refusal-and-exact-builder-selector-2026-10-23).
E-h and E-i did not run.

### Exact Trixie case (ADR 0091, 2026-10-23)

The approved Trixie base replaces the entry's identity in source; the D4
mechanism is unchanged. The frozen arm64 entry is now index
`sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`,
child manifest
`sha256:6c6ae3622772575c3ac02ecb2b02a06d05f19e1713a0cbff476ef37bca79e90f`,
config `sha256:7efd45553a98be3d940b73600550669831c0be34f30c521159e7030a91fcdee6`,
the same `_tkinter` path, **70,584 bytes**, SHA-256
`9fe4f2c93a746b000a15ebb6fbb71ea33b3b7888efb70e3c1296fac8b30c2c96`, ELF
machine 183, missing exactly `libtcl8.6.so` and `libtk8.6.so`. Its import set
is the **77** names that imported in the observed no-exclusion baseline
(1,722 entries, 82 ELF files, 78 lib-dynload names): the historical 78 minus
`nis`, which this base no longer ships. No extra module is invented.

Every step above still applies; no glob, fallback or amd64 entry exists.
Pure units cover the constants and refuse the legacy entry, wrong hash or
size, the 78-name set, a lost import and an extra unresolved library. The
trim has not run on this base; native evidence (and retained dependency
ownership) awaits the canonical D12 preflight under separate admission.

### Deferred alternatives

**B: Tcl/Tk dependency research.** Exact packages, versions, hashes, origins,
transitive closure, licenses, ABI, image/runtime impact, rollback and tests
are unestablished. A concrete operator-approved dependency disposition must
precede any install. No such dependency is selected.

**C: keep D12 held.** The hold remains the rollback and present build state.
The old bundled-libpq findings remain open, without endorsement of the old pin.

## Separate mandatory gates

The frozen D3 native manifest, runtime numeric libpq, E-g/E-h/E-i, final image,
C ABI, P2 and coverage remain open. Same-building-daemon pre-consume admission
and O3 manifest placement still require a concrete parent-reviewed design.
The application ledger remains `maximum_total` 0 (original 2 total, 1 per
platform, no retries, 0 used). Releasing it requires a **separate written
operator P3 disposition** covering unknown runtime and missing incumbent
inventory. Route A supplies no P3 waiver or budget release, no amd64 native
qualification, no new Go campaign, deployment or publication authority.
Dynamic C Psycopg 3.3.6, system libpq and application Go 1.26 remain approved.

## Falsification

Refuse if live bytes or baseline imports differ, another ELF is unresolved,
the exact deletion affects another file, retained imports fail, notices are
lost, or a release-image consumer requires Tk. Static identity is not final
image acceptance. Later E-h may expose a separate closure refusal.
