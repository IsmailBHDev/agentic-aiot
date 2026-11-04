
import asyncio
import json
import logging

from mqtt_bus import PahoBus
from edge_agent import process_message, analyze_devices

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC = "aiot/telemetry/+"

EXPECTED_DEVICES = {"node-01", "node-02", "node-03"}

# Messages regroupés par numéro d'itération
pending_iterations = {}


async def on_message(topic, data):
    try:
        message = json.loads(data.decode("utf-8"))

        device_id = message["src"]["agent"]
        iteration = message["iteration"]

        if device_id not in EXPECTED_DEVICES:
            return

        # Traitement individuel
        process_message(message)

        # Regroupement des messages de la même itération
        batch = pending_iterations.setdefault(iteration, {})
        batch[device_id] = message

        if EXPECTED_DEVICES.issubset(batch.keys()):
            print(f"\n===== EDGE : ITERATION {iteration} =====")

            analyze_devices(list(batch.values()))

            del pending_iterations[iteration]

    except (ValueError, KeyError, TypeError) as error:
        print(f"EDGE MQTT : Message invalide : {error}")


async def main():
    logging.basicConfig(level=logging.INFO)

    bus = PahoBus(
        BROKER_HOST,
        BROKER_PORT,
        client_id="mqtt-edge-adapter-local"
    )

    await bus.subscribe(TOPIC, on_message)
    await bus.start()

    print("EDGE MQTT : En attente des mesures IoT...")

    try:
        await asyncio.Event().wait()
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
