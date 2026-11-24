"""IOT-178 : coût des configurations C0 à C2 (tailles, temps, octets, traitement Edge).

Trois mesures, toutes hors réseau :
1. primitives : temps de signature, vérification, encapsulation et
   décapsulation sur N opérations, avec les tailles de clés et de sorties ;
2. messages : taille réelle d'un message de télémétrie et d'un incident,
   en clair, signés (C1, C2) et scellés pour le Cloud ;
3. Edge : temps de traitement par message dans le vrai chemin
   ``mqtt_edge_adapter.on_message``, sur les 600 observations du test
   historique, avec et sans vérification, en plusieurs répétitions.

Les latences du banc B3 en réseau local ne sont pas mesurées ici.

Usage : python -B src/evaluate_pq_cost.py --output results/pq_cost_<date>.json
"""

import argparse
import asyncio
import contextlib
import io
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cryptography
from cryptography.hazmat.primitives.asymmetric import mlkem, x25519

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_pq_attacks as attacks  # noqa: E402
import message_auth  # noqa: E402
import mqtt_edge_adapter  # noqa: E402
import secure_channel  # noqa: E402

SIGNATURES = ("ed25519", "ml-dsa-44", "ml-dsa-65", "ml-dsa-87")
EDGE_CONFIGURATIONS = ("none", "ed25519", "ml-dsa-44", "ml-dsa-65")
CHANNEL_MODES = tuple(secure_channel.MODES)
SAMPLE_INCIDENT = {
    "id": "00000000-0000-4000-8000-000000000000",
    "device_id": "node-03",
    "temperature": 28.164,
    "reference": 25.742,
    "reason": "SENSOR_INCONSISTENCY",
    "session_id": "synthetic-seed-42",
    "timestamp": "2026-11-23T12:00:00+00:00",
    "action": "ISOLATE",
    "iteration": 132,
}


def summary(samples_ms):
    ordered = sorted(samples_ms)
    return {
        "n": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 4),
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[max(0, round(0.95 * len(ordered)) - 1)], 4),
    }


def timed(operation, repetitions):
    samples = []
    for _ in range(repetitions):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start) * 1000)
    return summary(samples)


def sample_message():
    message = attacks.make_message("node-03", 28.164, 0, "synthetic-seed-42", 132)
    message["ts"] = "2026-11-23T12:00:00+00:00"
    message["id"] = "00000000-0000-4000-8000-000000000001"
    return message


def wire_size(value):
    return len(json.dumps(value).encode("utf-8"))


def primitives(repetitions):
    message = json.dumps(sample_message()).encode("utf-8")
    results = {}
    for algorithm in SIGNATURES:
        private_key = message_auth.generate_private_key(algorithm)
        public_key = private_key.public_key()
        signature = private_key.sign(message)
        results[algorithm] = {
            "public_key_bytes": len(public_key.public_bytes_raw()),
            "signature_bytes": len(signature),
            "sign": timed(lambda: private_key.sign(message), repetitions),
            "verify": timed(lambda: public_key.verify(signature, message), repetitions),
        }
    kem_private = mlkem.MLKEM768PrivateKey.generate()
    kem_public = kem_private.public_key()
    _, ciphertext = kem_public.encapsulate()
    results["ml-kem-768"] = {
        "public_key_bytes": len(kem_public.public_bytes_raw()),
        "ciphertext_bytes": len(ciphertext),
        "encapsulate": timed(kem_public.encapsulate, repetitions),
        "decapsulate": timed(lambda: kem_private.decapsulate(ciphertext), repetitions),
    }
    dh_private = x25519.X25519PrivateKey.generate()
    peer = x25519.X25519PrivateKey.generate().public_key()
    results["x25519"] = {
        "public_key_bytes": len(peer.public_bytes_raw()),
        "exchange": timed(lambda: dh_private.exchange(peer), repetitions),
    }
    return results


