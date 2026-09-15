# Zunit Static Extraction Examples

These files are public-safe ZUNIT0 design examples. They are not production test
fixtures, and they must not be executed.

The examples illustrate future static zunit extraction cases:

- `basic.zunit`: suite/test-case structure, command-under-test intent, and
  simple assertions.
- `hooks.zunit`: setup/teardown-style hooks with mutating-looking cleanup that
  must remain non-executed source intent.
- `assertions-and-commands.zunit`: status/output expectations and
  command-under-test wrappers that must not become runtime execution evidence.
- `helpers-fixtures-mocks.zunit`: helper references, fixture references, mocks,
  and stubs as test-framework intent.
- `dynamic-and-redaction.zunit`: computed tests/helpers/commands and fake
  secret-like values that future extractors must bound or redact.
- `false-positives.zunit`: comments, strings, arrays, heredocs, and case labels
  that look like zunit constructs but should not be over-extracted.

All examples are static extraction input samples only. They use `.invalid`
domains and fake placeholders, contain no real private paths or secrets, and
should remain non-executable.
