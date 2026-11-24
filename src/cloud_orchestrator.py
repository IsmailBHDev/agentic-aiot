
"""Orchestrateur Cloud : transmission des incidents vers A2A."""
from datetime import datetime, timezone
import json
import os
import uuid
from pathlib import Path
import argparse
import time
import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
INCIDENTS_FILE = Path(os.environ.get(
    "AIOT_CLOUD_INCIDENT_FILE", str(BASE_DIR / "data" / "cloud_incidents.jsonl")
))
DECISIONS_FILE = Path(os.environ.get(
    "AIOT_CLOUD_DECISION_FILE", str(BASE_DIR / "data" / "cloud_decisions.jsonl")
))

A2A_URL = os.environ.get("AIOT_A2A_URL", "http://127.0.0.1:9000/")


def send_to_a2a(incident: dict) -> dict:
    """Envoie un incident Cloud à l'agent A2A."""

    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "text",
                        "text": json.dumps(incident)
                    }
                ]
            }
        }
    }

    response = httpx.post(
        A2A_URL,
        json=request,
        timeout=10.0
    )

    response.raise_for_status()
    result = response.json()

    if "error" in result:
        raise RuntimeError(result["error"])

    return result


def save_decision(response: dict, expected_incident_id=None) -> dict:
    """Extrait et enregistre une décision reçue via A2A."""

    result = response["result"]

    if result["status"]["state"] != "completed":
        raise ValueError("A2A analysis is not completed")

    text = result["artifacts"][0]["parts"][0]["text"]
    analysis = json.loads(text)

    if not isinstance(analysis, dict):
        raise ValueError("Invalid A2A analysis")

    if not analysis.get("cloud_incident_id"):
        raise ValueError("Missing cloud_incident_id")
    if expected_incident_id is not None and analysis["cloud_incident_id"] != expected_incident_id:
        raise ValueError("A2A response references a different Cloud incident")

    decision = {
        **analysis,
        "a2a_task_id": result["id"],
        "decision_timestamp": datetime.now(
            timezone.utc
        ).isoformat()
    }

    DECISIONS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with DECISIONS_FILE.open(
        "a",
        encoding="utf-8"
    ) as file:
        file.write(
            json.dumps(decision, ensure_ascii=False)
            + "\n"
        )

    return decision

def get_processed_incident_ids() -> set[str]:
    """Récupère les incidents ayant déjà une décision enregistrée."""

    if not DECISIONS_FILE.exists():
        return set()

    processed_ids = set()

    with DECISIONS_FILE.open(
        "r",
        encoding="utf-8"
    ) as file:
        for line in file:
            if not line.strip():
                continue

            decision = json.loads(line)
            incident_id = decision.get("cloud_incident_id")

            if incident_id:
                processed_ids.add(incident_id)

    return processed_ids


def process_pending_incidents():
    """Analyse tous les incidents Cloud sans décision enregistrée."""

    if not INCIDENTS_FILE.exists():
        return 0

    incidents = [
        json.loads(line)
        for line in INCIDENTS_FILE.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    processed_ids = get_processed_incident_ids()
    processed_count = 0

    for incident in incidents:
        incident_id = incident.get("cloud_incident_id")

        if not incident_id:
            continue

        if incident_id in processed_ids:
            continue

        print(
            f"A2A : Analyse de l'incident {incident_id}",
            flush=True
        )

        try:
            response = send_to_a2a(incident)
            decision = save_decision(response, expected_incident_id=incident_id)

            processed_ids.add(incident_id)
            processed_count += 1

            print(
                f"A2A : Décision enregistrée "
                f"pour {decision['device_id']} "
                f"({decision['severity']})",
                flush=True
            )

        except Exception as error:
            print(
                f"A2A : Erreur pour {incident_id} : {error}",
                flush=True
            )

    return processed_count


def main():
    parser = argparse.ArgumentParser(
        description="Agentic-AIoT Cloud A2A Orchestrator"
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Surveiller automatiquement les incidents Cloud"
    )

    args = parser.parse_args()

    if not args.watch:
        count = process_pending_incidents()
        print(f"A2A : {count} incident(s) traité(s).")
        return

    print(
        "A2A : Surveillance automatique active",
        flush=True
    )

    try:
        while True:
            process_pending_incidents()
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nA2A : Surveillance arrêtée.")


if __name__ == "__main__":
    main()
