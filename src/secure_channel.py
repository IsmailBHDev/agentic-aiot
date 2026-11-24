"""Canal Edge -> Cloud authentifié et chiffré (IOT-177, menaces T5 et T6).

Chaque incident est signé par l'Edge puis chiffré pour le Cloud :
- échange de clés : X25519 (C1), ML-KEM-768 (C2, FIPS 203) ou les deux
  combinés (hybride), par encapsulation éphémère à chaque incident ;
- dérivation : HKDF-SHA256 sur le ou les secrets partagés ;
- chiffrement : AES-256-GCM, l'en-tête de l'enveloppe servant de données
  associées ;
- signature de l'incident : Ed25519 (C1) ou ML-DSA-44 (C2).

Configuration : AIOT_CHANNEL_MODE = none (défaut) | x25519 | ml-kem-768 | x25519+ml-kem-768.
Clés (hors Git) dans AIOT_KEY_DIR : cloud.<kem>.key/.pub et edge.<signature>.key/.pub.
Quand le mode est actif, le Cloud refuse tout incident non scellé.
"""

import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import mlkem, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import message_auth

CHANNEL_MODE_ENV = "AIOT_CHANNEL_MODE"
NO_CHANNEL = "none"
ENVELOPE_VERSION = 1
HKDF_INFO = b"agentic-aiot edge-cloud channel v1"

# Mode -> (composantes d'échange de clés, algorithme de signature de l'incident)
MODES = {
    "x25519": (("x25519",), "ed25519"),
    "ml-kem-768": (("ml-kem-768",), "ml-dsa-44"),
    "x25519+ml-kem-768": (("x25519", "ml-kem-768"), "ml-dsa-44"),
}
EDGE_KEY_NAME = "edge"
CLOUD_KEY_NAME = "cloud"


class ChannelError(ValueError):
    """Incident refusé par le canal : non scellé, altéré, rejoué ou mal signé."""


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _unb64(text):
    return base64.b64decode(text, validate=True)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def channel_mode():
    mode = os.environ.get(CHANNEL_MODE_ENV, NO_CHANNEL).strip().lower()
    if mode != NO_CHANNEL and mode not in MODES:
        raise ValueError(f"Unknown {CHANNEL_MODE_ENV}: {mode}")
    return mode


# --- Clés --------------------------------------------------------------------

def generate_cloud_keys(mode):
    keys = {}
    for kem in MODES[mode][0]:
        keys[kem] = (
            x25519.X25519PrivateKey.generate() if kem == "x25519"
            else mlkem.MLKEM768PrivateKey.generate()
        )
    return keys


def _load_kem_private(kem, raw):
    if kem == "x25519":
        return x25519.X25519PrivateKey.from_private_bytes(raw)
    return mlkem.MLKEM768PrivateKey.from_seed_bytes(raw)


def _load_kem_public(kem, raw):
    if kem == "x25519":
        return x25519.X25519PublicKey.from_public_bytes(raw)
    return mlkem.MLKEM768PublicKey.from_public_bytes(raw)


def create_channel_keys(mode, directory=None):
    """Crée les clés du Cloud (échange) et de l'Edge (signature) pour ce mode."""
    directory = Path(directory or message_auth.key_dir())
    directory.mkdir(parents=True, exist_ok=True)
    for kem, private_key in generate_cloud_keys(mode).items():
        (directory / f"{CLOUD_KEY_NAME}.{kem}.key").write_bytes(private_key.private_bytes_raw())
        (directory / f"{CLOUD_KEY_NAME}.{kem}.pub").write_bytes(private_key.public_key().public_bytes_raw())
    message_auth.create_keyring(MODES[mode][1], [EDGE_KEY_NAME], directory)


def _read(directory, name):
    return (Path(directory) / name).read_bytes()


# --- Scellement et ouverture -------------------------------------------------

def _derive_key(secrets, header):
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=HKDF_INFO + b"|" + _canonical({k: header[k] for k in ("v", "mode", "sig_alg")}),
    ).derive(b"".join(secrets))


