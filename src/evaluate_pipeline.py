"""Évaluation des latences du pipeline Agentic-AIoT."""

import csv
import json
from datetime import datetime
from pathlib import Path
import statistics

BASE_DIR = Path(__file__).resolve().parents[1]

INCIDENTS_FILE = BASE_DIR / "data" / "cloud_incidents.jsonl"
DECISIONS_FILE = BASE_DIR / "data" / "cloud_decisions.jsonl"
OUTPUT_FILE = BASE_DIR / "results" / "pipeline_latency.csv"


def load_jsonl(path):
    """Charge les enregistrements JSONL."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    with path.open("r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def latency_ms(start, end):
    """Calcule la différence entre deux horodatages en ms."""
    start_time = datetime.fromisoformat(start)
    end_time = datetime.fromisoformat(end)

    return round(
        (end_time - start_time).total_seconds() * 1000,
        3
    )


def print_session_statistics(rows):
    """Affiche les statistiques de latence par session."""

    sessions = {}

    for row in rows:
        session_id = row["session_id"]

        if not session_id:
            continue

        sessions.setdefault(session_id, []).append(row)

    print("\n=== STATISTIQUES PAR SESSION ===")

    for session_id, incidents in sessions.items():
        edge_cloud = [
            row["edge_to_cloud_ms"]
            for row in incidents
        ]

        cloud_a2a = [
            row["cloud_to_a2a_ms"]
            for row in incidents
        ]

        total = [
            row["edge_to_decision_ms"]
            for row in incidents
        ]

        print(f"\nSession : {session_id}")
        print(f"Nombre d'incidents : {len(incidents)}")

        print(
            "Edge -> Cloud (moyenne) :",
            round(statistics.mean(edge_cloud), 3),
            "ms"
        )

        print(
            "Cloud -> A2A (moyenne) :",
            round(statistics.mean(cloud_a2a), 3),
            "ms"
        )

        print(
            "Edge -> Décision (moyenne) :",
            round(statistics.mean(total), 3),
            "ms"
        )

        print(
            "Edge -> Décision (médiane) :",
            round(statistics.median(total), 3),
            "ms"
        )


def main():
    incidents = load_jsonl(INCIDENTS_FILE)
    decisions = load_jsonl(DECISIONS_FILE)
    EXPERIMENT_SESSION_ID = (
    "db3ddcce-ac07-4dae-ada5-98838716bd02"
    )

    incidents = [
        incident
        for incident in incidents
        if incident.get("session_id") == EXPERIMENT_SESSION_ID
    ]

    decisions_by_id = {
        decision["cloud_incident_id"]: decision
        for decision in decisions
        if decision.get("cloud_incident_id")
    }

    rows = []

    for incident in incidents:
        incident_id = incident.get("cloud_incident_id")
        decision = decisions_by_id.get(incident_id)

        if not decision:
            continue

        edge_time = incident["timestamp"]
        cloud_time = incident["cloud_received_at"]
        decision_time = decision["decision_timestamp"]

        rows.append({
            "session_id": incident.get("session_id"),
            "cloud_incident_id": incident_id,
            "device_id": incident.get("device_id"),
            "reason": incident.get("reason"),
            "edge_to_cloud_ms": latency_ms(
                edge_time, cloud_time
            ),
            "cloud_to_a2a_ms": latency_ms(
                cloud_time, decision_time
            ),
            "edge_to_decision_ms": latency_ms(
                edge_time, decision_time
            )
        })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "session_id",
        "cloud_incident_id",
        "device_id",
        "reason",
        "edge_to_cloud_ms",
        "cloud_to_a2a_ms",
        "edge_to_decision_ms"
    ]

    with OUTPUT_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Incidents Cloud : {len(incidents)}")
    print(f"Décisions A2A : {len(decisions)}")
    print(f"Incidents associés : {len(rows)}")
    print_session_statistics(rows)
    print(f"Résultats enregistrés : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
