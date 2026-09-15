#!/usr/bin/env zsh
# Static extraction fixture only. Do not execute.

setopt extendedglob nullglob prompt_subst
unsetopt beep nomatch
emulate -L zsh

export EXAMPLE_MODE="public"
EXAMPLE_VALUE="safe"
source ./lib/example.zsh

mkcd() {
  mkdir -p "$1" && cd "$1"
}

function greet {
  print -r -- "$1"
}
