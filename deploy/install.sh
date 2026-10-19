#!/usr/bin/env bash
# Instaluje fixwatch na serwerze (Contabo / dowolny Linux z systemd) jako usługę 24/7.
# Na serwerze jako root (np. w konsoli VNC z panelu Contabo):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/Felixor69/onepiece-bot/claude/busy-ptolemy-anm020/deploy/install.sh)
#
# Pyta o token BetsAPI i webhook Discorda (jeśli ich jeszcze nie ma), wysyła wiadomość
# testową na Discord i odpala usługę. Ponowne uruchomienie = aktualizacja kodu.
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
ask() {
    # Pyta tylko gdy wartości nie ma ani w zmiennej, ani w .env.
    local name=$1 prompt=$2 value=${!1:-}
    if [ -z "$value" ] && ! grep -q "^$name=." "$DIR/.env"; then
        read -r -p "$prompt: " value < /dev/tty
    fi
    set_env "$name" "$value"
}
set_env DATA_SOURCE "${DATA_SOURCE:-betsapi}"
ask BETSAPI_TOKEN "Token BetsAPI"
ask DISCORD_WEBHOOK_URL "Webhook Discorda (ustawienia kanału > Integracje > Webhooki > Kopiuj URL)"

cd "$DIR"
if "$DIR/venv/bin/python" - <<'PY'
from dotenv import load_dotenv
from fixwatch.notify import send_discord
# Jawna sciezka: skrypt leci przez stdin, a find_dotenv() z golego load_dotenv()
# wywala sie wtedy na assercie ramki stosu (AssertionError).
load_dotenv(".env")
raise SystemExit(0 if send_discord("✅ fixwatch: test połączenia z serwera, alerty będą tutaj.") else 1)
PY
then
    echo "Wiadomość testowa wysłana na Discord."
else
    echo "UWAGA: Discord nie przyjął wiadomości – sprawdź webhook w $DIR/.env" >&2
fi

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
