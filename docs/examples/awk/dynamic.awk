# Static extraction example only. Do not execute.

BEGIN {
  command = "printf dynamic-example"
  output_file = "./out/" ENVIRON["EXAMPLE_NAME"] ".txt"
  field_index = 2
  dynamic_regex = ENVIRON["EXAMPLE_PATTERN"]
}

$0 ~ dynamic_regex {
  print $(field_index) > output_file
  command | getline result
  print result | command
  system(command)
}

/token/ {
  api_token = "FAKE_AWK_TOKEN_VALUE"
  print "[redacted-token-placeholder]"
}
