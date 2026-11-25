"""IOT-153 : coupure Device -> Edge (pertes, doublons, désordre, lots incomplets).

Les 600 observations du test historique (200 itérations) sont rejouées par le
vrai chemin Edge MQTT (``mqtt_edge_adapter.on_message``) avec une horloge
simulée. Pour chaque taux de perte, des messages sont supprimés, d'autres
dupliqués (retransmissions QoS 1) et l'ordre est mélangé dans chaque lot.
Une coupure franche d'un capteur est aussi simulée.

Mesures : lots complets et expirés, décisions B2 (jamais deux pour un même
lot), conformité des décisions des lots complets à la référence, alertes B1
journalisées même quand le lot reste incomplet, rappel effectif.

Usage : python -B src/evaluate_device_loss.py --output results/resilience_device_loss_<date>.json
"""

import argparse
import asyncio
import contextlib
import io
import json
import platform
import random
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_pq_attacks as attacks  # noqa: E402
import mqtt_edge_adapter  # noqa: E402
from telemetry import ITERATION_TIMEOUT_SECONDS  # noqa: E402

LOSS_RATES = (0.0, 0.01, 0.05, 0.10, 0.20, 0.30)
DUPLICATE_RATE = 0.10
SEEDS = (11, 22, 33)
OUTAGE_DEVICE = "node-02"
OUTAGE_ITERATIONS = (60, 120)  # coupure franche de node-02 sur ces itérations [début, fin)


class Replay:
    """Edge MQTT neuf, horloge simulée, décisions B2 comptées par lot."""

    def __init__(self, workdir):
        self.run = attacks.EdgeRun("none", workdir)
        self.clock = SimpleNamespace(now=1000.0)
        mqtt_edge_adapter.time = SimpleNamespace(monotonic=lambda: self.clock.now)
        self.decision_calls = Counter()
        self.b1_alert_keys = set()
        analyze = self.run._analyze

        def counting(messages):
            first = messages[0]
            self.decision_calls[first["session_id"], first["iteration"]] += 1
            return analyze(messages)

        mqtt_edge_adapter.analyze_devices = counting

    async def deliver(self, message):
        if message["payload"]["prediction"] == 1:
            self.b1_alert_keys.add((message["session_id"], message["iteration"], message["src"]["agent"]))
        await self.run.send(message)

    def expire_all(self):
        for key in list(mqtt_edge_adapter.iteration_start_times):
            mqtt_edge_adapter.expire_iteration(key, self.clock.now)


def plan_iteration(rng, messages, loss_rate, duplicate_rate, cut_device=None):
    """Messages réellement reçus par l'Edge pour une itération."""
    received = []
    for message in messages:
        if message["src"]["agent"] == cut_device:
            continue
        if rng.random() < loss_rate:
            continue
        received.append(message)
        if rng.random() < duplicate_rate:
            received.append(json.loads(json.dumps(message)))  # retransmission identique
    rng.shuffle(received)
    return received


async def replay(replay_state, groups, rng, loss_rate, duplicate_rate, outage=False):
    sent = Counter()
    for index, key in enumerate(groups):
        messages = attacks.legit_messages(groups, key)
        cut = OUTAGE_DEVICE if outage and OUTAGE_ITERATIONS[0] <= index < OUTAGE_ITERATIONS[1] else None
        received = plan_iteration(rng, messages, loss_rate, duplicate_rate, cut)
        sent["messages_emitted"] += len(messages)
        sent["messages_received"] += len(received)
        sent["b1_alerts_received"] += len({
            m["id"] for m in received if m["payload"]["prediction"] == 1
        })
        for message in received:
            await replay_state.deliver(message)
        # Un lot incomplet expire après ITERATION_TIMEOUT_SECONDS (surveillance simulée).
        replay_state.clock.now += ITERATION_TIMEOUT_SECONDS + 0.5
        replay_state.expire_all()
    return sent


