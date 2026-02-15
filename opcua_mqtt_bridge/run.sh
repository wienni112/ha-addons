#!/usr/bin/with-contenv bash
set -euo pipefail

CFG_DIR="/config/opcua_mqtt_bridge"
TAGS_FILE="${TAGS_FILE:-/config/opcua_mqtt_bridge/tags.yaml}"
EXAMPLE_FILE="/app/tags.example.yaml"

PKI_DIR="/data/pki"
CLIENT_CERT_PEM="${PKI_DIR}/client_cert.pem"
CLIENT_KEY_PEM="${PKI_DIR}/client_key.pem"
CLIENT_CERT_DER="${PKI_DIR}/client_cert.der"

# WICHTIG: App URI MUSS später auch im Python-Client gesetzt werden
APP_URI="${OPCUA_APPLICATION_URI:-urn:ha:opcua_mqtt_bridge:plc01}"

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

if [[ ! -f "$CLIENT_CERT_PEM" || ! -f "$CLIENT_KEY_PEM" ]]; then
  echo "[opcua_mqtt_bridge] Generating OPC UA client certificate with SAN URI: $APP_URI"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CLIENT_KEY_PEM" \
    -out "$CLIENT_CERT_PEM" \
    -days 3650 \
    -subj "/CN=opcua-mqtt-bridge" \
    -addext "subjectAltName=URI:$APP_URI"
fi

# DER für Siemens Trustlist/Import
openssl x509 -in "$CLIENT_CERT_PEM" -outform der -out "$CLIENT_CERT_DER"

echo "[opcua_mqtt_bridge] Starting bridge..."
exec python3 /app/main.py
