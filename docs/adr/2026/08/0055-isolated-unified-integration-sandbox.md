# ADR 0055: Isolated Unified Integration Sandbox

## Status

Accepted as the mandatory backend for every integration and staging execution,
including the hosted Staging Gate and optional local diagnostics.
REPOMAP-TEST-ISO1-FIX1 corrected the test-control cancellation handoff and
qualified the complete integration population in the owned sandbox.
REPOMAP-CI0B-FIX31 closes the hosted report, prerequisite, diagnostic, and
combined-suite adoption conditions. TEST-ISO2 removes direct host execution,
closes writable host-state channels, and adds direct-pytest enforcement; no
second integration class is justified.

## Date

2026-08-22

## Context

RepoMap's integration tests deliberately exercise temporary Postgres, Docker
SDK and CLI behavior, image/container/volume ownership, process cancellation,
IPC, native Go helpers, and resource mediation. Running those tests against a
persistent developer daemon and host namespaces risks pollution even when the
test harness performs exact cleanup.

Before this decision, `--suite int` also selected unit tests. The complete
`--suite all` gate obtained correct aggregate coverage from one unit-plus-int
pytest process, but all resource-capable work ran on the caller's host.

TEST-ISO1 mechanically inventoried every entry integration and unit module.
Representative real tests proved Docker, Postgres, resource mediation, nested
bind mounts, IPC, native toolchain, and ordinary process/cancellation
capabilities. A later full-population attempt exposed two exact SCALE13
cancellation nodes whose accepted STARTED lifecycle has no terminal frame under
the Linux sandbox. The child exits from the authorized SIGINT with status `-2`;
the frame stream remains below its bound. Running pytest in the outer main
process tree instead of through `docker exec`, and matching the accepted Python
3.13.12 runtime, did not change the result.

REPOMAP-TEST-ISO1-FIX1 proved that `threading.Event().wait()` does execute
Python `KeyboardInterrupt` and `finally` unwind under the sandbox runtime. The
defect was a test-supervisor handoff race: the parent could send SIGINT after
writing the STARTED acknowledgement but before the child had settled it and
entered the blocker. A test-only child readiness byte now proves that the real
send/ack transport has returned before the parent sends its sole SIGINT. The
two exact cancellation nodes and one fresh full integration population then
passed with complete lifecycle and rollback evidence.

## Accepted design retained by the qualified backend

### One suite, replaceable backend

`unit` is unit only, `int` is integration only, and the retired `all` selector
is rejected. `int` and `staging` automatically enter the nested-Docker sandbox;
`--sandbox` remains only as a compatible assertion flag. A closed marker/token
pair, exact inner `DOCKER_HOST`, and absence of the host socket prevent
recursive relaunch without creating a forgeable Boolean bypass. Direct pytest
collection under the integration root enforces the same boundary before
fixtures or workload setup. Unit owns hard 85% statement and 85% branch
coverage, while integration independently owns hard 80% line and branch
coverage.

Exact selectors after `--` remain unchanged and are validated against the
selected suite root. Scoped integration execution therefore retains file,
class, test, and parameterized-node fidelity.

### Monolithic owned DinD sandbox

One collision-resistant privileged outer container runs `dockerd` and pytest.
It mounts host source read-only at `/workspace-ro`, projects a disposable
tmpfs-backed overlay at `/workspace`, and keeps generated build and package
metadata output in the same container-private tmpfs. `/sandbox-scratch`,
OverlayFS upper/work state, temporary files, pytest state, language/build
caches, HOME, Git configuration, the owner marker, and inner-Docker state are
invocation-scoped. The test process and daemon therefore resolve nested source
and scratch bind paths identically without a writable host bind.
Pytest executes as the sandbox-local root test identity because overlay and
namespace setup require that identity; its home is run-owned scratch. Test
scratch authority (`REPOMAP_TEST_SCRATCH_ROOT`) is established under a dedicated
sandbox-owned directory (`/sandbox-scratch/test-scratch`, mode `0700`) so that
safety ownership checks match the sandbox test runner identity. Repository
source remains a read-only host bind/overlay whose numeric ownership can differ
from sandbox UID 0. Git's ownership check remains enabled, and only the exact
sandbox repository root `/workspace` is marked safe for sandbox-local VCS
metadata reads; wildcard trust and host Git configuration/credentials remain
forbidden. The daemon remains privileged and exposes only its owned Unix socket.

