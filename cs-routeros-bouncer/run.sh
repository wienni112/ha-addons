#!/usr/bin/env sh
set -e

export CROWDSEC_URL="${CROWDSEC_URL:-$(bashio::config 'crowdsec_url')}"
export CROWDSEC_BOUNCER_API_KEY="${CROWDSEC_BOUNCER_API_KEY:-$(bashio::config 'crowdsec_bouncer_api_key')}"
export MIKROTIK_HOST="${MIKROTIK_HOST:-$(bashio::config 'mikrotik_host')}"
export MIKROTIK_USER="${MIKROTIK_USER:-$(bashio::config 'mikrotik_user')}"
export MIKROTIK_PASS="${MIKROTIK_PASS:-$(bashio::config 'mikrotik_pass')}"

exec /app/cs-routeros-bouncer
