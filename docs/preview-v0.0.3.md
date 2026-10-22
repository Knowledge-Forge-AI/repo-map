# RepoMap Preview v0.0.3

**Date:** 2026-10-22
**Distribution:** Public source preview. It is not published to any package
manager or registry, and the promotion creates no tag.
**Steward author identity:** Samuel Leighton Lair <sam.lair@knowledge-forge.ai>

The [changelog](../CHANGELOG.md#003---2026-10-22) lists the changes. This note
records the exact public source identity and hosted evidence for the release.
Exact commit identities are given because they are needed to reproduce this
release. All of them resolve in the public repository
[Knowledge-Forge-AI/repo-map](https://github.com/Knowledge-Forge-AI/repo-map).

## Source identity

| Role | Public identity |
| --- | --- |
| Release commit (qualified `staging` head) | `24d15650a2d4563d188acb8bbf34a0dabf8f3d65` |
| Release tree | `9074842664ae831a458e9021a616c0c7f68a4b02` |
| Previous `main` (v0.0.2) | `1bc81cf88d58305251b61e01069a75c932f7d2de` |
| Hosted test merge (parents: previous `main`, then release commit) | `1f425d34de18612bbb23e42890cc9d9f8c69e575` |
| Pull request | [#12](https://github.com/Knowledge-Forge-AI/repo-map/pull/12), `staging` into `main` |

The previous `main` is an ancestor of the release commit, so the hosted test
merge has the release tree. The promotion fast-forwards `main` to the release
commit and creates no squash or merge commit. This is a one-time exception to
the squash convention ([ADR 0086](adr/2026/10/0086-preview-003-staging-ancestry.md)).
The history it keeps is required by the author-metadata proof
([ADR 0085](adr/2026/10/0085-public-author-metadata-correction.md)).

Steward commits in the release range use the author identity above. Historical
committer fields are unchanged, as ADR 0085 specifies.

## Hosted qualification

[Release-qualification run 59](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/39735512802),
attempt 1, was triggered by the pull request. It executed and passed all eight
jobs on the test merge above.

| Job | Result |
| --- | --- |
| source-and-export-policy | passed |
| pre-review-static (20 checks) | passed |
| unit-tests | passed: 13,037, skipped: 40 |
| staging-integration-gate | smoke passed; measured 1,784 passed and 12 skipped; 3 abrupt-behavior cases passed |
| main-system-gate | 5 of 5 scenarios passed; cleanup verified |
| codeql-analysis (go) | passed |
| codeql-analysis (python) | passed |
| sbom-and-vulnerability-scan | passed |

The staging and system reports were validated against the test merge, its
parents and tree, and an independently derived source digest. The coverage
denominator is all 647 product Python files.

| Coverage | Lines | Branches | Hard gate |
| --- | --- | --- | --- |
| Unit | 56,770 / 60,625 (93.64%) | 17,298 / 19,752 (87.58%) | 85 / 85: passed |
| Integration (measured) | 54,528 / 60,625 (89.94%) | 16,167 / 19,752 (81.85%) | 80 / 80: passed |
| Go (staging gate) | 574 / 653 statements (87.90%) | not measured | 80: passed |

The hard gates are unchanged. The 87/87 unit target was met. The 82%
integration branch target was not met: 30 more covered branches were needed.
That target is outstanding. It was not waived and no gate was changed.

## Limits

- The run qualifies the core profile. The optional pgvector profile was not
  part of it, and production pgvector is not admitted.
- This note and other documentation describing the promotion are in a later
  `staging` commit. That commit is not part of the qualified release and is
  not covered by run 59.
- The run produced its standard workflow artifacts. No separate trusted gate
  result was produced, and no deployment is implied.
