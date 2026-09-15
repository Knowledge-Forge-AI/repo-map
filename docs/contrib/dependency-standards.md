# RepoMap Dependency Standards

Dependencies should have a clear project benefit and should fit RepoMap's
runtime, packaging, and safety model.

## Evaluation Priorities

Evaluate dependency proposals in this order:

1. Performance benefit.
2. Readability benefit.
3. Reduction in code size or maintenance burden.

Those priorities do not replace engineering judgment. A small amount of simple,
well-tested local code may be better than a dependency. A dependency can be the
right choice when it makes behavior more correct, maintainable, or efficient.

## Review Criteria

Before adding a dependency, consider:

- stability and release cadence;
- maintainer organization and project health;
- security posture and vulnerability history;
- license compatibility with RepoMap;
- packaging and platform compatibility;
- runtime footprint and transitive dependency risk;
- compatibility with local containerized test and smoke environments;
- operational impact on CLI, MCP, extraction, canonicalization, storage, and
  readback workflows.

Document substantial runtime, storage, CLI, MCP, extraction, canonicalization,
or security-impacting dependency decisions in an ADR or contribution note. For
performance-sensitive claims, benchmark or demonstrate the benefit where
practical.

Do not add dependencies merely to avoid small/simple code. Do not introduce
any dependency unless the accepted phase explicitly allows it; in particular,
do not introduce parser or runtime dependencies in static extraction phases
without that explicit allowance.
