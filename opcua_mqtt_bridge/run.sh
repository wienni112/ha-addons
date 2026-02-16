#!/usr/bin/with-contenv bash
set -euo pipefail

CFG_DIR="/config/opcua_mqtt_bridge"
TAGS_FILE="${TAGS_FILE:-/config/opcua_mqtt_bridge/tags.yaml}"
EXAMPLE_FILE="/app/tags.example.yaml"

PKI_DIR="/data/pki"

# tatsächlicher Container-Hostname (HA Add-on)
ADDON_HOSTNAME="$(hostname 2>/dev/null || cat /etc/hostname)"
ADDON_IP="$(hostname -i 2>/dev/null | awk '{print $1}' || true)"

# Suffix aus config
# Suffix aus options.json (ohne bashio)
URI_SUFFIX="$(python3 - <<'PY'
import json
try:
    with open("/data/options.json","r",encoding="utf-8") as f:
        opts=json.load(f)
    print((opts.get("opcua",{}) or {}).get("application_uri_suffix","OPCUA2MQTT") or "OPCUA2MQTT")
except Exception:
    print("OPCUA2MQTT")
PY
)"

echo "[opcua_mqtt_bridge] application_uri_suffix: ${URI_SUFFIX}"
APP_URI="urn:${ADDON_HOSTNAME}:HA:${URI_SUFFIX}"
echo "[opcua_mqtt_bridge] Using Application URI: $APP_URI"

CERT_BASE="${ADDON_HOSTNAME}-${URI_SUFFIX}"

CLIENT_CERT_PEM="${PKI_DIR}/${CERT_BASE}.pem"
CLIENT_KEY_PEM="${PKI_DIR}/${CERT_BASE}.key.pem"
CLIENT_CERT_DER="${PKI_DIR}/${CERT_BASE}.der"

CERT_O="${CERT_O:-HA}"
CERT_C="${CERT_C:-DE}"
CERT_ST="${CERT_ST:-}"
CERT_L="${CERT_L:-}"

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

OPENSSL_CNF="$(mktemp)"
cat > "$OPENSSL_CNF" <<EOF
[ req ]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[ dn ]
CN = ${ADDON_HOSTNAME}
O  = ${CERT_O}
C  = ${CERT_C}
ST = ${CERT_ST}
L  = ${CERT_L}

[ v3_req ]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment, dataEncipherment
extendedKeyUsage = clientAuth
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = ${ADDON_HOSTNAME}
URI.1 = ${APP_URI}
EOF

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

openssl x509 -in "$CLIENT_CERT_PEM" -outform der -out "$CLIENT_CERT_DER"

# Symlinks NACHdem die Dateien existieren (für Python-Kompatibilität)
ln -sf "${CLIENT_CERT_PEM}" "${PKI_DIR}/client_cert.pem"
ln -sf "${CLIENT_KEY_PEM}"  "${PKI_DIR}/client_key.pem"
ln -sf "${CLIENT_CERT_DER}" "${PKI_DIR}/client_cert.der"

echo "[opcua_mqtt_bridge] Starting bridge..."
exec python3 -u /app/main.py
