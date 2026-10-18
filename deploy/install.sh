#!/usr/bin/env bash
# Instaluje fixwatch na serwerze (Contabo / dowolny Linux z systemd) jako usługę 24/7.
#
#   curl -fsSL https://raw.githubusercontent.com/Felixor69/onepiece-bot/claude/busy-ptolemy-anm020/deploy/install.sh \
#     | sudo BETSAPI_TOKEN=... DISCORD_WEBHOOK_URL=... bash
#
# Ponowne uruchomienie = aktualizacja kodu (istniejący .env zostaje, chyba że podasz nowe wartości).
set -euo pipefail

REPO=https://github.com/Felixor69/onepiece-bot.git
BRANCH=${BRANCH:-claude/busy-ptolemy-anm020}
DIR=/opt/fixwatch

if ! command -v git >/dev/null || ! python3 -m venv --help >/dev/null 2>&1; then
    apt-get update -q && apt-get install -yq git python3 python3-venv
fi

if [ -d "$DIR/.git" ]; then
    git -C "$DIR" fetch -q origin "$BRANCH"
    git -C "$DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
    git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q requests python-dotenv

touch "$DIR/.env"
chmod 600 "$DIR/.env"
set_env() {
    [ -n "${2:-}" ] || return 0
    sed -i "/^$1=/d" "$DIR/.env"
    echo "$1=$2" >> "$DIR/.env"
}
set_env DATA_SOURCE "${DATA_SOURCE:-betsapi}"
set_env BETSAPI_TOKEN "${BETSAPI_TOKEN:-}"
set_env DISCORD_WEBHOOK_URL "${DISCORD_WEBHOOK_URL:-}"

cat > /etc/systemd/system/fixwatch.service <<EOF
[Unit]
Description=fixwatch - skaner podejrzanych rynkow goli
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -u -m fixwatch
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable -q fixwatch
systemctl restart fixwatch
echo "fixwatch działa. Logi: journalctl -u fixwatch -f"
