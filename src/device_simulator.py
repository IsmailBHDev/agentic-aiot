
import random
import time
import json
import uuid
import math
import os
import socket
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import joblib
import pandas as pd
from aiocoap import Context, Message, POST
from mqttsn import MqttSnClient
from message_auth import NO_AUTH, auth_mode, load_signer
from model_signing import load_model


# ==========================================
# 1. CONFIGURATION
# ==========================================

devices = ["node-01", "node-02", "node-03"]

TEMP_THRESHOLD = 35

device_states = {
    "node-01": "NORMAL",
    "node-02": "NORMAL",
    "node-03": "NORMAL"
}

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_FILE = BASE_DIR / "models" / "device_model.joblib"

# IOT-158 : si AIOT_OTA_DEVICE_DIR est défini, le modèle actif installé par
# l'OTA simulé est chargé (signature revérifiée) et sa version est ajoutée à
# la télémétrie. Sinon, comportement historique : modèle de référence du dépôt.
OTA_DEVICE_DIR = os.environ.get("AIOT_OTA_DEVICE_DIR")
MODEL_VERSION = None
if OTA_DEVICE_DIR:
    import ota

    _ota_agent = ota.device_from_environment(OTA_DEVICE_DIR)
    model, MODEL_VERSION = _ota_agent.load_active()
    MODEL_FILE = _ota_agent.slots / ota.release_file(MODEL_VERSION)
else:
    # IOT-176 : signature vérifiée avant chargement si AIOT_MODEL_SIGNING est actif
    model = load_model(MODEL_FILE)

print("Modèle ML chargé avec succès")

EDGE_HOST = "127.0.0.1"
EDGE_PORT = 5000

COAP_URL = os.environ.get("AIOT_COAP_URL", "coap://127.0.0.1:5683/telemetry")

# IOT-166 : configurables pour les conteneurs ; valeurs historiques par défaut
MQTTSN_HOST = os.environ.get("MQTTSN_HOST", "127.0.0.1")
MQTTSN_PORT = int(os.environ.get("MQTTSN_PORT", "10000"))

latencies = []

# IOT-174 : signature des messages selon AIOT_AUTH_MODE (aucune en C0)
AUTH_MODE = auth_mode()
signers = (
    {device: load_signer(device, AUTH_MODE) for device in devices}
    if AUTH_MODE != NO_AUTH else {}
)


def authenticate(message):
    """Signe le message du capteur lorsque l'authentification est active."""
    signer = signers.get(message["src"]["agent"])
    return signer.sign(message) if signer else message


# ==========================================
# 2. COMMUNICATION COAP
# ==========================================

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


# ==========================================
# 3. COMMUNICATION MQTT-SN
# ==========================================

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


# ==========================================
# 4. COMMUNICATION TCP
# ==========================================

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


# ==========================================
# 5. CREATION DES MESSAGES
# ==========================================

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


# ==========================================
# 6. SIMULATION DES CAPTEURS ET ML
# ==========================================

def simulate_device(device_id, iteration):

    # Scénario FDI : température falsifiée
    if device_id == "node-02" and iteration == 5:
        temperature = 32.5
        vibration = 0.3

    # Scénario de surchauffe
    elif device_id == "node-03" and iteration == 8:
        temperature = 40.0
        vibration = 1.1

    # Fonctionnement normal
    else:
        temperature = round(random.uniform(24, 26), 2)
        vibration = round(random.uniform(0.1, 0.5), 3)

    # Préparation des données ML
    features = pd.DataFrame(
        [[temperature, vibration]],
        columns=["temperature", "vibration"]
    )

    # Mesure de la latence ML
    start_time = time.perf_counter()

    prediction = int(model.predict(features)[0])

    end_time = time.perf_counter()

    inference_ms = (end_time - start_time) * 1000

    anomaly = prediction == 1

    if anomaly:
        device_states[device_id] = "SAFE_MODE"

    message = create_message(
        device_id,
        temperature,
        anomaly
    )

    # Informations ML
    message["payload"]["vibration"] = vibration
    message["payload"]["prediction"] = prediction
    message["payload"]["inference_ms"] = round(
        inference_ms, 4
    )
    if MODEL_VERSION is not None:
        message["payload"]["model_version"] = MODEL_VERSION

    return message


# ==========================================
# 7. EXECUTION DE LA SIMULATION
# ==========================================

async def run_simulation():

    # Identifiant unique de cette exécution
    session_id = str(uuid.uuid4())

    print(f"\n===== SESSION : {session_id} =====")

    clients = {}

    try:
        # Un client MQTT-SN pour chaque capteur
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

                # Identifier la session et l'itération
                message["session_id"] = session_id
                message["iteration"] = i + 1
                message = authenticate(message)

                # Enregistrer la latence ML
                latencies.append(
                    message["payload"]["inference_ms"]
                )

                # Transmission MQTT-SN
                await send_to_edge_mqttsn(
                    clients[device],
                    message
                )

            await asyncio.sleep(1)

    finally:
        for client in clients.values():
            await client.close()

    return session_id


# ==========================================
# 8. RAPPORT DE PERFORMANCE
# ==========================================

session_id = asyncio.run(run_simulation())

sorted_latencies = sorted(latencies)

p95_index = math.ceil(
    0.95 * len(sorted_latencies)
) - 1

report = {
    "session_id": session_id,
    "total_predictions": len(latencies),
    "average_latency_ms": round(mean(latencies), 4),
    "max_latency_ms": round(max(latencies), 4),
    "p95_latency_ms": round(
        sorted_latencies[p95_index], 4
    ),
    "model_size_bytes": MODEL_FILE.stat().st_size
}

report_file = BASE_DIR / "data" / "performance_report.json"

report_file.parent.mkdir(
    parents=True,
    exist_ok=True
)

with open(report_file, "w", encoding="utf-8") as file:
    json.dump(report, file, indent=4)

print("\n===== RAPPORT DE PERFORMANCE =====")
print(json.dumps(report, indent=4))
