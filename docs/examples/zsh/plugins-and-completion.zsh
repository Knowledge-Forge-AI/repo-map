# Static extraction example only. Do not execute.

plugins=(git docker kubectl)
ZSH_THEME="example-theme"
source "$ZSH/oh-my-zsh.sh"

zinit light zsh-users/zsh-autosuggestions
antigen bundle zsh-users/zsh-completions
zplug "zsh-users/zsh-syntax-highlighting"
antidote load
eval "$(sheldon source)"

zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zmodload zsh/complist
bindkey -e
bindkey '^R' history-incremental-search-backward

#compdef mytool
_arguments '1:command:->cmds' '*::arg:->args'
