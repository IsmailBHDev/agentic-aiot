"""Authentification des messages Device -> Edge (IOT-174).

Chaque capteur signe ses messages avec sa clé privée ; l'Edge vérifie la
signature avec la clé publique du capteur avant tout regroupement B2.

Configurations (variable d'environnement AIOT_AUTH_MODE) :
- ``none``      : C0, aucune signature (comportement historique, par défaut) ;
- ``ed25519``   : C1, référence classique ;
- ``ml-dsa-44`` : C2, post-quantique (FIPS 204), choix par défaut d'IOT-173 ;
- ``ml-dsa-65`` et ``ml-dsa-87`` : niveaux supérieurs, mesurés dans IOT-178.

La signature couvre tout le message sauf la signature elle-même, y compris
l'identifiant, l'horodatage et un compteur strictement croissant par capteur.
Le compteur bloque le rejeu d'un message déjà accepté. Ce module ne modifie
ni le calcul B2 ni son seuil.
"""

import base64
import json
import os
import time
from collections import deque
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519, mldsa

AUTH_MODE_ENV = "AIOT_AUTH_MODE"
KEY_DIR_ENV = "AIOT_KEY_DIR"
DEFAULT_KEY_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "keys"
NO_AUTH = "none"

# Durée pendant laquelle un compteur déjà vu est mémorisé. Elle couvre la
# fenêtre de fraîcheur de telemetry.py (300 s + 5 s de décalage).
REPLAY_RETENTION_SECONDS = 305

ALGORITHMS = {
    "ed25519": (ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey),
    "ml-dsa-44": (mldsa.MLDSA44PrivateKey, mldsa.MLDSA44PublicKey),
    "ml-dsa-65": (mldsa.MLDSA65PrivateKey, mldsa.MLDSA65PublicKey),
    "ml-dsa-87": (mldsa.MLDSA87PrivateKey, mldsa.MLDSA87PublicKey),
}


class AuthError(ValueError):
    """Message refusé par l'authentification ; ``reason`` sert aux compteurs."""

    def __init__(self, reason):
        super().__init__(f"Authentication failed: {reason}")
        self.reason = reason


def auth_mode():
    mode = os.environ.get(AUTH_MODE_ENV, NO_AUTH).strip().lower()
    if mode != NO_AUTH and mode not in ALGORITHMS:
        raise ValueError(f"Unknown {AUTH_MODE_ENV}: {mode}")
    return mode


def key_dir():
    return Path(os.environ.get(KEY_DIR_ENV, DEFAULT_KEY_DIR))


def canonical_bytes(message):
    """Octets signés : message sans le champ ``auth.sig``, en JSON canonique."""
    unsigned = dict(message)
    auth = dict(unsigned.get("auth") or {})
    auth.pop("sig", None)
    unsigned["auth"] = auth
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _private_class(algorithm):
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    return ALGORITHMS[algorithm][0]


def _public_class(algorithm):
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    return ALGORITHMS[algorithm][1]


def generate_private_key(algorithm):
    return _private_class(algorithm).generate()


def private_key_bytes(private_key):
    """Graine de 32 octets (ML-DSA) ou clé brute de 32 octets (Ed25519)."""
    return private_key.private_bytes_raw()


def load_private_key(algorithm, raw):
    cls = _private_class(algorithm)
    if algorithm == "ed25519":
        return cls.from_private_bytes(raw)
    return cls.from_seed_bytes(raw)


def load_public_key(algorithm, raw):
    return _public_class(algorithm).from_public_bytes(raw)


