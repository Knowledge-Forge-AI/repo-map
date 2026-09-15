# Static extraction fixture only. Do not execute.

git status --short | sed 's/^/git /'
print -r -- "hello" > ./out/message.txt
print -r -- "again" >> ./out/message.txt
cat < ./fixtures/input.txt
print -r -- "err" 2> ./out/error.txt
print -r -- "both" &> ./out/all.txt
print -r -- "dup" 2>&1
read value <<< "inline"
print -r -- "left" && print -r -- "right"
print -r -- "maybe" || print -r -- "fallback"
