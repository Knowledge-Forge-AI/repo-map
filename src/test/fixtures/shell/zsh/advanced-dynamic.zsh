# Static extraction fixture only. Do not execute.

eval "$DYNAMIC_COMMAND"
eval "$(sheldon source)"
source "$COMPUTED_SOURCE"
autoload "$COMPUTED_FUNCTION"
fpath=("$COMPUTED_FPATH" $fpath)
"${COMMANDS[@]}"
zinit ice wait lucid
zplug load
antidote load
print -- "$DYNAMIC_GLOB"/*.zsh(N)
