
import pandas as pd
import joblib

from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, classification_report

# 1. Définir les chemins
BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_FILE = BASE_DIR / "data" / "sensor_dataset.csv"
MODEL_DIR = BASE_DIR / "models"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 2. Charger le dataset
data = pd.read_csv(DATASET_FILE)

print("Dataset chargé :", len(data), "observations")

# 3. Séparer les caractéristiques et la cible
X = data[["temperature", "vibration"]]
y = data["label"]

# 4. Séparer entraînement et test
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

# 5. Créer le modèle
model = DecisionTreeClassifier(
    max_depth=3,
    random_state=42
)

# 6. Entraîner le modèle
model.fit(X_train, y_train)

# 7. Évaluer le modèle
predictions = model.predict(X_test)

accuracy = accuracy_score(y_test, predictions)

print(f"\nAccuracy : {accuracy:.4f}")
print("\nRapport de classification :")
print(classification_report(y_test, predictions))

# 8. Enregistrer le modèle
MODEL_FILE = MODEL_DIR / "device_model.joblib"

joblib.dump(model, MODEL_FILE)

print(f"\nModèle enregistré : {MODEL_FILE}")
