"""IOT-158 : OTA simulé — installation vérifiée, attaques refusées, retour arrière."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_ota  # noqa: E402
import message_auth  # noqa: E402
import ota  # noqa: E402
import telemetry  # noqa: E402
from ota import OtaError  # noqa: E402

SIGNED = ("ed25519", "ml-dsa-44")


@pytest.fixture(scope="module")
def bench():
    return evaluate_ota.Bench()


def keypair(algorithm):
    private_key = message_auth.generate_private_key(algorithm)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def scenarios(bench, tmp_path_factory):
    keys = {mode: keypair(mode) for mode in SIGNED}
    attacker = {mode: keypair(mode) for mode in SIGNED}
    workdir = tmp_path_factory.mktemp("ota")
    return {mode: evaluate_ota.run_scenarios(bench, workdir, mode, keys, attacker)
            for mode in evaluate_ota.MODES}


@pytest.mark.parametrize("mode", evaluate_ota.MODES)
def test_reference_v1_reproduces_the_evaluated_b1(scenarios, mode):
    """Corrige IOT-180 : le capteur exécute le B1 des résultats (600/600)."""
    record = scenarios[mode]["install_reference_v1"]
    assert record["status"] == "installed" and record["active_version"] == 1
    assert record["agreement_with_reference_b1"] == 600
    assert record["f1_test"] == 0.8493


@pytest.mark.parametrize("mode", evaluate_ota.MODES)
def test_nominal_update_and_rollback(scenarios, mode):
    assert scenarios[mode]["update_v2"]["active_version"] == 2
    rollback = scenarios[mode]["rollback_then_update"]
    assert rollback["status"] == "up_to_date" and rollback["active_version"] == 1
    assert rollback["rejected_versions"] == [2]


@pytest.mark.parametrize("mode", evaluate_ota.MODES)
@pytest.mark.parametrize("scenario, reason", [
    ("corrupted_in_transit", "digest_mismatch"),
    ("older_catalog", "not_newer"),
    ("incompatible_model", "health_check_failed"),
])
def test_refused_in_every_mode(scenarios, mode, scenario, reason):
    record = scenarios[mode][scenario]
    assert record["status"] == "refused" and record["reason"] == reason
    assert record["f1_test"] == 0.8493  # version active intacte


@pytest.mark.parametrize("mode", SIGNED)
@pytest.mark.parametrize("scenario", ["poisoned_repository", "unsigned_release", "disguised_downgrade"])
def test_signatures_block_repository_attacks(scenarios, mode, scenario):
    record = scenarios[mode][scenario]
    assert record["status"] == "refused" and record["reason"] == "bad_signature"
    assert record["f1_test"] == 0.8493


@pytest.mark.parametrize("scenario", ["poisoned_repository", "unsigned_release"])
def test_unsigned_mode_accepts_a_poisoned_repository(scenarios, scenario):
    """Comparateur C0 : sans signature, l'empreinte du catalogue ne protège pas."""
    record = scenarios["none"][scenario]
    assert record["status"] == "installed" and record["f1_test"] == 0.0


def test_signature_is_checked_before_deserialisation(bench, tmp_path):
    private_key, public_key = keypair("ml-dsa-44")
    _, attacker_public = keypair("ml-dsa-44")
    ota.publish_release(tmp_path / "repo", bench.reference, 1, "ml-dsa-44", private_key)
    calls = []
    device = ota.DeviceOta(tmp_path / "device", "ml-dsa-44", attacker_public,
                           loader=lambda path: calls.append(path))
    result = device.update(tmp_path / "repo")
    assert result["status"] == "refused" and result["reason"] == "bad_signature"
    assert calls == [] and device.active_version is None
    assert not (tmp_path / "device" / "staging").exists()


def test_tampered_active_slot_is_refused_at_boot(bench, tmp_path):
    private_key, public_key = keypair("ed25519")
    ota.publish_release(tmp_path / "repo", bench.reference, 1, "ed25519", private_key)
    device = ota.DeviceOta(tmp_path / "device", "ed25519", public_key)
    assert device.update(tmp_path / "repo")["status"] == "installed"
    model, version = device.load_active()
    assert version == 1
    slot = device.slots / ota.release_file(1)
    data = bytearray(slot.read_bytes())
    data[-10] ^= 0x01
    slot.write_bytes(bytes(data))
    with pytest.raises(OtaError) as error:
        device.load_active()
    assert error.value.reason == "digest_mismatch"


def test_rollback_requires_a_previous_version(bench, tmp_path):
    ota.publish_release(tmp_path / "repo", bench.reference, 1, "none")
    device = ota.DeviceOta(tmp_path / "device", "none")
    device.update(tmp_path / "repo")
    with pytest.raises(OtaError):
        device.rollback()


def test_publishing_twice_the_same_version_fails(bench, tmp_path):
    ota.publish_release(tmp_path / "repo", bench.reference, 1, "none")
    with pytest.raises(ValueError):
        ota.publish_release(tmp_path / "repo", bench.reference, 1, "none")


def telemetry_message(**payload):
    return {
        "session_id": "s", "iteration": 1, "id": "m", "type": "telemetry",
        "src": {"agent": "node-01"},
        "payload": {"temperature": 25.0, "vibration": 0.3, "inference_ms": 0.1,
                    "prediction": 0, **payload},
    }


def test_model_version_in_telemetry_is_optional_and_validated():
    telemetry.validate_telemetry(telemetry_message())
    telemetry.validate_telemetry(telemetry_message(model_version=2))
    for bad in (0, "2", 1.5, True):
        with pytest.raises(ValueError):
            telemetry.validate_telemetry(telemetry_message(model_version=bad))
