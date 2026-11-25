"""IOT-157 : pipeline de réentraînement de B1 à partir des journaux de l'Edge.

1. **Collecte.** Des sessions synthétiques nouvelles (graines 606 à 909, jamais
   utilisées par l'expérience historique ni par E07) sont produites par le
   générateur d'E07. Le capteur y exécute la version active (v1, le B1 de
   référence) ; chaque mesure passe par le vrai chemin Edge MQTT
   (``mqtt_edge_adapter.on_message``), qui journalise ses incidents. Le pipeline
   tient en parallèle un journal de télémétrie de l'Edge (mesures reçues).
2. **Jeu de données.** Le journal de télémétrie est joint au journal
   d'incidents par (session, itération, capteur). Deux sources d'étiquettes :
   - ``incidents`` : 1 si l'Edge a journalisé un incident pour cette mesure
     (``LOCAL_ML_ANOMALY`` ou ``SENSOR_INCONSISTENCY``), sans intervention humaine ;
   - ``annotated`` : étiquette du générateur, qui simule un opérateur qui
     confirme ou infirme chaque mesure revue.
3. **Réentraînement.** Mêmes hyperparamètres que B1 (profondeur 3, graine 42),
   sur l'entraînement historique (``data/collaborative_train.csv``) plus les
   sessions de retour (606, 707). Aucun réglage.
4. **Validation.** Un candidat n'est promu que si son F1 sur la session de
   validation (808) est au moins celui de la version active.
5. **Test.** La session 909 est tenue à l'écart et ne sert qu'au rapport final.
   Le test historique (600 observations) n'est jamais utilisé.
6. **Version.** Chaque candidat porte l'empreinte SHA-256 du modèle et du jeu
   de données. Avec ``--publish-repo``, un candidat promu est publié par l'OTA
   (IOT-158) sous la version suivante du catalogue.

Usage : python -B src/retrain_b1.py --output results/retraining_b1_<date>.json [--publish-repo DIR]
"""

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_e07  # noqa: E402
import evaluate_pq_attacks as attacks  # noqa: E402
import evaluate_tinyml  # noqa: E402

FEATURES = ["temperature", "vibration"]
KEY = ["session_id", "iteration", "device_id"]
FEEDBACK_SEEDS = (606, 707)
VALIDATION_SEED = 808
TEST_SEED = 909
LABEL_SOURCES = ("incidents", "annotated")
THRESHOLD = 2.50


def session(seed):
    frame = evaluate_e07.generate_session(seed)
    frame["session_id"] = f"feedback-seed-{seed}"
    return frame


def sha256_frame(frame):
    data = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_model(model):
    import joblib

    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


# ---------------------------------------------------------------- 1. collecte

async def _replay(run, frame, predictions):
    for (_, iteration), group in frame.groupby(["session_id", "iteration"], sort=True):
        for index, row in group.iterrows():
            message = attacks.make_message(
                row["device_id"], float(row["temperature"]), int(predictions[index]),
                row["session_id"], int(iteration))
            message["payload"]["vibration"] = float(row["vibration"])
            await run.send(message)


def collect(frame, model, workdir):
    """Rejoue une session par l'Edge ; renvoie (journal de télémétrie, incidents)."""
    frame = frame.reset_index(drop=True)
    predictions = model.predict(frame[FEATURES]).astype(int)
    telemetry = frame[KEY + FEATURES].copy()
    telemetry["b1_prediction"] = predictions
    with attacks.edge_sandbox(), contextlib.redirect_stdout(io.StringIO()):
        run = attacks.EdgeRun("none", workdir)
        asyncio.run(_replay(run, frame, predictions))
        incidents = run.incidents()
    return telemetry, incidents


# ---------------------------------------------------------------- 2. jeu de données

def build_dataset(telemetry, incidents, truth, label_source):
    """Joint télémétrie et incidents ; ``truth`` fournit l'étiquette annotée."""
    import pandas as pd

    flagged = {(i["session_id"], i.get("iteration"), i["device_id"]) for i in incidents}
    dataset = telemetry.copy()
    dataset["incident"] = [
        int((s, it, d) in flagged)
        for s, it, d in dataset[KEY].itertuples(index=False, name=None)
    ]
    annotated = truth[KEY + ["label"]]
    dataset = dataset.merge(annotated, on=KEY, how="left", validate="one_to_one")
    if dataset["label"].isna().any():
        raise ValueError("mesure sans étiquette annotée")
    dataset["label"] = dataset["label"].astype(int)
    if label_source == "incidents":
        dataset["train_label"] = dataset["incident"]
    elif label_source == "annotated":
        dataset["train_label"] = dataset["label"]
    else:
        raise ValueError(label_source)
    return pd.DataFrame(dataset)


def label_quality(dataset):
    """Qualité des étiquettes issues des incidents, mesurée contre l'annotation."""
    stats = evaluate_e07.metrics(dataset["label"], dataset["incident"])
    return {key: stats[key] for key in ("n", "tp", "fp", "fn", "recall")} | {
        "precision": round(stats["tp"] / max(1, stats["tp"] + stats["fp"]), 4),
    }


# ---------------------------------------------------------------- 3 à 5

def train(frame, labels):
    from sklearn.tree import DecisionTreeClassifier

    return DecisionTreeClassifier(max_depth=3, random_state=42).fit(frame[FEATURES], labels)


def b2_predictions(frame, b1):
    return (b1 == 1) | (frame["deviation"].abs() > THRESHOLD).to_numpy()


