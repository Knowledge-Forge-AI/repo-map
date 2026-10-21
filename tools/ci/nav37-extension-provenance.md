# NAV37 Extension Provenance Exit

Phase: `REPOMAP-PRODUCT6-NAVIGATION37-EXTENSION-PROVENANCE1`. [ADR 0084](../../docs/adr/2026/10/0084-extension-aware-backup-and-restore.md)
accepts D9-A only; the [contract](../../docs/specs/postgresql-extension-restore-contract-v1.md)
keeps D9-B and production pgvector admission separate.

PostgreSQL backups now record format-2 provenance. Formats 1 and 2 remain
readable; shared support and actual TOC checks refuse unsupported extensions
before restore creation, drop and graph/control upgrades. Core restore semantics
and graph selection remain. Bounded observations, literal TOC names, namespaced
maintenance custody and exact-route client identities do not establish extension
replay or artifact admission.

Final private scoped checks passed 179 unit and 33 core
containerized integration cases. The public candidate repeats those exact
selections and its static, inventory, ratchet and export checks before publication.
Three dispatcher attempts are drained; final native revision errors remain
recorded. Independent source findings were amended and parent-verified, with no
second independent review after final amendments. The reviewer could not inspect
Git or retained scratch evidence; parent checks supply those separate boundaries.

Complete local suites and Python coverage are unselected. Canonical Go preflight
component coverage is separate. Hosted new-candidate qualification and coverage
remain pending. Requested targets are 87/87 unit and 82/82 integration against
unchanged hard gates 85/85 and 80/80. Optional pgvector remains unqualified by core
CI. Private retention/lineage HOLD is separate; `utility_not_measured`; roadmap
step 6 remains incomplete. Publication stops this bounded continuation.

The public ownership transition admits exactly four new clean retained runtime
modules for this D9-A foundation. All incumbent classifications and historical
authority records remain unchanged; no debt, import edge or ceiling is increased.
