"""IOT-158 : évaluation de l'OTA simulé (installation, attaques, retour arrière, coût).

La version 1 publiée est le B1 de référence (profondeur 3, graine 42, réentraîné
en mémoire sur ``data/collaborative_train.csv``) : après installation, le capteur
doit reproduire les 600 prédictions de ``results/baseline_b1_predictions.csv``.
C'est ce qui corrige, sans toucher au fichier gelé ``models/device_model.joblib``,
l'écart signalé par IOT-180.

Modes comparés : ``none`` (empreinte du catalogue seulement, comparateur non
protégé), ``ed25519`` et ``ml-dsa-44``. Chaque scénario part d'un dépôt et d'un
capteur neufs, dans un dossier temporaire sous ``artifacts/``.

Le modèle « empoisonné » est un arbre valide qui prédit toujours 0 : il masque
toutes les anomalies. Aucun pickle malveillant n'est fabriqué ; le risque
d'exécution de code au chargement d'un modèle non vérifié est seulement rappelé.

Usage : python -B src/evaluate_ota.py --output results/ota_<date>.json
"""

import argparse
import json
import platform
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import message_auth
import model_signing
import ota

ROOT = Path(__file__).resolve().parents[1]
MODES = ("none", "ed25519", "ml-dsa-44")
FEATURES = ota.FEATURES


def f1(predictions, labels):
    tp = sum(p == 1 and y == 1 for p, y in zip(predictions, labels))
    fp = sum(p == 1 and y == 0 for p, y in zip(predictions, labels))
    fn = sum(p == 0 and y == 1 for p, y in zip(predictions, labels))
    return round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0


class Bench:
    """Données, modèles et clés partagés par tous les scénarios."""

    def __init__(self):
        import pandas as pd
        from sklearn.tree import DecisionTreeClassifier

        import evaluate_tinyml

        self.reference, self.train, self.test = evaluate_tinyml.train_reference()
        self.labels = self.test["label"].astype(int).tolist()
        self.reference_predictions = pd.read_csv(
            ROOT / "results" / "baseline_b1_predictions.csv")["b1_prediction"].astype(int).tolist()
        if self.predict(self.reference) != self.reference_predictions:
            raise SystemExit("Le B1 réentraîné ne reproduit pas les 600 prédictions de référence")
        # v2 nominale : même méthode, autre graine (mécanique de mise à jour seulement).
        self.retrained = DecisionTreeClassifier(max_depth=3, random_state=7).fit(
            self.train[FEATURES], self.train["label"])
        # Modèle empoisonné : arbre valide qui répond toujours 0.
        self.poisoned = DecisionTreeClassifier(max_depth=1, random_state=0).fit(
            self.train[FEATURES], [0] * len(self.train))
        # Modèle incompatible : trois variables au lieu de deux.
        wide = self.train[FEATURES].assign(extra=0.0)
        self.incompatible = DecisionTreeClassifier(max_depth=3, random_state=42).fit(
            wide, self.train["label"])

    def predict(self, model):
        return model.predict(self.test[FEATURES]).astype(int).tolist()

    def detection(self, model):
        predictions = self.predict(model)
        return {
            "agreement_with_reference_b1": sum(
                a == b for a, b in zip(predictions, self.reference_predictions)),
            "f1_test": f1(predictions, self.labels),
        }


class Setup:
    """Dépôt OTA + capteur neufs pour un mode donné."""

    def __init__(self, workdir, mode, keys):
        self.root = Path(tempfile.mkdtemp(dir=workdir))
        self.repo = self.root / "repo"
        self.mode = mode
        self.private_key, public_key = keys.get(mode, (None, None))
        self.device = ota.DeviceOta(self.root / "device", mode, public_key)

    def publish(self, model, version):
        return ota.publish_release(self.repo, model, version, self.mode, self.private_key)

    def rewrite_catalog(self, change):
        catalog = ota.read_catalog(self.repo)
        change(catalog)
        (self.repo / ota.CATALOG).write_text(json.dumps(catalog), encoding="utf-8")

    def refresh_digest(self, version):
        """Ce que fait un attaquant qui contrôle le dépôt : recalcule l'empreinte."""
        data = (self.repo / ota.release_file(version)).read_bytes()

        def change(catalog):
            for item in catalog["releases"]:
                if item["version"] == version:
                    item["size"] = len(data)
                    item["sha256"] = ota._sha256(data)
        self.rewrite_catalog(change)


def outcome(setup, result, bench):
    record = {"status": result["status"], "active_version": setup.device.active_version}
    if "reason" in result:
        record["reason"] = result["reason"]
    if setup.device.active_version is not None:
        model, _ = setup.device.load_active()
        record.update(bench.detection(model))
    return record


