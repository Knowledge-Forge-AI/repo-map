# CI71 runtime hygiene repair and bounded CI72 handoff

ADR0098 records the approved conditional repair. CI71 passed eight of nine
jobs; its only system build reached the final combined assertion for absent
build-only Python modules and `/usr/local/include`. The diagnostic does not
identify the failing conjunct. Unit and M integration coverage exceeded their
hard gates by two percentage points. No final image or system scenario resulted.

The candidate adds one `RUN rmdir /usr/local/include` after the runtime Python
payload copy, frozen closure and linker-cache refresh, before runtime Python.
Only an empty real directory can be removed. Nonempty headers, symlinks,
ordinary files and a missing directory refuse. The full final release probe,
dynamic C Psycopg/system libpq checks, package/ownership/hash/version/ABI/license
guards and every base, SDK, dependency and lock input remain unchanged.

The new clean integration owner observes the exact cached native PostgreSQL
base with its entrypoint overridden, no network or server, read-only root and
the declared data path on tmpfs. It requires the pinned platform/config and an
empty real include directory. A manifest-only identity fallback cannot supply
config proof. Refutation or unavailable identity blocks publication. The
existing canonical sandbox supplies its ordinary frozen prerequisites; the
test performs no extra image pull or build.

A separate disposable dependency-only Python container exercises the actual
rendered rmdir instruction and the structurally selected, unchanged header
operand from the final probe. Empty removal, retained nonempty headers,
directory-target and dangling symlinks, ordinary files and missing paths are
distinct cases. `os.path.exists` follows symlinks and sees a dangling target as
absent; rmdir still refuses either symlink. The test restores the original
directory after removing only its controlled fixture, then verifies exact
container cleanup and the resource baseline. This is header-mechanism evidence,
not proof of all build-module absence or an assembled PostgreSQL image.

The owner is mandatory in hosted staging M under unchanged discovery. Local
ARM observation cannot qualify AMD. Hosted staging and the system builder run
alongside each other, so the hosted base observation cannot gate the fourth
start. A missing, nonempty or symlink AMD path can fail the new instruction and
consume the entire slot before the final probe. Passing component checks is
never a forecast of a passing image.

Local proof is bounded to the approved 41 unit paths, three integration owners
and existing ten-check static profile, with `--no-coverage`. At most two further
executions per class raise cumulative maxima to unit13/integration11/static15;
the second requires a finding and correcting change. All historical failed
attempts remain counted. RED1/diagnostic1, complete local suites, local coverage
and local SDK/application builds remain excluded. Exact execution results and
unselected gates belong to the phase commit and primary Exit.

The one-use closed v1 grant/proof pins the actual reviewed decision, immutable
pre-append ledger, source/recipe/Dockerfile, unchanged SDK, exact staging/main
parents and workflow72/attempt1. Only the grant has maxima4/4. Every spent
CI69/70/71 nonce or reservation, stale identity, rerun and other ordinal refuses.
The approved fourth native AMD start belongs solely to the existing system
builder. Any actual or uncertain start spends it; no retry or automatic rearm.
The original held defaults and all prior consumed starts remain preserved.

One normal staging push is authorized after independent review, fresh parent
source/proof/custody acceptance, exact-commit reporting, committed export checks,
fresh remote binding and one atomic exception/reservation/audit append. No
manual dispatch/rerun/cancellation, PR-state, main/tag/history mutation,
dependency/SDK/pin/linkage change, emulation, infrastructure or live deployment
follows. P3, image, platform, incumbent comparison, merge and deployment remain
separate and unaccepted. Hosted CI72 owns complete coverage and native assembled
image results for the exact published candidate.
