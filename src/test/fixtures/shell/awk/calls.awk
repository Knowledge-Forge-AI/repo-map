# Static extraction fixture only. Do not execute.

function normalize(value,    trimmed) {
  trimmed = tolower(value)
  return trimmed
}

{
  cleaned = normalize($1)
  print length(cleaned)
  formatted = sprintf("%s:%s", cleaned, $2)
  gsub(/secret/, "redacted", formatted)
  matched = match(formatted, /active/)
  clipped = substr(formatted, 1, 5)
}
