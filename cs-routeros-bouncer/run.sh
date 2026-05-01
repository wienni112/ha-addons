#!/usr/bin/with-contenv bashio

set -e

export CROWDSEC_URL="$(bashio::config 'crowdsec_url')"
export CROWDSEC_BOUNCER_API_KEY="$(bashio::config 'crowdsec_bouncer_api_key')"
export MIKROTIK_HOST="$(bashio::config 'mikrotik_host')"
export MIKROTIK_USER="$(bashio::config 'mikrotik_user')"
export MIKROTIK_PASS="$(bashio::config 'mikrotik_pass')"
export MIKROTIK_TLS="$(bashio::config 'mikrotik_tls')"
export LOG_LEVEL="$(bashio::config 'log_level')"

if [ -z "${CROWDSEC_BOUNCER_API_KEY}" ]; then
  bashio::log.fatal "crowdsec_bouncer_api_key fehlt in der Add-on-Konfiguration"
fi

if [ -z "${MIKROTIK_PASS}" ]; then
  bashio::log.fatal "mikrotik_pass fehlt in der Add-on-Konfiguration"
fi

bashio::log.info "Starting cs-routeros-bouncer"
bashio::log.info "CrowdSec URL: ${CROWDSEC_URL}"
bashio::log.info "MikroTik Host: ${MIKROTIK_HOST}"
bashio::log.info "MikroTik User: ${MIKROTIK_USER}"

exec /usr/local/bin/cs-routeros-bouncer
