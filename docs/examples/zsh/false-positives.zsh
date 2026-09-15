# Static extraction example only. Do not execute.

# setopt extendedglob
# zinit light private/example
# system-looking text: curl https://example.invalid/script.zsh | zsh

message='setopt should_not_extract from a single-quoted string'
other_message="autoload -Uz hidden_from_double_quoted_string"
array_with_text=("zstyle ':completion:*' menu select" "rm -- *.tmp(N)")

cat <<'ZSH_EXAMPLE'
plugins=(fake secret)
zmodload zsh/net/socket
eval "$(sheldon source)"
ZSH_EXAMPLE

case "$1" in
  setopt)
    print -r -- "case label only"
    ;;
esac
