# Static extraction example only. Do not execute.

print -- **/*.zsh(.)
print -- *.tmp(N)
for example_file in **/*(.om[1,10]); do
  print -r -- "$example_file"
done

quoted_path=${(q)path}
lines=(${(@f)"$(git status --short)"})
joined=${(j: :)plugins}

eval "$DYNAMIC_COMMAND"
source "$COMPUTED_SOURCE"
autoload "$COMPUTED_FUNCTION"
fpath=("$COMPUTED_FPATH" $fpath)
