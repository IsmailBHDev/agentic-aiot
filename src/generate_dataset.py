
import csv
import random
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATASET_FILE = DATA_DIR / "sensor_dataset.csv"

with open(DATASET_FILE, "w", newline="", encoding="utf-8") as file:

    writer = csv.writer(file)

    writer.writerow(["temperature", "vibration", "label"])

    # 500 observations normales
    for i in range(500):

        temperature = round(random.uniform(24, 30), 2)
        vibration = round(random.uniform(0.1, 0.5), 3)

        writer.writerow([temperature, vibration, 0])

    # 500 observations anormales
    for i in range(500):

        temperature = round(random.uniform(36, 45), 2)
        vibration = round(random.uniform(0.7, 1.5), 3)

        writer.writerow([temperature, vibration, 1])

print(f"Dataset généré : {DATASET_FILE}")
print("Nombre d'observations : 1000")
