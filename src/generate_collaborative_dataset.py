
"""Génération d'un dataset expérimental multi-capteurs."""

import csv
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

OUTPUT_FILE = (
    BASE_DIR / "data" / "collaborative_dataset.csv"
)

RANDOM_SEED = 42
NUM_ITERATIONS = 1000

DEVICES = [
    "node-01",
    "node-02",
    "node-03"
]

COLUMNS = [
    "session_id",
    "iteration",
    "device_id",
    "temperature",
    "vibration",
    "reference_temperature",
    "scenario",
    "label"
]


def generate_measurements(rng, iteration, scenario):
    """Génère trois mesures synchronisées et annotées."""

    ambient = rng.uniform(24.5, 27.0)

    if scenario == "COMMON_VARIATION":
        ambient += rng.uniform(1.5, 2.5)

    temperatures = [
        ambient + rng.gauss(0, 0.35)
        for _ in DEVICES
    ]

    vibrations = [
        max(0.01, rng.gauss(0.25, 0.06))
        for _ in DEVICES
    ]

    labels = [0] * len(DEVICES)

    if scenario == "LOCAL_ANOMALY":
        target = rng.randrange(len(DEVICES))
        temperatures[target] += rng.uniform(10, 14)
        vibrations[target] += rng.uniform(0.6, 1.0)
        labels[target] = 1

    elif scenario == "CONTEXTUAL_ANOMALY":
        target = rng.randrange(len(DEVICES))
        temperatures[target] += rng.uniform(3.0, 4.5)
        labels[target] = 1

    # Référence calculée sans utiliser la mesure du capteur cible.
    rows = []

    for index, device_id in enumerate(DEVICES):
        neighbors = [
            value
            for j, value in enumerate(temperatures)
            if j != index
        ]

        reference = sum(neighbors) / len(neighbors)

        rows.append({
            "session_id": f"synthetic-seed-{RANDOM_SEED}",
            "iteration": iteration,
            "device_id": device_id,
            "temperature": round(temperatures[index], 3),
            "vibration": round(vibrations[index], 3),
            "reference_temperature": round(reference, 3),
            "scenario": scenario,
            "label": labels[index]
        })

    return rows


def main():
    rng = random.Random(RANDOM_SEED)

    scenarios = (
        ["NORMAL"] * 700
        + ["LOCAL_ANOMALY"] * 100
        + ["CONTEXTUAL_ANOMALY"] * 100
        + ["COMMON_VARIATION"] * 100
    )

    rng.shuffle(scenarios)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    total_rows = 0

    with OUTPUT_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=COLUMNS
        )

        writer.writeheader()

        for iteration, scenario in enumerate(
            scenarios, start=1
        ):
            rows = generate_measurements(
                rng, iteration, scenario
            )

            writer.writerows(rows)
            total_rows += len(rows)

    print("=== Collaborative Dataset Generator ===")
    print("Itérations :", len(scenarios))
    print("Observations :", total_rows)
    print("Fichier généré :", OUTPUT_FILE)


if __name__ == "__main__":
    main()
