# Hakvision PTZ Server

MQTT-basierter PTZ-Server für Hikvision Kameras mit ISAPI Unterstützung.

Dieses Add-on dient als zentrale Steuerinstanz für PTZ-Kameras.\
Es empfängt MQTT-Kommandos und übersetzt diese in Hikvision ISAPI
API-Aufrufe.

------------------------------------------------------------------------

## 🧠 Architektur

    Client (HA / Joystick / StreamDeck / Automation)
            │
            ▼
            MQTT
            │
            ▼
    Hakvision PTZ Server (Add-on)
            │
            ▼
    Hikvision Kamera (ISAPI)

Nur dieses Add-on spricht direkt mit der Kamera.

------------------------------------------------------------------------

## 📦 Unterstützte Funktionen

-   Continuous Move (Pan / Tilt / Zoom)
-   Diagonale Bewegung
-   Speed Mapping
-   Deadzone Filter
-   Smooth Stop Logik
-   Preset Steuerung
-   MQTT Topic Struktur
-   VLAN kompatibel

------------------------------------------------------------------------

## 📡 MQTT Topics

Standard Topic Prefix:

    ptz/<camera_id>/cmd/...

------------------------------------------------------------------------

### ▶ Bewegung

**Topic**

    ptz/camera1/cmd/move

**Payload**

``` json
{
  "pan": -5,
  "tilt": 2,
  "zoom": 0,
  "speed": 4
}
```

------------------------------------------------------------------------

### ⏹ Stop

**Topic**

    ptz/camera1/cmd/stop

**Payload**

``` json
{}
```

------------------------------------------------------------------------

### 🎯 Preset

**Topic**

    ptz/camera1/cmd/preset

**Payload**

``` json
{
  "preset": 3
}
```

------------------------------------------------------------------------

## ⚙ Konfiguration

Im Add-on einstellbar:

-   MQTT Host / Port
-   MQTT Benutzer / Passwort
-   Kamera IP
-   Kamera Login
-   PTZ Channel
-   Deadzone
-   Max Speed
-   Smooth Stop Timeout

------------------------------------------------------------------------

## 🏠 Home Assistant Integration

Beispiel Button:

``` yaml
service: mqtt.publish
data:
  topic: ptz/camera1/cmd/move
  payload: '{"pan": -5, "tilt": 0, "speed": 3}'
```

------------------------------------------------------------------------

## 🔐 Netzwerk Design

Empfohlen:

-   Kamera in separatem VLAN\
-   Nur Hakvision PTZ Server darf Kamera erreichen\
-   Clients kommunizieren ausschließlich über MQTT

------------------------------------------------------------------------

## 🚀 Typische Use-Cases

-   PTZ Steuerung per Dashboard
-   Hardware Joystick Integration
-   Preset-Automationen
-   StreamDeck Control
-   Veranstaltungs-Streaming
-   Kirchen- / Eventtechnik
-   Homelab Kamera Monitoring

------------------------------------------------------------------------

## 📌 Hinweise

Dieses Add-on nutzt die offizielle Hikvision ISAPI Schnittstelle.

ONVIF wird bewusst nicht verwendet, da ISAPI stabiler und performanter
ist.

------------------------------------------------------------------------

## ✍ Maintainer

DoubleU\
https://github.com/wienni112
