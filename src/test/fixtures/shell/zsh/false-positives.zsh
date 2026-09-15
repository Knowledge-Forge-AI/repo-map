# Static extraction fixture only. Do not execute.

# setopt hidden_from_comment
# zinit light private/example
# source ./private/plugin.zsh
# autoload -Uz hidden_from_comment
# zstyle ':completion:*' menu select
# bindkey '^R' hidden-widget
# compinit
# print -- **/*.secret(.)
# curl https://example.invalid/hidden

message='setopt should_not_extract from a single-quoted string'
other_message="autoload -Uz hidden_from_double_quoted_string"
array_with_text=("zstyle ':completion:*' menu select" "rm -- *.tmp(N)")
prompt_text='PROMPT="$(zinit light hidden/example)"'
glob_text='print -- **/*.zsh(.)'
param_text='${(q)path}'
network_text='curl https://example.invalid/hidden'

cat <<'ZSH_EXAMPLE'
setopt hidden_from_heredoc
source ./hidden-from-heredoc.zsh
eval "$(sheldon source)"
plugins=(hidden private)
ZSH_THEME="hidden-theme"
zstyle ':completion:*' menu select
print -- **/*.zsh(.)
curl https://example.invalid/heredoc
ZSH_EXAMPLE

case "$1" in
  setopt)
    print -r -- "case label only"
    ;;
  zinit)
    print -r -- "plugin case label only"
    ;;
  *.zsh(.))
    print -r -- "glob-looking case label only"
    ;;
esac
