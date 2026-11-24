"""Signature des modèles distribués aux capteurs (IOT-176, menace T8).

Le Cloud signe chaque fichier de modèle ; le capteur vérifie la signature
AVANT de le charger. La vérification précède ``joblib.load`` car ce format
désérialise du pickle : un fichier modifié pourrait exécuter du code.

La signature est stockée à côté du modèle, dans ``<modèle>.sig`` (JSON) :
algorithme, nom du fichier, taille, empreinte SHA-256 et signature base64.
Le modèle de référence ``models/device_model.joblib`` n'est pas modifié.

Variable d'environnement : AIOT_MODEL_SIGNING = none (défaut) | ed25519 | ml-dsa-44 | ...
Clé publique du Cloud : <AIOT_KEY_DIR>/cloud.<algorithme>.pub
"""

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature

import message_auth

MODEL_SIGNING_ENV = "AIOT_MODEL_SIGNING"
CLOUD_KEY_NAME = "cloud"


class ModelSignatureError(ValueError):
    """Modèle refusé : signature absente, invalide ou ne correspondant pas."""


def signature_path(model_path):
    model_path = Path(model_path)
    return model_path.with_name(model_path.name + ".sig")


def _manifest(model_path, algorithm, data):
    return {
        "alg": algorithm,
        "file": Path(model_path).name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _signed_bytes(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_model(model_path, algorithm, private_key):
    """Écrit ``<modèle>.sig`` et renvoie son chemin."""
    data = Path(model_path).read_bytes()
    manifest = _manifest(model_path, algorithm, data)
    manifest["sig"] = base64.b64encode(private_key.sign(_signed_bytes(manifest))).decode("ascii")
    path = signature_path(model_path)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def verify_model(model_path, algorithm, public_key):
    """Vérifie le modèle et renvoie son contenu ; lève ``ModelSignatureError``."""
    model_path = Path(model_path)
    path = signature_path(model_path)
    if not path.exists():
        raise ModelSignatureError("missing signature")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        signature = base64.b64decode(stored.pop("sig"), validate=True)
    except (ValueError, KeyError, TypeError):
        raise ModelSignatureError("malformed signature file") from None
    if stored.get("alg") != algorithm:
        raise ModelSignatureError("wrong algorithm")
    data = model_path.read_bytes()
    if stored != _manifest(model_path, algorithm, data):
        raise ModelSignatureError("model does not match its signed manifest")
    try:
        public_key.verify(signature, _signed_bytes(stored))
    except InvalidSignature:
        raise ModelSignatureError("bad signature") from None
    return data


def load_verified_model(model_path, algorithm, public_key, loader=None):
    """Vérifie puis charge le modèle ; ``loader`` vaut ``joblib.load`` par défaut."""
    verify_model(model_path, algorithm, public_key)
    if loader is None:
        import joblib
        loader = joblib.load
    return loader(model_path)


def model_signing_mode():
    mode = os.environ.get(MODEL_SIGNING_ENV, message_auth.NO_AUTH).strip().lower()
    if mode != message_auth.NO_AUTH and mode not in message_auth.ALGORITHMS:
        raise ValueError(f"Unknown {MODEL_SIGNING_ENV}: {mode}")
    return mode


def load_model(model_path, loader=None):
    """Point d'entrée des capteurs : vérifie le modèle si la signature est activée."""
    mode = model_signing_mode()
    if loader is None:
        import joblib
        loader = joblib.load
    if mode == message_auth.NO_AUTH:
        return loader(model_path)
    key_path = message_auth.key_dir() / f"{CLOUD_KEY_NAME}.{mode}.pub"
    public_key = message_auth.load_public_key(mode, key_path.read_bytes())
    return load_verified_model(model_path, mode, public_key, loader)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Signe un modèle avec la clé du Cloud.")
    parser.add_argument("model")
    parser.add_argument("algorithm", choices=sorted(message_auth.ALGORITHMS))
    parser.add_argument("--key-dir", default=None)
    args = parser.parse_args()
    directory = Path(args.key_dir or message_auth.key_dir())
    key_file = directory / f"{CLOUD_KEY_NAME}.{args.algorithm}.key"
    if not key_file.exists():
        message_auth.create_keyring(args.algorithm, [CLOUD_KEY_NAME], directory)
    private_key = message_auth.load_private_key(args.algorithm, key_file.read_bytes())
    print(f"Signature écrite : {sign_model(args.model, args.algorithm, private_key)}")


if __name__ == "__main__":
    main()
