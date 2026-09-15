# Static extraction example only. Do not execute.

#!/usr/bin/env bash

# rm -rf /tmp/example should stay a comment.
quoted_command="curl https://example.invalid/not-a-command"
single_quoted='apt-get install not-a-command'
array_values=("docker compose up" "kubectl apply")

case "${1:-}" in
    curl)
        echo "case pattern, not command evidence"
        ;;
esac

cat <<'COMMENT_BLOCK'
systemctl restart not-a-service
Authorization: <redacted>
COMMENT_BLOCK

example_assignment="sudo launchctl kickstart not-a-command"
