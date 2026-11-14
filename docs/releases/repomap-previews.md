# Historical RepoMap public source previews

The repository is now named Common Lore Index. These are the existing RepoMap
source releases, with annotated tags and GitHub prerelease entries backfilled
on 2026-11-13. Tag creation does not rewrite commits or imply new qualification.

| Version | Original source promotion | Exact corrected-history commit | Release |
|---|---|---|---|
| v0.0.1 | 2026-09-15 | `001cac6298ff18b272e2f92a4c5ff8b047cdfbcf` | [RepoMap v0.0.1](https://github.com/Knowledge-Forge-AI/common-lore-index/releases/tag/v0.0.1) |
| v0.0.2 | 2026-10-08 | `1bc81cf88d58305251b61e01069a75c932f7d2de` | [RepoMap v0.0.2](https://github.com/Knowledge-Forge-AI/common-lore-index/releases/tag/v0.0.2) |
| v0.0.3 | 2026-10-29 | `5ad00d162ad8a04430874275246a53227578c533` | [RepoMap v0.0.3](https://github.com/Knowledge-Forge-AI/common-lore-index/releases/tag/v0.0.3) |

The v0.0.3 tag identifies the **final** closeout promoted through PR13 after
[CI87 attempt1](https://github.com/Knowledge-Forge-AI/common-lore-index/actions/runs/40779161422).
It has tree `5a6f7a1402d0aa77c86c214bc9419eb6f8c1e8c6`. All nine jobs passed;
unit coverage was 87.9763% statements/87.6070% branches and measured integration
90.1658%/82.3417%, above the unchanged 85/85 and80/80 hard gates.

The earlier [v0.0.3 promotion note](../preview-v0.0.3.md) records the interim
2026-10-22 promotion and CI59. It remains historical evidence, distinct from
the final CI87/PR13 source now tagged v0.0.3. The final source and corrected
author ancestry are preserved. Optional pgvector, other platform and deployment
acceptance were separate from that core qualification.

These previews have GitHub source archives only. No package-manager or container
registry publication is implied. The first release under the Common Lore Index
name is the prospective v0.0.4, conditional on its own passing qualification.
