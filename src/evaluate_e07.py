"""Reproduce the E07 synthetic evaluation without rewriting historical inputs."""

import argparse
import json
import platform
import random
from pathlib import Path
from statistics import mean, stdev

import numpy as np
import pandas as pd
import sklearn
from sklearn.tree import DecisionTreeClassifier

from edge_agent import DIFFERENCE_THRESHOLD, calculate_b2
from generate_collaborative_dataset import DEVICES, generate_measurements
from select_b2_threshold import FEATURES, THRESHOLDS, add_collaborative_deviation

SEEDS = (101, 202, 303, 404, 505)
FIXED_LOCAL_THRESHOLD = 32.0
STRESS_ITERATIONS = 30
SCENARIOS = (
    ["NORMAL"] * 700 + ["LOCAL_ANOMALY"] * 100
    + ["CONTEXTUAL_ANOMALY"] * 100 + ["COMMON_VARIATION"] * 100
)
STRESS = {
    "noise": ((0, 0, 3.2), (0, 0, 1), 3),
    "healthy_drift": ((0, 0, 0), (0, 0, 0), 3),
    "missing_sensor": ((0, 3.2, 0), (0, 1, 0), 2),
    "heterogeneous_offsets": ((-2, 0, 2), (0, 0, 0), 3),
    "common_failure": ((4, 4, 4), (1, 1, 1), 3),
    "two_coordinated_faults": ((0, 3.5, 3.5), (0, 1, 1), 3),
    "progressive_anomaly": ((0, 0, 0), (0, 0, 1), 3),
    "exact_threshold": ((0, 0, 2.5), (0, 0, 1), 3),
    "above_threshold": ((0, 0, 2.5001), (0, 0, 1), 3),
}


def generate_session(seed):
    rng = random.Random(seed)
    scenarios = SCENARIOS.copy()
    rng.shuffle(scenarios)
    rows = []
    for iteration, scenario in enumerate(scenarios, start=1):
        for row in generate_measurements(rng, iteration, scenario):
            row["session_id"] = f"e07-seed-{seed}"
            rows.append(row)
    return add_collaborative_deviation(pd.DataFrame(rows))


def session_folds(seeds):
    for index, test_seed in enumerate(seeds):
        validation_seed = seeds[(index + 1) % len(seeds)]
        train_seeds = [seed for seed in seeds if seed not in (test_seed, validation_seed)]
        yield train_seeds, validation_seed, test_seed


def metrics(labels, predictions):
    labels = np.asarray(labels, dtype=bool)
    predictions = np.asarray(predictions, dtype=bool)
    tp = int(np.count_nonzero(labels & predictions))
    tn = int(np.count_nonzero(~labels & ~predictions))
    fp = int(np.count_nonzero(~labels & predictions))
    fn = int(np.count_nonzero(labels & ~predictions))
    return {
        "n": labels.size, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "f1": 2 * tp / max(1, 2 * tp + fp + fn),
        "recall": tp / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
    }


def select_threshold(validation, predictions):
    scores = [
        {"threshold": threshold, **metrics(
            validation["label"], predictions | (validation["deviation"] > threshold)
        )}
        for threshold in THRESHOLDS
    ]
    best = min(scores, key=lambda row: (-row["f1"], row["fp"], row["threshold"]))
    return best["threshold"], scores


def stress_results(model, seed):
    results = {}
    for scenario, (offsets, labels, available) in STRESS.items():
        rng = random.Random(f"e07-stress-{seed}-{scenario}")
        truth = []
        local = []
        combined = []
        collaborative = []
        for iteration in range(1, STRESS_ITERATIONS + 1):
            ambient = rng.uniform(24.5, 26.5)
            if scenario in ("exact_threshold", "above_threshold"):
                ambient = 25.0
            values = [ambient + offset for offset in offsets[:available]]
            if scenario == "noise":
                values = [value + rng.gauss(0, 0.9) for value in values]
            elif scenario in ("healthy_drift", "progressive_anomaly"):
                values[-1] += 4 * (iteration - 1) / (STRESS_ITERATIONS - 1)

            features = pd.DataFrame({
                "temperature": values,
                "vibration": [0.25] * available,
            })
            predictions = model.predict(features).astype(int).tolist()
            truth.extend(labels[:available])
            local.extend(predictions)
            if available < len(DEVICES):
                continue

            messages = [
                {
                    "session_id": f"stress-{seed}-{scenario}",
                    "iteration": iteration,
                    "src": {"agent": device},
                    "payload": {"temperature": value, "prediction": prediction},
                }
                for device, value, prediction in zip(DEVICES, values, predictions)
            ]
            _, decisions = calculate_b2(messages)
            collaborative.extend(row["collaborative_alert"] for row in decisions.values())
            combined.extend(row["b2_prediction"] for row in decisions.values())
        results[scenario] = {
            "iterations": STRESS_ITERATIONS,
            "missing_observations": (len(DEVICES) - available) * STRESS_ITERATIONS,
            "collaborative_coverage": available == len(DEVICES),
            "b1": metrics(truth, local),
            "collaborative_only": metrics(truth, collaborative) if collaborative else None,
            "b2": metrics(truth, combined) if combined else None,
        }
    return results


def summarize(values):
    return {
        "mean": mean(values), "sample_sd": stdev(values),
        "min": min(values), "max": max(values),
    }


def evaluate():
    sessions = {seed: generate_session(seed) for seed in SEEDS}
    folds = []
    for train_seeds, validation_seed, test_seed in session_folds(SEEDS):
        train = pd.concat([sessions[seed] for seed in train_seeds], ignore_index=True)
        validation = sessions[validation_seed]
        test = sessions[test_seed]
        model = DecisionTreeClassifier(max_depth=3, random_state=42)
        model.fit(train[FEATURES], train["label"])
        threshold, sweep = select_threshold(validation, model.predict(validation[FEATURES]))
        b1 = model.predict(test[FEATURES])
        collaborative = test["deviation"] > DIFFERENCE_THRESHOLD
        predictions = {
            "fixed_local": test["temperature"] > FIXED_LOCAL_THRESHOLD,
            "b1": b1,
            "collaborative_only": collaborative,
            "b2_fixed": b1 | collaborative,
            "b2_validation_selected": b1 | (test["deviation"] > threshold),
        }
        context = test["scenario"] == "CONTEXTUAL_ANOMALY"
        folds.append({
            "train_seeds": train_seeds, "validation_seed": validation_seed,
            "test_seed": test_seed, "validation_threshold": threshold,
            "validation_sweep": sweep,
            "test": {name: metrics(test["label"], values) for name, values in predictions.items()},
            "contextual_test": {
                name: metrics(test.loc[context, "label"], np.asarray(values)[context])
                for name, values in predictions.items()
            },
            "stress": stress_results(model, test_seed),
        })

    return {
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "scikit_learn": sklearn.__version__},
        "fixed_b2_threshold": DIFFERENCE_THRESHOLD,
        "fixed_local_threshold": FIXED_LOCAL_THRESHOLD,
        "summary_by_session": {
            method: {field: summarize([fold["test"][method][field] for fold in folds])
                     for field in ("f1", "recall", "false_positive_rate", "fp")}
            for method in predictions
        },
        "paired_b2_minus_b1_f1": summarize([
            fold["test"]["b2_fixed"]["f1"] - fold["test"]["b1"]["f1"] for fold in folds
        ]),
        "folds": folds,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
