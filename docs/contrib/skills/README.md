# RepoMap Contributor Skills

This directory holds public AI-agent skills for contributors who are modifying
RepoMap source, tests, docs, ADRs, status docs, or phase records.

Operator and runtime skills live under `docs/ops/skills/`. The repository's
`.agents/skills` and `.claude/skills` catalogs are active relative-symlink
discovery projections of both canonical skill roots. Projection bodies are
never canonical.

Current contributor skills:

- `repomap-phase-hygiene`: phase planning, status exits, verification, and
  commit-message hygiene.
- `repo-map-development-standards`: coding and contribution standards for
  RepoMap implementation work.
- `repo-map-testing-standards`: test selection, complete gates, and docs-only
  verification standards.
