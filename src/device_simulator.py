import random
import time
import json
import uuid
from datetime import datetime, timezone
import joblib
import pandas as pd
from pathlib import Path
import socket
import asyncio
from aiocoap import Context, Message, POST
from mqttsn import MqttSnClient

devices = ["node-01", "node-02", "node-03"]

TEMP_THRESHOLD = 35

device_states = {
    "node-01": "NORMAL",
    "node-02": "NORMAL",
    "node-03": "NORMAL"
}
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_FILE = BASE_DIR / "models" / "device_model.joblib"

model = joblib.load(MODEL_FILE)

print("Modèle ML chargé avec succès")


EDGE_HOST = "127.0.0.1"
EDGE_PORT = 5000


COAP_URL = "coap://127.0.0.1:5683/telemetry"
MQTTSN_HOST = "127.0.0.1"
MQTTSN_PORT = 10001
async def send_to_edge_coap(protocol, message):

    request = Message(
        code=POST,
        uri=COAP_URL,
        payload=json.dumps(message).encode("utf-8")
    )

    try:
        response = await protocol.request(request).response

        if response.code.is_successful():
            print(
                f"COAP DEVICE : {message['src']['agent']} "
                f"envoye - {response.code}"
            )
        else:
            print(
                f"COAP DEVICE : Requete refusee "
                f"- {response.code}"
            )

    except Exception as error:
        print(f"COAP DEVICE : Erreur : {error}")


async def send_to_edge_mqttsn(client, message):
    """Publie une mesure IoT via MQTT-SN."""

    device_id = message["src"]["agent"]
    topic = f"aiot/telemetry/{device_id}"

    payload = json.dumps(message).encode("utf-8")

    try:
        await client.publish(topic, payload, qos=1)

        print(
            f"MQTT-SN DEVICE : {device_id} "
            f"envoye sur {topic}"
        )

    except Exception as error:
        print(
            f"MQTT-SN DEVICE : Erreur pour "
            f"{device_id} : {error}"
        )


def send_to_edge(message):
    """Envoie un message JSON au serveur Edge via TCP."""

    try:
        with socket.create_connection(
            (EDGE_HOST, EDGE_PORT),
            timeout=5
        ) as client:

            data = json.dumps(message) + "\n"

            client.sendall(data.encode("utf-8"))

            print(
                f"DEVICE : Message envoyé par "
                f"{message['src']['agent']}"
            )

    except OSError as error:
        print(f"DEVICE : Erreur réseau : {error}")


def create_message(device_id, temperature, anomaly):

    message = {
        "v": 1,
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "anomaly_alert" if anomaly else "telemetry",
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
            "temperature": temperature,
            "status": device_states[device_id],
            "anomaly": anomaly
        }
    }

    return message


def simulate_device(device_id, iteration):

    # Scénario FDI : fausse température plausible
    if device_id == "node-02" and iteration == 5:
        temperature = 32.5
        vibration = 0.3

    # Scénario de surchauffe sur node-03
    elif device_id == "node-03" and iteration == 8:
        temperature = 40.0
        vibration = 1.1

    # Fonctionnement normal
    else:
        temperature = round(random.uniform(24, 26), 2)
        vibration = round(random.uniform(0.1, 0.5), 3)

    # Préparer les données pour le modèle ML
    features = pd.DataFrame(
        [[temperature, vibration]],
        columns=["temperature", "vibration"]
    )

    # Prédiction locale
    start_time = time.perf_counter()

    prediction = int(model.predict(features)[0])

    end_time = time.perf_counter()

    inference_ms = (end_time - start_time) * 1000

    anomaly = prediction == 1

    if anomaly:
        device_states[device_id] = "SAFE_MODE"

    message = create_message(device_id, temperature, anomaly)

    # Ajouter les informations ML au message
    message["payload"]["vibration"] = vibration
    message["payload"]["prediction"] = prediction
    message["payload"]["inference_ms"] = round(inference_ms, 4)

    return message



latencies = []



async def run_simulation():

    # Un client MQTT-SN pour chaque capteur simulé
    clients = {}

    try:
        for device in devices:
            client = MqttSnClient(client_id=device)

            await client.connect(
                MQTTSN_HOST,
                MQTTSN_PORT
            )

            clients[device] = client

        # Simulation de 10 itérations
        for i in range(10):

            print(f"\n===== ITERATION {i + 1} =====")

            for device in devices:

                message = simulate_device(device, i)

                latencies.append(
                    message["payload"]["inference_ms"]
                )

                message["iteration"] = i + 1

                # Transmission MQTT-SN
                await send_to_edge_mqttsn(
                    clients[device],
                    message
                )

            await asyncio.sleep(1)

    finally:
        for client in clients.values():
            await client.close()


asyncio.run(run_simulation())



from statistics import mean
import math

# Trier les latences
sorted_latencies = sorted(latencies)

# Calculer le percentile P95 (nearest rank)
p95_index = math.ceil(0.95 * len(sorted_latencies)) - 1

report = {
    "total_predictions": len(latencies),
    "average_latency_ms": round(mean(latencies), 4),
    "max_latency_ms": round(max(latencies), 4),
    "p95_latency_ms": round(sorted_latencies[p95_index], 4),
    "model_size_bytes": MODEL_FILE.stat().st_size
}

# Enregistrer le rapport
report_file = BASE_DIR / "data" / "performance_report.json"

with open(report_file, "w", encoding="utf-8") as file:
    json.dump(report, file, indent=4)

print("\n===== RAPPORT DE PERFORMANCE =====")
print(json.dumps(report, indent=4))

