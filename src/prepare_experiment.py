
"""Préparation des données expérimentales Agentic-AIoT."""

from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


BASE_DIR = Path(__file__).resolve().parents[1]

INPUT_FILE = BASE_DIR / "data" / "collaborative_dataset.csv"

TRAIN_FILE = BASE_DIR / "data" / "collaborative_train.csv"
TEST_FILE = BASE_DIR / "data" / "collaborative_test.csv"

RANDOM_SEED = 42


def main():
    data = pd.read_csv(INPUT_FILE)

    # Une ligne par itération pour réaliser le découpage.
    iterations = (
        data[["session_id", "iteration", "scenario"]]
        .drop_duplicates()
    )

    train_iterations, test_iterations = train_test_split(
        iterations,
        test_size=0.2,
        random_state=RANDOM_SEED,
        stratify=iterations["scenario"]
    )

    # Associer les observations aux itérations sélectionnées.
    keys = ["session_id", "iteration"]

    train = data.merge(
        train_iterations[keys],
        on=keys,
        how="inner",
        validate="many_to_one"
    )

    test = data.merge(
        test_iterations[keys],
        on=keys,
        how="inner",
        validate="many_to_one"
    )

    # Vérifier qu'aucune itération n'est partagée.
    train_keys = set(
        map(tuple, train[keys].drop_duplicates().to_numpy())
    )

    test_keys = set(
        map(tuple, test[keys].drop_duplicates().to_numpy())
    )

    assert train_keys.isdisjoint(test_keys)
    assert len(train) + len(test) == len(data)

    train.to_csv(TRAIN_FILE, index=False)
    test.to_csv(TEST_FILE, index=False)

    print("=== EXPERIMENT DATA SPLIT ===")
    print("Train observations :", len(train))
    print("Test observations :", len(test))
    print("Train iterations :", len(train_keys))
    print("Test iterations :", len(test_keys))

    print("\nTrain scenarios :")
    print(train["scenario"].value_counts().to_string())

    print("\nTest scenarios :")
    print(test["scenario"].value_counts().to_string())

    print("\nTrain labels :")
    print(train["label"].value_counts().sort_index().to_string())

    print("\nTest labels :")
    print(test["label"].value_counts().sort_index().to_string())

    print("\nFichiers enregistrés :")
    print(TRAIN_FILE)
    print(TEST_FILE)


if __name__ == "__main__":
    main()
