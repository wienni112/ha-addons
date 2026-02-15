#!/usr/bin/with-contenv bash
set -e

LOG_LEVEL="$(bashio::config 'log_level')"
export LOG_LEVEL

exec python -m app.main
