#!/bin/sh
# Стабильный CloudPub URL на любом хосте: один CLOUDPUB_AGENT_ID + CLOUDPUB_TOKEN.
# Сервер привязывает публикации к agent_id; run поднимает уже существующие.
# Не задавать HTTP= в compose — иначе register создаст новый hostname.
set -eu

CLO=/clo
export HOME=/home/cloudpub
CONFIG_DIR="$HOME/.config/cloudpub"
CONFIG="$CONFIG_DIR/client.toml"

if [ -z "${TOKEN:-}" ]; then
  echo "CLOUDPUB_TOKEN/TOKEN не задан" >&2
  exit 1
fi

if [ -z "${CLOUDPUB_AGENT_ID:-}" ]; then
  echo "CLOUDPUB_AGENT_ID не задан (фиксированный agent_id → стабильный *.cloudpub.ru)" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG" ]; then
  printf '%s\n' \
    "agent_id = \"${CLOUDPUB_AGENT_ID}\"" \
    'server = "https://cloudpub.ru/"' \
    >"$CONFIG"
fi

# Всегда один и тот же agent_id (не зависит от машины / wipe volume).
if grep -q '^agent_id[[:space:]]*=' "$CONFIG"; then
  sed -i "s/^agent_id[[:space:]]*=.*/agent_id = \"${CLOUDPUB_AGENT_ID}\"/" "$CONFIG"
else
  echo "agent_id = \"${CLOUDPUB_AGENT_ID}\"" >>"$CONFIG"
fi

"$CLO" set token "$TOKEN"

echo "cloudpub: agent_id=${CLOUDPUB_AGENT_ID} → run (sticky publications)"
exec "$CLO" run
