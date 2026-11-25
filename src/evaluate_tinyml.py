"""IOT-156 : contrainte TinyML simulée pour le modèle B1.

Le B1 historique (arbre de décision de profondeur 3, graine 42, entraîné sur
``data/collaborative_train.csv``) est réentraîné en mémoire : aucun modèle n'est
écrit et les résultats historiques ne sont pas modifiés. On vérifie d'abord
qu'il reproduit les 600 prédictions de ``results/baseline_b1_predictions.csv``.

Variantes comparées sur le test historique (600 observations) et sur
l'entraînement (2 400) :
- référence : modèle scikit-learn sérialisé par joblib ;
- arbre élagué : sous-arbres dont toutes les feuilles ont la même classe
  remplacés par une feuille (aucun changement de prédiction possible) ;
- quantification entière des seuils et des mesures : millièmes (int32, sans
  perte pour des mesures au millième) et centièmes (int16, avec perte) ;
- table compacte : un enregistrement d'octets par nœud, comme en mémoire flash.

Mesures : taille en octets, nombre de nœuds, temps d'inférence d'un échantillon,
accord avec la référence et F1.

Usage : python -B src/evaluate_tinyml.py --output results/tinyml_b1_<date>.json
"""

import argparse
import io
import json
import platform
import statistics
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN_FILE = ROOT / "data" / "collaborative_train.csv"
TEST_FILE = ROOT / "data" / "collaborative_test.csv"
REFERENCE_PREDICTIONS = ROOT / "results" / "baseline_b1_predictions.csv"
DEPLOYED_MODEL = ROOT / "models" / "device_model.joblib"
FEATURES = ["temperature", "vibration"]
LEAF = -1
# Mise à l'échelle entière : (facteur, format struct du seuil, nom)
QUANTIZATIONS = {
    "int32_milli": (1000, "i", "millièmes, int32"),
    "int16_centi": (100, "h", "centièmes, int16"),
}


def train_reference():
    import pandas as pd
    from sklearn.tree import DecisionTreeClassifier

    train = pd.read_csv(TRAIN_FILE)
    test = pd.read_csv(TEST_FILE)
    model = DecisionTreeClassifier(max_depth=3, random_state=42).fit(train[FEATURES], train["label"])
    return model, train, test


def tree_nodes(model):
    """Arbre scikit-learn -> liste de nœuds (feature, seuil, gauche, droite, classe)."""
    tree = model.tree_
    nodes = []
    for index in range(tree.node_count):
        left, right = int(tree.children_left[index]), int(tree.children_right[index])
        if left == LEAF:
            nodes.append({"leaf": True, "cls": int(tree.value[index][0].argmax())})
        else:
            nodes.append({
                "leaf": False, "feature": int(tree.feature[index]),
                "threshold": float(tree.threshold[index]), "left": left, "right": right,
            })
    return nodes


def prune(nodes):
    """Remplace tout sous-arbre de classe unique par une feuille, puis renumérote."""

    def classes(index):
        node = nodes[index]
        if node["leaf"]:
            return {node["cls"]}
        return classes(node["left"]) | classes(node["right"])

    pruned = []

    def copy(index):
        node = nodes[index]
        position = len(pruned)
        pruned.append(None)
        found = classes(index)
        if node["leaf"] or len(found) == 1:
            pruned[position] = {"leaf": True, "cls": found.pop()}
        else:
            new = dict(node)
            new["left"] = copy(node["left"])
            new["right"] = copy(node["right"])
            pruned[position] = new
        return position

    copy(0)
    return pruned


def quantize(nodes, scale):
    """Seuils entiers : x <= t  équivaut à  round(x * scale) <= floor(t * scale)
    lorsque les mesures ont au plus la résolution 1/scale."""
    import math

    quantized = []
    for node in nodes:
        if node["leaf"]:
            quantized.append(dict(node))
        else:
            quantized.append({**node, "threshold": math.floor(node["threshold"] * scale)})
    return quantized


def predict(nodes, values):
    index = 0
    while True:
        node = nodes[index]
        if node["leaf"]:
            return node["cls"]
        index = node["left"] if values[node["feature"]] <= node["threshold"] else node["right"]


def pack(nodes, threshold_format):
    """Table d'octets : nœud interne = type, feature, seuil, gauche, droite ; feuille = type, classe."""
    blob = bytearray()
    for node in nodes:
        if node["leaf"]:
            blob += struct.pack("<BB", 1, node["cls"])
        else:
            blob += struct.pack(f"<BB{threshold_format}BB", 0, node["feature"], node["threshold"],
                                node["left"], node["right"])
    return bytes(blob)


def f1(predictions, labels):
    tp = sum(1 for p, y in zip(predictions, labels) if p and y)
    fp = sum(1 for p, y in zip(predictions, labels) if p and not y)
    fn = sum(1 for p, y in zip(predictions, labels) if not p and y)
    return round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0


def timing(operation, samples, repetitions):
    durations = []
    for _ in range(repetitions):
        for sample in samples:
            start = time.perf_counter()
            operation(sample)
            durations.append((time.perf_counter() - start) * 1000)
    ordered = sorted(durations)
    return {
        "n": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 5),
        "median_ms": round(statistics.median(ordered), 5),
        "p95_ms": round(ordered[round(0.95 * len(ordered)) - 1], 5),
    }