def run_scenarios(bench, workdir, mode, keys, attacker_keys):
    results = {}

    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    results["install_reference_v1"] = outcome(s, s.device.update(s.repo), bench)

    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    s.publish(bench.retrained, 2)
    results["update_v2"] = outcome(s, s.device.update(s.repo), bench)

    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    s.publish(bench.retrained, 2)
    path = s.repo / ota.release_file(2)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    results["corrupted_in_transit"] = outcome(s, s.device.update(s.repo), bench)

    # Dépôt compromis : modèle empoisonné, empreinte recalculée, signé par l'attaquant.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    attacker_private = attacker_keys.get(mode, (None, None))[0]
    ota.publish_release(s.repo, bench.poisoned, 2, mode, attacker_private)
    results["poisoned_repository"] = outcome(s, s.device.update(s.repo), bench)

    # Dépôt compromis : modèle empoisonné sans signature.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    ota.publish_release(s.repo, bench.poisoned, 2, message_auth.NO_AUTH)
    results["unsigned_release"] = outcome(s, s.device.update(s.repo), bench)

    # Rétrogradation déguisée : l'ancienne v1 signée renommée en v3.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    s.publish(bench.retrained, 2)
    s.device.update(s.repo)
    old = s.repo / ota.release_file(1)
    shutil.copyfile(old, s.repo / ota.release_file(3))
    if model_signing.signature_path(old).exists():
        shutil.copyfile(model_signing.signature_path(old),
                        model_signing.signature_path(s.repo / ota.release_file(3)))
    v1 = next(item for item in ota.read_catalog(s.repo)["releases"] if item["version"] == 1)
    s.rewrite_catalog(lambda c: c["releases"].append({**v1, "version": 3, "file": ota.release_file(3)}))
    results["disguised_downgrade"] = outcome(s, s.device.update(s.repo), bench)

    # Catalogue ramené à une version antérieure à la version active.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.publish(bench.retrained, 2)
    s.device.update(s.repo)
    s.rewrite_catalog(lambda c: c.update(releases=[r for r in c["releases"] if r["version"] == 1]))
    results["older_catalog"] = outcome(s, s.device.update(s.repo), bench)

    # Version légitime mais incompatible : refusée par le contrôle de santé.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    s.publish(bench.incompatible, 2)
    results["incompatible_model"] = outcome(s, s.device.update(s.repo), bench)

    # Retour arrière : v2 abandonnée puis non réinstallée.
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    s.device.update(s.repo)
    s.publish(bench.retrained, 2)
    s.device.update(s.repo)
    s.device.rollback()
    after = s.device.update(s.repo)
    record = outcome(s, after, bench)
    record["rejected_versions"] = s.device.state()["rejected"]
    results["rollback_then_update"] = record
    return results


def measure_cost(bench, workdir, mode, keys, repetitions):
    s = Setup(workdir, mode, keys)
    s.publish(bench.reference, 1)
    model_path = s.repo / ota.release_file(1)
    signature = model_signing.signature_path(model_path)
    durations, verify = [], []
    for _ in range(repetitions):
        device = ota.DeviceOta(Path(tempfile.mkdtemp(dir=workdir)), mode, s.device.public_key)
        result = device.update(s.repo)
        if result["status"] != "installed":
            raise SystemExit(f"Installation nominale refusée en mode {mode}: {result}")
        durations.append(result["duration_ms"])
        if mode != message_auth.NO_AUTH:
            start = time.perf_counter()
            model_signing.verify_model(model_path, mode, s.device.public_key)
            verify.append((time.perf_counter() - start) * 1000)
    return {
        "model_bytes": model_path.stat().st_size,
        "signature_file_bytes": signature.stat().st_size if signature.exists() else 0,
        "install_ms_mean": round(statistics.mean(durations), 3),
        "install_ms_median": round(statistics.median(durations), 3),
        "signature_verify_ms_mean": round(statistics.mean(verify), 3) if verify else None,
        "repetitions": repetitions,
    }


def evaluate(repetitions=20, workdir=None):
    import cryptography
    import sklearn

    bench = Bench()
    keys, attacker = {}, {}
    for mode in MODES:
        if mode != message_auth.NO_AUTH:
            for store in (keys, attacker):
                private_key = message_auth.generate_private_key(mode)
                store[mode] = (private_key, private_key.public_key())
    base = Path(workdir or ROOT / "artifacts")
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="ota-eval-", dir=base))
    try:
        return {
            "ticket": "IOT-158",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "python": platform.python_version(), "platform": platform.platform(),
                "scikit_learn": sklearn.__version__, "cryptography": cryptography.__version__,
            },
            "reference_check": {"retrained_matches_reference_predictions": True,
                                "reference_f1_test": f1(bench.reference_predictions, bench.labels)},
            "scenarios": {mode: run_scenarios(bench, scratch, mode, keys, attacker) for mode in MODES},
            "cost": {mode: measure_cost(bench, scratch, mode, keys, repetitions) for mode in MODES},
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    document = evaluate(args.repetitions)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for mode, scenarios in document["scenarios"].items():
        print(f"\n== {mode}")
        for name, record in scenarios.items():
            print(f"  {name:24} {record['status']:10} {record.get('reason', ''):20} "
                  f"v{record['active_version']} F1={record.get('f1_test')}")
    print(json.dumps(document["cost"], indent=2))


if __name__ == "__main__":
    main()
