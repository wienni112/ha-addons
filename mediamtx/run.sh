#!/command/with-contenv bash
set -e

CONFIG_DST="/config/mediamtx.yml"
CONFIG_SRC="/etc/mediamtx.yml"

# falls der User noch keine Config hat -> Default hinschreiben
if [ ! -f "$CONFIG_DST" ]; then
  echo "No $CONFIG_DST found, creating default..."
  cp "$CONFIG_SRC" "$CONFIG_DST"
fi

echo "Starting MediaMTX with config: $CONFIG_DST"
exec /usr/bin/mediamtx "$CONFIG_DST"