def evaluate(repetitions=3):
    import warnings

    import joblib
    import numpy as np
    import pandas as pd

    # Inférence sur tableau NumPy sans noms de colonnes : avertissement attendu.
    warnings.filterwarnings("ignore", message="X does not have valid feature names")
    model, train, test = train_reference()
    reference = pd.read_csv(REFERENCE_PREDICTIONS)["b1_prediction"].astype(int).tolist()
    sk_test = model.predict(test[FEATURES]).astype(int).tolist()
    if sk_test != reference:
        raise SystemExit("Le B1 réentraîné ne reproduit pas les 600 prédictions de référence")

    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    nodes = tree_nodes(model)
    pruned = prune(nodes)
    test_values = test[FEATURES].to_numpy().tolist()
    train_values = train[FEATURES].to_numpy().tolist()
    labels_test = test["label"].astype(int).tolist()
    sk_train = model.predict(train[FEATURES]).astype(int).tolist()

    def compare(predictor):
        on_test = [predictor(values) for values in test_values]
        on_train = [predictor(values) for values in train_values]
        return {
            "agreement_test": sum(a == b for a, b in zip(on_test, sk_test)),
            "agreement_train": sum(a == b for a, b in zip(on_train, sk_train)),
            "f1_test": f1(on_test, labels_test),
        }

    variants = {
        "sklearn_joblib": {
            "nodes": model.tree_.node_count,
            "bytes": len(buffer.getvalue()),
            "agreement_test": len(reference), "agreement_train": len(sk_train),
            "f1_test": f1(sk_test, labels_test),
        },
        "pruned_float64": {
            "nodes": len(pruned),
            "bytes": len(pack(pruned, "d")),
            **compare(lambda values: predict(pruned, values)),
        },
    }
    quantized_trees = {}
    for name, (scale, threshold_format, label) in QUANTIZATIONS.items():
        quantized = quantize(pruned, scale)
        quantized_trees[name] = (quantized, scale)
        variants[f"pruned_{name}"] = {
            "description": label,
            "nodes": len(quantized),
            "bytes": len(pack(quantized, threshold_format)),
            **compare(lambda values, q=quantized, s=scale: predict(q, [round(v * s) for v in values])),
        }

    samples = test_values[:200]
    frames = [pd.DataFrame([values], columns=FEATURES) for values in samples]
    arrays = [np.array([values]) for values in samples]
    frame_queue = iter(frames * repetitions)
    array_queue = iter(arrays * repetitions)
    milli, milli_scale = quantized_trees["int32_milli"]
    inference = {
        "sklearn_dataframe": timing(lambda _: model.predict(next(frame_queue)), samples, repetitions),
        "sklearn_numpy": timing(lambda _: model.predict(next(array_queue)), samples, repetitions),
        "python_table_float": timing(lambda values: predict(pruned, values), samples, repetitions),
        "python_table_int32_milli": timing(
            lambda values: predict(milli, [round(v * milli_scale) for v in values]), samples, repetitions
        ),
    }

    deployed = None
    if DEPLOYED_MODEL.exists():
        deployed_model = joblib.load(DEPLOYED_MODEL)
        deployed_test = deployed_model.predict(test[FEATURES]).astype(int).tolist()
        deployed = {
            "file": str(DEPLOYED_MODEL.relative_to(ROOT)).replace("\\", "/"),
            "nodes": int(deployed_model.tree_.node_count),
            "file_bytes": DEPLOYED_MODEL.stat().st_size,
            "agreement_with_reference_b1_test": sum(a == b for a, b in zip(deployed_test, reference)),
            "f1_test": f1(deployed_test, labels_test),
        }
    return {
        "reference_check": {"retrained_matches_reference_predictions": True, "test_size": len(reference)},
        "variants": variants,
        "inference_single_sample": inference,
        "rules": {
            "pruned_float64": pruned,
            "pruned_int32_milli": milli,
        },
        "deployed_simulator_model": deployed,
    }


def table(results):
    lines = [
        "| Variante | Nœuds | Taille (octets) | Accord test / entraînement | F1 test |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, item in results["variants"].items():
        lines.append(
            f"| {name} | {item['nodes']} | {item['bytes']} | "
            f"{item['agreement_test']}/600 · {item['agreement_train']}/2400 | {item['f1_test']:.2%} |"
        )
    lines += ["", "| Inférence d'un échantillon | Moyenne (ms) | Médiane (ms) | p95 (ms) |", "|---|---:|---:|---:|"]
    for name, stats in results["inference_single_sample"].items():
        lines.append(f"| {name} | {stats['mean_ms']} | {stats['median_ms']} | {stats['p95_ms']} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    results = evaluate()
    import sklearn
    document = {
        "ticket": "IOT-156",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Simulation sur PC : tailles et accords exacts ; temps Python, non représentatifs d'un microcontrôleur.",
        "versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "scikit_learn": sklearn.__version__,
        },
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(results))
    if results["deployed_simulator_model"]:
        print("Modèle du simulateur :", json.dumps(results["deployed_simulator_model"], ensure_ascii=False))


if __name__ == "__main__":
    main()
