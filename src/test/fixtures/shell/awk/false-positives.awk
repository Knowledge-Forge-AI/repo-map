# Static extraction fixture only. Do not execute.

# BEGIN { system("rm -rf ./out") }
# function hidden(value) { print value }
# /FAKE/ { print $0 }
# @include "comment-only.awk"

BEGIN {
  text = "function pretend(value) { system(\"curl https://example.invalid\") }"
  braces = "{ BEGIN END getline system }"
  comment_like = "# print value > secret.txt"
  include_like = "@include \"not-loaded.awk\""
  pipe_like = "print value | \"sort\""
}

/literal text/ {
  print "getline line < \"not-a-real-file.txt\""
  print "system(\"rm -rf ./out\")"
  print "BEGIN { print \"not a real block\" }"
  print "@load \"not-loaded\""
}

/WARN|ERROR/ {
  print "regex alternation only"
}

/case\/division/ {
  ratio = 10 / 2
  print ratio
}
