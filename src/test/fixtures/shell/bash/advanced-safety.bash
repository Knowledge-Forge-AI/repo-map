#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.

shopt -s expand_aliases
alias ll='ls -la'
alias gs='git status --short'
alias dangerous='rm -rf ./out'
alias secret_alias='printf %s FAKE_ALIAS_TOKEN'
alias "$dynamic_alias=$dynamic_target"

items=(alpha beta "$DYNAMIC_ITEM")
items+=("delta")
declare -a names=("one" "two")
declare -A labels=([ok]="green" [fail]="red")
declare -A secret_map=([ApiToken]="FAKE_BASH_ARRAY_TOKEN")

trap 'cleanup_fixture' EXIT
trap "echo FAKE_TRAP_TOKEN" INT TERM
trap - EXIT

cleanup_fixture() {
    local count=0
    count=$((count + 1))
    (( count += 1 ))
    let "count=count+1"

    if [ -f ./data/input.txt ]; then
        printf '%s\n' "file exists"
    fi

    if [[ -n "${EXAMPLE_VALUE:-}" ]]; then
        printf '%s\n' "value present"
    fi

    test -d ./data

    case "${1:-}" in
        start|restart)
            printf '%s\n' "start"
            ;;
        stop)
            printf '%s\n' "stop"
            ;;
        docker)
            printf '%s\n' "label only"
            ;;
        *)
            printf '%s\n' "default"
            ;;
    esac

    eval "$DYNAMIC_COMMAND"
    command eval "$DYNAMIC_COMMAND"
    "$COMMAND_NAME"
    "${COMMAND_ARRAY[@]}"
    bash -c "$DYNAMIC_TEXT"
    source "$COMPUTED_SOURCE"
    value="${!INDIRECT_NAME}"
    replacement="${EXAMPLE_VALUE/pat/repl}"
}