def measure(replay_state, groups, sent):
    metrics = mqtt_edge_adapter.collection_metrics
    incidents = replay_state.run.incidents()
    local_alerts = sum(1 for i in incidents if i.get("reason") == "LOCAL_ML_ANOMALY")
    conform = mismatched = 0
    positives = detected = detected_with_b1 = 0
    b1_alert_keys = replay_state.b1_alert_keys
    for (session, iteration), rows in groups.items():
        for row in rows:
            decision = replay_state.run.decisions.get((session, iteration, row["device_id"]))
            if decision is not None:
                if decision == int(row["b2_prediction"]):
                    conform += 1
                else:
                    mismatched += 1
            if int(row["label"]):
                positives += 1
                if decision == 1:
                    detected += 1
                if decision == 1 or (session, iteration, row["device_id"]) in b1_alert_keys:
                    detected_with_b1 += 1
    double_decisions = sum(1 for calls in replay_state.decision_calls.values() if calls > 1)
    return {
        **sent,
        "batches_completed": metrics["batches_completed"],
        "batches_expired": metrics["batches_expired"],
        "observations_missing_at_timeout": metrics["observations_missing_at_timeout"],
        "duplicates_ignored": metrics["messages_duplicate"],
        "b2_decisions": conform + mismatched,
        "b2_decisions_matching_reference": conform,
        "b2_decisions_differing": mismatched,
        "double_decisions": double_decisions,
        "local_alerts_journaled": local_alerts,
        "iterations_without_any_message": len(groups) - metrics["batches_completed"] - metrics["batches_expired"],
        "b2_recall_on_positives": round(detected / positives, 4) if positives else None,
        "recall_b2_or_delivered_b1_alert": round(detected_with_b1 / positives, 4) if positives else None,
        "positives": positives,
    }


def evaluate(limit=None, seeds=SEEDS, loss_rates=LOSS_RATES, workdir=None):
    """Balayage des taux de perte (plusieurs graines) puis coupure franche d'un capteur."""
    groups = attacks.load_reference(limit)
    results = {"loss_sweep": {}, "sensor_outage": {}}
    saved_time = mqtt_edge_adapter.time
    with attacks.edge_sandbox(), tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        try:
            for rate in loss_rates:
                runs = []
                for seed in seeds:
                    state = Replay(workdir or tmp)
                    sent = asyncio.run(replay(state, groups, random.Random(seed), rate, DUPLICATE_RATE))
                    runs.append({"seed": seed, **measure(state, groups, sent)})
                results["loss_sweep"][f"{rate:.2f}"] = runs
            state = Replay(workdir or tmp)
            sent = asyncio.run(replay(state, groups, random.Random(seeds[0]), 0.0, 0.0, outage=True))
            results["sensor_outage"] = measure(state, groups, sent)
        finally:
            mqtt_edge_adapter.time = saved_time
    return results


def summary_table(results):
    lines = [
        "| Perte | Lots complets | Lots expirés | Décisions B2 conformes / différentes | Doubles décisions | Alertes B1 reçues → journalisées | Rappel B2 | Rappel B2 ou alerte B1 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rate, runs in results["loss_sweep"].items():
        def mean(key):
            return sum(run[key] for run in runs) / len(runs)
        lines.append(
            f"| {float(rate):.0%} | {mean('batches_completed'):.1f} | {mean('batches_expired'):.1f} | "
            f"{mean('b2_decisions_matching_reference'):.1f} / {mean('b2_decisions_differing'):.1f} | "
            f"{sum(run['double_decisions'] for run in runs)} | "
            f"{mean('b1_alerts_received'):.1f} → {mean('local_alerts_journaled'):.1f} | "
            f"{mean('b2_recall_on_positives'):.1%} | {mean('recall_b2_or_delivered_b1_alert'):.1%} |"
        )
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
        "ticket": "IOT-153",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference": "results/collaborative_b2_predictions.csv",
        "iteration_timeout_seconds": ITERATION_TIMEOUT_SECONDS,
        "duplicate_rate": DUPLICATE_RATE,
        "seeds": list(SEEDS),
        "sensor_outage": {"device": OUTAGE_DEVICE, "iterations": list(OUTAGE_ITERATIONS)},
        "versions": {"python": platform.python_version(), "platform": platform.platform()},
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary_table(results))
    print("Coupure franche :", json.dumps(results["sensor_outage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
