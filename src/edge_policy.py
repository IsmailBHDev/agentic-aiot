"""IOT-159 : règles de l'Edge ajustées depuis le Cloud (politique signée).

Le Cloud publie une politique numérotée et signée ; l'Edge ne l'applique que si
la signature est valide, la version strictement supérieure à la version active
et chaque champ autorisé et dans ses bornes. Deux règles seulement sont
ajustables :

- ``batch_timeout_seconds`` : délai d'expiration d'un lot incomplet
  (MQTT et CoAP), borné à [1, 60] s ; historique : 5 s ;
- ``isolation`` : politique d'isolement logique après une incohérence
  collaborative :
  - ``isolate_once`` (historique) : un capteur isolé ne produit plus
    d'incident ``SENSOR_INCONSISTENCY`` dans sa session ;
  - ``report_all`` : le capteur reste isolé, mais chaque nouvelle incohérence
    est encore journalisée.

Le seuil B2 (2,50 °C) n'est **pas** ajustable : toute politique contenant un
autre champ, dont un seuil, est refusée. L'isolement n'agit que sur la
journalisation des incidents ; les décisions B2 ne changent pas.

Sans politique appliquée, l'Edge garde le comportement historique. Au
démarrage, ``AIOT_EDGE_POLICY_FILE`` désigne une politique signée à appliquer
(vérifiée avec la clé ``cloud.<alg>.pub`` et ``AIOT_POLICY_SIGNING``).
"""

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature

import message_auth

POLICY_FILE_ENV = "AIOT_EDGE_POLICY_FILE"
POLICY_SIGNING_ENV = "AIOT_POLICY_SIGNING"
CLOUD_KEY_NAME = "cloud"
ISOLATION_MODES = ("isolate_once", "report_all")
TIMEOUT_BOUNDS = (1.0, 60.0)
ALLOWED_FIELDS = {"version", "batch_timeout_seconds", "isolation"}


class PolicyError(ValueError):
    """Politique refusée ; ``reason`` est un code court stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class EdgePolicy:
    version: int = 0
    batch_timeout_seconds: float = 5.0
    isolation: str = "isolate_once"


HISTORICAL = EdgePolicy()
# Politique active de l'Edge (lue par mqtt_edge_adapter, coap_server et edge_agent).
current = HISTORICAL


def reset():
    """Revient à la politique historique (tests et évaluations)."""
    global current
    current = HISTORICAL


def batch_timeout_seconds():
    return current.batch_timeout_seconds


def reports_isolated_devices():
    return current.isolation == "report_all"


def parse(document):
    """Valide les champs d'une politique et renvoie un ``EdgePolicy``."""
    extra = set(document) - ALLOWED_FIELDS
    if extra:
        raise PolicyError("forbidden_field", ", ".join(sorted(extra)))
    if set(document) != ALLOWED_FIELDS:
        raise PolicyError("missing_field", ", ".join(sorted(ALLOWED_FIELDS - set(document))))
    version = document["version"]
    timeout = document["batch_timeout_seconds"]
    isolation = document["isolation"]
    if type(version) is not int or version < 1:
        raise PolicyError("invalid_version")
    if type(timeout) not in (int, float) or not TIMEOUT_BOUNDS[0] <= timeout <= TIMEOUT_BOUNDS[1]:
        raise PolicyError("timeout_out_of_bounds")
    if isolation not in ISOLATION_MODES:
        raise PolicyError("invalid_isolation")
    return EdgePolicy(version, float(timeout), isolation)


def _canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------- Cloud

def sign_policy(document, algorithm, private_key):
    """Renvoie l'enveloppe signée ``{"policy", "alg", "sig"}`` (champs validés d'abord)."""
    parse(document)
    envelope = {"policy": dict(document), "alg": algorithm}
    if algorithm != message_auth.NO_AUTH:
        envelope["sig"] = base64.b64encode(private_key.sign(_canonical(envelope))).decode("ascii")
    return envelope


def write_policy(path, document, algorithm, private_key=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sign_policy(document, algorithm, private_key), indent=2) + "\n",
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------- Edge

def verify(envelope, algorithm, public_key):
    """Vérifie la signature et les champs ; renvoie un ``EdgePolicy``."""
    if not isinstance(envelope, dict) or not isinstance(envelope.get("policy"), dict):
        raise PolicyError("malformed")
    if envelope.get("alg") != algorithm:
        raise PolicyError("wrong_algorithm")
    if algorithm != message_auth.NO_AUTH:
        signed = {key: value for key, value in envelope.items() if key != "sig"}
        try:
            signature = base64.b64decode(envelope["sig"], validate=True)
            public_key.verify(signature, _canonical(signed))
        except (KeyError, ValueError, TypeError, InvalidSignature):
            raise PolicyError("bad_signature") from None
    return parse(envelope["policy"])


def apply(envelope, algorithm, public_key=None):
    """Applique une politique plus récente ; lève ``PolicyError`` sans rien changer."""
    global current
    policy = verify(envelope, algorithm, public_key)
    if policy.version <= current.version:
        raise PolicyError("not_newer")
    current = policy
    return policy


def apply_from_environment():
    """Applique ``AIOT_EDGE_POLICY_FILE`` s'il est défini ; renvoie la politique active."""
    path = os.environ.get(POLICY_FILE_ENV)
    if not path:
        return current
    algorithm = os.environ.get(POLICY_SIGNING_ENV, message_auth.NO_AUTH).strip().lower()
    public_key = None
    if algorithm != message_auth.NO_AUTH:
        if algorithm not in message_auth.ALGORITHMS:
            raise ValueError(f"Unknown {POLICY_SIGNING_ENV}: {algorithm}")
        key_path = message_auth.key_dir() / f"{CLOUD_KEY_NAME}.{algorithm}.pub"
        public_key = message_auth.load_public_key(algorithm, key_path.read_bytes())
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    return apply(envelope, algorithm, public_key)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Publie une politique Edge signée par le Cloud.")
    parser.add_argument("output")
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--batch-timeout", type=float, default=HISTORICAL.batch_timeout_seconds)
    parser.add_argument("--isolation", choices=ISOLATION_MODES, default=HISTORICAL.isolation)
    parser.add_argument("--algorithm", default=message_auth.NO_AUTH,
                        choices=[message_auth.NO_AUTH, *sorted(message_auth.ALGORITHMS)])
    args = parser.parse_args()
    private_key = None
    if args.algorithm != message_auth.NO_AUTH:
        directory = message_auth.key_dir()
        key_file = directory / f"{CLOUD_KEY_NAME}.{args.algorithm}.key"
        if not key_file.exists():
            message_auth.create_keyring(args.algorithm, [CLOUD_KEY_NAME], directory)
        private_key = message_auth.load_private_key(args.algorithm, key_file.read_bytes())
    document = {"version": args.version, "batch_timeout_seconds": args.batch_timeout,
                "isolation": args.isolation}
    print(f"Politique écrite : {write_policy(args.output, document, args.algorithm, private_key)}")


if __name__ == "__main__":
    main()
