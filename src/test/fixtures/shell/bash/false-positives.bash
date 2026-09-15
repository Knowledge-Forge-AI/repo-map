#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
# eval "$commented"
# rm -rf ./not-a-side-effect
# curl https://example.invalid/not-a-network-call -o ./not-a-file
# alias bad='rm -rf ./comment-alias'
# trap 'docker run comment-image' EXIT
quoted_command="curl https://example.invalid/not-a-command"
side_effect_string="docker compose up -d && kubectl apply -f ./not-real.yaml"
single_quoted='source ./not-a-source.bash'
example_assignment="safe static value"
alias_string="alias bad='curl https://example.invalid/not-real'"
trap_string="trap 'rm -rf ./trap-string' EXIT"
array_values=("eval array-entry" "source ./array-entry.bash" "rm ./array-entry")
advanced_array_values=("alias array_alias='docker run nope'" "trap 'kubectl apply -f nope' EXIT")

case "${1:-}" in
    eval)
        echo "case label, not dynamic invocation"
        ;;
    docker)
        echo "case label, not command"
        ;;
esac

cat <<'COMMENT_BLOCK'
source ./heredoc-source.bash
eval "$heredoc"
apt-get install heredoc-package
printf '%s\n' "heredoc" > ./out/not-real.txt
alias heredoc_alias='rm -rf ./heredoc-alias'
trap 'docker run heredoc-image' EXIT
COMMENT_BLOCK

function real_function {
    local visible_value="ok"
}
