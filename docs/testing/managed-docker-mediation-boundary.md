# Managed Docker Mediation Boundary

## Status

Current. `TEST-IMAGE-LIFECYCLE1-R1-OBS1-RECOVER4-W1-R3` delivered the enforced
mediation surface described here; `TEST-IMAGE-LIFECYCLE1-R1-OBS1-ARCHDOCS1-R1`
recorded it as the single durable reference. Before this document the enforced
surface was reconstructible only from source plus scattered phase evidence.

This document is the one place that enumerates what mediation covers. Other
documents cross-reference it rather than restating the surface set.

## Purpose

`repomap_test_support.resource_docker_mediation` makes every image build and
image acquisition in a test or smoke process pass through one canonical
authority, so the managed test-image manager remains the only creator,
selector, attribution owner, and cleanup authority for RepoMap test images.

## Enforced Surfaces

Mediation patches exactly seven surfaces:

1. `docker.models.images.ImageCollection.build`
2. `docker.models.images.ImageCollection.pull`
3. `docker.api.build.BuildApiMixin.build`
4. `docker.api.image.ImageApiMixin.pull`
5. `docker.api.image.ImageApiMixin.import_image`
6. `docker.api.image.ImageApiMixin.load_image`
7. `subprocess.Popen.__init__`, by argv classification

Surfaces 1–6 are the Docker SDK high-level and low-level image routes.
`import_image` and `load_image` are mediated as acquisition alongside `pull`
because each can introduce an Engine image object without a build.

Surface 7 classifies `argv[0]` by basename against the container-runtime set
`docker`, `podman`, `nerdctl`, then inspects the subcommand for a build or a
pull.

## Class Patching, Not Instance Patching

Mediation replaces attributes on SDK **classes and mixins**, never on client
instances. Every client constructed anywhere in the process therefore inherits
the guarded methods, whether it was built through `docker.from_env()` or
through `docker.APIClient()`. No registration, injection, or client-passing
discipline is required of call sites, and a client constructed after mediation
is installed is covered identically to one constructed before.

### Client-construction sites

The repository constructs Docker clients at ten sites: nine `docker.from_env()`
call sites plus one `docker.APIClient()` construction at
`tools/scale12_resource_sampling.py:467`.

The nine `docker.from_env()` call sites are:

- `tools/run_tests.py:373`
- `tools/test_image_cache.py:30`
- `tools/smoke/container_smoke.py:52`
- `src/test/support/python/repomap_test_support/test_cov5k_r2_image_route.py:30`
- `src/test/support/python/repomap_test_support/postgres_container.py:148`
- `src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executors.py:811`
- `src/test/support/python/repomap_test_support/test_cov5k_r2_fix1_executors.py:840`
- `src/test/support/python/repomap_test_support/test_cov5k_r2_fix3_container_pairs.py:81`
- `src/test/int/python/repomap_test_support/test_cov5k_r2_fix3_container_pairs.int.test.py:93`

Two further textual `docker.from_env()` matches are **not** call sites and are
excluded from the count: the explanatory comment at `tools/run_tests.py:371`
and the module docstring at
`src/test/support/python/repomap_test_support/resource_docker_mediation.py:4`.
Because of those two, a naive text search reports eleven matches. There are
nine `from_env` call sites. Do not describe the inventory as "ten `from_env`
sites"; ten is the client-construction total, and one of the ten is an
`APIClient` construction.

## Scope Of The Closure Claim

Closure is claimed **only** over:

- the Docker SDK class surfaces listed above; and
- `docker` / `podman` / `nerdctl` argv classification reached through
  `subprocess.Popen.__init__`.

The generic container-CLI ecosystem is **not** claimed closed. Two bypasses are
honestly excluded rather than defended:

- a wrapper script or shell alias whose `argv[0]` basename is not one of the
  three classified runtimes; and
- process creation through `os.exec*`, which does not route through
  `subprocess.Popen`.

Documentation must not widen this claim. Mediation is a strong structural
guard over the routes RepoMap actually uses, not a sandbox.

## Re-entrancy

In-flight tracking is scoped **per operation kind**, not per process. A
mediated build that internally triggers a pull is still observed and ledgered
as a pull; the outer build's in-flight state does not mask it. The re-entrancy
guard exists to avoid double-counting one operation, not to suppress nested
operations of a different kind.

## Fail-Closed Run-Wide Boundary

`repomap_test_support.resource_docker_boundary.RunWideDockerBoundary` fails
closed. It raises `RunWideDockerResidueError` when the ledger is missing, when
the canonical authority is missing, or when the canonical authority is not
installed. An absent or uninstalled authority is treated as a boundary
violation, never as "nothing to check".

## Lock Scope Limit

The lifecycle single-flight lock is derived from the project root: it lives at
`.scratch/locks/repomap-test-images-<uid>.lock` beneath the checkout, and it
deliberately does not follow the runner's per-run `TMPDIR`.

Serialization is therefore **checkout-scoped**, not host-scoped. Independent
runner processes launched against the same checkout serialize inventory,
build, and GC. Two checkouts sharing one Docker daemon and one
`repomap-test-runtime:*` tag namespace hold separate locks and do **not**
serialize with each other. A host-stable coordinator is deferred, not decided;
no document may claim cross-checkout or global-host coordination exists.

## Preserved Evidence Semantics

### Isolated refusal proof

Proof B's isolated `unmanaged_build_count=1` and `unmanaged_pull_count=1` are
**intentional refusal evidence**. They record that mediation observed and
refused an unmanaged operation, which is the proof's whole point. They must
never be suppressed, refiltered, or reinterpreted as failures. A canonical run
is a different context: there, zero unmanaged operations is the success
condition.

### Single-draw anchors

The proof driver's `attempt_count` and `second_attempt_allowed` fields are
literal payload constants. They are not measurements and must not be cited as
evidence that a single draw occurred. The real single-draw anchors are the
journal-derived build-event count and the run-once scratch guard.

## Related Documents

- `docs/adr/2026/08/0052-managed-test-image-namespace-runtime-cache-and-deterministic-gc.md`
- `docs/testing/test-runner-policy.md`
- `docs/testing/containerized-smoke-test-design.md`
- `docs/contrib/testing-standards.md`
