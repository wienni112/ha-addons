#!/usr/bin/with-contenv bash
set -euo pipefail

CFG_DIR="/config/opcua_mqtt_bridge"
TAGS_FILE="${TAGS_FILE:-/config/opcua_mqtt_bridge/tags.yaml}"
EXAMPLE_FILE="/app/tags.example.yaml"

PKI_DIR="/data/pki"
CLIENT_CERT_DER="${PKI_DIR}/client_cert.der"
CLIENT_KEY_PEM="${PKI_DIR}/client_key.pem"

echo "[opcua_mqtt_bridge] Preparing config dir..."
mkdir -p "$CFG_DIR"

if [[ ! -f "$TAGS_FILE" ]]; then
  echo "[opcua_mqtt_bridge] tags.yaml not found at: $TAGS_FILE"
  echo "[opcua_mqtt_bridge] Creating example tags.yaml..."
  if [[ -f "$EXAMPLE_FILE" ]]; then
    cp "$EXAMPLE_FILE" "$TAGS_FILE"
  else
    cat > "$TAGS_FILE" <<'YAML'
read: []
rw: []
YAML
  fi
  echo "[opcua_mqtt_bridge] Please edit: $TAGS_FILE"
fi

echo "[opcua_mqtt_bridge] Preparing PKI..."
mkdir -p "$PKI_DIR"

if [[ ! -f "$CLIENT_CERT_DER" || ! -f "$CLIENT_KEY_PEM" ]]; then
  echo "[opcua_mqtt_bridge] Generating OPC UA client certificate..."
  openssl req -x509 -newkey rsa:2048 \
    -keyout "$CLIENT_KEY_PEM" \
    -out "$CLIENT_CERT_DER" \
    -outform DER \
    -days 3650 \
    -nodes \
    -subj "/CN=ha-opcua-mqtt-bridge"
fi

echo "[opcua_mqtt_bridge] Starting bridge..."
exec python3 /app/main.py
