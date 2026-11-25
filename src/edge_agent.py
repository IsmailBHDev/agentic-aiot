
import json
import os
import uuid
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import median

import edge_policy

# Chemin du fichier d'incidents
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INCIDENT_FILE = Path(os.environ.get(
    "AIOT_EDGE_INCIDENT_FILE", str(DATA_DIR / "incidents.jsonl")
))

# Noeuds isoles independants pour chaque session
isolated_devices_by_session = {}

# Seuil d'incoherence entre les capteurs
DIFFERENCE_THRESHOLD = 2.50


def get_isolated_devices(session_id):
    """Retourne les noeuds isoles d'une session."""
    return isolated_devices_by_session.setdefault(session_id, set())


def save_incident(
    device_id,
    temperature,
    reference,
    reason,
    session_id,
    *,
    iteration=None
):
    INCIDENT_FILE.parent.mkdir(parents=True, exist_ok=True)

    incident = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "device_id": device_id,
        "temperature": temperature,
        "reference": reference,
        "reason": reason,
        "action": (
            "ISOLATE"
            if reason == "SENSOR_INCONSISTENCY"
            else "SAFE_MODE_REPORTED"
        )
    }
    if iteration is not None:
        incident["iteration"] = iteration

    with open(INCIDENT_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(incident) + "\n")

    print(f"EDGE : Incident enregistré pour {device_id}")


def isolate_device(device_id, session_id):
    """Isole un noeud uniquement dans sa session."""

    isolated_devices = get_isolated_devices(session_id)

    if device_id not in isolated_devices:
        isolated_devices.add(device_id)

        print(
            f"EDGE : {device_id} isolé logiquement "
            f"dans la session {session_id}"
        )


def process_message(message):
    """Traite une mesure individuelle."""

    session_id = message["session_id"]
    device_id = message["src"]["agent"]

    temperature = message["payload"]["temperature"]
    vibration = message["payload"]["vibration"]
    prediction = message["payload"]["prediction"]
    inference_ms = message["payload"]["inference_ms"]

    isolated_devices = get_isolated_devices(session_id)

    print(f"Latence ML : {inference_ms:.4f} ms")
    print(f"EDGE : Message reçu de {device_id}")
    print(f"Température : {temperature} °C")
    print(f"Vibration : {vibration}")
    print(f"Prédiction ML : {prediction}")

    if message["type"] == "anomaly_alert":

        print(f"EDGE : Alerte ML reçue de {device_id}")

        save_incident(
            device_id,
            temperature,
            None,
            "LOCAL_ML_ANOMALY",
            session_id,
            iteration=message.get("iteration")
        )

    if device_id in isolated_devices:
        print(f"EDGE : {device_id} est déjà isolé")


def calculate_b2(messages):
    """Retourne la médiane et les décisions B2 pour trois mesures synchronisées."""
    if len(messages) != 3:
        raise ValueError("B2 requiert trois mesures")

    group_keys = set()
    payloads = {}
    for message in messages:
        try:
            session_id = message["session_id"]
            iteration = message["iteration"]
            device_id = message["src"]["agent"]
            payload = message["payload"]
            temperature = payload["temperature"]
            prediction = payload["prediction"]
        except (KeyError, TypeError) as error:
            raise ValueError("Mesure B2 incomplete ou mal formee") from error

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Identifiant de session B2 invalide")
        if type(iteration) is not int or iteration < 0:
            raise ValueError("Iteration B2 invalide")
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("Identifiant de capteur B2 invalide")
        try:
            valid_temperature = type(temperature) in (int, float) and isfinite(temperature)
        except OverflowError:
            valid_temperature = False
        if not valid_temperature:
            raise ValueError("Temperature B2 invalide")
        if type(prediction) is not int or prediction not in (0, 1):
            raise ValueError("Prediction B1 invalide")
        if device_id in payloads:
            raise ValueError("B2 requiert trois capteurs distincts")

        group_keys.add((session_id, iteration))
        payloads[device_id] = payload

    if len(group_keys) != 1:
        raise ValueError("B2 requiert une session et une iteration communes")

    reference = median(payload["temperature"] for payload in payloads.values())
    decisions = {}
    for device_id, payload in payloads.items():
        signed_deviation = payload["temperature"] - reference
        deviation = abs(signed_deviation)
        collaborative_alert = deviation > DIFFERENCE_THRESHOLD
        b1_prediction = payload["prediction"]
        decisions[device_id] = {
            "temperature": payload["temperature"],
            "reference": reference,
            "signed_deviation": signed_deviation,
            "deviation": deviation,
            "b1_prediction": b1_prediction,
            "collaborative_alert": collaborative_alert,
            "b2_prediction": b1_prediction == 1 or collaborative_alert,
        }

    return reference, decisions


def analyze_devices(messages):
    """Calcule B2, puis applique la politique d'isolement de la session."""
    if len(messages) < 3:
        return

    reference, decisions = calculate_b2(messages)
    session_id = messages[0]["session_id"]
    isolated_devices = get_isolated_devices(session_id)

    print(f"\nEDGE : Médiane = {reference:.2f} °C")

    for device_id, decision in decisions.items():
        # IOT-159 : en report_all, un capteur déjà isolé reste journalisé
        if decision["collaborative_alert"] and (
            device_id not in isolated_devices
            or edge_policy.reports_isolated_devices()
        ):

            print(
                f"EDGE : Incohérence détectée sur {device_id}"
            )

            save_incident(
                device_id,
                decision["temperature"],
                reference,
                "SENSOR_INCONSISTENCY",
                session_id,
                iteration=messages[0]["iteration"]
            )

            isolate_device(device_id, session_id)

    return reference, decisions
