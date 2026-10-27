# CI70 runtime linker-cache repair

Phase `REPOMAP-PRODUCT6-NAVIGATION47-CI70FIX1` follows
[ADR 0097](../../docs/adr/2026/10/0097-runtime-linker-cache-and-bounded-amd-attempt.md).

[CI70](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40404913486)
passed eight of nine jobs. The system build failed in the strict release probe:
`libpython3.so` could not resolve `libpython3.12.so.1.0`. The runtime recipe now
refreshes its linker cache after copying Python and installing the frozen closure,
before using runtime Python. The release probe and all package, dynamic C Psycopg,
system-libpq, hash, version, ABI and license checks remain unchanged.

The scoped regression owners cover runtime-stage ordering and the actual ELF
checks across a missing cache, cache refresh and a missing library inside one
disposable, networkless dependency-only test container. That mechanism case is
not an assembled PostgreSQL image qualification. Actual scoped commands and
results belong to the phase commit and retained exact-source evidence.

The operator approved one additional native AMD application start through the
existing sole system builder: three cumulative starts, with the earlier two
still spent. The one-use grant binds the exact decision, cumulative ledger,
source/recipe/Dockerfile and unchanged SDK to PR13 synchronize, workflow 71,
attempt 1. Both spent nonce/reservation pairs, stale candidates and reruns refuse.
An actual or uncertain start consumes this allowance even on failure; no retry.

Local scoped proof is bounded at cumulative unit 11/integration 9/static 13, using
41 unit paths and the same two integration owners with `--no-coverage`.
Complete local suites, local coverage and SDK/application builds are excluded.
Coverage thresholds and the two-point targets remain unchanged.

One normal staging publication may trigger the existing automatic campaign.
Native assembled-image and complete hosted coverage results remain pending.
P3, image/platform acceptance, incumbent comparison, merge and deployment remain
separate. Public main stays preview 0.0.3. No manual rerun/dispatch, PR-state,
main/tag/history mutation, new dependency/pin, static linking or live deployment
is included.
