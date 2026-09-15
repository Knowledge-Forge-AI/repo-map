# Bats Static Extraction Examples

These files are public-safe BATS0 design examples. They are not production test
fixtures, and they must not be executed.

The examples illustrate future static Bats extraction cases:

- `basic.bats`: `@test` blocks, simple `run` use, assertions, and a skip.
- `helpers-and-loads.bats`: hooks, `load`, `bats_load_library`, and fixture path
  conventions.
- `run-and-assertions.bats`: status, output, line, file, directory, and
  refutation helpers with bounded expectations.
- `false-positives.bats`: comments, strings, arrays, and heredocs that look like
  Bats tests or assertions but should not be over-extracted.

All examples are static extraction input samples only. They use `.invalid`
domains and redacted placeholders, contain no real private paths, and should
remain non-executable.
