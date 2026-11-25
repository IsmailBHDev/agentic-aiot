"""IOT-158 : mise à jour OTA simulée des modèles B1 (Cloud -> Device).

Côté Cloud, ``publish_release`` dépose une version numérotée du modèle dans un
dépôt (dossier local qui simule le serveur OTA) : fichier
``device_model-v<N>.joblib``, signature ``.sig`` (IOT-176) et entrée dans
``catalog.json`` (version, fichier, taille, SHA-256, algorithme, métadonnées).

Côté capteur, ``DeviceOta`` installe la dernière version du catalogue :

1. version strictement supérieure à la version active et non rejetée
   (protection contre la rétrogradation) ;
2. téléchargement simulé vers une zone de transit ;
3. taille et SHA-256 conformes au catalogue ;
4. signature vérifiée avec la clé publique du Cloud, AVANT ``joblib.load``
   (sauf en mode ``none``, gardé comme comparateur non protégé) ;
5. chargement, puis contrôle de santé (prédiction 0/1 sur des sondes) ;
6. activation atomique (``state.json`` remplacé d'un bloc) ; l'ancienne
   version est conservée pour le retour arrière.

Tout échec laisse la version active intacte. ``rollback`` revient à la version
précédente et marque la version abandonnée comme rejetée, pour qu'elle ne soit
pas réinstallée à la mise à jour suivante.

Le nom de fichier contient la version et fait partie du manifeste signé :
renommer une ancienne version signée pour la présenter comme nouvelle échoue.
Le catalogue n'est pas signé ; en mode ``none``, un attaquant qui contrôle le
dépôt peut donc remplacer le modèle et son empreinte (scénario S4).
"""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import message_auth
import model_signing
from model_signing import ModelSignatureError

CATALOG = "catalog.json"
STATE = "state.json"
FEATURES = ["temperature", "vibration"]
# Sondes du contrôle de santé : mesures normales et extrêmes.
HEALTH_PROBES = [[25.0, 0.3], [40.0, 1.1], [10.0, 0.0], [32.5, 0.3]]


