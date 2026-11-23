
"""Création d'un ensemble de validation pour B2."""

from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

SOURCE = DATA_DIR / "collaborative_train.csv"
TRAIN_OUT = DATA_DIR / "b2_train.csv"
VAL_OUT = DATA_DIR / "b2_validation.csv"

KEYS = ["session_id", "iteration"]


def main():
    data = pd.read_csv(SOURCE)

    iterations = data[
        KEYS + ["scenario"]
    ].drop_duplicates()

    train_ids, val_ids = train_test_split(
        iterations,
        test_size=0.20,
        random_state=42,
        stratify=iterations["scenario"]
    )

    train = data.merge(
        train_ids[KEYS],
        on=KEYS,
        validate="many_to_one"
    )

    validation = data.merge(
        val_ids[KEYS],
        on=KEYS,
        validate="many_to_one"
    )

    train_keys = set(
        map(tuple, train[KEYS].drop_duplicates().to_numpy())
    )
    val_keys = set(
        map(tuple, validation[KEYS].drop_duplicates().to_numpy())
    )

    assert train_keys.isdisjoint(val_keys)
    assert len(train) + len(validation) == len(data)

    train.to_csv(TRAIN_OUT, index=False)
    validation.to_csv(VAL_OUT, index=False)

    print("=== B2 VALIDATION SPLIT ===")
    print("Train observations :", len(train))
    print("Validation observations :", len(validation))
    print("Train iterations :", len(train_keys))
    print("Validation iterations :", len(val_keys))

    print("\nValidation labels :")
    print(validation["label"].value_counts().sort_index())

    print("\nValidation scenarios :")
    print(validation["scenario"].value_counts())


if __name__ == "__main__":
    main()
