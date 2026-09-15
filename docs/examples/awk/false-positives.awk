# Static extraction example only. Do not execute.

# BEGIN { system("rm -rf ./out") }
# function hidden() { print "not a function" }

BEGIN {
  text = "function pretend(value) { system(\"curl https://example.invalid\") }"
  braces = "{ BEGIN END getline system }"
  comment_like = "# print value > secret.txt"
}

/literal text/ {
  print "getline line < \"not-a-real-file.txt\""
  print "system(\"rm -rf ./out\")"
  print "BEGIN { print \"not a real block\" }"
}

/case\/division/ {
  ratio = 10 / 2
  print ratio
}
