
"""Sélection du seuil B2 sur les données de validation."""

from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score
)

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

TRAIN_FILE = DATA_DIR / "b2_train.csv"
VAL_FILE = DATA_DIR / "b2_validation.csv"

FEATURES = ["temperature", "vibration"]
KEYS = ["session_id", "iteration"]

THRESHOLDS = [0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]


def add_collaborative_deviation(data):
    result = data.copy()

    result["group_median"] = (
        result.groupby(KEYS)["temperature"]
        .transform("median")
    )

    result["deviation"] = (
        result["temperature"] - result["group_median"]
    ).abs()

    return result


def main():
    train = pd.read_csv(TRAIN_FILE)
    validation = pd.read_csv(VAL_FILE)

    # Entraîner B1 uniquement sur b2_train.
    model = DecisionTreeClassifier(
        max_depth=3,
        random_state=42
    )

    model.fit(train[FEATURES], train["label"])

    validation = add_collaborative_deviation(
        validation
    )

    validation["b1_prediction"] = model.predict(
        validation[FEATURES]
    )

    print("=== B2 THRESHOLD VALIDATION ===")

    results = []

    for threshold in THRESHOLDS:
        collaborative_alert = (
            validation["deviation"] > threshold
        ).astype(int)

        predictions = np.maximum(
            validation["b1_prediction"],
            collaborative_alert
        )

        precision = precision_score(
            validation["label"],
            predictions,
            zero_division=0
        )

        recall = recall_score(
            validation["label"],
            predictions,
            zero_division=0
        )

        f1 = f1_score(
            validation["label"],
            predictions,
            zero_division=0
        )

        false_positives = int(
            (
                (validation["label"] == 0)
                & (predictions == 1)
            ).sum()
        )

        results.append({
            "threshold": threshold,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "false_positives": false_positives
        })

    results_df = pd.DataFrame(results)

    print(results_df.to_string(index=False))

    # Critère explicite : F1 maximal, puis moins de FP.
    best = results_df.sort_values(
        ["f1", "false_positives", "threshold"],
        ascending=[False, True, True]
    ).iloc[0]

    print("\nSeuil sélectionné :", best["threshold"])
    print("F1 validation :", best["f1"])


if __name__ == "__main__":
    main()
