# Common Lore Index transition and v0.1.0 delivery

## Accepted direction

The operator authorized advancing the reviewed remaining-roadmap proposal on
2026-10-29. The selected identity is Common Lore Index (CLOE), distribution
`common-lore-index`, preferred executable `cloe`, home selector `CLOE_HOME`,
default `~/.cloe`, and base/local configuration suffixes `.cloe.toml`
and `.local.cloe.toml`. These are target surfaces, not a claim that the full
rename has shipped. ADR0118 selects `common_lore_index` and installed ownership;
ADR0123 defines their coordinated source cutover and finite compatibility. Preserve the current license and
Samuel Leighton Lair <sam.lair@knowledge-forge.ai> as public commit identity.

## Starting point and working custody

Public main is v0.0.3 at `5ad00d162ad8a04430874275246a53227578c533`, qualified
by [CI87 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40779161422).
All nine jobs and the retained same-attempt system/staging contracts pass;
Python unit and integration coverage meet the two-point margin. Core
qualification does not establish optional pgvector usefulness/admission,
hosted ARM/Windows support or deployment acceptance. ADR 0105 retains the
informational treatment of inherited Debian issues.

The qualified public tree is the implementation baseline for compatibility
preparation. Preserve the private checkout's concurrent tracked/untracked work
and the three-way reconciliation map. This does not declare private-line
reintegration complete. Resolve those differences before a broad namespace
move; do not reset or mirror public content over protected private work.

## Dependency-ordered milestones

| Workstream | Outcome and acceptance |
|---|---|
| W0 | Reconcile release evidence, current docs and private/public implementation custody; preserve historical reports and private-only material. |
| W1 | CLOE rebrand and compatibility: config/home, packaging, commands, import/resource ownership and supported migration/recovery. |
| W2 | Query modes, privacy and publication-bound text projection, representative tasks, baselines and grading before tuning. |
| W3 | Useful measured PostgreSQL native FTS with identifier/phrase policy; evaluate optional trigram matching within extension admission. |
| W4 | Intent-aware navigation and compact context with valid serialized-byte bounds, provenance, omission accounting and advisory freshness. |
| W5 | Useful optional pgvector and measured fusion after the lexical baseline, plus the named-workload JSONB disposition. |
| W6 | Bounded Rust extraction and quality/performance pilot through retained Python semantics and parser-helper admission. |
| W7 | Measure and govern actual expensive work; qualify first useful Local/Server and mixed-material experiences. |
| W8 | Exact-candidate installed/release qualification and an evidence-backed v0.2.0 search-engine decision. |

W1 starts with [configuration compatibility](../ops/cloe-config-compatibility.md)
under [ADR 0109](../adr/2026/10/0109-cloe-configuration-compatibility.md).
Its usable new-format loader and inert filename planner are a preparatory
milestone; full rebranding and live migration remain subsequent work.

CI92 qualified the configuration compatibility/recovery milestone on staging
`bec838a210f3ffea84986ae85986e4081b2e8291`, with all nine jobs passing and
the retained same-attempt staging obligations verified. The next W1 milestone,
[ADR 0112](../adr/2026/10/0112-cloe-runtime-configuration-producer.md), enables
explicit CLOE runtime setup and existing-family detection, with guarded targets,
dry-run replay and connected configuration/mount readback. It retains legacy
empty-home defaults and is not the broad namespace/default-home/data migration.
CI93 attempt 1 qualified that runtime-setup candidate at
`433a2edf89284f71f10996d20c88bcf3e311c9de`, including all nine jobs and the
retained same-attempt staging/system obligations. That result does not qualify
the local successors described below.

[ADR 0114](../adr/2026/10/0114-cloe-config-migration-apply-recovery.md) adds
explicit, confirmed configuration filename apply, rollback and finalize for an
owned private home. It uses durable journaled backups, crash recovery and
drift refusal. It does not change the default home, namespaces or data. Its
hosted qualification is now established by CI95 attempt 1 on staging
`ed23f6fff49b7796ee70e50e29d6e4db4779d6fe`, together with the W0 runner recovery
and its CI94 corrections. All nine jobs passed. Retained same-attempt smoke/M/A
and system contracts validate against independently derived committed source;
unit coverage is 88.1/87.6 and measured integration coverage 90.1/82.1, exceeding
the hard floors by at least two percentage points. This does not qualify later
local successors or perform a main promotion.

