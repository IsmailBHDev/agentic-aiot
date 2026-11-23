
"""Évaluation B2 sur le jeu de test final."""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = (
    BASE_DIR / "results" / "baseline_b1_predictions.csv"
)
OUTPUT_FILE = (
    BASE_DIR / "results" / "collaborative_b2_predictions.csv"
)

THRESHOLD = 2.50
KEYS = ["session_id", "iteration"]


def main():
    data = pd.read_csv(INPUT_FILE)

    # Vérifier les groupes de capteurs synchronisés.
    groups = data.groupby(KEYS)

    assert (groups.size() == 3).all()
    assert (
        groups["device_id"].nunique() == 3
    ).all()

    # Médiane de température des trois capteurs.
    data["group_median"] = (
        groups["temperature"].transform("median")
    )

    data["deviation"] = (
        data["temperature"] - data["group_median"]
    ).abs()

    # Détection collaborative.
    data["collaborative_alert"] = (
        data["deviation"] > THRESHOLD
    ).astype(int)

    # B2 = B1 OU alerte collaborative.
    data["b2_prediction"] = np.maximum(
        data["b1_prediction"],
        data["collaborative_alert"]
    )

    print("=== FINAL TEST : B1 VS B2 ===")
    print("Threshold :", THRESHOLD)
    print("Observations :", len(data))

    for name, column in [
        ("B1 Local", "b1_prediction"),
        ("B2 Collaborative", "b2_prediction")
    ]:
        y_true = data["label"]
        y_pred = data[column]

        print(f"\n{name}")
        print("Accuracy :", round(
            accuracy_score(y_true, y_pred), 4
        ))
        print("Precision :", round(
            precision_score(
                y_true, y_pred, zero_division=0
            ), 4
        ))
        print("Recall :", round(
            recall_score(
                y_true, y_pred, zero_division=0
            ), 4
        ))
        print("F1-score :", round(
            f1_score(
                y_true, y_pred, zero_division=0
            ), 4
        ))
        print("Confusion matrix :")
        print(confusion_matrix(
            y_true, y_pred, labels=[0, 1]
        ))

    print("\n=== RESULTS BY SCENARIO ===")

    for scenario, subset in data.groupby("scenario"):
        print(f"\n{scenario}")

        for column in ["b1_prediction", "b2_prediction"]:
            tp = int((
                (subset["label"] == 1)
                & (subset[column] == 1)
            ).sum())

            fn = int((
                (subset["label"] == 1)
                & (subset[column] == 0)
            ).sum())

            fp = int((
                (subset["label"] == 0)
                & (subset[column] == 1)
            ).sum())

            print(
                f"{column}: TP={tp}, FN={fn}, FP={fp}"
            )

    OUTPUT_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    data.to_csv(OUTPUT_FILE, index=False)

    print("\nResults saved :", OUTPUT_FILE)


if __name__ == "__main__":
    main()
