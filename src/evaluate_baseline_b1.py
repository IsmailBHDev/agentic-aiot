
"""Évaluation scientifique B1 : détection ML locale."""

from pathlib import Path

import joblib
import pandas as pd

from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report
)


BASE_DIR = Path(__file__).resolve().parents[1]

TRAIN_FILE = BASE_DIR / "data" / "collaborative_train.csv"
TEST_FILE = BASE_DIR / "data" / "collaborative_test.csv"

MODEL_FILE = BASE_DIR / "models" / "baseline_b1.joblib"
RESULT_FILE = BASE_DIR / "results" / "baseline_b1_predictions.csv"

FEATURES = ["temperature", "vibration"]


def main():
    train = pd.read_csv(TRAIN_FILE)
    test = pd.read_csv(TEST_FILE)

    X_train = train[FEATURES]
    y_train = train["label"]

    X_test = test[FEATURES]
    y_test = test["label"]

    model = DecisionTreeClassifier(
        max_depth=3,
        random_state=42
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    print("=== BASELINE B1 : LOCAL ML ===")

    print("Accuracy :", round(
        accuracy_score(y_test, predictions), 4
    ))

    print("Precision :", round(
        precision_score(
            y_test, predictions, zero_division=0
        ), 4
    ))

    print("Recall :", round(
        recall_score(
            y_test, predictions, zero_division=0
        ), 4
    ))

    print("F1-score :", round(
        f1_score(
            y_test, predictions, zero_division=0
        ), 4
    ))

    print("\nConfusion matrix :")
    print(confusion_matrix(
        y_test, predictions, labels=[0, 1]
    ))

    print("\nClassification report :")
    print(classification_report(
        y_test, predictions, zero_division=0
    ))

    results = test.copy()
    results["b1_prediction"] = predictions

    MODEL_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    RESULT_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    joblib.dump(model, MODEL_FILE)
    results.to_csv(RESULT_FILE, index=False)

    print("\nModèle :", MODEL_FILE)
    print("Prédictions :", RESULT_FILE)


if __name__ == "__main__":
    main()

