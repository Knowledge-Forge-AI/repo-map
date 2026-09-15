# Awk Static Extraction Examples

These files are public-safe AWK0 design examples. They are not production test
fixtures, and they must not be executed.

The examples illustrate future static awk extraction cases:

- `basic.awk`: shebang, BEGIN/END blocks, pattern/action rules, fields,
  records, and a function.
- `io-and-pipes.awk`: file reads, file writes, command pipes, and `system()`
  source examples that must never be executed by extraction.
- `dynamic.awk`: dynamic file, command, regex, and field expressions that
  should become bounded dynamic or unknown evidence.
- `false-positives.awk`: comments and strings that look like awk constructs or
  command text but should not be over-extracted.

All examples are static extraction input samples only. They use fake
placeholders and `.invalid` domains where needed, contain no real private paths
or secrets, and should remain non-executable.
