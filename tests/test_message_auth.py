"""IOT-174 : signature de la télémétrie et vérification à l'Edge.

Tests hors réseau. Ils vérifient que les messages falsifiés, modifiés ou
rejoués sont rejetés avant le regroupement B2, et que la signature ne change
aucune des 600 décisions B2 de référence.
"""

import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiocoap import Code, Message

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent
import message_auth
import mqtt_edge_adapter
from coap_server import AlertResource, TelemetryResource
from message_auth import AuthError, DeviceSigner, EdgeVerifier

DEVICES = ("node-01", "node-02", "node-03")
SIGNATURE_ALGORITHMS = ("ed25519", "ml-dsa-44", "ml-dsa-65", "ml-dsa-87")


def telemetry(device, temperature, prediction=0, session="session-1", iteration=1):
    return {
        "v": 1,
        "id": uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "anomaly_alert" if prediction else "telemetry",
        "src": {"tier": "device", "agent": device},
        "session_id": session,
        "iteration": iteration,
        "payload": {
            "temperature": temperature,
            "prediction": prediction,
            "vibration": 0.3,
            "inference_ms": 0.5,
        },
    }


def keyring(algorithm="ml-dsa-44", clock=None):
    private = {d: message_auth.generate_private_key(algorithm) for d in DEVICES}
    signers = {d: DeviceSigner(d, algorithm, key) for d, key in private.items()}
    public = {d: key.public_key() for d, key in private.items()}
    verifier = EdgeVerifier(algorithm, public, clock=clock or (lambda: 0.0))
    return signers, verifier


@pytest.fixture
def incident_log(monkeypatch, tmp_path):
    path = tmp_path / "incidents.jsonl"
    monkeypatch.setattr(edge_agent, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edge_agent, "INCIDENT_FILE", path)
    monkeypatch.setattr(edge_agent, "isolated_devices_by_session", {})
    return path


@pytest.fixture
def mqtt_state(monkeypatch):
    for name in (
        "pending_iterations", "iteration_start_times",
        "processed_message_ids", "completed_iterations",
    ):
        monkeypatch.setattr(mqtt_edge_adapter, name, {})
    monkeypatch.setattr(mqtt_edge_adapter, "collection_metrics", Counter())


# --- Signature et vérification ------------------------------------------------

@pytest.mark.parametrize("algorithm", SIGNATURE_ALGORITHMS)
def test_signed_message_is_accepted(algorithm):
    signers, verifier = keyring(algorithm)
    signed = signers["node-01"].sign(telemetry("node-01", 25.0))

    assert verifier.verify(signed) == "node-01"
    assert signed["auth"]["alg"] == algorithm


@pytest.mark.parametrize("algorithm", SIGNATURE_ALGORITHMS)
def test_modified_temperature_is_rejected(algorithm):
    signers, verifier = keyring(algorithm)
    signed = signers["node-01"].sign(telemetry("node-01", 25.0))
    signed["payload"]["temperature"] = 28.5

    with pytest.raises(AuthError) as error:
        verifier.verify(signed)
    assert error.value.reason == "bad_signature"


def test_attacker_key_cannot_impersonate_a_sensor():
    _, verifier = keyring()
    attacker = DeviceSigner(
        "node-01", "ml-dsa-44", message_auth.generate_private_key("ml-dsa-44")
    )

    with pytest.raises(AuthError) as error:
        verifier.verify(attacker.sign(telemetry("node-01", 28.5)))
    assert error.value.reason == "bad_signature"


def test_signature_of_one_sensor_cannot_be_moved_to_another():
    signers, verifier = keyring()
    signed = signers["node-02"].sign(telemetry("node-02", 25.0))
    signed["src"]["agent"] = "node-01"

    with pytest.raises(AuthError):
        verifier.verify(signed)


