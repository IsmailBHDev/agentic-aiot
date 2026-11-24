"""IOT-175 : rejeu des attaques S1 à S3 du modèle de menace, en C0, C1 et C2.

Les attaques passent par le vrai chemin Edge MQTT (``mqtt_edge_adapter.on_message``)
et visent les 600 observations du test historique (200 itérations). Les
messages légitimes reprennent les températures et les prédictions B1 de
``results/collaborative_b2_predictions.csv`` ; les données, le seuil de 2,50 °C
et les résultats historiques ne sont pas modifiés.

- S1 : l'attaquant usurpe node-02 et node-03 dans chaque lot, avec leur vraie
  température + 3,50 °C, et ses messages arrivent avant les messages légitimes.
- S2 : l'attaquant rejoue les trois mesures de l'itération précédente,
  réétiquetées pour l'itération courante, avant les messages légitimes.
- S3 : l'attaquant envoie de fausses alertes locales B1 pour node-01 dans une
  session distincte.

Usage : python -B src/evaluate_pq_attacks.py --output results/pq_attacks_<date>.json
"""

import argparse
import asyncio
import contextlib
import csv
import io
import json
import platform
import sys
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cryptography

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import message_auth  # noqa: E402
import mqtt_edge_adapter  # noqa: E402

REFERENCE = ROOT / "results" / "collaborative_b2_predictions.csv"
DEVICES = ("node-01", "node-02", "node-03")
FORGED_DEVICES = ("node-02", "node-03")
FORGED_SHIFT_CELSIUS = 3.5
FAKE_ALERTS = 200
CONFIGURATIONS = ("none", "ed25519", "ml-dsa-44")
STATE = ("pending_iterations", "iteration_start_times",
         "processed_message_ids", "completed_iterations")


def load_reference(limit=None):
    groups = defaultdict(list)
    with REFERENCE.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            groups[row["session_id"], int(row["iteration"])].append(row)
    keys = sorted(groups, key=lambda key: (key[0], key[1]))
    if limit:
        keys = keys[:limit]
    return {key: sorted(groups[key], key=lambda row: row["device_id"]) for key in keys}


def make_message(device, temperature, prediction, session, iteration):
    return {
        "v": 1,
        "id": uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "anomaly_alert" if prediction else "telemetry",
        "src": {"tier": "device", "agent": device},
        "dst": {"tier": "edge", "agent": "edge-coordinator"},
        "session_id": session,
        "iteration": iteration,
        "payload": {
            "temperature": temperature,
            "prediction": prediction,
            "vibration": 0.3,
            "inference_ms": 0.5,
        },
    }


class EdgeRun:
    """Un Edge MQTT neuf, avec journal d'incidents et état isolés."""

    def __init__(self, algorithm, workdir):
        self.algorithm = algorithm
        self.decisions = {}
        self.signers = {}
        self.attacker = {}
        verifier = None
        if algorithm != message_auth.NO_AUTH:
            private = {d: message_auth.generate_private_key(algorithm) for d in DEVICES}
            self.signers = {
                d: message_auth.DeviceSigner(d, algorithm, key) for d, key in private.items()
            }
            # L'attaquant connaît l'algorithme et les identifiants, pas les clés.
            self.attacker = {
                d: message_auth.DeviceSigner(
                    d, algorithm, message_auth.generate_private_key(algorithm)
                )
                for d in DEVICES
            }
            verifier = message_auth.EdgeVerifier(
                algorithm, {d: key.public_key() for d, key in private.items()}
            )
        self.incident_file = Path(workdir) / f"incidents-{algorithm}-{uuid4().hex[:8]}.jsonl"
        edge_agent.DATA_DIR = Path(workdir)
        edge_agent.INCIDENT_FILE = self.incident_file
        edge_agent.isolated_devices_by_session = {}
        for name in STATE:
            setattr(mqtt_edge_adapter, name, {})
        mqtt_edge_adapter.collection_metrics = Counter()
        mqtt_edge_adapter.message_verifier = verifier
        mqtt_edge_adapter.analyze_devices = self._analyze

    def _analyze(self, messages):
        reference, decisions = edge_agent.analyze_devices(messages)
        first = messages[0]
        for device, decision in decisions.items():
            self.decisions[first["session_id"], first["iteration"], device] = decision["b2_prediction"]
        return reference, decisions

    def legitimate(self, message):
        signer = self.signers.get(message["src"]["agent"])
        return signer.sign(message) if signer else message

    def forged(self, message):
        signer = self.attacker.get(message["src"]["agent"])
        return signer.sign(message) if signer else message

    async def send(self, message):
        await mqtt_edge_adapter.on_message(
            f"aiot/telemetry/{message['src']['agent']}",
            json.dumps(message).encode("utf-8"),
        )

    def incidents(self):
        if not self.incident_file.exists():
            return []
        with self.incident_file.open(encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]


