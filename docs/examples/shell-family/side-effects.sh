# Static extraction example only. Do not execute.

#!/usr/bin/env bash

perform_maintenance_examples() {
    local target_dir="./var/example"
    local archive_url="https://example.invalid/archive.tar.gz"

    mkdir -p "$target_dir"
    touch "$target_dir/state.txt"
    cp ./fixtures/source.txt "$target_dir/source.txt"
    mv "$target_dir/source.txt" "$target_dir/current.txt"
    ln -sfn "$target_dir/current.txt" ./current-link
    chmod 0644 "$target_dir/current.txt"

    curl -fsS "$archive_url" -o "$target_dir/archive.tar.gz"
    tar -xzf "$target_dir/archive.tar.gz" -C "$target_dir"

    sudo apt-get install example-package
    brew install example-tool
    npm install --global example-cli
    docker compose up -d
    kubectl apply -f ./k8s/example.yaml
    systemctl restart example.service
    launchctl kickstart gui/501/example.agent
    crontab ./cron/example.cron
}
