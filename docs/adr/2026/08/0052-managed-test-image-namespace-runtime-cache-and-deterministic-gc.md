# ADR 0052: Managed Test Image Namespace, Runtime Cache, And Deterministic GC

## Status

Accepted for TEST-IMAGE-LIFECYCLE1 implementation. This decision supersedes
ADR 0048's default that ordinary smoke can only consume an operator-prepared
image. It does not rewrite ADR 0048 or weaken its ownership invariants.

## Date

2026-08-16

## Context

The stopped TEST-RUNNER-SAFETY3-FINAL candidate proved the canonical pytest
population and coverage gates but could not start smoke because its historical
exact local image ID was absent. Requiring each phase to prepare or identify a
manual image encourages indistinguishable local images and leaves cache
retention to agent judgment.

ADR 0048 correctly prohibits broad prune, guessed ownership, mutation of
shared or unrelated images, mutable deployment selection, and cleanup without
exact current-run attribution. Its ordinary-smoke no-build default is narrower
than those safety goals and is replaced here by one repository-owned manager.

## Decision

### Image classes and namespaces

Deployment runtime images use `repomap-runtime:<deployment-identity>`. Newly
managed deployment tags never use `latest`. Test-image selection and GC never
select or remove this namespace.

Reusable dependency-only test images use:

```text
repomap-test-runtime:py<major><minor>-<architecture>-<fingerprint-prefix>
```

They carry the exact managed, class, schema, full-fingerprint, and repository
labels defined by TEST-IMAGE-LIFECYCLE1. They are persistent cache state, not
current-run residue.

Ephemeral build-test images use
`repomap-test-ephemeral:<run-id>-<ordinal>` and carry exact managed, class,
schema, run-ID, and repository labels. They are current-run resources and are
removed by exact Engine image ID at run close.

Legacy `repomap-runtime-<hash>:latest` images are
`legacy_unclassified`. Their names do not prove deployment or test ownership.
Automation inventories but never retags or deletes them.

### Runtime identity

The runtime fingerprint is SHA-256 over canonical sorted-key JSON containing:

- recipe schema;
- Docker server architecture;
- configured exact base reference, local Engine ID, and RepoDigests;
- Python base family and version;
- normalized `[project].dependencies` from `pyproject.toml`;
- lock or resolution input when the repository owns one;
- the project Psycopg release input; and
- explicit canonical-smoke runtime extras.

Candidate commit, candidate source hashes, phase, run ID, wall time, and random
values are excluded. Dynamic or unextractable dependency declarations fail
closed. The current repository has no runtime lock input, so that field is
canonically `null` rather than inferred.

### Dependency-only build

The manager materializes from the configured exact Python base and installs
only the normalized declared runtime dependencies. It creates one label-free,
exactly ledgered temporary container under a collision-resistant run-bound
name and a checkout-stable mode-0600 intent/created manifest. The manifest binds
project, phase, run ID, role, name, exact base ID, exact returned container ID,
stable materialization network mode, and ledger path so an interrupted
materialization is recovered before the next run-wide Docker snapshot. The
manager installs and probes dependencies there,
commits that container once as the final managed runtime-cache image, and
exactly removes the temporary container before ensure returns. This path does not call
the Docker image builder and therefore does not materialize runtime-build
intermediate Engine image objects or opaque builder cache state. The recipe
does not copy RepoMap source and does not install the RepoMap package. Smoke
continues to mount the current checkout read-only at `/workspace` and selects
`/workspace/src/main/python` through `PYTHONPATH`.

Successful ensure requires exactly one new Engine image ID when materializing:
the exact final ID returned by `container.commit`. Any additional image ID is
unattributed, is never deletion authority, and fails the operation. Failed
materialization still attempts exact temporary-container cleanup; cleanup
failure is terminal as `managed_runtime_build_cleanup_failed` and never
broadens to a prune or force-removal path.

Dependency acquisition uses the stable repository-owned policy
`dependency-acquisition-built-in-bridge-v1`. The label-free materialization
container may attach only to the Engine's pre-existing built-in `bridge`, after
readback proves name `bridge`, driver `bridge`, and local scope. The manager has
no network-creation path. The container has no repository source, credential,
or volume mount. This exception ends when materialization cleanup removes the
exact ledgered container; the built-in bridge must remain the same pre-existing
network object. Runtime dependency probes and ordinary smoke/product-test
containers remain network-disabled.

