# Project Profile Schema

RepoMap profiles describe repository conventions that the generic discovery
rules cannot know on their own. Profiles are optional: basic discovery works
without one, and profile facts should remain explicit instead of being
hardcoded into the engine.

Profiles are TOML files. The initial schema supports directory roles and exact
path overrides:

```toml
command_dirs = ["bin", "ops"]
script_dirs = ["scripts"]
generated_dirs = ["build/generated"]

[role_overrides]
"README.md" = "documentation"

[confidence_overrides]
"README.md" = "manual"
```

Fields:

- `command_dirs`: repository-relative directories whose files should be treated
  as user-facing entry points.
- `script_dirs`: repository-relative directories whose files should be treated
  as internal scripts.
- `generated_dirs`: repository-relative directories whose files should be marked
  as generated.
- `role_overrides`: exact repository-relative paths mapped to roles.
- `confidence_overrides`: exact repository-relative paths mapped to confidence
  labels.

Valid roles are `config`, `documentation`, `entrypoint`, `generated`, `script`,
`source`, `test`, and `unknown`.

Valid confidence labels are `extracted`, `heuristic`, `manual`, and `unknown`.

The discovery CLI accepts an optional profile:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --profile repomap-profile.toml --jsonl
```
