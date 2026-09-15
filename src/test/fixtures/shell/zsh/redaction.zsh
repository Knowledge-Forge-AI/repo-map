# Static extraction fixture only. Do not execute.

API_TOKEN="FAKE_ZSH_TOKEN_VALUE"
export PASSWORD="FAKE_ZSH_PASSWORD_VALUE"
ZSH_PRIVATE_REPO="https://token.example.invalid/private"
PROMPT="fixture prompt"
zstyle ':example:secret' token 'FAKE_ZSH_ZSTYLE_TOKEN'
PROMPT="FAKE_ZSH_PROMPT_TOKEN"
git push https://FAKE_ZSH_ARG_TOKEN@example.invalid/private/repo
typeset -A secrets=([token]="FAKE_ZSH_ARRAY_TOKEN")
secret_paths=("FAKE_ZSH_PATH_TOKEN")
curl "https://FAKE_ZSH_URL_TOKEN@example.invalid/private"
