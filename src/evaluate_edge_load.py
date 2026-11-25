"""IOT-154 : surcharge de l'Edge (débit croissant, latence, pertes, saturation).

Le vrai chemin Edge MQTT (``mqtt_edge_adapter.on_message``) reçoit des messages
à débit imposé, en temps réel, sur une seule boucle asyncio. Les messages
reprennent les températures et prédictions B1 du test historique, avec une
nouvelle session à chaque passage pour éviter la déduplication.

Pour chaque débit offert : débit atteint, temps de séjour par message (attente
+ traitement), lots complets et expirés (un lot expire si son traitement prend
du retard au-delà de 5 s). Mesuré en C0 et avec vérification ML-DSA-44 (C2).
Le broker et le réseau ne sont pas inclus : la mesure isole la capacité de
calcul de l'Edge. Les impressions de l'Edge sont redirigées en mémoire.

Usage : python -B src/evaluate_edge_load.py --output results/resilience_edge_load_<date>.json
"""

import argparse
import asyncio
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

import evaluate_pq_attacks as attacks  # noqa: E402
import mqtt_edge_adapter  # noqa: E402

RATES = (100, 500, 1000, 2000, 5000, 10000, 20000, 50000)
CONFIGURATIONS = ("none", "ml-dsa-44")
DURATION_SECONDS = 2.0
MAX_MESSAGES = 30000
LATENCY_BUDGET_MS = 100.0


def build_stream(run, groups, count):
    """``count`` messages sérialisés (signés si la configuration l'exige)."""
    wires = []
    cycle = 0
    while len(wires) < count:
        for key in groups:
            session, iteration = key
            for message in attacks.legit_messages(groups, key):
                message["session_id"] = f"{session}-load{cycle}"
                wires.append(json.dumps(run.legitimate(message)).encode("utf-8"))
                if len(wires) == count:
                    return wires
        cycle += 1
    return wires


async def offer(wires, rate):
    start = time.perf_counter()
    sojourn = []
    service = []
    for index, data in enumerate(wires):
        arrival = start + index / rate
        delay = arrival - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        begin = time.perf_counter()
        await mqtt_edge_adapter.on_message("aiot/telemetry/load", data)
        end = time.perf_counter()
        service.append((end - begin) * 1000)
        sojourn.append((end - arrival) * 1000)
    elapsed = time.perf_counter() - start
    return sojourn, service, elapsed


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))]


def measure_rate(algorithm, groups, rate, workdir, duration=DURATION_SECONDS, max_messages=MAX_MESSAGES):
    count = max(30, min(max_messages, int(rate * duration)))
    count -= count % 3
    run = attacks.EdgeRun(algorithm, workdir)
    wires = build_stream(run, groups, count)
    sojourn, service, elapsed = asyncio.run(offer(wires, rate))
    # Surveillance finale : les lots encore ouverts expireraient après 5 s.
    metrics = mqtt_edge_adapter.collection_metrics
    achieved = count / elapsed if elapsed else 0.0
    return {
        "offered_rate": rate,
        "messages": count,
        "achieved_rate": round(achieved, 1),
        "achieved_share": round(achieved / rate, 3),
        "service_mean_ms": round(statistics.fmean(service), 4),
        "sojourn_p50_ms": round(percentile(sojourn, 0.50), 3),
        "sojourn_p95_ms": round(percentile(sojourn, 0.95), 3),
        "sojourn_max_ms": round(max(sojourn), 3),
        "batches_completed": metrics["batches_completed"],
        "batches_expired": metrics["batches_expired"],
        "messages_auth_rejected": metrics["messages_auth_rejected"],
        "messages_invalid": metrics["messages_invalid"],
    }


def saturation(points):
    """Plus haut débit offert tenu (≥ 95 % atteint, p95 de séjour ≤ budget)."""
    sustained = [
        point["offered_rate"] for point in points
        if point["achieved_share"] >= 0.95 and point["sojourn_p95_ms"] <= LATENCY_BUDGET_MS
    ]
    return max(sustained) if sustained else None


def evaluate(rates=RATES, configurations=CONFIGURATIONS, duration=DURATION_SECONDS,
             max_messages=MAX_MESSAGES, workdir=None):
    groups = attacks.load_reference()
    results = {}
    with attacks.edge_sandbox(), tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        for algorithm in configurations:
            points = [
                measure_rate(algorithm, groups, rate, workdir or tmp, duration, max_messages)
                for rate in rates
            ]
            results[algorithm] = {
                "points": points,
                "sustained_rate": saturation(points),
                "max_achieved_rate": max(point["achieved_rate"] for point in points),
            }
    return results


def table(results):
    lines = [
        "| Configuration | Débit offert (msg/s) | Débit atteint | Traitement moyen (ms) | Séjour p50 / p95 (ms) | Lots complets / expirés |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for algorithm, data in results.items():
        for point in data["points"]:
            lines.append(
                f"| {algorithm} | {point['offered_rate']} | {point['achieved_rate']} | "
                f"{point['service_mean_ms']} | {point['sojourn_p50_ms']} / {point['sojourn_p95_ms']} | "
                f"{point['batches_completed']} / {point['batches_expired']} |"
            )
        lines.append(f"| {algorithm} — débit tenu | {data['sustained_rate']} | max {data['max_achieved_rate']} | | | |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    results = evaluate()
    document = {
        "ticket": "IOT-154",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Capacité de calcul de l'Edge (on_message), une boucle asyncio, sans broker ni réseau.",
        "duration_seconds": DURATION_SECONDS,
        "max_messages": MAX_MESSAGES,
        "latency_budget_ms": LATENCY_BUDGET_MS,
        "versions": {"python": platform.python_version(), "platform": platform.platform()},
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(results))


if __name__ == "__main__":
    main()
