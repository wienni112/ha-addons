import asyncio
import json
import logging
import yaml
from asyncua import Client, ua
import paho.mqtt.client as mqtt

OPTIONS_FILE = "/data/options.json"

def load_options():
    with open(OPTIONS_FILE, "r") as f:
        return json.load(f)

def load_tags(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

class SubHandler:
    def __init__(self, mqtt_client, prefix, qos, retain):
        self.mqtt = mqtt_client
        self.prefix = prefix
        self.qos = qos
        self.retain = retain
        self.node_path_map = {}

    def datachange_notification(self, node, val, data):
        path = self.node_path_map.get(node.nodeid.to_string())
        if path:
            topic = f"{self.prefix}/state/{path}"
            self.mqtt.publish(topic, val, qos=self.qos, retain=self.retain)

async def main():
    opts = load_options()
    tags = load_tags(opts["bridge"]["tags_file"])

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("opcua_bridge")

    # MQTT Setup
    mqtt_client = mqtt.Client()
    if opts["mqtt"]["username"]:
        mqtt_client.username_pw_set(
            opts["mqtt"]["username"],
            opts["mqtt"]["password"]
        )
    mqtt_client.connect(opts["mqtt"]["host"], opts["mqtt"]["port"])
    mqtt_client.loop_start()

    prefix = opts["mqtt"]["topic_prefix"]

    async with Client(opts["opcua"]["url"]) as client:
        log.info("Connected to OPC UA")

        mqtt_client.publish(f"{prefix}/meta/availability", "online", retain=True)

        handler = SubHandler(
            mqtt_client,
            prefix,
            opts["mqtt"]["qos_state"],
            opts["mqtt"]["retain_states"]
        )

        subscription = await client.create_subscription(
            opts["opcua"]["publishing_interval_ms"],
            handler
        )

        node_map = {}

        for section in ["read", "rw"]:
            for tag in tags.get(section, []):
                node = client.get_node(tag["node"])
                node_map[tag["path"]] = node
                handler.node_path_map[node.nodeid.to_string()] = tag["path"]
                await subscription.subscribe_data_change(node)

        # MQTT Write Handling
        def on_message(client_m, userdata, msg):
            topic = msg.topic.replace(f"{prefix}/cmd/", "")
            if topic in node_map:
                payload = msg.payload.decode()
                node = node_map[topic]

                async def write():
                    try:
                        if payload.lower() in ["true","1","on"]:
                            await node.write_value(True)
                        elif payload.lower() in ["false","0","off"]:
                            await node.write_value(False)
                        else:
                            await node.write_value(float(payload))
                    except Exception as e:
                        log.error(f"Write error {topic}: {e}")

                asyncio.create_task(write())

        mqtt_client.subscribe(f"{prefix}/cmd/#", qos=opts["mqtt"]["qos_cmd"])
        mqtt_client.on_message = on_message

        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
