#!/usr/bin/env gawk -f
# Static extraction fixture only. Do not execute.

@include "lib.awk"

BEGINFILE {
  seen_file = FILENAME
}

ENDFILE {
  print FILENAME
}

BEGIN {
  converted = gensub(/a/, "b", "g", "alpha")
  FPAT = "([^,]+)|(\"[^\"]+\")"
  PROCINFO["sorted_in"] = "@ind_str_asc"
}
