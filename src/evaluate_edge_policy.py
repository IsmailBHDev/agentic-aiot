"""IOT-159 : évaluation des règles Edge ajustées depuis le Cloud.

1. **Distribution.** Politique légitime, altérée, avec un champ interdit (seuil
   B2), hors bornes, signée par un tiers, non signée ou plus ancienne, en modes
   ``none``, ``ed25519`` et ``ml-dsa-44``.
2. **Non-régression.** Les 600 observations du test historique sont rejouées
   par le vrai chemin Edge MQTT sous chaque combinaison de politiques : les
   décisions B2 doivent rester identiques à la référence (le seuil n'est pas
   ajustable et l'isolement n'agit que sur la journalisation).
3. **Isolement.** La session 909 (générateur d'E07, B1 de référence) est
   rejouée en ``isolate_once`` puis en ``report_all`` : incidents
   ``SENSOR_INCONSISTENCY``, anomalies contextuelles couvertes, faux incidents,
   et qualité des incidents comme étiquettes (lien avec IOT-157).
4. **Délai des lots.** Le test historique est rejoué avec une horloge simulée :
   une itération par seconde, 80 % des messages en 0 à 0,2 s, 20 % en retard
   de 1 à 9 s (graines 11, 22, 33). Pour chaque délai : lots complets,
   expirés, rappel B2 et délai de décision.

Usage : python -B src/evaluate_edge_policy.py --output results/edge_policy_<date>.json
"""

import argparse
import asyncio
import base64
import contextlib
import io
import json
import platform
import random
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import edge_policy  # noqa: E402
import evaluate_device_loss as loss  # noqa: E402
import evaluate_pq_attacks as attacks  # noqa: E402
import message_auth  # noqa: E402
import mqtt_edge_adapter  # noqa: E402
import retrain_b1  # noqa: E402
import evaluate_tinyml  # noqa: E402

MODES = ("none", "ed25519", "ml-dsa-44")
TIMEOUTS = (1.0, 2.0, 5.0, 10.0)
DELAY_SEEDS = (11, 22, 33)
LATE_SHARE = 0.20
ISOLATION_SESSION_SEED = retrain_b1.TEST_SEED


def policy_document(version=2, timeout=5.0, isolation="report_all"):
    return {"version": version, "batch_timeout_seconds": timeout, "isolation": isolation}


@contextlib.contextmanager
def policy(document=None):
    """Applique une politique non signée le temps d'un rejeu, puis revient à l'historique."""
    edge_policy.reset()
    try:
        if document is not None:
            edge_policy.apply(edge_policy.sign_policy(document, "none", None), "none")
        yield edge_policy.current
    finally:
        edge_policy.reset()


# ---------------------------------------------------------------- 1. distribution

def distribution(mode):
    cloud = attacker = None
    public_key = None
    if mode != message_auth.NO_AUTH:
        cloud = message_auth.generate_private_key(mode)
        attacker = message_auth.generate_private_key(mode)
        public_key = cloud.public_key()

    def attempt(envelope, active=None):
        edge_policy.reset()
        if active is not None:
            edge_policy.apply(edge_policy.sign_policy(active, mode, cloud), mode, public_key)
        before = edge_policy.current
        try:
            applied = edge_policy.apply(envelope, mode, public_key)
            result = {"status": "applied", "version": applied.version,
                      "batch_timeout_seconds": applied.batch_timeout_seconds,
                      "isolation": applied.isolation}
        except edge_policy.PolicyError as error:
            result = {"status": "refused", "reason": error.reason,
                      "unchanged": edge_policy.current == before}
        edge_policy.reset()
        return result

    legit = edge_policy.sign_policy(policy_document(), mode, cloud)
    tampered = json.loads(json.dumps(legit))
    tampered["policy"]["batch_timeout_seconds"] = 60.0
    threshold = json.loads(json.dumps(legit))
    threshold["policy"]["b2_threshold_celsius"] = 1.0
    out_of_bounds = {"policy": policy_document(timeout=0.1), "alg": mode}
    if cloud is not None:  # signé par la vraie clé, en contournant le contrôle de publication
        out_of_bounds["sig"] = base64.b64encode(
            cloud.sign(edge_policy._canonical(out_of_bounds))).decode("ascii")
    results = {
        "legitimate": attempt(legit),
        "tampered_after_signing": attempt(tampered),
        "b2_threshold_injected": attempt(threshold),
        "out_of_bounds_timeout": attempt(out_of_bounds),
        "older_version": attempt(edge_policy.sign_policy(policy_document(version=2), mode, cloud),
                                 active=policy_document(version=3)),
    }
    if mode != message_auth.NO_AUTH:
        results["signed_by_third_party"] = attempt(edge_policy.sign_policy(policy_document(), mode, attacker))
        unsigned = {"policy": policy_document(), "alg": mode}
        results["unsigned"] = attempt(unsigned)
    try:
        edge_policy.sign_policy({**policy_document(), "b2_threshold_celsius": 1.0}, mode, cloud)
        results["cloud_cannot_publish_threshold"] = False
    except edge_policy.PolicyError:
        results["cloud_cannot_publish_threshold"] = True
    return results