def detection_metrics(run, groups):
    counts = Counter()
    contextual = Counter()
    for (session, iteration), rows in groups.items():
        for row in rows:
            label = int(row["label"])
            predicted = run.decisions.get((session, iteration, row["device_id"]))
            if predicted is None:
                counts["no_decision"] += 1
                continue
            counts[("tp" if predicted else "fn") if label else ("fp" if predicted else "tn")] += 1
            if row["scenario"] == "CONTEXTUAL_ANOMALY" and label:
                contextual["detected" if predicted else "missed"] += 1
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "observations": sum(len(rows) for rows in groups.values()),
        "tp": tp, "fp": fp, "fn": fn, "tn": counts["tn"],
        "no_decision": counts["no_decision"],
        "f1": round(f1, 4),
        "contextual_detected": contextual["detected"],
        "contextual_total": contextual["detected"] + contextual["missed"],
    }


def collection(run):
    metrics = mqtt_edge_adapter.collection_metrics
    return {
        "messages_received": metrics["messages_received"],
        "messages_auth_rejected": metrics["messages_auth_rejected"],
        "messages_duplicate": metrics["messages_duplicate"],
        "messages_closed_batch": metrics["messages_closed_batch"],
        "batches_completed": metrics["batches_completed"],
    }


def legit_messages(groups, key):
    session, iteration = key
    return [
        make_message(row["device_id"], float(row["temperature"]),
                     int(row["b1_prediction"]), session, iteration)
        for row in groups[key]
    ]


async def scenario_baseline(run, groups):
    for key in groups:
        for message in legit_messages(groups, key):
            await run.send(run.legitimate(message))


async def scenario_forged_pair(run, groups):
    for key in groups:
        session, iteration = key
        for row in groups[key]:
            if row["device_id"] in FORGED_DEVICES:
                forged = make_message(
                    row["device_id"],
                    round(float(row["temperature"]) + FORGED_SHIFT_CELSIUS, 3),
                    0, session, iteration,
                )
                await run.send(run.forged(forged))
        for message in legit_messages(groups, key):
            await run.send(run.legitimate(message))


async def scenario_replay(run, groups):
    captured = {}
    for key in groups:
        session, iteration = key
        previous = captured.get(session)
        if previous:
            for message in previous:
                replayed = deepcopy(message)
                replayed["iteration"] = iteration
                replayed["id"] = uuid4().hex
                replayed["ts"] = datetime.now(timezone.utc).isoformat()
                await run.send(replayed)  # la signature d'origine est conservée
        sent = []
        for message in legit_messages(groups, key):
            signed = run.legitimate(message)
            sent.append(signed)
            await run.send(signed)
        captured[session] = sent


async def scenario_fake_alerts(run):
    for iteration in range(1, FAKE_ALERTS + 1):
        alert = make_message("node-01", 41.0, 1, "attack-fake-alerts", iteration)
        await run.send(run.forged(alert))


def evaluate(limit=None, workdir=None):
    groups = load_reference(limit)
    results = {"baseline": {}, "S1_forged_pair": {}, "S2_replay": {}, "S3_fake_alerts": {}}
    # Les impressions de l'Edge sont masquées pendant les rejeux.
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        workdir = workdir or tmp
        for algorithm in CONFIGURATIONS:
            run = EdgeRun(algorithm, workdir)
            asyncio.run(scenario_baseline(run, groups))
            results["baseline"][algorithm] = {**detection_metrics(run, groups), **collection(run)}

            run = EdgeRun(algorithm, workdir)
            asyncio.run(scenario_forged_pair(run, groups))
            results["S1_forged_pair"][algorithm] = {**detection_metrics(run, groups), **collection(run)}

            run = EdgeRun(algorithm, workdir)
            asyncio.run(scenario_replay(run, groups))
            results["S2_replay"][algorithm] = {**detection_metrics(run, groups), **collection(run)}

            run = EdgeRun(algorithm, workdir)
            asyncio.run(scenario_fake_alerts(run))
            fake = [i for i in run.incidents() if i.get("session_id") == "attack-fake-alerts"]
            results["S3_fake_alerts"][algorithm] = {
                "alerts_sent": FAKE_ALERTS,
                "incidents_created": len(fake),
                **collection(run),
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None,
                        help="Nombre d'itérations du test historique (200 par défaut)")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    output.parent.mkdir(parents=True, exist_ok=True)
    results = evaluate(args.limit)
    document = {
        "ticket": "IOT-175",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference": str(REFERENCE.relative_to(ROOT)).replace("\\", "/"),
        "b2_threshold_celsius": edge_agent.DIFFERENCE_THRESHOLD,
        "forged_devices": list(FORGED_DEVICES),
        "forged_shift_celsius": FORGED_SHIFT_CELSIUS,
        "configurations": list(CONFIGURATIONS),
        "versions": {
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "platform": platform.platform(),
        },
        "results": results,
    }
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