The bridge is transient materialization machinery, not final runtime content.
It is therefore excluded from the runtime fingerprint: the exact dependency
specifications, resolved installed versions, immutable base, architecture, and
final runtime contract remain the identity-bearing inputs. No phase, run,
time, random, or candidate-source input is added to force freshness.

Every failed materialization retains private structured evidence containing
the stage, exact container ID and repository-owned name, configured and
read-back network mode, command category, exit code, separate stdout/stderr,
nested exception type/message/chain, cleanup result, and final presence. The
normal raised error remains bounded; private raw streams are not copied into
ordinary terminal or public report output. A proof/evidence path refuses an
opaque outer materialization error without the structured inner record.

Repository-owned development proof schema `2` is a fixed identity namespace
for exercising the same materializer when canonical schema `1` is already
cached. It changes only the canonical `recipe_schema` field and grants no
additional image or cleanup authority.

Persistent runtime-cache images have a closed label schema: managed `true`,
class `runtime-cache`, schema `1`, repository `repo-map`, and the full runtime
fingerprint. No other label is accepted. In particular, current-run resource
phase, project, retention, role, and run-ID keys are absent rather than empty.
Docker commit merges a source container's labels and cannot remove inherited
keys, which is why the materialization container deliberately carries no
Docker labels; its equivalent positive ownership lives in the persisted exact
ledger/manifest/name claim instead.

The configured acquisition reference is exactly
`<repository>[:<optional-tag>]@sha256:<64 lowercase hex>`. The optional tag is
human version-selection metadata. Immutable Engine authority is the canonical
repository plus exact digest, rendered `<repository>@sha256:<digest>`; a
registry port is part of the repository and is never parsed as the optional
tag. On a miss, under the same checkout-stable single-flight authority as
runtime build and GC, the manager repeats exact local lookup and pulls only that
canonical repository digest. Engine RepoDigests pass only when at least one
entry has the same canonical repository and exact digest. Same-digest
different-repository, same-repository different-digest, tag-only, and
Engine-ID-only matches are insufficient. The exact Engine image ID remains
separate provenance. Mutable tags, registry discovery, alternative bases,
fallback digests, and agent-selected acquisition are prohibited.

Architecture comparison uses only the closed aliases `arm64`/`aarch64` to
`arm64` and `amd64`/`x86_64` to `amd64`. Other values compare only when both
are the same exact lowercase token; differing or fuzzy values fail closed. Raw
image and server values remain evidence alongside the canonical pair.

A newly pulled base is persistent `managed_external_test_base_cache` state only
when the manager and ledger retain its exact creation, repository digest,
Engine ID, and architecture and terminal Engine readback still matches. It is
reported separately from RepoMap runtime caches, never consumes one of their
two retention slots, and is never removed by test GC because its layers may be
shared outside RepoMap.

### Single manager and smoke integration

`repomap_test_support.resource_test_images.TestImageManager` is the only
test-image creator, selector, attribution owner, and cleanup authority.
Individual tests and smoke do not build, pull, prune, or remove images outside
that manager.

Runtime ensure and GC use one owner-only checkout-stable lock under the
repository-owned ignored scratch directory, at `.scratch/locks` beneath the
project root, named per uid. The lock deliberately does not follow the runner's
per-run `TMPDIR`, so independent runner processes launched against the same
checkout serialize inventory, build, and GC.

Stability holds per project root, not per host. Two checkouts sharing one
Docker daemon and one `repomap-test-runtime:*` tag namespace hold separate
locks and do not serialize with each other; a host-stable coordinator is
deferred, not decided. Mid-run external removal of the scratch lock directory
can cause two processes to flock different inodes. That is an explicit
non-goal, not a defended property.

Canonical smoke asks the manager to ensure and validate the dependency runtime,
then consumes the exact returned Engine image ID. An explicit exact-ID override
remains a diagnostic input. It grants no ownership or cleanup authority and is
never interpreted as a deployment-image classification.

### Run-wide boundary

A new current-run image may remain at terminal close as
`managed_persistent_test_runtime_cache_image` only when the manager records its
exact ID, the ledger records observed current-run creation without cleanup
authority, and terminal Engine readback proves the full labels, matching
fingerprint, test-runtime-only tags, and absence of any deployment tag.

