# Static extraction fixture only. Do not execute.

BEGIN {
  dynamic_regex = ENVIRON["EXAMPLE_PATTERN"]
  field_index = 2
  output_file = "./out/" ENVIRON["EXAMPLE_NAME"] ".txt"
  command = ENVIRON["EXAMPLE_COMMAND"]
}

$0 ~ dynamic_regex {
  print $(field_index)
  print $0 > output_file
  command | getline result
  print result | command
  system(command)
}
