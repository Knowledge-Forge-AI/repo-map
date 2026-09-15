#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
cat <<EOF
echo "not a command"
TOKEN=FAKE_BASH_HEREDOC_TOKEN
EOF

cat <<'LITERAL'
docker run not-a-command
PASSWORD=FAKE_BASH_HEREDOC_PASSWORD
LITERAL

cat <<-INDENTED
	api_key=FAKE_BASH_HEREDOC_API_KEY
INDENTED