class DeviceSigner:
    """Signe les messages d'un capteur avec un compteur strictement croissant."""

    def __init__(self, device_id, algorithm, private_key):
        self.device_id = device_id
        self.algorithm = algorithm
        self.private_key = private_key
        self._last_counter = 0

    def _next_counter(self):
        # Compteur en microsecondes : il reste croissant après un redémarrage
        # du capteur tant que l'horloge est synchronisée.
        self._last_counter = max(self._last_counter + 1, time.time_ns() // 1000)
        return self._last_counter

    def sign(self, message):
        signed = dict(message)
        signed["auth"] = {"alg": self.algorithm, "ctr": self._next_counter()}
        signature = self.private_key.sign(canonical_bytes(signed))
        signed["auth"]["sig"] = base64.b64encode(signature).decode("ascii")
        return signed


class EdgeVerifier:
    """Vérifie origine, intégrité et unicité des messages reçus par l'Edge."""

    def __init__(self, algorithm, public_keys, clock=time.monotonic):
        self.algorithm = algorithm
        self.public_keys = dict(public_keys)
        self.clock = clock
        self._seen = {}  # (device_id, ctr) -> date de réception
        # File dans l'ordre de réception : l'oubli des compteurs anciens coûte
        # O(1) amorti par message au lieu de parcourir tous les compteurs (IOT-154).
        self._order = deque()

    def verify(self, message):
        """Renvoie le capteur authentifié ou lève ``AuthError``."""
        if not isinstance(message, dict):
            raise AuthError("not_a_message")
        auth = message.get("auth")
        if not isinstance(auth, dict):
            raise AuthError("missing")
        if auth.get("alg") != self.algorithm:
            raise AuthError("wrong_algorithm")
        counter = auth.get("ctr")
        if type(counter) is not int or counter <= 0:
            raise AuthError("invalid_counter")
        source = message.get("src")
        device_id = source.get("agent") if isinstance(source, dict) else None
        public_key = self.public_keys.get(device_id)
        if public_key is None:
            raise AuthError("unknown_device")
        try:
            signature = base64.b64decode(auth.get("sig", ""), validate=True)
            public_key.verify(signature, canonical_bytes(message))
        except (InvalidSignature, ValueError, TypeError):
            raise AuthError("bad_signature") from None

        now = self.clock()
        self._forget_old(now)
        if (device_id, counter) in self._seen:
            raise AuthError("replay")
        self._seen[device_id, counter] = now
        self._order.append((now, (device_id, counter)))
        return device_id

    def _forget_old(self, now):
        while self._order and now - self._order[0][0] >= REPLAY_RETENTION_SECONDS:
            received, entry = self._order.popleft()
            if self._seen.get(entry) == received:
                del self._seen[entry]


def create_keyring(algorithm, devices, directory=None):
    """Crée une paire de clés par capteur et les enregistre (hors Git)."""
    directory = Path(directory or key_dir())
    directory.mkdir(parents=True, exist_ok=True)
    keys = {}
    for device_id in devices:
        private_key = generate_private_key(algorithm)
        (directory / f"{device_id}.{algorithm}.key").write_bytes(
            private_key_bytes(private_key)
        )
        (directory / f"{device_id}.{algorithm}.pub").write_bytes(
            private_key.public_key().public_bytes_raw()
        )
        keys[device_id] = private_key
    return keys


def load_signer(device_id, algorithm, directory=None):
    path = Path(directory or key_dir()) / f"{device_id}.{algorithm}.key"
    return DeviceSigner(device_id, algorithm, load_private_key(algorithm, path.read_bytes()))


def load_verifier(algorithm, devices, directory=None):
    directory = Path(directory or key_dir())
    keys = {
        device_id: load_public_key(
            algorithm, (directory / f"{device_id}.{algorithm}.pub").read_bytes()
        )
        for device_id in devices
    }
    return EdgeVerifier(algorithm, keys)


def verifier_from_env(devices):
    """Vérificateur de l'Edge selon AIOT_AUTH_MODE ; ``None`` en C0."""
    mode = auth_mode()
    if mode == NO_AUTH:
        return None
    return load_verifier(mode, devices)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Crée les clés des capteurs simulés.")
    parser.add_argument("algorithm", choices=sorted(ALGORITHMS))
    parser.add_argument("--devices", nargs="+", default=["node-01", "node-02", "node-03"])
    parser.add_argument("--key-dir", default=None)
    args = parser.parse_args()
    create_keyring(args.algorithm, args.devices, args.key_dir)
    print(f"Clés {args.algorithm} créées dans {args.key_dir or key_dir()}")


if __name__ == "__main__":
    main()
