
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

# Chemin du fichier d'incidents
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INCIDENT_FILE = DATA_DIR / "incidents.jsonl"

# Noeuds isoles independants pour chaque session
isolated_devices_by_session = {}

# Seuil d'incoherence entre les capteurs
DIFFERENCE_THRESHOLD = 5


def get_isolated_devices(session_id):
    """Retourne les noeuds isoles d'une session."""
    return isolated_devices_by_session.setdefault(session_id, set())


def save_incident(
    device_id,
    temperature,
    reference,
    reason,
    session_id
):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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
            session_id
        )

    if device_id in isolated_devices:
        print(f"EDGE : {device_id} est déjà isolé")


def analyze_devices(messages):
    """Analyse collaborative des capteurs d'une session."""

    if not messages:
        return

    session_id = messages[0]["session_id"]

    # Protection contre le melange des sessions
    if any(
        message["session_id"] != session_id
        for message in messages
    ):
        raise ValueError(
            "Analyse impossible : sessions differentes"
        )

    isolated_devices = get_isolated_devices(session_id)

    # Conserver uniquement les noeuds non isoles
    temperatures = {}

    for message in messages:
        device_id = message["src"]["agent"]

        if device_id not in isolated_devices:
            temperatures[device_id] = (
                message["payload"]["temperature"]
            )

    if len(temperatures) < 3:
        print("EDGE : Moins de 3 nœuds actifs")
        print("EDGE : Analyse collective suspendue")
        return

    # Calcul de la temperature mediane
    reference = median(temperatures.values())

    print(f"\nEDGE : Médiane = {reference:.2f} °C")

    for device_id, temperature in temperatures.items():

        difference = abs(temperature - reference)

        if difference > DIFFERENCE_THRESHOLD:

            print(
                f"EDGE : Incohérence détectée sur {device_id}"
            )

            save_incident(
                device_id,
                temperature,
                reference,
                "SENSOR_INCONSISTENCY",
                session_id
            )

            isolate_device(device_id, session_id)

        else:
            print(f"EDGE : {device_id} cohérent")
