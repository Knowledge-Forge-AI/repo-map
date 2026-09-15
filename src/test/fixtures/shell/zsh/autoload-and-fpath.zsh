# Static extraction fixture only. Do not execute.

fpath=(./functions "$ZDOTDIR/completions" $fpath)
FPATH=(./site-functions $FPATH)
autoload -Uz compinit promptinit
autoload "$COMPUTED_FUNCTION"
compinit