The host Docker socket is never mounted. The internal marker rejects a present
`/var/run/docker.sock`, and both Docker SDK and CLI probes must resolve
`unix:///run/repomap-docker.sock`.

The sandbox uses the accepted Python 3.13.12 runtime, Go 1.25 with CGO support,
golangci-lint 2.6.2,
Docker 29.4, PostgreSQL 17 client/build tools, and the project's pinned Python
build dependencies.
Its three base images use immutable repository digests. The reusable
dependency-only image carries exact RepoMap owner and recipe labels and never
contains candidate source. At most two positively owned images are retained;
the current and container-referenced images are protected, and stale removal
uses exact IDs, no-prune semantics, and absence readback.

Inner `/var/lib/docker` is a 4 GiB tmpfs. Report generation alone uses the
outer container writable layer at the fixed `/sandbox-report/report` path so
it survives process exit long enough for bounded export; it never supplies an
OverlayFS upper/work directory. The launcher removes the exact outer
ID with volumes and verifies absence on success, test or setup failure,
SIGINT/SIGTERM, and launcher exceptions. Host container/image/volume/network
identities are compared before creation and after cleanup. Unexpected new
objects fail closed and are reported by bounded counts; they are never deleted
without attribution.

`--cgroupns=host` is required for real Docker memory-stat observations. Process
and IPC namespaces remain sandbox-local. This is a pollution-control boundary,
not a hostile-code security boundary, because privileged DinD shares the host
or VM kernel.

### Unit purity

Canonical unit items activate a closed runtime purity state. Repository-owned
Postgres construction fails before either starting or consuming a live
container session, while injected doubles remain valid. The mechanical entry
inventory found no live Docker, Postgres, service, or persistent-IPC unit
violation, so no unit test was moved.

In combined unit-plus-integration runs (`--suite all`), one session-owned
Postgres handle is shared across the process lifetime; unit test doubles must
be scoped and restored rather than replace or clear that owner.

The runtime hook is intentionally bounded. It does not ban harmless
subprocesses, temporary files, loopback-only pure fixtures, or fake Docker
clients. A future direct live-resource constructor outside the guarded support
surface must add its own hook; the inventory remains the backstop for detecting
such a new path.

## Consequences

### PR26-STAGING-FIX2 candidate capacity correction

This direct, uncommitted implementation candidate records the supplied review's
disposition; no new independent review is required for this revision. Manager
finalization and hosted qualification remain pending. It does not revise the
trusted gate-result contract.

The launcher performs bounded sandbox setup, then measures the already
materialized image's outer writable layer before releasing the canonical runner.
The only mapping described by this candidate is the classic Docker
`overlay2` mapping: exact container inspection must identify an upper directory
under the daemon's `DockerRootDir/overlay2`, and the container's root mount must
identify that same upper directory. Linux OverlayFS forwards `statfs` to its
upper filesystem. This is a restricted qualification target, not a live
target-driver claim: the mapping is inspected on the target and never inferred
from an Engine version. Unknown or unprovable mappings refuse explicitly, and
the layer-filesystem measurement does not claim the whole Docker data root, a
Mac disk, or the source checkout.

A fixed, private, current-owner binding is created for the invocation handoff and
records the schema, owner token, root-mount digest, and issuance metadata. The
read validates its token, mount, schema, and substitution, and rejects an
issuance value that is noninteger, negative, or in the future. Binding age alone
does not expire the invocation: late nested readers may revalidate the same
token and mount after more than 120 seconds while taking fresh `statvfs`
measurements. A different attempt cannot replay the binding because its owner
token differs. A malformed, substituted, or changed-mount binding refuses
and never falls back to scratch measurement; no timestamp refresh or heartbeat
loop extends it. The owner token establishes cooperative invocation identity;
privileged candidate code remains outside any hostile-code security claim. The
parent applies the architectural 10 GiB / 5 percent minimum; the inner
admission retains the selected profile's stronger requirements and all other
admission checks.

