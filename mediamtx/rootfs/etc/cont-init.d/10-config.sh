#!/command/with-contenv bashio
set -euo pipefail

CFG="/data/mediamtx.yml"
CONTENT="$(bashio::config 'mediamtx_config')"

if [ -z "${CONTENT}" ]; then
  bashio::log.error "mediamtx_config is empty. Please set it in the add-on configuration."
  exit 1
fi

mkdir -p /data
printf "%s\n" "${CONTENT}" > "${CFG}"
bashio::log.info "Wrote ${CFG}"
