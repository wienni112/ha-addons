#!/usr/bin/with-contenv bash
set -euo pipefail

CFG_DIR="/config/opcua_mqtt_bridge"
TAGS_FILE="${TAGS_FILE:-/config/opcua_mqtt_bridge/tags.yaml}"
EXAMPLE_FILE="/app/tags.example.yaml"

PKI_DIR="/data/pki"
CLIENT_CERT_PEM="${PKI_DIR}/client_cert.pem"
CLIENT_KEY_PEM="${PKI_DIR}/client_key.pem"
CLIENT_CERT_DER="${PKI_DIR}/client_cert.der"

HOSTNAME_ACTUAL="${HOSTNAME:-ha-addon}"

APP_URI="urn:${HOSTNAME_ACTUAL}:ha:OPCUA2MQTT"
echo "[opcua_mqtt_bridge] Using Application URI: $APP_URI"

# tatsächlicher Container-Hostname (HA Add-on)
ADDON_HOSTNAME="$(hostname 2>/dev/null || cat /etc/hostname)"
# optional: falls du per IP auf die Bridge gehst (meist nicht nötig, aber schadet nicht)
ADDON_IP="$(hostname -i 2>/dev/null | awk '{print $1}' || true)"

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

# OpenSSL config für OPC UA kompatible Zertifikate (SAN + KeyUsage + EKU)
OPENSSL_CNF="$(mktemp)"
cat > "$OPENSSL_CNF" <<EOF
[ req ]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[ dn ]
CN = ${ADDON_HOSTNAME}

[ v3_req ]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment, dataEncipherment
extendedKeyUsage = clientAuth
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = ${ADDON_HOSTNAME}
URI.1 = ${APP_URI}
EOF

# Optional IP als SAN hinzufügen (nur wenn ermittelt)
if [[ -n "${ADDON_IP}" ]]; then
  echo "IP.1 = ${ADDON_IP}" >> "$OPENSSL_CNF"
fi

if [[ ! -f "$CLIENT_CERT_PEM" || ! -f "$CLIENT_KEY_PEM" ]]; then
  echo "[opcua_mqtt_bridge] Generating OPC UA client certificate"
  echo "[opcua_mqtt_bridge]  - DNS SAN: ${ADDON_HOSTNAME}"
  echo "[opcua_mqtt_bridge]  - URI SAN: ${APP_URI}"
  [[ -n "${ADDON_IP}" ]] && echo "[opcua_mqtt_bridge]  - IP  SAN: ${ADDON_IP}"

  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CLIENT_KEY_PEM" \
    -out "$CLIENT_CERT_PEM" \
    -days 3650 \
    -config "$OPENSSL_CNF"
fi

rm -f "$OPENSSL_CNF"

# DER für Siemens Import
openssl x509 -in "$CLIENT_CERT_PEM" -outform der -out "$CLIENT_CERT_DER"

echo "[opcua_mqtt_bridge] Starting bridge..."
exec python3 /app/main.py