[The W0 custody audit](cloe-development-custody-v1.md),
REPOMAP-CLOE-CUSTODY1, preserves private work and distinguishes public successor
fixes from meaningful unincorporated harness work. It restores command-contract
characterization, the nonempty ICU-version assertion and accurate current
Local/Server descriptions. The subsequent
[ADR 0115](../adr/2026/10/0115-bounded-runner-failure-diagnostics.md) source slice
integrates typed first-cause retention, safe discovery diagnostics and guarded
cleanup, closing that mandatory W0 follow-up with scoped proof and independent
review. Preserved private experiments retain their W2/W5 owners; blanket
private-line reintegration and hosted successor qualification are not implied.
[ADR0118](../adr/2026/10/0118-cloe-installed-ownership-and-safe-home-selection.md)
settles the coordinated W1 distribution/import/resource/command ownership direction.
Safe default-home selection and current resource-ownership preparation form the
milestone qualified by CI97 attempt 1 on staging
`b90fa8e9c8126be2eac73620001c3869b2cf8e33`, including its two eager-facade
compatibility corrections. All nine jobs and retained same-attempt smoke/M/A
and system contracts pass; unit coverage is 88.0/87.6 and integration90.1/82.2,
meeting both two-point margins. The canonical distribution/import/resource/entrypoint
cutover remained atomic and subsequent at that checkpoint. Current scoped proof
and hosted successor qualification remain distinct.

[ADR0121](../adr/2026/10/0121-installed-ownership-diagnostics-and-service-upgrade-compatibility.md)
adds the next two-part upgrade prerequisite: explicit categorical installed-owner
diagnostics and exact persisted-service module recognition/reinstallation recovery.
The ordinary identity payload stays stable; legacy definitions never become
healthy or reactivate during failed uninstall. This is source preparation for
the atomic move, not installed-package qualification. The
[consumer inventory](../ops/cloe-installed-upgrade-compatibility.md) preserves the
documented configuration-migration Python API and names the remaining facade,
module-path projection and disposable install-order obligations. No blanket
no-facade policy or historical-authority rewrite is accepted.

Keep SQLite Local useful without Server or enrichment dependencies. Search
projections are derived from accepted captured material with privacy and
publication identity; they are not another graph authority. Current MCP
readers remain source-blind. Any body-text query gets an explicit capability
contract; even locator-only matching can expose private information.

Compare competent native tools, existing graph behavior, native FTS and graph,
compact context, then vectors/fusion on the same selected material and tasks.
Include correctness and failed attempts in cost results. Define numeric
criteria from the baseline before held-out evaluation. No fixed savings claim
or superiority follows from another project's marketing or a working SQL query.

OpenSearch/Elasticsearch implementation, public corpus services, Cloud alpha,
GUI/federation, a broad language rewrite and unqualified Windows claims remain
outside required v0.1.0 delivery. Versions below v0.1.0 remain GitHub source
previews; package-manager publication starts no earlier than v0.1.0.

## Coordinated W1 namespace milestone

CI98 attempt1 qualified staging `6d818ad6d43d38d47c64b8c474c2b64b853f631a`,
including all nine jobs and retained same-attempt contracts. Unit coverage was
88.1/87.7 and measured integration coverage90.1/82.2, meeting both two-point margins.
That result qualifies the prerequisite, not the successor package cutover.

[ADR0123](../adr/2026/10/0123-coordinated-cloe-package-and-namespace-cutover.md)
coordinates canonical source, distribution, resources, commands, finite documented
compatibility and installed ownership proof. Its strict source/document projection
preserves every historical authority and numerical debt ceiling. Local preparation
and exact source-edge checkpoints are combined with current consumer work before
one larger public campaign. Hosted qualification of this successor remains pending.
Live home/service migration, package-manager publication, repository rename and
release promotion remain separate. W2 follows the accepted dependency order after
this W1 milestone is qualified; preserved private experiments are not automatically
accepted or overwritten.
