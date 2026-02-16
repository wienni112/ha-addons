#!/usr/bin/with-contenv bash
set -euo pipefail

CFG_DIR="/config/opcua_mqtt_bridge"
TAGS_FILE="${TAGS_FILE:-/config/opcua_mqtt_bridge/tags.yaml}"
EXAMPLE_FILE="/app/tags.example.yaml"
PKI_DIR="/data/pki"

ADDON_HOSTNAME="$(hostname 2>/dev/null || cat /etc/hostname)"
ADDON_IP="$(hostname -i 2>/dev/null | awk '{print $1}' || true)"

# Read options.json once (no bashio)
read_json() {
  python3 - <<'PY' "$1" "$2"
import json, sys
path = sys.argv[1]
default = sys.argv[2]
try:
    with open("/data/options.json","r",encoding="utf-8") as f:
        opts=json.load(f)
    cur=opts
    for key in path.split("."):
        if not isinstance(cur, dict):
            cur = None
            break
        cur = cur.get(key)
    print(cur if (cur is not None and cur != "") else default)
except Exception:
    print(default)
PY
}

URI_SUFFIX="$(read_json 'opcua.application_uri_suffix' 'OPCUA2MQTT')"
CERT_O="$(read_json 'pki.cert_o' 'HA')"
CERT_C="$(read_json 'pki.cert_c' 'DE')"
CERT_ST="$(read_json 'pki.cert_st' '')"
CERT_L="$(read_json 'pki.cert_l' '')"

echo "[opcua_mqtt_bridge] application_uri_suffix: ${URI_SUFFIX}"

APP_URI="urn:${ADDON_HOSTNAME}:HA:${URI_SUFFIX}"
echo "[opcua_mqtt_bridge] Using Application URI: $APP_URI"

CERT_BASE="${ADDON_HOSTNAME}-${URI_SUFFIX}"
CLIENT_CERT_PEM="${PKI_DIR}/${CERT_BASE}.pem"
CLIENT_KEY_PEM="${PKI_DIR}/${CERT_BASE}.key.pem"
CLIENT_CERT_DER="${PKI_DIR}/${CERT_BASE}.der"

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

{
  echo "[ req ]"
  echo "distinguished_name = dn"
  echo "x509_extensions = v3_req"
  echo "prompt = no"
  echo ""
  echo "[ dn ]"
  echo "CN = ${ADDON_HOSTNAME}"
  echo "O  = ${CERT_O}"
  echo "C  = ${CERT_C}"
  if [[ -n "${CERT_ST}" ]]; then echo "ST = ${CERT_ST}"; fi
  if [[ -n "${CERT_L}"  ]]; then echo "L  = ${CERT_L}";  fi
  echo ""
  echo "[ v3_req ]"
  echo "basicConstraints = critical,CA:FALSE"
  echo "keyUsage = critical,digitalSignature,nonRepudiation,keyEncipherment,dataEncipherment"
  echo "extendedKeyUsage = critical,serverAuth,clientAuth"
  echo "subjectAltName = @alt_names"
  echo ""
  echo "[ alt_names ]"
  echo "DNS.1 = ${ADDON_HOSTNAME}"
  echo "URI.1 = ${APP_URI}"
  if [[ -n "${ADDON_IP}" ]]; then echo "IP.1 = ${ADDON_IP}"; fi
} > "$OPENSSL_CNF"

if [[ ! -f "$CLIENT_CERT_PEM" || ! -f "$CLIENT_KEY_PEM" ]]; then
  echo "[opcua_mqtt_bridge] Generating OPC UA client certificate"
  echo "[opcua_mqtt_bridge]  - DNS SAN: ${ADDON_HOSTNAME}"
  echo "[opcua_mqtt_bridge]  - URI SAN: ${APP_URI}"
  [[ -n "${ADDON_IP}" ]] && echo "[opcua_mqtt_bridge]  - IP  SAN: ${ADDON_IP}"

  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CLIENT_KEY_PEM" \
    -out "$CLIENT_CERT_PEM" \
    -days 3650 \
    -config "$OPENSSL_CNF" \
    -extensions v3_req
fi

rm -f "$OPENSSL_CNF"

openssl x509 -in "$CLIENT_CERT_PEM" -outform der -out "$CLIENT_CERT_DER"

ln -sf "${CLIENT_CERT_PEM}" "${PKI_DIR}/client_cert.pem"
ln -sf "${CLIENT_KEY_PEM}"  "${PKI_DIR}/client_key.pem"
ln -sf "${CLIENT_CERT_DER}" "${PKI_DIR}/client_cert.der"

echo "[opcua_mqtt_bridge] Starting bridge..."
exec python3 -u /app/main.py
