# Wienni112 Home Assistant Add-ons

Dieses Repository enthält eigene Home Assistant OS Add-ons für den Einsatz im Homelab.

Der Fokus liegt auf:

- Medien-Streaming (IP-Kameras / IPTV)
- Netzwerk-isolierten Diensten (VLAN Setups)
- saubere Integration in Home Assistant OS

Alle Add-ons sind für HAOS gebaut und werden direkt über den Add-on Store installiert.

---

## 📦 Enthaltene Add-ons

### 🎥 MediaMTX

Universeller Streaming-Server für:

- RTSP
- HLS (Browser / Smart TV)
- WebRTC (Low Latency)
- UDP / Multicast Ingest

Typische Use-Cases:

- IP-Kameras zentral verteilen
- IPTV lokal spiegeln
- Multicast → Unicast
- Streams für Home Assistant, VLC, Browser und TVs bereitstellen

---

## 🚀 Installation

### Repository in Home Assistant hinzufügen

In Home Assistant:

Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories


Repository URL hinzufügen:

https://github.com/wienni112/ha-addons


Danach erscheinen die Add-ons im Store.

---

## 🧠 Design-Prinzip

Dieses Repository folgt einem zentralen Streaming-Ansatz:

Kameras / IPTV
|
v
MediaMTX
|
+--> Home Assistant
+--> Browser
+--> VLC
+--> Smart TVs


Quellen bleiben isoliert (z.B. eigenes Kamera-VLAN), Clients greifen nur auf MediaMTX zu.

---

## 📄 Lizenz

Die einzelnen Add-ons können eigene Lizenzen haben.

MediaMTX selbst steht unter MIT License.

Dieses Repository stellt nur die Home Assistant Integration bereit.

---

## ✍ Maintainer

DoubleU
https://github.com/wienni112
