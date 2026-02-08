# MediaMTX Home Assistant Add-on

Dieses Add-on bringt MediaMTX als Streaming-Server direkt nach Home Assistant OS.

MediaMTX ist ein universeller Stream-Hub für:

- RTSP (Input / Output)
- HLS (Browser / Smart TVs)
- WebRTC (Low Latency)
- UDP / Multicast

Ideal für IP-Kameras, IPTV und VLAN-getrennte Netzwerke.

---

## ✨ Features

- RTSP Proxy / Server
- HLS Web Streams
- WebRTC Low Latency
- Multicast → Unicast
- Mehrere Quellen gleichzeitig
- Perfekt für Kamera VLAN Isolation

---

## 🚀 Installation

1. Repository hinzufügen:

https://github.com/wienni112/ha-addons


2. MediaMTX im Add-on Store auswählen
3. Installieren
4. Optional: Start on boot aktivieren
5. Starten

---

## ⚙️ Konfiguration

Die Konfiguration liegt in:

/config/mediamtx.yml


---

## 📷 Beispiel: IP Kamera

```yaml
paths:
  cam_einfahrt:
    source: rtsp://USER:PASS@172.22.15.10:554/STREAM
    sourceProtocol: tcp
Zugriff danach:

RTSP:

rtsp://HA_IP:8554/cam_einfahrt
Browser (HLS):

http://HA_IP:8888/cam_einfahrt
WebRTC:

http://HA_IP:8889
📺 IPTV / Multicast Beispiel
paths:
  ard:
    source: udp://239.0.0.1:10000

  zdf:
    source: udp://239.0.0.2:10000
🔐 Empfohlene Netzwerkstruktur
IPCAM VLAN
     |
     v
 MediaMTX (HAOS)
     |
     +--> Home Assistant
     +--> Browser
     +--> VLC
     +--> TVs
Kameras sollten nur MediaMTX erreichen dürfen – nicht alle Clients.

🛠 Ports
Standard:

RTSP: 8554

HLS: 8888

WebRTC: 8889

🧠 Tipps
RTSP bevorzugt über TCP

Kamera Bitrate begrenzen

GOP klein halten für niedrige Latenz

MSS Clamping im Router aktivieren (bei VLAN / VPN)

🐞 Troubleshooting
Kein Bild?
RTSP URL prüfen

Firewall zwischen Kamera VLAN und HAOS prüfen

Add-on Logs ansehen

Hohe Latenz?
Kamera auf "Low Latency" stellen

WebRTC statt HLS nutzen

📄 Lizenz
MediaMTX steht unter MIT License.

Dieses Add-on stellt nur die Home Assistant Integration bereit.
