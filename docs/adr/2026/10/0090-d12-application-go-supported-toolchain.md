# ADR 0090: D12 application Go 1.26.10 and one bounded native component proof

## Status

**Operator-approved scope (2026-10-22); design proposed for its required
independent pre-implementation review. Not implemented. NOT ACCEPTED.** The
operator chose "exact Go 1.26.10 plus bounded campaign" over the sealed
revision 2 proposal (SHA-256 `12ee437b…`) and its revision 3 addendum
(`a73bd665…`). Work stays in `REPOMAP-PRODUCT6-NAVIGATION45-D12DYNAMIC1`. No
pin changed and no image, layer or compiler was acquired or run when this was
written. Implementation and the campaign wait for that review and parent
closure. Source, image, platform and phase acceptance are false. The first
review found the plan not ready; see the
[plan review correction](#plan-review-correction-2026-10-22). A fresh
independent review found the corrected plan ready (see
[Plan readiness and sequencing](#plan-readiness-and-sequencing-2026-10-22)).
The source slice was then produced and awaits independent review; the
campaign is prepared and unused (see [Implementation](#implementation-2026-10-22)).
"Not implemented" above is historical: the Go source and campaign script
exist, the script was [corrected](#campaign-correction-2026-10-23), and no
Go 1.26.10 compiler has run. (Superseded 2026-10-23: the one native
linux/arm64 campaign has run. Its control status is failed because of cleanup
bookkeeping, while every component check passed. The campaign is spent. See
[Component campaign result](#component-campaign-result-2026-10-23). Still NOT
ACCEPTED.)

## Date

2026-10-22

## Context

- The application builder pins Go 1.25.12 (`GO_RELEASE_VERSION`) through
  `golang:1.25-bookworm@sha256:ea341baa…`; the SDK sandbox uses Go 1.25.10.
  Both are outside the upstream two-release support policy. This is a
  support finding; no reachable vulnerability is inferred.
- The release recipe is rendered by `render_server_dockerfile()` in
  `runtime/commands.py`; there is no `src/docker/Dockerfile`. Its `go-helper`
  stage runs `CGO_ENABLED=0 … go build -trimpath` and the final stage copies
  only the helper and `/usr/local/go/LICENSE`. **The Go `PATENTS` grant is not
  shipped today.**
- `src/main/go/go.mod` says `go 1.25`, with no `toolchain` line, no
  requirements and no `go.sum`; imports are standard or module-internal.
- Pin consumers are listed in D3. A duplicate literal in
  `tools/test_sandbox_contract.py` is pulled into every integration
  sandbox's inner daemon, and no test binds it to the constant. The D12
  source and recipe identities hash `src/main/go` and the rendered recipe.
- [ADR 0089 D8](0089-d12-dynamic-psycopg-and-system-libpq.md#d8-inventory-and-p3-classification)
  stops any unresolved `unknown` runtime finding before a reservation.

## Decision

**D1. Exact input.** Only the application builder changes, to
`golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af`
with `GO_RELEASE_VERSION = "1.26.10"`. Sealed native children: arm64 manifest
`08496309…`, config `347d64c4…`; amd64 manifest `88750ccd…`, config
`0d494ea9…`. Configs declare `GOLANG_VERSION=1.26.10` and
`GOTOOLCHAIN=local`; metadata is not execution evidence. Unchanged: the
`go 1.25` directive, zero external modules, the SDK image, linter, hosted
`setup-go`/`go-version-file`, govulncheck, Python pins and locks, native
package selections, and graph, schema, CLI and MCP behavior.

**D2. Recipe.** The builder's existing CGO-off `-trimpath` command gains an
explicit `GOTOOLCHAIN=local`. The final stage also copies
`/usr/local/go/PATENTS` to `/usr/share/doc/repomap-kg/go/PATENTS` and checks it
with `test -s`, like `LICENSE`. Nothing else leaves the builder.

**D3. Frozen implementation write scope.** `runtime/release.py`,
`runtime/commands.py`, `tools/test_sandbox_contract.py`, the unit owners
`arch7f_release_resources` and `test_sandbox_hosted_adoption` (a new equality
check binds the duplicate literal), the D12 core integration owner's notice
list, `docs/legal/third-party-notices.md`, `docs/specs/as-built-architecture.md`,
this ADR and the D12 native qualification companion note. Inspected and unchanged: `go.mod`, the SDK Dockerfile,
both hosted workflows, `tools/build_go_helper.py`, `candidate_image.py` (it
follows the constant), synthetic `1.25.12` fixtures in the system-gate tests,
the SDK's `go1.25` checks, and `psycopg-source.json`, whose GPL-3 provenance
names the old image the text was read from. Any other path is a stop.

**D4. One native component campaign.** It runs only after implementation and
review of this plan, on the host Docker engine's inherited context and
configuration, at the server's native platform. No context switch, builder,
emulator or host change. One container created from the exact image with
`--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges` and
`--pull never`; a frozen copy of `src/main/go` mounted read-only; phase-owned
writable output and cache mounts; executable tmpfs for `/tmp` and `HOME`.
Environment: `GOTOOLCHAIN=local`, `CGO_ENABLED=0`, `GOPROXY=off`, `GOSUMDB=off`,
`GOWORK=off`, `GOENV=off`, `GOFLAGS=-mod=readonly`, and `HOME`, `GOCACHE`,
`GOMODCACHE`, `GOTMPDIR` and `TMPDIR` on those owned mounts. The eight
revision 2 tests run with explicit package paths, anchored `-run`
expressions and `-count=1`, then the one `./cmd/repomap-go-extract` build with
the release settings, all in that same container. No `./...` test, coverage,
race or vet campaign.

**D5. Evidence.** Platform child manifest and config bound to D1; `go version`
and `go env`; compiler and linker hashes and ELF headers; per-test
`--- PASS` lines; `go version -m` of the binary (go1.26.10, `-trimpath=true`,
`CGO_ENABLED=0`, native `GOOS`/`GOARCH`); a static ELF with no interpreter or
dynamic section; frozen source digest before and after; binary size and
SHA-256; two byte-identical runs of a fixed protocol exchange;
`/usr/local/go/LICENSE` and `PATENTS` equal to the sealed tagged bytes
(`911f8f57…`, 1,453 bytes; `96f408bf…`, 1,303 bytes). Sanitized inspection
of the created container proves the flags and mounts before it starts.

**D6. One attempt.** Preconditions that change no Docker state may fail
without spending it. The campaign is spent when its first state-changing
command starts: the pull, or the create if the image pre-exists. A failure
after that, including a failed acquisition, keeps the finding and needs a
written disposition; a retry needs separate later authority. The application
build ledger is not touched: `maximum_total` 0; original two total, one per
platform, no retries, none used.

**D7. Cleanup.** Exact before/after inventories of images, containers,
volumes and networks. Remove the exact campaign container with its anonymous
volumes. Remove the image only if it did not pre-exist and nothing uses it.
Preserve everything else; never prune; report any residue or cleanup failure.

**D8. Python evidence.** Exact scoped unit and integration selectors through
`tools/run_tests.py --no-coverage` are frozen in the plan. They run the
SDK-built helper and prove recipe text, constants and existing behavior. They
are not new-compiler evidence; only the campaign is, for its native platform.
No Python-to-campaign-binary transport is designed or needed. If review
requires one, it must be designed and reviewed first. The SDK helper is never
presented as the new binary.

**D9. Sequencing and P3.** The approved Psycopg slice is completed and frozen
first. Then the Go slice, recomputed D12 source and recipe identities (no
pre-Go reservation or qualification is reused) and the campaign. After actual
evidence exists, a **separate written P3 disposition** must explicitly resolve
how D8's pre-build Go finding is treated given the component evidence. It
keeps the final-image Go inventory `unknown` as a post-build gate and grants no
silent bypass, hold release or final-image claim. Only an explicit later
disposition can release the hold. After any separately admitted build, the
shipped binary, its metadata and notices are compared with the component
evidence; a mismatch or gap is a failure. Missing incumbent inventory, native
closure, the other platform, positive inner-daemon preflight and hosted
coverage stay pending.

**D10. Support, licenses, supply chain, rollback.** Go 1.26 support ends when
Go 1.28 ships, expected in February 2027 (an estimate); a support checkpoint is
due before then. Bookworm is under LTS through 2028-06-30 and package-level
coverage is not presumed. The SDK Go 1.25.10 finding stays open with the
repository maintainer. Hosted source govulncheck does not establish the status
of a 1.26.10 binary. Retain BSD-3-Clause `LICENSE` and `PATENTS`; no legal
waiver. Rollback restores the 1.25.12 pin and expectations and keeps the
unsupported finding; it never declares 1.25 safe. Alternatives remain a
separate exact 1.27 proposal or a written retention of the finding.

## Plan review correction (2026-10-22)

A solo `claude_only` stage corrected the plan for G1–G5 and the parent's
disposition. Documents only; nothing was acquired or run. The approval
stands; the corrected stage plan awaits a fresh review. NOT ACCEPTED. This
section supersedes the conflicting text in D4, D6, D8 and D9.

- **G1.** Before consumption, the sealed index, native child and config are
  verified offline as one digest chain, and `docker info` records the store.
  The observed `overlayfs`/`io.containerd.snapshotter.v1` store gives `Id`
  equal to the index digest; a classic store gives the config digest. After
  the pull: `Id` must match the store, the RepoDigest must name the index, OS,
  architecture and variant must be native, and `RootFS`, `Env`, `Cmd`,
  `WorkingDir`, `Entrypoint`, `Volumes` and `User` must equal the sealed
  config. `Env` alone never suffices.
- **G2 (D6).** The campaign is spent by exclusively creating the fixed
  the retained Go campaign consumption record
  (absent today), after every non-consuming check and before the pull or
  create, even if nothing follows. No run-name reset, orphan bypass or retry.
- **G3.** For root under `--cap-drop ALL`, within the owned 0700 root: source
  `a+rX`, output and cache 0777 and empty. Modes, owner, symlinks and ACLs are
  checked before consumption, and nothing outside that root changes. An
  exact-UID route needs its own review.
- **G4.** The frozen int node's sandbox setup pulls the new pin into its
  disposable inner daemon (`docker exec <outer> docker pull
  GO_RELEASE_IMAGE`, `tools/test_sandbox.py`). The parent confirms this as a
  normal prerequisite: not the campaign, no consumption, no compiler evidence,
  and the node runs no Go. The campaign's executor is the parent host shell
  (`docker pull --platform <native>`), and it runs only after the future
  writer, reviewer, drains and source closure.
- **G5 (D4).** Only tracked regular `src/main/go` files are copied, with that
  prefix stripped so `/src` is the module root. Symlinks and escapes refuse.
  `go.mod` must equal its 54 committed bytes. `/tmp` is an executable tmpfs;
  `HOME` is a non-executable tmpfs.
- **Origins (D8).** The unit runner's Go step uses the curated host Go
  1.25.10 (darwin/arm64), and integration uses the SDK's Go 1.25.10
  (linux/arm64). Neither is new-compiler evidence.
- **Comparison (D9).** Byte identity is recorded as such. Different bytes
  with equal build metadata, static ELF and protocol output are a recorded
  difference that needs a written disposition. Any other mismatch fails.
  Equal versions never stand in for byte identity.
- **Also.** Inventories compare stable projections (raw output kept
  privately). An existing image with a sealed ID under another name refuses.
  `PATENTS` goes at `NOTICES` index 5. Red and mutation tests cover pin drift,
  `PATENTS` and `GOTOOLCHAIN=local`. Module-gated `GODEBUG` follows the
  unchanged `go 1.25`. The selectors and the SDK, linter, hosted Go, module,
  scan-tool and transport choices are unchanged.

## Plan readiness and sequencing (2026-10-22)

Documents only. NOT ACCEPTED.

- **Readiness.** A fresh independent review found the corrected stage plan
  (SHA-256 `435c3de2…`) ready, with no blocking correction. Its advisories:
  bind `D` to one absolute path; refuse untracked files under `src/main/go`;
  every integration sandbox pre-pulls the new pin after the change, not only
  the confirmed node; check Docker Desktop file sharing before consumption;
  and treat an absent `Entrypoint`, `Volumes` or `User` as inspect null or
  empty.
- **Sequence.** First the SDK probe import-order fix
  ([ADR 0089](0089-d12-dynamic-psycopg-and-system-libpq.md#sdk-probe-import-order-correction-2026-10-22))
  and its scoped units. Then exactly one frozen C compatibility attempt with
  the parent's eleven integration selectors. Only if it passes, the Go source
  change and its nine unit owners, the one Go-affected wheel node, and a
  prepared but unrun campaign script. The campaign runs only on the parent
  host, after the writer, review, drains and source custody close.
- **Outcome so far.** The C attempt was not executed. A rebuilt SDK image
  needs registry token access that the producing session's network policy
  denies, so the attempt would have failed in setup without testing the
  correction. No Go source, pin, notice or test changed. No campaign script
  was prepared. The campaign is unused and its consumption record is absent.
- **Superseded (parent R10 disposition).** The Sequence's "Only if it
  passes" and the Outcome above no longer hold. The parent's C11 cohort ran:
  20 passed, 1 failed on record framing
  ([ADR 0089](0089-d12-dynamic-psycopg-and-system-libpq.md#receipt-framing-application-apt-custody-and-probe-child-2026-10-22)),
  so no C cohort passed. The parent authorized the Go source in that state
  and deferred one combined final C/Go cohort, with the Go wheel node, to the
  corrected source; it has not run. Go source and campaign script exist
  ([Implementation](#implementation-2026-10-22)); no Go 1.26.10 compiler
  proof exists. (Superseded 2026-10-23: that combined cohort ran with 21
  passed, and the campaign ran; see
  [Component campaign result](#component-campaign-result-2026-10-23).)

## Implementation (2026-10-22)

Recorded before source changed. NOT ACCEPTED. The parent owns every
container check; the Go slice lands after M2 with local unit proof only.

- **Source.** Exactly plan `435c3de2…` and D3: the D1 pin and its duplicate,
  `GOTOOLCHAIN=local` on the one CGO-off `-trimpath` build, the `PATENTS` copy
  and `test -s`, `go/PATENTS` at `NOTICES` index 5 (not run), notices and docs.
- **Proof.** The nine planned unit owners, red then green, and mutations;
  the parent later runs one combined C11 cohort with the wheel owner.
- **Campaign.** `GO-CAMPAIGN.py` is prepared, not run; only the parent runs
  it, after closure and that cohort. Its review found it not ready; see
  [Campaign correction](#campaign-correction-2026-10-23).
  (Superseded 2026-10-23, historical wording kept: the corrected script ran
  once at native linux/arm64 and is spent; see
  [Component campaign result](#component-campaign-result-2026-10-23).)
- **Open.** Go component and final-image evidence, P3, incumbent inventory,
  coverage, amd64; all acceptance false. (Superseded 2026-10-23 for the Go
  component only: the parent accepted the native linux/arm64 component
  evidence within D4/D5, with the control status still FAILED and the
  campaign spent. Final-image evidence, P3, incumbent inventory, coverage and
  amd64 stay open, and all acceptance stays false.)

## Campaign correction (2026-10-23)

A fourteenth solo `claude_only` stage. The review of script `ab087cbd…`
answered not ready. Only the private-scratch script changed (now
`a7a1b008…`, not run in any mode, including `--dry-run`); no Go source, pin,
notice or Go test. NOT ACCEPTED.

- **F1.** Per `go help list`, `-test` reports a package rebuilt for a test
  binary as `p [q.test]`; the entry split it and always refused after
  consumption. Each non-empty row must now fully match a module-owned path,
  optionally followed by one space and a bracketed module-owned `….test`.
  Empty rows are standard packages. External, prefix-confused, malformed or
  empty output refuses.
- **F3.** Cleanup errors inside `finally` escaped before the result was
  written. Cleanup is now best-effort: each error or uncertainty is recorded
  and fails the result; `CAMPAIGN-RESULT.json` and stdout are still written
  (a failed write is printed and fails). The known container is removed even
  if enumeration fails. A failed, timed-out or malformed listing is unknown,
  not empty. The image is removed only if acquired with recorded ID and
  references and an empty successful ancestor query; never forced or
  pruned; nothing unrelated touched. `out` and `cache` must be empty at the
  source check and just before the record.
- **F2 limits.** The parent's read-only observations (engine 29.8.2, API
  1.56, native arm64; existing image and container field shapes; canonical
  bind sources) are shapes only. The Go image is absent, so actual image,
  config, container, `go env` and build-info assertions first run after
  spending. An actual `Variant` other than `v8` refuses after consumption.
  The sealed and actual image `Config` are compared after the unchanged
  `normalized()`, which drops every top-level key, known or unknown, whose
  value is null, `""`, `[]` or `{}`. `false`, `0` and every other non-empty
  value remain, so a differing or extra remaining field refuses after
  consumption. No pre-consumption probe. (Corrected 2026-10-23 by the
  fifteenth stage, wording only: this item first said nothing unknown is
  normalized and every extra `Config` field refuses. The script is
  unchanged, `a7a1b008…`.)
- **Unchanged.** Config, `RootFS` and native digest binding; pre-start flag
  and mount checks; fixed absolute `O_EXCL` 0600 record with file and
  directory `fsync`; one attempt even after a crash or failed acquisition;
  read-only root and source; no network; offline local compiler; eight
  tests; one CGO-off `-trimpath` build; exchange twice; `LICENSE`/`PATENTS`;
  parity; no new-root reset.
- **Proof.** Stdlib fixtures, injected fakes only: 8 tests (18 malformed row
  shapes, 13 cleanup failure modes) pass; the entry script fails them; four
  mutants are caught.

## Component campaign result (2026-10-23)

A sixteenth solo `claude_only` stage recorded the parent's executions, in
documents only; it ran nothing. NOT ACCEPTED.

- **Combined cohort.** The parent made one canonical run of the eleven frozen
  C11/Go-wheel selectors, with `--no-coverage` and no application profile:
  21 passed, exit 0 (parent-reported; log SHA-256 `f2e7efac…`, 3,968 bytes).
  Image, container, volume and network deltas were 0, and no application was
  built. This is SDK and test-image compatibility evidence only. The wheel
  node pulls the pin into the disposable inner daemon and runs no Go. Nothing
  in the cohort is Go 1.26.10, product libpq or final-image evidence. No
  complete suite or coverage ran.
- **Campaign.** After a non-consuming dry run (parent-reported; no dry-run
  output is in the stage's evidence), the parent ran script
  `a7a1b008…` once with `--spend` on the inherited host engine, at native
  linux/arm64. The consumption record exists (`c3b26714…`), and there is no
  retry, re-pull, new-root or dry-run authority. Observed:
  - the image identity chain: index `632dff73…`, child `08496309…`, config
    `347d64c4…`, and the container's manifest descriptor equal to the child;
  - `go version go1.26.10 linux/arm64` and the frozen `go env`;
  - `go 1.25` with no external module;
  - 8 of 8 named tests passed;
  - one CGO-off `-trimpath` build, with build info `go1.26.10`,
    `-trimpath=true`, `CGO_ENABLED=0` and linux/arm64;
  - a static ELF with no interpreter or dynamic section;
  - protocol `1`, and two identical exchange outputs `dde09e7f…`
    (306 observations and 1 `file_end`);
  - `LICENSE` `911f8f57…` and `PATENTS` `96f408bf…`, equal to the tagged
    bytes.

  The Go source digest `31a00acc…` was unchanged afterwards. The binary is
  3,899,852 bytes, `4fd3a6cc…`.
- **Control status: failed, retained.** The wrapper exited 1. No compiler,
  test, build, protocol or notice check failed. The cause: inspect lists the
  one image name `golang@sha256:632dff…` in both `RepoTags` and
  `RepoDigests`, and the script concatenated the two lists. The first
  removal deleted the image. The identical second removal returned "No such
  image" and was recorded as uncertain, so cleanup was incomplete although
  parity held.
- **Cleanup proof.** The exact container was removed, and the image was
  removed only after an empty ancestor query. The script's before and after
  projections of images, containers, volumes and networks are equal, with no
  residue. The parent's canonical inventories before, after and in a fresh
  read-only check are byte-identical. The reference and container are absent,
  and the campaign label lists nothing. No further removal or execution
  happened. The proof covers D7's four inventories; engine content collected
  lazily outside them is not claimed.
- **Disposition (produced, not accepted).** The stage's private disposition
  finds the component evidence technically acceptable for D4/D5 at
  linux/arm64 only. That acceptance is the D6 written disposition of a
  recorded failure: the status stays failed, and nothing is waived or
  retried. A one-line deduplication of the removal list is a private future
  proposal with an offline fixture; the used script is unchanged. The
  independent review and the parent decide.
- **Still open.** amd64 and any emulated platform; the final image and the D9
  helper comparison; the separate written P3 disposition; incumbent
  inventory; the inner-daemon preflight (2026-10-23: E1 exploration source is
  produced, unreviewed and unrun; see
  [ADR 0089](0089-d12-dynamic-psycopg-and-system-libpq.md#e1-exploration-implementation-checkpoint-2026-10-23));
  coverage. The application ledger is
  unchanged: `maximum_total` 0; original 2, 1 per platform, no retries,
  0 used.

## Scope and non-scope

In scope: D1–D10 only. Out of scope: SDK, linter, hosted or govulncheck
changes; an application image build, reservation, consumption or ledger
write; P3; any complete suite or runner policy change; publication,
deployment or CI triggers; amd64 qualification.

## What would prove this wrong

The plan is wrong if the exact image's native config or executed compiler is
not go1.26.10; the module needs a toolchain directive or external module; the
eight tests or the build need network, writable source or a different
compiler; the binary is dynamic, lacks `-trimpath`/`CGO_ENABLED=0` build
settings or produces nondeterministic output; `PATENTS` or `LICENSE` differs
from the tagged bytes; another path must change; or cleanup cannot restore the
inventories without touching resources the campaign did not create.

## Consequences

The D12 identities change and must be recomputed. Every integration sandbox
then pulls the new exact Go image into its disposable inner daemon. The
release image gains the `PATENTS` notice. The final-image Go finding stays
open until a built image is inspected.

## Rejected alternatives

- **Updating the SDK or hosted Go with the application.** Excluded by the
  approval.
- **A `go 1.26` directive or `toolchain` line.** Not needed; changes the
  module contract.
- **`go test ./...` or race under the new compiler.** Outside the bounded
  campaign; the SDK runner keeps its existing Go checks.
- **`GOPROXY=off` and similar in the application recipe.** Not approved for
  the recipe; zero modules means nothing is fetched. Revisit only by review.
- **Running the campaign as a non-root user.** Host-side ownership of bind
  mounts under this engine is unqualified; capabilities are dropped instead.
