"""IOT-155 : benchmark des trois niveaux Device, Edge et Cloud.

Mesures de calcul, hors réseau, sur la machine qui exécute le script :
- Device : chargement et taille du modèle B1, inférence telle que le capteur
  la fait (DataFrame d'une ligne puis ``predict``), signature du message ;
- Edge : traitement d'un message par ``on_message`` (C0 et ML-DSA-44) et
  calcul B2 d'un lot de trois mesures ;
- Cloud : enregistrement d'un incident, ouverture d'un incident scellé,
  analyse A2A à règles.

Les latences réseau du banc B3 (Edge -> Cloud, Cloud -> décision) sont reprises
du fichier de résultats réseau s'il existe. La colonne RAG reste vide jusqu'à E14.

Usage : python -B src/evaluate_tiers.py --output results/tiers_benchmark_<date>.json
"""

import argparse
import contextlib
import io
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cloud_store  # noqa: E402
import edge_agent  # noqa: E402
import evaluate_pq_attacks as attacks  # noqa: E402
import evaluate_pq_cost as cost  # noqa: E402
import message_auth  # noqa: E402
import secure_channel  # noqa: E402

MODEL_FILE = ROOT / "models" / "device_model.joblib"
NETWORK_RESULTS = ROOT / "results" / "pq_b3_network_2026-11-25.json"
OPERATIONS = 1000


def summary(samples):
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 4),
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[max(0, round(0.95 * len(ordered)) - 1)], 4),
    }


def timed(operation, repetitions):
    samples = []
    for _ in range(repetitions):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start) * 1000)
    return summary(samples)


def device_tier(repetitions):
    import joblib
    import pandas as pd

    start = time.perf_counter()
    model = joblib.load(MODEL_FILE)
    load_ms = (time.perf_counter() - start) * 1000
    rows = [(25.0 + 0.01 * (i % 200), 0.1 + 0.002 * (i % 200)) for i in range(repetitions)]
    queue = iter(rows)

    def infer():
        temperature, vibration = next(queue)
        features = pd.DataFrame([[temperature, vibration]], columns=["temperature", "vibration"])
        int(model.predict(features)[0])

    model.predict(pd.DataFrame([[25.0, 0.2]], columns=["temperature", "vibration"]))  # échauffement
    message = cost.sample_message()
    signing = {}
    for algorithm in ("ed25519", "ml-dsa-44"):
        signer = message_auth.DeviceSigner("node-03", algorithm, message_auth.generate_private_key(algorithm))
        signing[algorithm] = timed(lambda: signer.sign(message), repetitions)
    return {
        "model_bytes": MODEL_FILE.stat().st_size,
        "model_load_ms": round(load_ms, 3),
        "inference_with_dataframe": timed(infer, repetitions),
        "message_signing": signing,
    }


