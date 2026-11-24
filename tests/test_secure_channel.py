"""IOT-177 : canal Edge -> Cloud signé et chiffré (X25519, ML-KEM-768, hybride)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cloud_store  # noqa: E402
import message_auth  # noqa: E402
import secure_channel  # noqa: E402
from secure_channel import ChannelError, CloudOpener, EdgeSealer  # noqa: E402

MODES = tuple(secure_channel.MODES)
INCIDENT = {
    "id": "edge-incident-1",
    "device_id": "node-03",
    "temperature": 28.164,
    "reference": 25.742,
    "reason": "SENSOR_INCONSISTENCY",
    "session_id": "synthetic-seed-42",
    "iteration": 132,
    "action": "ISOLATE",
}


def channel(mode, edge_key=None):
    cloud_private = secure_channel.generate_cloud_keys(mode)
    sig_alg = secure_channel.MODES[mode][1]
    edge_private = message_auth.generate_private_key(sig_alg)
    sealer = EdgeSealer(
        mode, {k: v.public_key() for k, v in cloud_private.items()}, edge_key or edge_private
    )
    opener = CloudOpener(mode, cloud_private, edge_private.public_key())
    return sealer, opener


@pytest.mark.parametrize("mode", MODES)
def test_sealed_incident_round_trip(mode):
    sealer, opener = channel(mode)
    envelope = json.loads(json.dumps(sealer.seal(INCIDENT)))

    assert opener.open(envelope) == INCIDENT


@pytest.mark.parametrize("mode", MODES)
def test_envelope_hides_incident_content(mode):
    sealer, _ = channel(mode)
    wire = json.dumps(sealer.seal(INCIDENT))

    for secret in ("node-03", "SENSOR_INCONSISTENCY", "synthetic-seed-42", "28.164"):
        assert secret not in wire


@pytest.mark.parametrize("mode", MODES)
def test_modified_ciphertext_is_rejected(mode):
    sealer, opener = channel(mode)
    envelope = sealer.seal(INCIDENT)
    payload = bytearray(secure_channel._unb64(envelope["sealed"]["payload"]))
    payload[0] ^= 0x01
    envelope["sealed"]["payload"] = secure_channel._b64(bytes(payload))

    with pytest.raises(ChannelError):
        opener.open(envelope)


def test_modified_header_is_rejected():
    sealer, opener = channel("ml-kem-768")
    envelope = sealer.seal(INCIDENT)
    envelope["sealed"]["sig_alg"] = "ed25519"

    with pytest.raises(ChannelError):
        opener.open(envelope)


def test_mode_mismatch_is_rejected():
    sealer, _ = channel("x25519")
    _, opener = channel("ml-kem-768")

    with pytest.raises(ChannelError):
        opener.open(sealer.seal(INCIDENT))


@pytest.mark.parametrize("mode", MODES)
def test_incident_signed_by_another_key_is_rejected(mode):
    """L'attaquant connaît la clé publique du Cloud mais pas la clé de l'Edge."""
    sig_alg = secure_channel.MODES[mode][1]
    honest_sealer, opener = channel(mode)
    attacker = EdgeSealer(
        mode, honest_sealer.cloud_public_keys, message_auth.generate_private_key(sig_alg)
    )

    with pytest.raises(ChannelError):
        opener.open(attacker.seal({**INCIDENT, "reason": "LOCAL_ML_ANOMALY"}))


def test_replayed_envelope_is_rejected():
    sealer, opener = channel("x25519+ml-kem-768")
    envelope = sealer.seal(INCIDENT)

    opener.open(envelope)
    with pytest.raises(ChannelError, match="replayed"):
        opener.open(envelope)


def test_plain_incident_is_rejected_by_opener():
    _, opener = channel("ml-kem-768")

    with pytest.raises(ChannelError, match="not sealed"):
        opener.open(INCIDENT)


# --- Configuration, clés et intégration au stockage Cloud --------------------

@pytest.fixture
def cloud_file(tmp_path, monkeypatch):
    path = tmp_path / "cloud_incidents.jsonl"
    monkeypatch.setenv("AIOT_CLOUD_INCIDENT_FILE", str(path))
    monkeypatch.setattr(cloud_store, "_opener_cache", {})
    return path


def test_c0_is_the_default(monkeypatch):
    monkeypatch.delenv(secure_channel.CHANNEL_MODE_ENV, raising=False)

    assert secure_channel.channel_mode() == "none"
    assert secure_channel.sealer_from_env() is None
    assert secure_channel.opener_from_env() is None


@pytest.mark.parametrize("mode", MODES)
def test_cloud_store_opens_sealed_incidents(mode, tmp_path, monkeypatch, cloud_file):
    keys = tmp_path / "keys"
    secure_channel.create_channel_keys(mode, keys)
    monkeypatch.setenv(secure_channel.CHANNEL_MODE_ENV, mode)
    monkeypatch.setenv(message_auth.KEY_DIR_ENV, str(keys))

    result = cloud_store.report_incident(secure_channel.sealer_from_env().seal(INCIDENT))

    record = json.loads(cloud_file.read_text(encoding="utf-8"))
    assert result["status"] == "accepted"
    assert {key: record[key] for key in INCIDENT} == INCIDENT
    assert "sealed" not in record


def test_cloud_store_refuses_plain_incident_when_channel_is_active(tmp_path, monkeypatch, cloud_file):
    keys = tmp_path / "keys"
    secure_channel.create_channel_keys("ml-kem-768", keys)
    monkeypatch.setenv(secure_channel.CHANNEL_MODE_ENV, "ml-kem-768")
    monkeypatch.setenv(message_auth.KEY_DIR_ENV, str(keys))

    with pytest.raises(ValueError):
        cloud_store.report_incident(dict(INCIDENT))
    assert not cloud_file.exists()


def test_cloud_store_refuses_sealed_incident_in_c0(monkeypatch, cloud_file):
    monkeypatch.delenv(secure_channel.CHANNEL_MODE_ENV, raising=False)
    sealer, _ = channel("ml-kem-768")

    with pytest.raises(ValueError):
        cloud_store.report_incident(sealer.seal(INCIDENT))


def test_cloud_store_keeps_plain_incidents_in_c0(monkeypatch, cloud_file):
    monkeypatch.delenv(secure_channel.CHANNEL_MODE_ENV, raising=False)

    assert cloud_store.report_incident(dict(INCIDENT))["status"] == "accepted"
