
import json
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

session_id = str(uuid.uuid4())

client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"timeout-test-{uuid.uuid4().hex[:8]}"
)

client.connect("127.0.0.1", 1883, 60)
client.loop_start()

try:
    print(f"SESSION TEST : {session_id}")

    for device_id in ["node-01", "node-02"]:

        message = {
            "v": 1,
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "iteration": 1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "telemetry",
            "src": {
                "tier": "device",
                "agent": device_id
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

        topic = f"aiot/telemetry/{device_id}"

        result = client.publish(
            topic,
            json.dumps(message),
            qos=1
        )

        result.wait_for_publish()

        print(f"Message publie : {device_id}")

finally:
    client.disconnect()
    client.loop_stop()
