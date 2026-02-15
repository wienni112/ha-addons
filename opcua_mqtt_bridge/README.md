# OPC UA ↔ MQTT Bridge (Home Assistant Add-on)

High speed bidirectional OPC UA to MQTT bridge using OPC UA
Subscriptions.

This add-on connects to an OPC UA server (e.g. Siemens S7-1200 /
S7-1500) and synchronizes variables in real-time to MQTT.

No polling. No Node-RED. No HA discovery required.

------------------------------------------------------------------------

## 🚀 Features

-   OPC UA DataChange Subscriptions (low latency)
-   Bidirectional MQTT ↔ OPC UA
-   Configurable MQTT namespace
-   Fully configurable via Add-on options
-   Tags defined in YAML
-   Designed for industrial control (heating, automation, etc.)

------------------------------------------------------------------------

## 🏗 Architecture

OPC UA Server ⇄ HA Add-on (Subscriptions) ⇄ MQTT Broker

Topics structure:

`<prefix>`{=html}/state/`<path>`{=html} (SPS → MQTT)
`<prefix>`{=html}/cmd/`<path>`{=html} (MQTT → SPS)
`<prefix>`{=html}/meta/availability

Example:

opcua/plc01/state/Analog/Temp_Eingang
opcua/plc01/cmd/Sollwert/Temp_Halle opcua/plc01/meta/availability

------------------------------------------------------------------------

## ⚙ Add-on Configuration

### OPC UA

  Option                   Description
  ------------------------ ----------------------------------------------------
  url                      OPC UA endpoint (e.g. opc.tcp://192.168.1.10:4840)
  security                 None, Sign, SignAndEncrypt
  username                 Optional
  password                 Optional
  publishing_interval_ms   Subscription update rate

### MQTT

  Option          Description
  --------------- -----------------------
  host            MQTT broker host
  port            MQTT broker port
  topic_prefix    Base namespace
  qos_state       QoS for state updates
  qos_cmd         QoS for commands
  retain_states   Retain state messages

### Bridge

  Option      Description
  ----------- ------------------------
  tags_file   Path to tags YAML file

------------------------------------------------------------------------

## 📝 Tags Configuration

Create the file:

/config/opcua_mqtt_bridge/tags.yaml

Example:

read: - path: "Analog/Temp_Eingang" node: "ns=3;s=Analog.Temp_Eingang"
type: float

-   path: "Status/Heizung_Ausschank" node:
    "ns=3;s=Status.Heizung_Ausschank" type: bool

rw: - path: "Sollwert/Temp_Halle" node: "ns=3;s=Sollwert.Temp_Halle"
type: float

-   path: "Steuer/ANF/AUTO/JR" node: "ns=3;s=Steuer.ANF_AUTO_JR" type:
    bool

-   read = subscribe only

-   rw = subscribe + write support

------------------------------------------------------------------------

## 🔁 Write Logic

To write a value to the PLC:

`<prefix>`{=html}/cmd/`<path>`{=html}

Examples:

opcua/plc01/cmd/Sollwert/Temp_Halle → 22.5
opcua/plc01/cmd/Steuer/ANF/AUTO/JR → true

Supported values: - true / false - 1 / 0 - numeric values

------------------------------------------------------------------------

## 🟢 Availability

The bridge publishes:

`<prefix>`{=html}/meta/availability

Values: - online - offline

------------------------------------------------------------------------

## 🔐 Security

Currently supports: - None - Username/Password

Certificate-based security can be added in future versions.

------------------------------------------------------------------------

## 🧠 Notes

-   Uses OPC UA Subscriptions (not polling)
-   Designed for fast real-time sync
-   Thread-safe MQTT write handling
-   Suitable for heating and building automation systems

------------------------------------------------------------------------

## 🛠 Roadmap

-   OPC UA auto-browse generator
-   Certificate support
-   Deadband filtering
-   Change-only publishing
-   Write acknowledgment topics
-   HA MQTT Discovery mode (optional)

------------------------------------------------------------------------

## 👤 Maintainer

David Wieninger\
https://github.com/wienni112