def message_sizes():
    plain = sample_message()
    telemetry = {"none": {"bytes": wire_size(plain), "overhead_bytes": 0}}
    for algorithm in SIGNATURES:
        signer = message_auth.DeviceSigner(
            "node-03", algorithm, message_auth.generate_private_key(algorithm)
        )
        size = wire_size(signer.sign(plain))
        telemetry[algorithm] = {
            "bytes": size,
            "overhead_bytes": size - wire_size(plain),
            "ratio": round(size / wire_size(plain), 2),
        }
    incident = {"none": {"bytes": wire_size(SAMPLE_INCIDENT), "overhead_bytes": 0}}
    for mode in CHANNEL_MODES:
        cloud = secure_channel.generate_cloud_keys(mode)
        sig_alg = secure_channel.MODES[mode][1]
        sealer = secure_channel.EdgeSealer(
            mode, {k: v.public_key() for k, v in cloud.items()},
            message_auth.generate_private_key(sig_alg),
        )
        size = wire_size(sealer.seal(SAMPLE_INCIDENT))
        incident[mode] = {
            "signature": sig_alg,
            "bytes": size,
            "overhead_bytes": size - wire_size(SAMPLE_INCIDENT),
            "ratio": round(size / wire_size(SAMPLE_INCIDENT), 2),
        }
    return {"telemetry_message": telemetry, "sealed_incident": incident}


def channel_times(repetitions):
    results = {}
    for mode in CHANNEL_MODES:
        cloud = secure_channel.generate_cloud_keys(mode)
        sig_alg = secure_channel.MODES[mode][1]
        edge_key = message_auth.generate_private_key(sig_alg)
        sealer = secure_channel.EdgeSealer(mode, {k: v.public_key() for k, v in cloud.items()}, edge_key)
        envelopes = [sealer.seal(SAMPLE_INCIDENT) for _ in range(repetitions)]
        opener = secure_channel.CloudOpener(mode, cloud, edge_key.public_key())
        queue = iter(envelopes)
        results[mode] = {
            "seal": timed(lambda: sealer.seal(SAMPLE_INCIDENT), repetitions),
            "open": timed(lambda: opener.open(next(queue)), repetitions),
        }
    return results


def edge_processing(repetitions, limit=None):
    groups = attacks.load_reference(limit)
    results = {}
    with attacks.edge_sandbox(), tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        for algorithm in EDGE_CONFIGURATIONS:
            per_message = []
            signing = []
            for _ in range(repetitions):
                run = attacks.EdgeRun(algorithm, tmp)
                wires = []
                for key in groups:
                    for message in attacks.legit_messages(groups, key):
                        start = time.perf_counter()
                        signed = run.legitimate(message)
                        signing.append((time.perf_counter() - start) * 1000)
                        wires.append(json.dumps(signed).encode("utf-8"))

                async def replay():
                    for data in wires:
                        start = time.perf_counter()
                        await mqtt_edge_adapter.on_message("aiot/telemetry/x", data)
                        per_message.append((time.perf_counter() - start) * 1000)

                asyncio.run(replay())
                assert mqtt_edge_adapter.collection_metrics["batches_completed"] == len(groups)
                assert mqtt_edge_adapter.collection_metrics["messages_auth_rejected"] == 0
            results[algorithm] = {
                "messages": len(per_message),
                "edge_on_message": summary(per_message),
                "device_signing": summary(signing) if algorithm != "none" else None,
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    parser.add_argument("--operations", type=int, default=1000)
    parser.add_argument("--edge-repetitions", type=int, default=5)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "ticket": "IOT-178",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Mesures hors réseau sur une seule machine ; latences B3 en réseau local non incluses.",
        "operations_per_primitive": args.operations,
        "edge_repetitions": args.edge_repetitions,
        "versions": {
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
        },
        "primitives": primitives(args.operations),
        "sizes": message_sizes(),
        "channel": channel_times(args.operations),
        "edge_processing": edge_processing(args.edge_repetitions),
    }
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: document[k] for k in ("sizes", "edge_processing")}, indent=2))


if __name__ == "__main__":
    main()
