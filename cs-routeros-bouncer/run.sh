#!/usr/bin/with-contenv bashio

set -e

export CROWDSEC_URL="$(bashio::config 'crowdsec_url')"
export CROWDSEC_BOUNCER_API_KEY="$(bashio::config 'crowdsec_bouncer_api_key')"
export MIKROTIK_HOST="$(bashio::config 'mikrotik_host')"
export MIKROTIK_USER="$(bashio::config 'mikrotik_user')"
export MIKROTIK_PASS="$(bashio::config 'mikrotik_pass')"
export MIKROTIK_TLS="$(bashio::config 'mikrotik_tls')"

export FIREWALL_IPV4_ENABLED="$(bashio::config 'firewall_ipv4_enabled')"
export FIREWALL_IPV6_ENABLED="$(bashio::config 'firewall_ipv6_enabled')"
export FIREWALL_FILTER_ENABLED="$(bashio::config 'firewall_filter_enabled')"
export FIREWALL_RAW_ENABLED="$(bashio::config 'firewall_raw_enabled')"
export FIREWALL_DENY_ACTION="$(bashio::config 'firewall_deny_action')"
export LOG_LEVEL="$(bashio::config 'log_level')"

bashio::log.info "Starting CrowdSec RouterOS Bouncer"
bashio::log.info "CrowdSec LAPI: ${CROWDSEC_URL}"
bashio::log.info "MikroTik API: ${MIKROTIK_HOST}"

exec /usr/local/bin/cs-routeros-bouncer
