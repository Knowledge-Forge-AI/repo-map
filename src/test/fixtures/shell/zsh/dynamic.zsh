# Static extraction fixture only. Do not execute.

eval "$DYNAMIC_COMMAND"
source "$COMPUTED_SOURCE"
autoload "$COMPUTED_FUNCTION"
eval "$(sheldon source)"
"${COMMANDS[@]}"
lines=(${(@f)"$(git status --short)"})
zstyle "$COMPUTED_CONTEXT" matcher-list "$COMPUTED_VALUE"
PROMPT="${COMPUTED_PROMPT}"