Scratch remains an exact 8 GiB tmpfs and exhaustive managed scratch retains its
4 GiB runaway ceiling. `validate_scratch_capacity()` takes no quota or allocated
byte arguments: it independently requires current whole-scratch free space of at
least a 1 GiB policy margin, an exact 8 GiB scratch total, an exact 4 GiB inner
Docker tmpfs, and nonzero inner-Docker free space. This physical check includes
pressure from non-ledger overlay state, metadata, caches, temporary files, and
HOME. The `QuotaTracker` remains the sole effective logical limit, including a
validated override; profile maxima are ceilings, not reservations. The existing
8 GiB integration quota therefore remains supported and accepted by logical
admission, while a separately labelled physical-capacity refusal may occur first
when current scratch headroom is below the margin. No quota is silently lowered,
and a tmpfs limit is not evidence of available physical RAM.

Inner Docker remains independently limited to 4 GiB. Its exhaustion is not a
host-reserve failure. Report bytes remain in `/sandbox-report/report` on the
outer writable layer, including bounded export after stop. Declared tmpfs
limits are not current consumption. Expected mount, filesystem, and decoding
failures at the capacity-helper boundary become bounded capacity-domain
refusals with causes retained privately; raw paths and exception text do not
enter public messages. Cleanup remains in the typed runner path and preserves
primary workload or interruption precedence. The existing degraded-memory and
pressure-attestation checks remain mandatory.

Some outer-container and inner-daemon setup necessarily occurs before a
pre-smoke/pre-pytest capacity refusal because the real backing mapping and
tmpfs measurements must exist first. A refusal therefore does not mean that no
setup occurred. When a report is requested, the outer container is stopped and
the report export is attempted before exact outer removal, at
`/sandbox-report/report` outside scratch; no workload is released after the
refusal.

