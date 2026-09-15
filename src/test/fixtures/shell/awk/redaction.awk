# Static extraction fixture only. Do not execute.

BEGIN {
  api_token = "FAKE_AWK_TOKEN_VALUE"
  password = "FAKE_AWK_PASSWORD_VALUE"
  system("printf FAKE_AWK_SYSTEM_TOKEN")
  print $0 > "docs/examples/awk/FAKE_AWK_PATH_TOKEN.txt"
  public_value = "safe"
}
