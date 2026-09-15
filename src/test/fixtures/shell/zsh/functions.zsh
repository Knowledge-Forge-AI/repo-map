# Static extraction fixture only. Do not execute.

precmd() {
  print -r -- "precmd source evidence only"
}

chpwd() {
  print -r -- "$PWD"
}
