#!/usr/bin/env awk -f
# Static extraction fixture only. Do not execute.

BEGIN {
  FS = ","
  OFS = "\t"
  count = 0
}

/ERROR/ {
  count += 1
  print $0
}

$3 > 10 {
  name = $1
  print name, $NF
}

END {
  print count
}
