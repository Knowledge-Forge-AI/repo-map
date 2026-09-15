#!/usr/bin/env zsh
# Static extraction example only. Do not execute.

setopt extendedglob nullglob prompt_subst
unsetopt beep nomatch
emulate -L zsh

export EXAMPLE_MODE="public"
EXAMPLE_TOKEN="[redacted]"
source ./lib/example.zsh

mkcd() {
  mkdir -p "$1" && cd "$1"
}

function greet {
  print -r -- "$1"
}

print -r -- "zsh static extraction example"