def score(model, frame):
    b1 = model.predict(frame[FEATURES]).astype(int)
    rounded = {}
    for name, predictions in (("b1", b1), ("b2", b2_predictions(frame, b1))):
        stats = evaluate_e07.metrics(frame["label"], predictions)
        rounded[name] = {key: round(value, 4) if isinstance(value, float) else value
                         for key, value in stats.items()}
    by_scenario = {}
    for scenario, group in frame.assign(b1=b1).groupby("scenario"):
        positives = group[group["label"] == 1]
        by_scenario[scenario] = {
            "b1_detected": f"{int(positives['b1'].sum())}/{len(positives)}",
            "b1_false_positives": int(((group["label"] == 0) & (group["b1"] == 1)).sum()),
        }
    rounded["b1_by_scenario"] = by_scenario
    return rounded


def run_pipeline(workdir, publish_repo=None, algorithm="none", private_key=None):
    import pandas as pd

    active, historical_train, _ = evaluate_tinyml.train_reference()
    sessions = {seed: session(seed) for seed in (*FEEDBACK_SEEDS, VALIDATION_SEED, TEST_SEED)}

    journals = {seed: collect(sessions[seed], active, workdir) for seed in FEEDBACK_SEEDS}
    feedback = {}
    for source in LABEL_SOURCES:
        parts = [build_dataset(*journals[seed], sessions[seed], source) for seed in FEEDBACK_SEEDS]
        feedback[source] = pd.concat(parts, ignore_index=True)

    validation, test = sessions[VALIDATION_SEED], sessions[TEST_SEED]
    active_validation = score(active, validation)
    candidates = {}
    for source, data in feedback.items():
        training = pd.concat([
            historical_train[FEATURES].assign(train_label=historical_train["label"]),
            data[FEATURES + ["train_label"]],
        ], ignore_index=True)
        model = train(training, training["train_label"])
        on_validation = score(model, validation)
        promoted = on_validation["b1"]["f1"] >= active_validation["b1"]["f1"]
        candidates[source] = {
            "model": model,
            "record": {
                "label_source": source,
                "training_rows": len(training),
                "feedback_rows": len(data),
                "feedback_positive_labels": int(data["train_label"].sum()),
                "dataset_sha256": sha256_frame(training),
                "model_sha256": sha256_model(model),
                "nodes": int(model.tree_.node_count),
                "validation": on_validation,
                "promoted": bool(promoted),
                "test": score(model, test),
            },
        }

    published = None
    promoted = [c for c in candidates.values() if c["record"]["promoted"]]
    if publish_repo and promoted:
        import ota

        # Le candidat promu au meilleur F1 de validation ; à égalité, l'annotation.
        best = max(promoted, key=lambda c: (c["record"]["validation"]["b1"]["f1"],
                                             c["record"]["label_source"] == "annotated"))
        latest = ota.latest_release(publish_repo)
        version = (latest["version"] if latest else 0) + 1
        record = best["record"]
        ota.publish_release(publish_repo, best["model"], version, algorithm, private_key, {
            "source": f"IOT-157, étiquettes {record['label_source']}",
            "dataset_sha256": record["dataset_sha256"],
            "model_sha256": record["model_sha256"],
            "validation_f1": record["validation"]["b1"]["f1"],
        })
        published = {"version": version, "label_source": record["label_source"]}

    return {
        "sessions": {
            "feedback": [f"feedback-seed-{s}" for s in FEEDBACK_SEEDS],
            "validation": f"feedback-seed-{VALIDATION_SEED}",
            "test": f"feedback-seed-{TEST_SEED}",
            "historical_test_used": False,
        },
        "collection": {
            f"feedback-seed-{seed}": {
                "measurements": len(journals[seed][0]),
                "incidents": len(journals[seed][1]),
                "incidents_by_reason": {
                    reason: sum(i["reason"] == reason for i in journals[seed][1])
                    for reason in ("LOCAL_ML_ANOMALY", "SENSOR_INCONSISTENCY")
                },
            }
            for seed in FEEDBACK_SEEDS
        },
        "incident_label_quality": label_quality(feedback["incidents"]),
        "active_v1": {
            "model_sha256": sha256_model(active),
            "validation": active_validation,
            "test": score(active, test),
        },
        "candidates": {source: c["record"] for source, c in candidates.items()},
        "published": published,
    }


def evaluate(workdir=None, publish_repo=None, algorithm="none", private_key=None):
    import numpy
    import pandas
    import sklearn

    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        results = run_pipeline(tmp, publish_repo, algorithm, private_key)
    return {
        "ticket": "IOT-157",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "numpy": numpy.__version__, "pandas": pandas.__version__,
            "scikit_learn": sklearn.__version__,
        },
        **results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    parser.add_argument("--publish-repo", default=None,
                        help="dépôt OTA où publier le candidat promu (signature selon AIOT_MODEL_SIGNING)")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    algorithm, private_key = "none", None
    if args.publish_repo:
        import ota

        algorithm, private_key = ota.cloud_signing_key()
    workdir = ROOT / "artifacts"
    workdir.mkdir(exist_ok=True)
    document = evaluate(workdir, args.publish_repo, algorithm, private_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "collection": document["collection"],
        "incident_label_quality": document["incident_label_quality"],
        "active_v1": {k: document["active_v1"][k]["b1"] for k in ("validation", "test")},
        "candidates": {s: {"promoted": c["promoted"], "validation_b1": c["validation"]["b1"],
                           "test_b1": c["test"]["b1"], "test_b2": c["test"]["b2"]}
                       for s, c in document["candidates"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
