
import asyncio
import json
import uuid
from datetime import datetime, timezone

from aiocoap import Context, Message, POST


COAP_URL = "coap://127.0.0.1:5683/telemetry"


async def send_telemetry():

    # Creer un message IoT
    message = {
        "v": 1,
        "iteration": 1,
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "telemetry",
        "src": {
            "tier": "device",
            "agent": "node-01"
        },
        "dst": {
            "tier": "edge",
            "agent": "edge-coordinator"
        },
        "payload": {
            "temperature": 25.4,
            "vibration": 0.3,
            "prediction": 0,
            "inference_ms": 1.2
        }
    }

    # Creer le contexte CoAP
    protocol = await Context.create_client_context()

    try:
        # Preparer une requete POST
        request = Message(
            code=POST,
            uri=COAP_URL,
            payload=json.dumps(message).encode("utf-8")
        )

        # Envoyer la requete et attendre la reponse
        response = await protocol.request(request).response

        print("DEVICE : Message CoAP envoye")
        print(f"EDGE : Code de reponse = {response.code}")
        print(
            "EDGE : Reponse = "
            + response.payload.decode("utf-8")
        )

    finally:
        await protocol.shutdown()


if __name__ == "__main__":
    asyncio.run(send_telemetry())