@pytest.mark.parametrize(
    "change, reason",
    [
        (lambda m: m.pop("auth"), "missing"),
        (lambda m: m["auth"].update(alg="ed25519"), "wrong_algorithm"),
        (lambda m: m["auth"].update(ctr=0), "invalid_counter"),
        (lambda m: m["auth"].update(sig="pas du base64!"), "bad_signature"),
        (lambda m: m["src"].update(agent="node-99"), "unknown_device"),
    ],
)
def test_malformed_authentication_is_rejected(change, reason):
    signers, verifier = keyring()
    signed = signers["node-01"].sign(telemetry("node-01", 25.0))
    change(signed)

    with pytest.raises(AuthError) as error:
        verifier.verify(signed)
    assert error.value.reason == reason


def test_replayed_message_is_rejected_until_retention_ends():
    clock = SimpleNamespace(now=0.0)
    signers, verifier = keyring(clock=lambda: clock.now)
    signed = signers["node-01"].sign(telemetry("node-01", 25.0))

    verifier.verify(signed)
    with pytest.raises(AuthError) as error:
        verifier.verify(json.loads(json.dumps(signed)))
    assert error.value.reason == "replay"

    # Après la rétention, la fenêtre de fraîcheur de telemetry.py prend le relais.
    clock.now = message_auth.REPLAY_RETENTION_SECONDS
    assert verifier.verify(signed) == "node-01"


def test_counters_strictly_increase_for_each_sensor():
    signers, _ = keyring()
    counters = [
        signers["node-01"].sign(telemetry("node-01", 25.0))["auth"]["ctr"]
        for _ in range(50)
    ]
    assert counters == sorted(set(counters))


def test_signature_survives_json_transport():
    signers, verifier = keyring()
    signed = signers["node-03"].sign(telemetry("node-03", 25.742))
    received = json.loads(json.dumps(signed).encode("utf-8").decode("utf-8"))

    assert verifier.verify(received) == "node-03"


# --- Configuration et clés -----------------------------------------------------

def test_c0_is_the_default(monkeypatch):
    monkeypatch.delenv(message_auth.AUTH_MODE_ENV, raising=False)

    assert message_auth.auth_mode() == "none"
    assert message_auth.verifier_from_env(DEVICES) is None


def test_unknown_mode_is_refused(monkeypatch):
    monkeypatch.setenv(message_auth.AUTH_MODE_ENV, "rsa-1024")

    with pytest.raises(ValueError):
        message_auth.auth_mode()


@pytest.mark.parametrize("algorithm", ("ed25519", "ml-dsa-44"))
def test_keyring_round_trip_from_disk(tmp_path, monkeypatch, algorithm):
    message_auth.create_keyring(algorithm, DEVICES, tmp_path)
    monkeypatch.setenv(message_auth.AUTH_MODE_ENV, algorithm)
    monkeypatch.setenv(message_auth.KEY_DIR_ENV, str(tmp_path))

    signer = message_auth.load_signer("node-02", algorithm)
    verifier = message_auth.verifier_from_env(DEVICES)

    assert verifier.verify(signer.sign(telemetry("node-02", 25.0))) == "node-02"


# --- Intégration Edge : MQTT et CoAP -----------------------------------------

def deliver_mqtt(message):
    asyncio.run(
        mqtt_edge_adapter.on_message(
            f"aiot/telemetry/{message['src']['agent']}",
            json.dumps(message).encode("utf-8"),
        )
    )


def test_mqtt_rejects_forged_sensor_before_grouping(incident_log, mqtt_state, monkeypatch):
    signers, verifier = keyring()
    monkeypatch.setattr(mqtt_edge_adapter, "message_verifier", verifier)
    attacker = DeviceSigner(
        "node-01", "ml-dsa-44", message_auth.generate_private_key("ml-dsa-44")
    )

    deliver_mqtt(attacker.sign(telemetry("node-01", 28.5)))
    deliver_mqtt(telemetry("node-02", 28.5))  # non signé

    assert mqtt_edge_adapter.pending_iterations == {}
    assert mqtt_edge_adapter.processed_message_ids == {}
    metrics = mqtt_edge_adapter.collection_metrics
    assert metrics["messages_auth_rejected"] == 2
    assert metrics["auth_rejected_bad_signature"] == 1
    assert metrics["auth_rejected_missing"] == 1
    assert not incident_log.exists()


