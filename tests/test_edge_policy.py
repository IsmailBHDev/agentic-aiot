"""IOT-159 : politique Edge signée (délai des lots, isolement), seuil B2 non ajustable."""

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import edge_policy  # noqa: E402
import evaluate_edge_policy  # noqa: E402
import message_auth  # noqa: E402
import mqtt_edge_adapter  # noqa: E402
import telemetry  # noqa: E402
from edge_policy import PolicyError  # noqa: E402


@pytest.fixture(autouse=True)
def historical_policy():
    edge_policy.reset()
    yield
    edge_policy.reset()


def document(**changes):
    return {"version": 2, "batch_timeout_seconds": 10.0, "isolation": "report_all", **changes}


def test_default_policy_is_the_historical_behaviour():
    assert edge_policy.current.version == 0
    assert edge_policy.batch_timeout_seconds() == telemetry.ITERATION_TIMEOUT_SECONDS
    assert edge_policy.current.isolation == "isolate_once"
    assert edge_agent.DIFFERENCE_THRESHOLD == 2.50


@pytest.mark.parametrize("bad, reason", [
    (document(b2_threshold_celsius=1.0), "forbidden_field"),
    ({"version": 2, "isolation": "report_all"}, "missing_field"),
    (document(version=0), "invalid_version"),
    (document(batch_timeout_seconds=0.5), "timeout_out_of_bounds"),
    (document(batch_timeout_seconds=61), "timeout_out_of_bounds"),
    (document(batch_timeout_seconds=True), "timeout_out_of_bounds"),
    (document(isolation="never"), "invalid_isolation"),
])
def test_invalid_policies_are_refused(bad, reason):
    with pytest.raises(PolicyError) as error:
        edge_policy.parse(bad)
    assert error.value.reason == reason


@pytest.mark.parametrize("algorithm", ("ed25519", "ml-dsa-44"))
def test_signed_policy_is_applied_once(algorithm):
    cloud = message_auth.generate_private_key(algorithm)
    envelope = edge_policy.sign_policy(document(), algorithm, cloud)
    applied = edge_policy.apply(envelope, algorithm, cloud.public_key())
    assert applied == edge_policy.current
    assert edge_policy.batch_timeout_seconds() == 10.0 and edge_policy.reports_isolated_devices()
    with pytest.raises(PolicyError) as error:
        edge_policy.apply(envelope, algorithm, cloud.public_key())
    assert error.value.reason == "not_newer"


@pytest.mark.parametrize("mode", evaluate_edge_policy.MODES)
def test_distribution_scenarios(mode):
    results = evaluate_edge_policy.distribution(mode)
    assert results["legitimate"]["status"] == "applied"
    assert results["cloud_cannot_publish_threshold"] is True
    assert results["older_version"]["reason"] == "not_newer"
    assert results["out_of_bounds_timeout"]["reason"] == "timeout_out_of_bounds"
    refused = [name for name, item in results.items()
               if isinstance(item, dict) and item["status"] == "refused"]
    assert all(results[name]["unchanged"] for name in refused)
    if mode == "none":
        assert results["tampered_after_signing"]["status"] == "applied"  # comparateur non protégé
        assert results["b2_threshold_injected"]["reason"] == "forbidden_field"
    else:
        for name in ("tampered_after_signing", "b2_threshold_injected",
                     "signed_by_third_party", "unsigned"):
            assert results[name]["reason"] == "bad_signature"
    assert edge_policy.current == edge_policy.HISTORICAL


def message(device, temperature, iteration):
    return {"session_id": "s", "iteration": iteration, "src": {"agent": device},
            "payload": {"temperature": temperature, "prediction": 0}}


@pytest.mark.parametrize("isolation, expected", [("isolate_once", 1), ("report_all", 3)])
def test_isolation_policy_changes_only_the_incident_log(tmp_path, monkeypatch, isolation, expected):
    monkeypatch.setattr(edge_agent, "INCIDENT_FILE", tmp_path / "incidents.jsonl")
    monkeypatch.setattr(edge_agent, "isolated_devices_by_session", {})
    edge_policy.apply(edge_policy.sign_policy(document(isolation=isolation), "none", None), "none")
    decisions = []
    with contextlib.redirect_stdout(io.StringIO()):
        for iteration in (1, 2, 3):
            _, decision = edge_agent.analyze_devices([
                message("node-01", 25.0, iteration), message("node-02", 25.2, iteration),
                message("node-03", 29.0, iteration)])
            decisions.append(decision["node-03"]["b2_prediction"])
    incidents = [json.loads(line) for line in (tmp_path / "incidents.jsonl").read_text().splitlines()]
    assert decisions == [True, True, True]  # B2 inchangé
    assert len(incidents) == expected
    assert {i["reason"] for i in incidents} == {"SENSOR_INCONSISTENCY"}
    assert edge_agent.isolated_devices_by_session["s"] == {"node-03"}


def test_mqtt_batch_timeout_follows_the_policy(monkeypatch):
    for name in ("pending_iterations", "iteration_start_times", "completed_iterations"):
        monkeypatch.setattr(mqtt_edge_adapter, name, {})
    monkeypatch.setattr(mqtt_edge_adapter, "collection_metrics", __import__("collections").Counter())
    edge_policy.apply(edge_policy.sign_policy(document(batch_timeout_seconds=2.0), "none", None), "none")
    key = ("s", 1)
    mqtt_edge_adapter.pending_iterations[key] = {"node-01": {}}
    mqtt_edge_adapter.iteration_start_times[key] = 100.0
    with contextlib.redirect_stdout(io.StringIO()):
        mqtt_edge_adapter.expire_iteration(key, 101.9)
        assert key in mqtt_edge_adapter.pending_iterations
        mqtt_edge_adapter.expire_iteration(key, 102.0)
    assert key not in mqtt_edge_adapter.pending_iterations
    assert key in mqtt_edge_adapter.completed_iterations


def test_policy_file_is_applied_at_startup(tmp_path, monkeypatch):
    algorithm = "ml-dsa-44"
    message_auth.create_keyring(algorithm, [edge_policy.CLOUD_KEY_NAME], tmp_path)
    key = (tmp_path / f"cloud.{algorithm}.key").read_bytes()
    cloud = message_auth.load_private_key(algorithm, key)
    path = edge_policy.write_policy(tmp_path / "policy.json", document(), algorithm, cloud)
    monkeypatch.setenv("AIOT_KEY_DIR", str(tmp_path))
    monkeypatch.setenv(edge_policy.POLICY_FILE_ENV, str(path))
    monkeypatch.setenv(edge_policy.POLICY_SIGNING_ENV, algorithm)
    applied = edge_policy.apply_from_environment()
    assert applied.version == 2 and applied.isolation == "report_all"
