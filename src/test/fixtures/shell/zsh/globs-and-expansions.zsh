# Static extraction fixture only. Do not execute.

print -- **/*.zsh(.)
print -- *.tmp(N)
for example_file in **/*(.om[1,10]); do
  print -r -- "$example_file"
done
print -- ^*.tmp
print -- *.(zsh|sh)

quoted_path=${(q)path}
lines=(${(@f)"$(git status --short)"})
joined=${(j: :)plugins}
upper=${(U)name}
lower=${(L)name}
unique=(${(u)items})
