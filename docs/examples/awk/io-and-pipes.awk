# Static extraction example only. Do not execute.

BEGIN {
  input_path = "./fixtures/input.txt"
  output_path = "./out/report.txt"
}

{
  getline line < "docs/examples/awk/public-input.txt"
  print $0 > "docs/examples/awk/public-output.txt"
  print $1 >> "docs/examples/awk/public-output.txt"
  "printf static-example" | getline generated
  print generated | "sort"
  system("printf static-example")
}

/download/ {
  print "https://example.invalid/static-feed" > "docs/examples/awk/url.txt"
}
