# Static extraction fixture only. Do not execute.

tools=(git docker kubectl)
path=("./bin" $path)
local names=(alpha beta "$DYNAMIC_NAME")
typeset -a colors=(red blue green)
readonly labels=(ok warning failure)
