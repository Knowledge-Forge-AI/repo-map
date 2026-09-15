# Shell-Family Static Extraction Examples

These files are public-safe design examples for SH0. They are not production
test fixtures, and they must not be executed.

The examples illustrate future static extraction cases for Bash, Bats, awk,
zsh, and zunit work:

- `basic.sh`: shebang, options, functions, assignments, exports, sourcing,
  commands, arguments, pipelines, redirects, and heredocs.
- `side-effects.sh`: uncalled function containing mutating-looking operational
  commands that future extractors should classify conservatively.
- `dynamic.sh`: dynamic invocation, command substitution, process substitution,
  computed source paths, traps, aliases, and arrays.
- `redaction.env.example`: redaction-sensitive variable names with redacted
  placeholder values only.

All examples are static extraction input samples only. They use `.invalid`
domains and redacted placeholders, contain no real private paths, and should
remain non-executable.
