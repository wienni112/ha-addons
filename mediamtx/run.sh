#!/usr/bin/with-contenv bash
set -e

CFG=/config/mediamtx.yml

echo "Writing MediaMTX config..."

printf "%s\n" "$MEDIAMTX_CONFIG" > "$CFG"

echo "Starting MediaMTX..."

exec /usr/local/bin/mediamtx "$CFG"
