#!/bin/sh
# Стабильный CloudPub URL без CLOUDPUB_AGENT_ID в .env:
# agent_id зашит ниже (не секрет) + bind-mount ./docker/cloudpub.
# Сервер привязывает публикации к agent_id; run поднимает уже существующие.
# Не задавать HTTP= в compose — иначе register создаст новый hostname.
set -eu

CLO=/clo
export HOME=/home/cloudpub
CONFIG_DIR="$HOME/.config/cloudpub"
CONFIG="$CONFIG_DIR/client.toml"

# Общий агент команды → https://incompletely-immortal-ling.cloudpub.ru
# Смена id = новый hostname на cloudpub.ru (и ручной re-publish).
AGENT_ID="cc9d4150-d529-48e0-93c2-ff8ba5c56fd8"

if [ -z "${TOKEN:-}" ]; then
  echo "CLOUDPUB_TOKEN/TOKEN не задан" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG" ]; then
  printf '%s\n' \
    "agent_id = \"${AGENT_ID}\"" \
    'server = "https://cloudpub.ru/"' \
    >"$CONFIG"
fi

# Всегда один и тот же agent_id (не зависит от машины / wipe volume).
if grep -q '^agent_id[[:space:]]*=' "$CONFIG"; then
  sed -i "s/^agent_id[[:space:]]*=.*/agent_id = \"${AGENT_ID}\"/" "$CONFIG"
else
  echo "agent_id = \"${AGENT_ID}\"" >>"$CONFIG"
fi

"$CLO" set token "$TOKEN"

echo "cloudpub: agent_id=${AGENT_ID} → run (sticky publications)"
exec "$CLO" run
