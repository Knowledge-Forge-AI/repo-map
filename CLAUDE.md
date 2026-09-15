# CLAUDE.md

Claude-specific adapter for the RepoMap repository.

- `AGENTS.md` is the shared project canon. This file supplements it and does
  not weaken or override it; when the two appear to conflict, follow
  `AGENTS.md`.
- Project skills live under `docs/ops/skills/` and `docs/contrib/skills/`;
  the `.claude/skills` catalog is their discovery projection, while bodies
  under `docs/` remain canonical.
- Detailed procedure belongs in skills and durable references, not in this
  file. Do not add coding, testing, phase, or Git workflow content here.

Working notes for Claude in this repository:

- Follow the skill-routing table in `AGENTS.md` at task open and use every
  skill that materially applies; one task may require multiple skills.
- Classify each change (docs-only versus source-affecting) before choosing a
  verification gate; docs-only work uses the docs-only gate in
  `repo-map-testing-standards`.
- Treat the safety boundaries in `AGENTS.md` as non-negotiable defaults for
  every suggestion, review, and edit.
- Keep this file within 40 physical lines; move anything larger to a skill
  or durable reference.