References: [Docker storage layout](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/)
and [Linux OverlayFS statfs implementation](https://github.com/torvalds/linux/blob/master/fs/overlayfs/super.c).

### PR26-STAGING-FIX3 builder hygiene and outer diagnostics

The pinned Go builder install now runs `go clean -cache -modcache` after a
successful golangci-lint install in the same `RUN`. Both commands must succeed.
The installed binary remains outside those caches; only that binary and GOROOT
are copied from the builder into the runtime stage. This removes avoidable
install-cache content from the committed builder layer. It does not reduce the
compilation peak, quantify disk savings, or establish hosted suite fit. Builder
cache, base layers, final image size, temporary build peak, scratch tmpfs and
inner-Docker tmpfs are distinct observations, not additive independent counters.
The changed recipe hash invalidates reuse of the previous managed recipe;
exact ownership and bounded image retention remain unchanged.

At the outer backing admission boundary, `repomap-sandbox-capacity-v1` records
the `outer_overlay_backing` stage, validated free/total bytes and integer free
percentage, the unchanged 10 GiB/5 percent floors, independent floor outcomes,
and the admitted/refused decision. Invalid or unbound probes emit only a
bounded refusal classification. No paths, mountinfo, owner tokens or raw
subprocess output enter that event. The inherited stderr channel receives the
record before acceptance or refusal, independently of any inner suite report.
If stderr writing fails, stdout receives a bounded channel-failure message and
the diagnostic; if both channels are unavailable, external evidence cannot be
guaranteed, but logging must not replace the primary outcome. No successful or
empty suite report is synthesized for an unreleased workload.

### Hosted lifecycle and evidence

The hosted Staging Gate now exposes only one owned outer container to the
persistent daemon. Postgres and Alpine prerequisites are pulled into the inner
daemon before the canonical inner Docker snapshot, so existing
operation-accounting semantics remain truthful. Immediately after the launcher
validates the exact outer container ID, it starts `docker logs --follow` for
that ID with output inherited by the launcher, so setup and test progress reach
the host while the container is running. After normal container exit, the
launcher waits for the follower to drain the final tail and does not issue a
second whole-log readback. On SIGINT, SIGTERM, or a launcher exception, exact
outer cleanup stops the container and the launcher drains or terminates and
joins the follower so it cannot be orphaned. A follower failure is reported and
fails an otherwise successful run without replacing an earlier test or
interruption result.

Reports remain a separate, explicit operation. The launcher stops the exact
container when needed, validates a fixed-source Docker-copy archive with member
and byte bounds, rejects path traversal, symlinks, special files, duplicate
members, symlinked ancestors, and existing destinations, exports normalized
user-owned regular files/directories, and only then removes the exact outer
container. With no `--report`, it neither reads a report source nor creates a
destination. If GitHub hard-kills the runner
without delivering cleanup time, the last buffered log tail and post-container
report export may still be absent; live following narrows the evidence loss but
cannot make an uncatchable kill recoverable. The Staging Gate's request/result
schemas, SHA binding, read-only permissions, single exhaustive command,
coverage thresholds, scratch admission, and evidence uploads are unchanged.

Sandbox startup adds local image construction and inner prerequisite-pull cost.
The managed dependency cache bounds host image retention; nested daemon state is
deliberately not cached. Rootless DinD is not required by this decision.

The backend remains replaceable. A future disposable JACA Tart Linux VM may run
the same integration suite through DinD or against the VM-owned Docker daemon
directly, because destroying the VM supplies the resource-isolation boundary.
No JACA, Tart, or nesting marker is encoded in test IDs or test semantics.

TEST-ISO2 supersedes the former developer-default distinction: local
integration is now an optional prompt-owned diagnostic through the same
automatic sandbox, while complete integration qualification belongs to the
logically approved hosted Staging Gate. REPOMAP-CI0B-FIX31
proved report export after sandbox removal, inner-daemon prerequisite pulls,
untruncated diagnostic log readback, and unchanged combined `--suite all`
dispatch, then selected the sandbox explicitly in `repomap-staging-gate`.
REPOMAP-CI0B-FIX32 replaces that readback with the owned live follower lifecycle
while preserving report export and cleanup authority. A
future Tart Linux direct-daemon backend remains an interchangeable pollution
boundary rather than a remedy for test-control semantics.

The closed host-effect allowlist is: read the checkout through its explicit
read-only bind; create and remove the exact owned outer container; use the
bounded dependency-only sandbox-image cache; emit stdout/stderr; and export an
explicitly requested validated report. The sandbox exposes no host Docker or
Postgres socket/port, home, SSH/provider/Git credentials, arbitrary device, or
operator-selected writable volume. Before/after host Docker accounting rejects
new unattributed containers, images, volumes, or networks without pruning them.
This remains a pollution-control design for ephemeral runners and VM-backed
Docker: privileged DinD shares a kernel and is not a hostile-code security
sandbox.

## Evidence

The machine-readable entry inventory is
[`../../../testing/test-iso1-entry-capability-inventory.json`](../../../testing/test-iso1-entry-capability-inventory.json).
The TEST-ISO1 exit record owns representative commands, cleanup evidence,
timing measurements, and verification disposition.
The REPOMAP-TEST-ISO1-FIX1 exit record owns the Linux signal characterization,
root-cause evidence, exact correction, and full-population qualification:
[`../../../status/2026/08/22/00783-repomap-test-iso1-fix1-linux-cancellation-continuity-exit.md`](../../../status/2026/08/22/00783-repomap-test-iso1-fix1-linux-cancellation-continuity-exit.md).
The REPOMAP-CI0B-FIX31 exit record owns the hosted listener diagnosis, report
export proof, workflow correction, and remaining remote qualification boundary:
[`../../../status/2026/08/22/00784-repomap-ci0b-fix31-hosted-staging-isolation-exit.md`](../../../status/2026/08/22/00784-repomap-ci0b-fix31-hosted-staging-isolation-exit.md).
The REPOMAP-CI0B-FIX32 exit record owns live-log process lifecycle, failure
precedence, and focused regression evidence:
[`../../../status/2026/08/23/00785-repomap-ci0b-fix32-hosted-sandbox-log-streaming-exit.md`](../../../status/2026/08/23/00785-repomap-ci0b-fix32-hosted-sandbox-log-streaming-exit.md).
