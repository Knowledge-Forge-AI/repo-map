# Static extraction fixture only. Do not execute.

/WARN/ { warn_count++ }

$2 == "active" { active_count += 1 }

/START/,/END/ {
  range_count += 1
}

{
  print $0
}

NR == 1