class OtaError(ValueError):
    """Mise à jour refusée ; ``reason`` est un code court stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def release_file(version):
    return f"device_model-v{version}.joblib"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write_json_atomic(path, document):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


# ---------------------------------------------------------------- Cloud

def read_catalog(repo_dir):
    path = Path(repo_dir) / CATALOG
    if not path.exists():
        return {"releases": []}
    return json.loads(path.read_text(encoding="utf-8"))


def publish_release(repo_dir, model, version, algorithm, private_key=None, metadata=None):
    """Sérialise ``model`` en version ``version``, le signe et l'ajoute au catalogue."""
    import joblib

    if type(version) is not int or version < 1:
        raise ValueError("version must be a positive integer")
    repo_dir = Path(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    catalog = read_catalog(repo_dir)
    if any(item["version"] == version for item in catalog["releases"]):
        raise ValueError(f"version {version} already published")

    path = repo_dir / release_file(version)
    joblib.dump(model, path)
    if algorithm != message_auth.NO_AUTH:
        if private_key is None:
            raise ValueError("a private key is required to sign a release")
        model_signing.sign_model(path, algorithm, private_key)
    data = path.read_bytes()
    catalog["releases"].append({
        "version": version,
        "file": path.name,
        "size": len(data),
        "sha256": _sha256(data),
        "alg": algorithm,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    })
    catalog["releases"].sort(key=lambda item: item["version"])
    _write_json_atomic(repo_dir / CATALOG, catalog)
    return path


def latest_release(repo_dir):
    releases = read_catalog(repo_dir)["releases"]
    return max(releases, key=lambda item: item["version"]) if releases else None


# ---------------------------------------------------------------- Device

def health_check(model):
    """Le modèle doit accepter (température, vibration) et répondre 0 ou 1."""
    import pandas as pd

    try:
        predictions = model.predict(pd.DataFrame(HEALTH_PROBES, columns=FEATURES))
    except Exception as error:  # modèle incompatible : refus contrôlé
        raise OtaError("health_check_failed", type(error).__name__) from None
    if len(predictions) != len(HEALTH_PROBES) or any(int(p) not in (0, 1) for p in predictions):
        raise OtaError("health_check_failed", "predictions outside {0, 1}")


class DeviceOta:
    """Agent OTA d'un capteur simulé ; état persistant dans ``device_dir``."""

    def __init__(self, device_dir, algorithm, public_key=None, loader=None):
        if algorithm != message_auth.NO_AUTH and public_key is None:
            raise ValueError("a public key is required when signatures are enabled")
        self.device_dir = Path(device_dir)
        self.algorithm = algorithm
        self.public_key = public_key
        self.loader = loader
        self.slots = self.device_dir / "models"
        self.staging = self.device_dir / "staging"
        self.slots.mkdir(parents=True, exist_ok=True)
        self.counters = {"installed": 0, "refused": 0, "rollbacks": 0}

    # -- état

    def state(self):
        path = self.device_dir / STATE
        if not path.exists():
            return {"active": None, "previous": None, "rejected": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, state):
        _write_json_atomic(self.device_dir / STATE, state)

    @property
    def active_version(self):
        active = self.state()["active"]
        return active["version"] if active else None

    def _load(self, path):
        if self.loader is not None:
            return self.loader(path)
        import joblib
        return joblib.load(path)

    def load_active(self):
        """Recharge le modèle actif en revérifiant sa signature ; ``(modèle, version)``."""
        active = self.state()["active"]
        if active is None:
            raise OtaError("no_active_model")
        path = self.slots / active["file"]
        self._verify(path, active)
        return self._load(path), active["version"]

    # -- vérification

    def _verify(self, path, release):
        data = path.read_bytes()
        if len(data) != release["size"] or _sha256(data) != release["sha256"]:
            raise OtaError("digest_mismatch")
        if self.algorithm != message_auth.NO_AUTH:
            try:
                model_signing.verify_model(path, self.algorithm, self.public_key)
            except ModelSignatureError as error:
                raise OtaError("bad_signature", str(error)) from None

    def _check_candidate(self, release, state):
        version = release.get("version")
        if type(version) is not int or release.get("file") != release_file(version):
            raise OtaError("malformed_release")
        if version in state["rejected"]:
            raise OtaError("version_rejected")
        active = state["active"]
        if active is not None and version <= active["version"]:
            raise OtaError("not_newer")

    # -- installation

    def install(self, repo_dir, release):
        """Installe ``release`` depuis ``repo_dir`` ; lève ``OtaError`` sans rien changer."""
        state = self.state()
        try:
            self._check_candidate(release, state)
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging.mkdir(parents=True)
            source = Path(repo_dir) / release["file"]
            staged = self.staging / release["file"]
            try:
                shutil.copyfile(source, staged)  # téléchargement simulé
            except FileNotFoundError:
                raise OtaError("download_failed") from None
            signature = model_signing.signature_path(source)
            if signature.exists():
                shutil.copyfile(signature, model_signing.signature_path(staged))
            self._verify(staged, release)  # avant toute désérialisation
            try:
                model = self._load(staged)
            except Exception as error:
                raise OtaError("load_failed", type(error).__name__) from None
            health_check(model)
        except OtaError:
            self.counters["refused"] += 1
            shutil.rmtree(self.staging, ignore_errors=True)
            raise

        for item in (staged, model_signing.signature_path(staged)):
            if item.exists():
                os.replace(item, self.slots / item.name)
        shutil.rmtree(self.staging, ignore_errors=True)
        entry = {key: release[key] for key in ("version", "file", "size", "sha256", "alg")}
        self._save_state({"active": entry, "previous": state["active"], "rejected": state["rejected"]})
        self._prune(keep={entry["file"], (state["active"] or {}).get("file")})
        self.counters["installed"] += 1
        return model

    def update(self, repo_dir):
        """Installe la dernière version publiée si elle est nouvelle.

        Renvoie ``{"status": "installed"|"up_to_date"|"refused", ...}``.
        """
        release = latest_release(repo_dir)
        state = self.state()
        if release is None:
            return {"status": "up_to_date", "active": self.active_version}
        active = state["active"]
        if active is not None and release.get("version") == active["version"]:
            return {"status": "up_to_date", "active": active["version"]}
        if release.get("version") in state["rejected"]:
            return {"status": "up_to_date", "active": self.active_version,
                    "skipped_rejected": release["version"]}
        start = time.perf_counter()
        try:
            self.install(repo_dir, release)
        except OtaError as error:
            return {"status": "refused", "reason": error.reason,
                    "version": release.get("version"), "active": self.active_version}
        return {"status": "installed", "active": self.active_version,
                "duration_ms": (time.perf_counter() - start) * 1000}

    def rollback(self):
        """Revient à la version précédente ; la version abandonnée est rejetée."""
        state = self.state()
        if state["previous"] is None:
            raise OtaError("no_previous_version")
        abandoned = state["active"]
        rejected = sorted(set(state["rejected"]) | {abandoned["version"]})
        self._save_state({"active": state["previous"], "previous": None, "rejected": rejected})
        self.counters["rollbacks"] += 1
        return state["previous"]["version"]

    def _prune(self, keep):
        for item in self.slots.iterdir():
            name = item.name[:-4] if item.name.endswith(".sig") else item.name
            if name not in keep:
                item.unlink()


def device_from_environment(device_dir):
    """Agent OTA configuré par AIOT_MODEL_SIGNING et la clé publique du Cloud."""
    algorithm = model_signing.model_signing_mode()
    public_key = None
    if algorithm != message_auth.NO_AUTH:
        key_path = message_auth.key_dir() / f"{model_signing.CLOUD_KEY_NAME}.{algorithm}.pub"
        public_key = message_auth.load_public_key(algorithm, key_path.read_bytes())
    return DeviceOta(device_dir, algorithm, public_key)


def cloud_signing_key():
    """``(algorithme, clé privée du Cloud)`` selon AIOT_MODEL_SIGNING ; crée la clé si absente."""
    algorithm = model_signing.model_signing_mode()
    if algorithm == message_auth.NO_AUTH:
        return algorithm, None
    directory = message_auth.key_dir()
    key_file = directory / f"{model_signing.CLOUD_KEY_NAME}.{algorithm}.key"
    if not key_file.exists():
        message_auth.create_keyring(algorithm, [model_signing.CLOUD_KEY_NAME], directory)
    return algorithm, message_auth.load_private_key(algorithm, key_file.read_bytes())


def main():
    import argparse

    import evaluate_tinyml

    parser = argparse.ArgumentParser(description="Publie le B1 de référence ou installe la dernière version.")
    sub = parser.add_subparsers(dest="command", required=True)
    publish = sub.add_parser("publish-reference", help="publie le B1 de référence (profondeur 3, graine 42)")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--version", type=int, default=1)
    update = sub.add_parser("update", help="installe la dernière version sur un capteur")
    update.add_argument("--repo", required=True)
    update.add_argument("--device-dir", required=True)
    args = parser.parse_args()

    if args.command == "publish-reference":
        algorithm, private_key = cloud_signing_key()
        model, _, _ = evaluate_tinyml.train_reference()
        path = publish_release(args.repo, model, args.version, algorithm, private_key,
                               {"source": "B1 de référence (max_depth=3, random_state=42)"})
        print(f"Version {args.version} publiée : {path}")
    else:
        print(json.dumps(device_from_environment(args.device_dir).update(args.repo), indent=2))


if __name__ == "__main__":
    main()