# ---------------------------------------------------------------- 2. non-régression

def parity(workdir):
    groups = attacks.load_reference()
    out = {}
    for timeout in TIMEOUTS:
        for isolation in edge_policy.ISOLATION_MODES:
            with policy(policy_document(timeout=timeout, isolation=isolation)), attacks.edge_sandbox(), \
                    contextlib.redirect_stdout(io.StringIO()):
                run = attacks.EdgeRun("none", workdir)
                asyncio.run(attacks.scenario_baseline(run, groups))
                matching = sum(
                    run.decisions.get((s, i, row["device_id"])) == bool(int(row["b2_prediction"]))
                    for (s, i), rows in groups.items() for row in rows)
                incidents = run.incidents()
            out[f"timeout={timeout:g}s,{isolation}"] = {
                "b2_decisions": len(run.decisions),
                "matching_reference": matching,
                "sensor_inconsistency_incidents": sum(
                    i["reason"] == "SENSOR_INCONSISTENCY" for i in incidents),
            }
    return out


# ---------------------------------------------------------------- 3. isolement

def isolation_effect(workdir):
    active, _, _ = evaluate_tinyml.train_reference()
    frame = retrain_b1.session(ISOLATION_SESSION_SEED)
    contextual = frame[frame["scenario"] == "CONTEXTUAL_ANOMALY"]
    contextual_keys = {
        (s, i, d) for s, i, d, label in
        contextual[retrain_b1.KEY + ["label"]].itertuples(index=False, name=None) if label == 1}
    negatives = {
        (s, i, d) for s, i, d, label in
        frame[retrain_b1.KEY + ["label"]].itertuples(index=False, name=None) if label == 0}
    out = {}
    for isolation in edge_policy.ISOLATION_MODES:
        with policy(policy_document(isolation=isolation)):
            telemetry, incidents = retrain_b1.collect(frame, active, workdir)
        collaborative = {(i["session_id"], i["iteration"], i["device_id"])
                         for i in incidents if i["reason"] == "SENSOR_INCONSISTENCY"}
        dataset = retrain_b1.build_dataset(telemetry, incidents, frame, "incidents")
        out[isolation] = {
            "sensor_inconsistency_incidents": len(collaborative),
            "contextual_anomalies": len(contextual_keys),
            "contextual_anomalies_with_incident": len(collaborative & contextual_keys),
            "collaborative_incidents_on_normal_measurements": len(collaborative & negatives),
            "incident_label_quality": retrain_b1.label_quality(dataset),
        }
    return out


# ---------------------------------------------------------------- 4. délai des lots

async def _delayed_replay(state, groups, rng, first_arrival):
    events = []
    for index, key in enumerate(groups):
        for message in attacks.legit_messages(groups, key):
            late = rng.random() < LATE_SHARE
            delay = rng.uniform(1.0, 9.0) if late else rng.uniform(0.0, 0.2)
            events.append((1000.0 + index + delay, index, message))
    events.sort(key=lambda event: (event[0], event[1]))
    for arrival, _, message in events:
        state.clock.now = arrival
        state.expire_all()
        key = (message["session_id"], message["iteration"])
        first_arrival.setdefault(key, arrival)
        await state.deliver(message)
    state.clock.now += 100.0
    state.expire_all()