def test_mqtt_accepts_signed_batch_and_runs_b2(incident_log, mqtt_state, monkeypatch):
    signers, verifier = keyring()
    monkeypatch.setattr(mqtt_edge_adapter, "message_verifier", verifier)
    analyzed = []
    monkeypatch.setattr(
        mqtt_edge_adapter, "analyze_devices",
        lambda messages: analyzed.append(messages) or edge_agent.analyze_devices(messages),
    )

    for device, temperature in zip(DEVICES, (25.0, 25.0, 28.0)):
        deliver_mqtt(signers[device].sign(telemetry(device, temperature)))

    assert len(analyzed) == 1
    assert mqtt_edge_adapter.collection_metrics["messages_auth_rejected"] == 0
    incident = json.loads(incident_log.read_text(encoding="utf-8"))
    assert incident["reason"] == "SENSOR_INCONSISTENCY"
    assert incident["device_id"] == "node-03"


def test_mqtt_without_verifier_keeps_historical_behaviour(incident_log, mqtt_state, monkeypatch):
    monkeypatch.setattr(mqtt_edge_adapter, "message_verifier", None)

    deliver_mqtt(telemetry("node-01", 25.0))

    assert ("session-1", 1) in mqtt_edge_adapter.pending_iterations
    assert mqtt_edge_adapter.collection_metrics["messages_auth_rejected"] == 0


def post(resource, message):
    request = Message(code=Code.POST, payload=json.dumps(message).encode("utf-8"))
    return asyncio.run(resource.render_post(request))


def test_coap_telemetry_rejects_forged_and_accepts_signed(incident_log):
    signers, verifier = keyring()
    collector = TelemetryResource(verifier=verifier)
    attacker = DeviceSigner(
        "node-01", "ml-dsa-44", message_auth.generate_private_key("ml-dsa-44")
    )

    assert post(collector, attacker.sign(telemetry("node-01", 28.5))).code == Code.UNAUTHORIZED
    assert post(collector, signers["node-01"].sign(telemetry("node-01", 25.0))).code == Code.CHANGED
    assert collector.collection_metrics["messages_auth_rejected"] == 1
    assert list(collector.pending.values())[0][1].keys() == {"node-01"}


def test_coap_alert_requires_signature_when_enabled(incident_log):
    signers, verifier = keyring()
    alert = {
        "type": "anomaly_alert",
        "src": {"agent": "node-01"},
        "payload": {"temperature": 28.0, "anomaly_type": "local"},
    }

    assert post(AlertResource(verifier=verifier), alert).code == Code.UNAUTHORIZED
    assert not incident_log.exists()
    assert post(AlertResource(verifier=verifier), signers["node-01"].sign(alert)).code == Code.CHANGED
    assert incident_log.exists()


# --- Non-régression : les 600 décisions B2 de référence ----------------------

@pytest.mark.parametrize("algorithm", ("ed25519", "ml-dsa-44"))
def test_signed_reference_replay_keeps_all_600_b2_decisions(incident_log, algorithm):
    signers, verifier = keyring(algorithm)
    groups = defaultdict(list)
    path = ROOT / "results" / "collaborative_b2_predictions.csv"
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            groups[row["session_id"], int(row["iteration"])].append(row)

    checked = 0
    for (session, iteration), rows in groups.items():
        received = []
        for row in rows:
            message = telemetry(
                row["device_id"], float(row["temperature"]),
                int(row["b1_prediction"]), session, iteration,
            )
            wire = json.dumps(signers[row["device_id"]].sign(message))
            signed = json.loads(wire)
            verifier.verify(signed)
            received.append(signed)
        reference, decisions = edge_agent.analyze_devices(received)
        for row in rows:
            decision = decisions[row["device_id"]]
            assert reference == float(row["group_median"])
            assert decision["collaborative_alert"] == int(row["collaborative_alert"])
            assert decision["b2_prediction"] == int(row["b2_prediction"])
            checked += 1

    assert checked == 600
