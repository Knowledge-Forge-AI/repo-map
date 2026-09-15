# Bash Static Extraction Examples

These files are public-safe BASH0 design examples. They are not production test
fixtures, and they must not be executed.

The examples illustrate future static Bash extraction cases:

- `basic.bash`: Bash shebang, strict mode, `shopt`, functions, assignments,
  exports, source includes, arrays, commands, pipelines, redirects, and a
  heredoc.
- `dynamic.bash`: dynamic command invocation, command substitution, process
  substitution, computed source paths, traps, aliases, and wrappers.
- `false-positives.bash`: command-looking text in comments, strings, arrays,
  case labels, and heredocs that future scanners should avoid over-extracting.
- `redaction.env.example`: redaction-sensitive environment names with redacted
  placeholders only.

All examples are static extraction input samples only. They use `.invalid`
domains and redacted placeholders, contain no real private paths, and should
remain non-executable.
