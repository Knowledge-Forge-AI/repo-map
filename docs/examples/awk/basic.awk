#!/usr/bin/env awk -f
# Static extraction example only. Do not execute.

BEGIN {
  FS = ","
  OFS = "\t"
  count = 0
}

/ERROR/ {
  count += 1
  print normalize($0)
}

$3 > 10 {
  name = $1
  print name, $NF
}

function normalize(value,    trimmed) {
  trimmed = value
  return trimmed
}

END {
  print count
}
