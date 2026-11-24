"""IOT-176 : un modèle modifié ou non signé est refusé avant tout chargement (S4)."""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import message_auth  # noqa: E402
import model_signing  # noqa: E402
from model_signing import ModelSignatureError  # noqa: E402

REFERENCE_MODEL = ROOT / "models" / "device_model.joblib"


@pytest.fixture
def model(tmp_path):
    """Copie du modèle de référence : l'original n'est jamais modifié."""
    path = tmp_path / "device_model.joblib"
    shutil.copyfile(REFERENCE_MODEL, path)
    return path


def cloud_keys(algorithm="ml-dsa-44"):
    private_key = message_auth.generate_private_key(algorithm)
    return private_key, private_key.public_key()


class Loader:
    """Remplace joblib.load : enregistre les chargements sans désérialiser."""

    def __init__(self):
        self.calls = []

    def __call__(self, path):
        self.calls.append(Path(path))
        return "loaded-model"


@pytest.mark.parametrize("algorithm", ("ed25519", "ml-dsa-44", "ml-dsa-65"))
def test_signed_model_is_loaded(model, algorithm):
    private_key, public_key = cloud_keys(algorithm)
    model_signing.sign_model(model, algorithm, private_key)
    loader = Loader()

    assert model_signing.load_verified_model(model, algorithm, public_key, loader) == "loaded-model"
    assert loader.calls == [model]


def test_modified_model_is_refused_before_loading(model):
    private_key, public_key = cloud_keys()
    model_signing.sign_model(model, "ml-dsa-44", private_key)
    data = bytearray(model.read_bytes())
    data[len(data) // 2] ^= 0xFF
    model.write_bytes(bytes(data))
    loader = Loader()

    with pytest.raises(ModelSignatureError, match="does not match"):
        model_signing.load_verified_model(model, "ml-dsa-44", public_key, loader)
    assert loader.calls == []


def test_replaced_model_with_rebuilt_manifest_is_refused(model):
    """L'attaquant recalcule l'empreinte mais ne peut pas re-signer."""
    private_key, public_key = cloud_keys()
    attacker_key, _ = cloud_keys()
    model.write_bytes(b"malicious pickle payload")
    model_signing.sign_model(model, "ml-dsa-44", attacker_key)
    loader = Loader()

    with pytest.raises(ModelSignatureError, match="bad signature"):
        model_signing.load_verified_model(model, "ml-dsa-44", public_key, loader)
    assert loader.calls == []


def test_unsigned_model_is_refused(model):
    _, public_key = cloud_keys()
    loader = Loader()

    with pytest.raises(ModelSignatureError, match="missing"):
        model_signing.load_verified_model(model, "ml-dsa-44", public_key, loader)
    assert loader.calls == []


def test_wrong_algorithm_is_refused(model):
    private_key, _ = cloud_keys("ed25519")
    model_signing.sign_model(model, "ed25519", private_key)
    _, public_key = cloud_keys("ml-dsa-44")

    with pytest.raises(ModelSignatureError, match="wrong algorithm"):
        model_signing.verify_model(model, "ml-dsa-44", public_key)


def test_load_model_without_signing_keeps_historical_behaviour(model, monkeypatch):
    monkeypatch.delenv(model_signing.MODEL_SIGNING_ENV, raising=False)
    loader = Loader()

    assert model_signing.load_model(model, loader) == "loaded-model"


def test_load_model_uses_cloud_key_from_key_dir(model, tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    message_auth.create_keyring("ml-dsa-44", [model_signing.CLOUD_KEY_NAME], keys)
    private_key = message_auth.load_private_key(
        "ml-dsa-44", (keys / "cloud.ml-dsa-44.key").read_bytes()
    )
    model_signing.sign_model(model, "ml-dsa-44", private_key)
    monkeypatch.setenv(model_signing.MODEL_SIGNING_ENV, "ml-dsa-44")
    monkeypatch.setenv(message_auth.KEY_DIR_ENV, str(keys))

    assert model_signing.load_model(model, Loader()) == "loaded-model"
    model.write_bytes(model.read_bytes() + b"\x00")
    with pytest.raises(ModelSignatureError):
        model_signing.load_model(model, Loader())


def test_reference_model_is_untouched():
    assert not model_signing.signature_path(REFERENCE_MODEL).exists()
