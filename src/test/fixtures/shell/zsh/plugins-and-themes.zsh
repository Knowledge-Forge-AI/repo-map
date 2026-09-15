# Static extraction fixture only. Do not execute.

plugins=(git docker kubectl)
ZSH_THEME="example-theme"
source "$ZSH/oh-my-zsh.sh"

zinit light zsh-users/zsh-autosuggestions
zinit ice wait lucid
antigen bundle zsh-users/zsh-completions
antigen apply
zplug "zsh-users/zsh-syntax-highlighting"
zplug load
antidote load
eval "$(sheldon source)"
