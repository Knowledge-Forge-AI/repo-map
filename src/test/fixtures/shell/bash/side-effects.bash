#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.

perform_side_effect_examples() {
    export EXAMPLE_TOKEN="FAKE_BASH_SIDE_EFFECT_TOKEN"
    printf '%s\n' "$EXAMPLE_MODE:${EXAMPLE_TOKEN:-redacted}"
    EXAMPLE_MODE=fixture git status --short
    env EXAMPLE_OVERLAY=1 make test

    cat ./data/input.txt
    grep "active" ./data/input.txt
    test -f ./data/input.txt

    printf '%s\n' "ok" > ./out/report.txt
    printf '%s\n' "more" >> ./out/report.txt
    grep "x" < ./data/input.txt
    python3 script.py 2> ./err.log
    cmd &> ./combined.log

    touch ./out/state.txt
    mkdir -p ./out/cache
    cp ./fixtures/source.txt ./out/source.txt
    mv ./out/source.txt ./out/current.txt
    ln -sfn ./out/current.txt ./current-link
    chmod 0644 ./out/current.txt
    chown example:example ./out/current.txt
    tar -xzf ./archives/example.tar.gz -C ./out
    unzip ./archives/example.zip -d ./out
    cp ./fixtures/source.txt "$DYNAMIC_TARGET"
    printf '%s\n' "profile" >> "$HOME/.bashrc"

    curl -fsS https://example.invalid/archive.tar.gz -o ./out/archive.tar.gz
    wget -O ./out/index.html https://example.invalid/index.html
    nc example.invalid 443
    ssh example.invalid true
    scp ./file.txt example.invalid:/tmp/file.txt
    curl "$DYNAMIC_URL" -o "$DYNAMIC_OUT"

    sudo apt-get install example-package
    brew install example-tool
    npm install --global example-cli
    pip install example-package
    gem install example-gem
    cargo install example-tool
    go install example.invalid/tool@latest
    npm --version

    systemctl restart example.service
    service example restart
    launchctl kickstart gui/501/example.agent
    brew services restart example
    crontab ./cron/example.cron

    docker compose up -d
    docker ps
    kubectl apply -f ./k8s/example.yaml
    kubectl get pods
    helm upgrade example ./chart
    terraform plan
    terraform apply -auto-approve

    nohup ./server.sh &
    kill "$PID"
    ssh-add ./keys/fixture_rsa
    security add-generic-password -a fixture -s example -w "FAKE_SECURITY_PASSWORD"
    spctl --add ./Example.app
    defaults write com.example.fixture Enabled -bool true
    docker login --password "FAKE_DOCKER_PASSWORD"
}