def timeout_effect(workdir):
    groups = attacks.load_reference()
    positives = {(s, i, row["device_id"]) for (s, i), rows in groups.items()
                 for row in rows if int(row["label"])}
    out = {}
    saved_time = mqtt_edge_adapter.time
    try:
        for timeout in TIMEOUTS:
            runs = []
            for seed in DELAY_SEEDS:
                with policy(policy_document(timeout=timeout, isolation="isolate_once")), \
                        attacks.edge_sandbox(), contextlib.redirect_stdout(io.StringIO()):
                    state = loss.Replay(workdir)
                    first_arrival, decision_delays = {}, []
                    counting = mqtt_edge_adapter.analyze_devices

                    def timed(messages, counting=counting, first_arrival=first_arrival,
                              decision_delays=decision_delays, state=state):
                        key = (messages[0]["session_id"], messages[0]["iteration"])
                        decision_delays.append(state.clock.now - first_arrival[key])
                        return counting(messages)

                    mqtt_edge_adapter.analyze_devices = timed
                    asyncio.run(_delayed_replay(state, groups, random.Random(seed), first_arrival))
                    metrics = mqtt_edge_adapter.collection_metrics
                    detected = sum(bool(state.run.decisions.get(key)) for key in positives)
                    runs.append({
                        "seed": seed,
                        "batches_completed": metrics["batches_completed"],
                        "batches_expired": metrics["batches_expired"],
                        "b2_decisions": len(state.run.decisions),
                        "b2_recall": round(detected / len(positives), 4),
                        "decision_delay_median_s": round(statistics.median(decision_delays), 3),
                        "decision_delay_max_s": round(max(decision_delays), 3),
                    })
            out[f"{timeout:g}"] = {
                "runs": runs,
                "mean_batches_completed": round(statistics.mean(r["batches_completed"] for r in runs), 1),
                "mean_b2_recall": round(statistics.mean(r["b2_recall"] for r in runs), 4),
                "mean_decision_delay_median_s": round(
                    statistics.mean(r["decision_delay_median_s"] for r in runs), 3),
            }
    finally:
        mqtt_edge_adapter.time = saved_time
        edge_policy.reset()
    return out


def evaluate(workdir=None):
    import cryptography

    base = Path(workdir or ROOT / "artifacts")
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        document = {
            "ticket": "IOT-159",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "cryptography": cryptography.__version__},
            "b2_threshold_celsius": edge_agent.DIFFERENCE_THRESHOLD,
            "historical_policy": {"batch_timeout_seconds": edge_policy.HISTORICAL.batch_timeout_seconds,
                                  "isolation": edge_policy.HISTORICAL.isolation},
            "distribution": {mode: distribution(mode) for mode in MODES},
            "b2_parity_historical_test": parity(tmp),
            "isolation_session": f"feedback-seed-{ISOLATION_SESSION_SEED}",
            "isolation": isolation_effect(tmp),
            "delay_model": {"late_share": LATE_SHARE, "on_time_delay_s": [0.0, 0.2],
                            "late_delay_s": [1.0, 9.0], "iteration_period_s": 1.0,
                            "seeds": list(DELAY_SEEDS)},
            "batch_timeout": timeout_effect(tmp),
        }
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    document = evaluate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for mode, results in document["distribution"].items():
        print(mode, {k: (v if isinstance(v, bool) else v.get("reason", v["status"]))
                     for k, v in results.items()})
    for name, item in document["b2_parity_historical_test"].items():
        print(name, item)
    print(json.dumps(document["isolation"], indent=1))
    for timeout, item in document["batch_timeout"].items():
        print(timeout, {k: v for k, v in item.items() if k != "runs"})


if __name__ == "__main__":
    main()
