#!/bin/sh
# Stable CloudPub URL: fixed AGENT_ID + TOKEN; clo run reuses publications.
# Do not set HTTP= in compose (register would mint a new hostname).
set -eu

CLO=/clo
export HOME=/home/cloudpub
CONFIG_DIR="$HOME/.config/cloudpub"
CONFIG="$CONFIG_DIR/client.toml"

# Team agent -> https://incompletely-immortal-ling.cloudpub.ru
AGENT_ID="cc9d4150-d529-48e0-93c2-ff8ba5c56fd8"

if [ -z "${TOKEN:-}" ]; then
  echo "CLOUDPUB_TOKEN/TOKEN not set" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG" ]; then
  printf '%s\n' \
    "agent_id = \"${AGENT_ID}\"" \
    'server = "https://cloudpub.ru/"' \
    >"$CONFIG"
fi

if grep -q '^agent_id[[:space:]]*=' "$CONFIG"; then
  sed -i "s/^agent_id[[:space:]]*=.*/agent_id = \"${AGENT_ID}\"/" "$CONFIG"
else
  echo "agent_id = \"${AGENT_ID}\"" >>"$CONFIG"
fi

"$CLO" set token "$TOKEN"

echo "cloudpub: agent_id=${AGENT_ID} -> run (sticky publications)"
exec "$CLO" run