class EdgeSealer:
    """Côté Edge : signe puis chiffre chaque incident pour le Cloud."""

    def __init__(self, mode, cloud_public_keys, edge_signing_key):
        self.mode = mode
        self.cloud_public_keys = cloud_public_keys
        self.edge_signing_key = edge_signing_key

    def seal(self, incident):
        kems, sig_alg = MODES[self.mode]
        header = {"v": ENVELOPE_VERSION, "mode": self.mode, "sig_alg": sig_alg}
        secrets = []
        for kem in kems:
            public_key = self.cloud_public_keys[kem]
            if kem == "x25519":
                ephemeral = x25519.X25519PrivateKey.generate()
                secrets.append(ephemeral.exchange(public_key))
                header["epk"] = _b64(ephemeral.public_key().public_bytes_raw())
            else:
                shared, ciphertext = public_key.encapsulate()
                secrets.append(shared)
                header["kem_ct"] = _b64(ciphertext)
        nonce = os.urandom(12)
        header["nonce"] = _b64(nonce)
        signature = self.edge_signing_key.sign(_canonical({"incident": incident, "nonce": header["nonce"]}))
        plaintext = _canonical({"incident": incident, "sig": _b64(signature)})
        payload = AESGCM(_derive_key(secrets, header)).encrypt(nonce, plaintext, _canonical(header))
        return {"sealed": {**header, "payload": _b64(payload)}}


class CloudOpener:
    """Côté Cloud : déchiffre, vérifie la signature de l'Edge et refuse le rejeu."""

    def __init__(self, mode, cloud_private_keys, edge_public_key):
        self.mode = mode
        self.cloud_private_keys = cloud_private_keys
        self.edge_public_key = edge_public_key
        self._seen_nonces = set()

    def open(self, envelope):
        if not isinstance(envelope, dict) or not isinstance(envelope.get("sealed"), dict):
            raise ChannelError("incident is not sealed")
        sealed = dict(envelope["sealed"])
        try:
            payload = _unb64(sealed.pop("payload"))
            header = sealed
            if header.get("v") != ENVELOPE_VERSION or header.get("mode") != self.mode:
                raise ChannelError("unexpected channel mode")
            kems, sig_alg = MODES[self.mode]
            if header.get("sig_alg") != sig_alg:
                raise ChannelError("unexpected signature algorithm")
            secrets = []
            for kem in kems:
                private_key = self.cloud_private_keys[kem]
                if kem == "x25519":
                    peer = x25519.X25519PublicKey.from_public_bytes(_unb64(header["epk"]))
                    secrets.append(private_key.exchange(peer))
                else:
                    secrets.append(private_key.decapsulate(_unb64(header["kem_ct"])))
            nonce = _unb64(header["nonce"])
            plaintext = AESGCM(_derive_key(secrets, header)).decrypt(nonce, payload, _canonical(header))
            content = json.loads(plaintext)
            incident = content["incident"]
            self.edge_public_key.verify(
                _unb64(content["sig"]), _canonical({"incident": incident, "nonce": header["nonce"]})
            )
        except ChannelError:
            raise
        except (InvalidTag, InvalidSignature, KeyError, ValueError, TypeError):
            raise ChannelError("sealed incident cannot be authenticated") from None
        if header["nonce"] in self._seen_nonces:
            raise ChannelError("replayed incident")
        self._seen_nonces.add(header["nonce"])
        return incident


def sealer_from_env(directory=None):
    mode = channel_mode()
    if mode == NO_CHANNEL:
        return None
    directory = directory or message_auth.key_dir()
    kems, sig_alg = MODES[mode]
    cloud_public = {kem: _load_kem_public(kem, _read(directory, f"{CLOUD_KEY_NAME}.{kem}.pub")) for kem in kems}
    edge_key = message_auth.load_private_key(sig_alg, _read(directory, f"{EDGE_KEY_NAME}.{sig_alg}.key"))
    return EdgeSealer(mode, cloud_public, edge_key)


def opener_from_env(directory=None):
    mode = channel_mode()
    if mode == NO_CHANNEL:
        return None
    directory = directory or message_auth.key_dir()
    kems, sig_alg = MODES[mode]
    cloud_private = {kem: _load_kem_private(kem, _read(directory, f"{CLOUD_KEY_NAME}.{kem}.key")) for kem in kems}
    edge_public = message_auth.load_public_key(sig_alg, _read(directory, f"{EDGE_KEY_NAME}.{sig_alg}.pub"))
    return CloudOpener(mode, cloud_private, edge_public)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Crée les clés du canal Edge -> Cloud.")
    parser.add_argument("mode", choices=sorted(MODES))
    parser.add_argument("--key-dir", default=None)
    args = parser.parse_args()
    create_channel_keys(args.mode, args.key_dir)
    print(f"Clés du canal {args.mode} créées dans {args.key_dir or message_auth.key_dir()}")


if __name__ == "__main__":
    main()
