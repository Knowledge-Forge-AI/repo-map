# Debian stable slim maintenance

ADR 0105 makes inherited Debian findings informational. RepoMap owns current
official stable-slim inputs, its assembly changes, runtime functionality,
dynamic Psycopg linkage, evidence integrity and cleanup. An affected Debian
package does not imply that RepoMap CI must fail or that Debian was fixed.

Before a new runtime/staging publication, run the read-only metadata check:

```sh
python3 tools/ci/debian_base_refresh.py --output-json <unused-evidence-path>.json
```

The check resolves the official stable release and current Trixie slim image,
then the selected official PostgreSQL and Python derivative tags. It verifies
both native platform configurations, their stable-slim root layer and the
immutable runtime pins. It downloads no image layers and executes no image.
Exit 1 means pins need refresh; an exception means provenance is unestablished.
This maintenance check is separate from vulnerability scanning and functional CI.

When pins change, update release.py and the exact platform config/package and
Python-payload metadata together. Retain the registry observation and archive
inspection, refresh the native-input envelope/hash and generated workflow
contracts, and prove compatibility through scoped tests and hosted native
preflight. Update tools/ci/debian_stable_slim.json with the frozen observation.
Do not substitute a mutable FROM, infer native execution from metadata, carry
old native results onto a changed image, or repair Debian packages downstream.
An upstream refresh after a campaign is frozen is handled at the next
publication, without invalidating an in-progress candidate.

The SDK and Go stages are build tools governed by their own pinned recipes;
their operating-system trees are not copied into the final runtime. The final
PostgreSQL and Python runtime inputs both derive from current stable slim.
Updating a toolchain or SDK recipe still requires its own compatibility work.
No scheduled job, additional application build, retry, main promotion or live
deployment is implied by this procedure.
