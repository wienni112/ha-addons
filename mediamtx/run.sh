#!/usr/bin/with-contenv sh
set -e

# Add-on config path (mapped via addon_config)
CFG_DIR="/config"
CFG_FILE="${CFG_DIR}/mediamtx.yml"

# Wenn keine Config existiert, eine Default anlegen
if [ ! -f "${CFG_FILE}" ]; then
  cp /etc/mediamtx.yml "${CFG_FILE}"
fi

exec /usr/bin/mediamtx "${CFG_FILE}"