The runner reports `new_managed_external_test_base_images`,
`new_managed_test_runtime_cache_images`, `new_unattributed_images`,
`current_run_ephemeral_image_residue`, and runtime-build-intermediate
created/removed/residue counts separately. It also closes every canonical
image build or pull into product/build-profile builds, managed test-runtime
builds, managed external-base pulls, unmanaged builds, and unmanaged pulls.
Product/build-profile and unmanaged counts must be zero; each managed count may
be zero or one. The container-commit materializer reports zero intermediate
created, removed, and residue. Managed persistent caches are accepted state.
Unattributed images, intermediate residue, and ephemeral residue remain
failures.

### Deterministic GC

Repository policy retains at most two managed RepoMap runtime-cache images.
The requested image is protected. Every image referenced by any existing
container is protected and reported as `gc_deferred_in_use`. Remaining managed
cache images are ordered by Docker `Created` timestamp and exact image ID;
oldest candidates are removed by exact ID until only the requested image and
newest eligible previous image remain.

Each removal requires positive managed labels, repository `repo-map`, class
`runtime-cache`, schema `1`, test-runtime-only tags, no container reference,
`force=False`, `noprune=True`, and exact absence readback. GC never uses a
repository wildcard, prefix-only deletion, dangling or age heuristics, or any
prune API.

An otherwise fully labelled managed runtime cache that has lost every tag is
never selected or accepted as persistent terminal state. It remains eligible
for exact-ID GC as a recoverable managed orphan; any non-test tag makes it
ambiguous and therefore non-removable.

### Ephemeral cleanup

The manager ledgers exact ephemeral IDs created for the current run. Closeout
removes only those IDs, refuses container-referenced images, and proves exact
absence. Cleanup failure is terminal and never expands deletion scope.

## Scope And Non-Scope

This decision authorizes the managed test-image lifecycle, smoke integration,
run-wide accounting, deterministic cache GC, unit fakes, one safe development
proof, and read-only legacy inventory.

It does not authorize legacy migration, deployment retagging or deletion,
broad prune, registry discovery, mutable or arbitrary pulls, final canonical
qualification, promotion of the stopped 53-path candidate, commit, or remote
publication.

## Alternatives Considered

Continuing manual image preparation was rejected because it leaves cache
identity and retention outside the repository. Candidate-keyed images were
rejected because mounted source is already the candidate authority and would
recreate one image per phase. Reusing deployment images was rejected because it
collapses independent ownership classes. Tag-only or dangling-image GC was
rejected because neither proves ownership.

## Consequences

Ordinary smoke can acquire one configured immutable external base when absent,
create one dependency cache, and reuse both across candidate phases. RepoMap
runtime-cache disk use remains bounded to two eligible entries plus explicitly
deferred in-use images. The external base is separate shared cache state.
Deployment and legacy images remain outside test GC authority.

The deployment namespace correction means a later deployment build uses
`repomap-runtime:<deployment-identity>` and may build a new image instead of
reusing an ambiguous legacy `repomap-runtime-<hash>:latest` tag. This phase does
not retag or delete that legacy image.

The runtime build still depends on exact pinned package declarations and the
configured immutable base. Network authority is limited to exact base
acquisition when absent and the materialization-only built-in bridge policy;
it grants no network access to runtime or smoke containers.

## Verification Strategy

Fake-owned and process-concurrent tests cover exact-digest acquisition,
fingerprint identity, namespace refusal, reuse, single pull/materialization,
post-acquisition RepoDigest and architecture refusal, GC ordering and in-use
protection, one-final-image enforcement, exact temporary-container cleanup,
expected bridge-mode recovery and wrong-mode refusal, opaque-failure refusal,
ephemeral exact cleanup, smoke network isolation, handoff, and run-wide
classification. A real
development proof exercises manager ensure, dependency probe, mounted-source
smoke, exact GC, and terminal accounting.

## Refresh Conditions

Revisit when RepoMap changes the lifecycle serialization or container-commit
materialization mechanism, the Python base or dependency resolver, changes
exact-digest acquisition authority, requires cross-architecture caches,
changes the two-image retention bound, or Docker changes image label,
reference, commit, removal, or Created-time semantics.
