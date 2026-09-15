# Static extraction fixture only. Do not execute.

zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zmodload zsh/complist
zmodload -u zsh/complist
bindkey -e
bindkey '^R' history-incremental-search-backward

#compdef mytool
_arguments '1:command:->cmds' '*::arg:->args'
