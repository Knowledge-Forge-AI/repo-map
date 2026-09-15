# Static extraction example only. Do not execute.
# Represents startup/profile syntax without being a real profile.

export ZDOTDIR="${HOME}/.config/zsh"
path=("$ZDOTDIR/bin" $path)
fpath=("$ZDOTDIR/functions" "$ZDOTDIR/completions" $fpath)

autoload -Uz compinit promptinit
compinit
promptinit

precmd() {
  print -r -- "precmd source evidence only"
}

chpwd() {
  print -r -- "$PWD"
}