def edge_tier(repetitions):
    processing = cost.edge_processing(repetitions=3)
    groups = attacks.load_reference()
    batches = []
    for key in list(groups)[:repetitions]:
        batch = attacks.legit_messages(groups, key)
        for message in batch:
            message.setdefault("payload", {})
        batches.append(batch)
    queue = iter(batches * (repetitions // max(1, len(batches)) + 1))
    with contextlib.redirect_stdout(io.StringIO()):
        b2 = timed(lambda: edge_agent.calculate_b2(next(queue)), repetitions)
    return {
        "on_message": {
            algorithm: processing[algorithm]["edge_on_message"]
            for algorithm in ("none", "ml-dsa-44")
        },
        "b2_batch_calculation": b2,
    }


def cloud_tier(repetitions, workdir):
    incident = dict(cost.SAMPLE_INCIDENT)
    results = {}
    cloud_file = Path(workdir) / "cloud.jsonl"
    previous = cloud_store.storage_path
    cloud_store.storage_path = lambda: cloud_file
    try:
        results["store_incident"] = timed(lambda: cloud_store.report_incident(dict(incident)), repetitions)
    finally:
        cloud_store.storage_path = previous
    mode = "ml-kem-768"
    keys = secure_channel.generate_cloud_keys(mode)
    edge_key = message_auth.generate_private_key("ml-dsa-44")
    sealer = secure_channel.EdgeSealer(mode, {k: v.public_key() for k, v in keys.items()}, edge_key)
    opener = secure_channel.CloudOpener(mode, keys, edge_key.public_key())
    envelopes = iter([sealer.seal(incident) for _ in range(repetitions)])
    results["open_sealed_incident_ml_kem_768"] = timed(lambda: opener.open(next(envelopes)), repetitions)
    try:
        from cloud_a2a_server import analyze_incident
    except ImportError as error:  # FastAPI absent de l'environnement
        results["a2a_rule_analysis"] = {"skipped": f"{type(error).__name__}: {error}"}
    else:
        stored = {**incident, "cloud_incident_id": "cloud-1"}
        results["a2a_rule_analysis"] = timed(lambda: analyze_incident(stored), repetitions)
    results["rag_supervisor"] = None  # E14
    return results


def network_reference():
    if not NETWORK_RESULTS.exists():
        return None
    document = json.loads(NETWORK_RESULTS.read_text(encoding="utf-8"))
    reference = {}
    for key, item in document["summary"].items():
        runs = [run for run in document["runs"]
                if f"{run['auth_mode']}|{run['channel_mode']}" == key]
        reference[key] = {
            name: round(statistics.median(run["latency_mean_ms"][name] for run in runs), 2)
            for name in ("edge_to_cloud", "cloud_to_decision", "edge_to_decision")
        }
    return {"source": str(NETWORK_RESULTS.relative_to(ROOT)).replace("\\", "/"), "median_ms": reference}


def evaluate(repetitions=OPERATIONS, workdir=None):
    with tempfile.TemporaryDirectory() as tmp:
        return {
            "device": device_tier(repetitions),
            "edge": edge_tier(min(repetitions, 200)),
            "cloud": cloud_tier(repetitions, workdir or tmp),
            "network_reference": network_reference(),
        }


def table(results):
    device, edge, cloud = results["device"], results["edge"], results["cloud"]
    a2a = cloud["a2a_rule_analysis"]
    rows = [
        ("Device", "Inférence B1 (DataFrame + predict)", device["inference_with_dataframe"]),
        ("Device", "Signature ML-DSA-44", device["message_signing"]["ml-dsa-44"]),
        ("Edge", "Traitement d'un message, C0", edge["on_message"]["none"]),
        ("Edge", "Traitement d'un message, ML-DSA-44", edge["on_message"]["ml-dsa-44"]),
        ("Edge", "Calcul B2 d'un lot", edge["b2_batch_calculation"]),
        ("Cloud", "Enregistrement d'un incident", cloud["store_incident"]),
        ("Cloud", "Ouverture d'un incident scellé (ML-KEM-768)", cloud["open_sealed_incident_ml_kem_768"]),
        ("Cloud", "Analyse A2A à règles", a2a if "mean_ms" in a2a else None),
    ]
    lines = ["| Niveau | Opération | Moyenne (ms) | Médiane (ms) | p95 (ms) |", "|---|---|---:|---:|---:|"]
    for tier, name, stats in rows:
        if stats is None:
            lines.append(f"| {tier} | {name} | non mesuré | | |")
        else:
            lines.append(f"| {tier} | {name} | {stats['mean_ms']} | {stats['median_ms']} | {stats['p95_ms']} |")
    lines.append(f"| Device | Modèle B1 | {device['model_bytes']} octets, chargé en {device['model_load_ms']} ms | | |")
    lines.append("| Cloud | Agent superviseur RAG | à venir (E14) | | |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    results = evaluate()
    import cryptography
    import sklearn
    document = {
        "ticket": "IOT-155",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Calcul par niveau, hors réseau ; latences réseau reprises du banc B3.",
        "operations": OPERATIONS,
        "versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "scikit_learn": sklearn.__version__,
            "cryptography": cryptography.__version__,
        },
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(results))
    reference = results["network_reference"]
    if reference:
        print("Réseau (médianes du banc B3, ms) :", json.dumps(reference["median_ms"]))


if __name__ == "__main__":
    main()
