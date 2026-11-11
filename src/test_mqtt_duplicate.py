
import json
import time
import uuid

import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC = "aiot/telemetry/node-01"

# Identifiants uniques pour ce test
session_id = str(uuid.uuid4())
message_id = str(uuid.uuid4())

message = {
    "v": 1,
    "id": message_id,
    "session_id": session_id,
    "iteration": 1,
    "type": "telemetry",
    "src": {
        "tier": "device",
        "agent": "node-01"
    },
    "dst": {
        "tier": "edge",
        "agent": "edge-coordinator"
    },
    "corr": None,
    "payload": {
        "temperature": 25.0,
        "vibration": 0.3,
        "prediction": 0,
        "inference_ms": 1.0,
        "status": "NORMAL",
        "anomaly": False
    }
}

payload = json.dumps(message)

client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"duplicate-test-{uuid.uuid4().hex[:8]}"
)

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

try:
    print(f"SESSION : {session_id}")
    print(f"MESSAGE ID : {message_id}")

    print("\nEnvoi 1 : message original")
    result = client.publish(TOPIC, payload, qos=1)
    result.wait_for_publish()
    print("Publication 1 confirmee")

    time.sleep(1)

    print("\nEnvoi 2 : meme message, meme UUID")
    result = client.publish(TOPIC, payload, qos=1)
    result.wait_for_publish()
    print("Publication 2 confirmee")

    time.sleep(1)

finally:
    client.loop_stop()
    client.disconnect()
