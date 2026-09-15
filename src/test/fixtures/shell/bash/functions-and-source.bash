#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
set -u
shopt -u nullglob
shopt -s extglob

. ./lib/common.bash
source ./lib/logging.sh
source "$DYNAMIC_SOURCE"

load_config() {
    CONFIG_PATH="./config/example.conf"
}

function invoke_task {
    typeset task_name="demo"
}
