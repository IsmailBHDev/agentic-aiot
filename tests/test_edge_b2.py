import csv
import json
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent


def measurement(device, temperature, prediction=0, session="session-1", iteration=1):
    return {
        "type": "anomaly_alert" if prediction else "telemetry",
        "src": {"agent": device},
        "session_id": session,
        "iteration": iteration,
        "payload": {
            "temperature": temperature,
            "prediction": prediction,
            "vibration": 0.3,
            "inference_ms": 0.5,
        },
    }


@pytest.fixture
def incident_log(monkeypatch, tmp_path):
    path = tmp_path / "incidents.jsonl"
    monkeypatch.setattr(edge_agent, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edge_agent, "INCIDENT_FILE", path)
    monkeypatch.setattr(edge_agent, "isolated_devices_by_session", {})
    return path


def test_calculate_b2_strict_threshold_and_no_side_effects(incident_log):
    messages = [
        measurement("node-01", 22.49),
        measurement("node-02", 25.0, prediction=1),
        measurement("node-03", 27.50),
    ]
    original = deepcopy(messages)

    reference, decisions = edge_agent.calculate_b2(messages)

    assert reference == 25.0
    assert decisions["node-01"]["signed_deviation"] == pytest.approx(-2.51)
    assert decisions["node-03"]["signed_deviation"] == 2.50
    assert decisions["node-01"]["deviation"] == pytest.approx(2.51)
    assert all(decision["reference"] == reference for decision in decisions.values())
    assert decisions["node-02"]["b1_prediction"] == 1
    assert [decision["collaborative_alert"] for decision in decisions.values()] == [
        True, False, False
    ]
    assert [decision["b2_prediction"] for decision in decisions.values()] == [
        True, True, False
    ]
    assert messages == original
    assert edge_agent.isolated_devices_by_session == {}
    assert not incident_log.exists()


@pytest.mark.parametrize("temperature", [22.4999, 27.5001])
def test_calculate_b2_combines_local_and_collaborative_signals(temperature):
    messages = [
        measurement("node-01", 25.0),
        measurement("node-02", 25.0),
        measurement("node-03", temperature, prediction=1),
    ]

    _, decisions = edge_agent.calculate_b2(messages)

    assert len(decisions) == 3
    assert decisions["node-03"]["b1_prediction"] == 1
    assert decisions["node-03"]["collaborative_alert"] is True
    assert decisions["node-03"]["b2_prediction"] is True


@pytest.mark.parametrize("change", ["missing", "device", "session", "iteration"])
def test_calculate_b2_rejects_invalid_groups(change):
    messages = [measurement(f"node-0{index}", 25.0) for index in range(1, 4)]
    if change == "missing":
        messages.pop()
    elif change == "device":
        messages[2]["src"]["agent"] = messages[0]["src"]["agent"]
    elif change == "session":
        messages[2]["session_id"] = "session-2"
    else:
        messages[2]["iteration"] = 2

    with pytest.raises(ValueError):
        edge_agent.calculate_b2(messages)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", " "),
        ("iteration", True),
        ("iteration", -1),
        ("agent", ""),
        ("temperature", float("nan")),
        ("temperature", float("inf")),
        ("temperature", "25.0"),
        ("prediction", 2),
        ("prediction", True),
    ],
)
def test_calculate_b2_rejects_invalid_values(field, value):
    messages = [measurement(f"node-0{index}", 25.0) for index in range(1, 4)]
    message = messages[0]
    if field == "agent":
        message["src"][field] = value
    elif field in message["payload"]:
        message["payload"][field] = value
    else:
        message[field] = value

    with pytest.raises(ValueError):
        edge_agent.calculate_b2(messages)


def test_calculate_b2_rejects_missing_prediction():
    messages = [measurement(f"node-0{index}", 25.0) for index in range(1, 4)]
    del messages[0]["payload"]["prediction"]

    with pytest.raises(ValueError):
        edge_agent.calculate_b2(messages)


def test_edge_preserves_incidents_and_continues_b2_after_isolation(incident_log):
    messages = [
        measurement("node-01", 25.0, prediction=1),
        measurement("node-02", 25.0),
        measurement("node-03", 28.0),
    ]
    edge_agent.process_message(messages[0])
    assert edge_agent.analyze_devices(messages[:1]) is None
    local = json.loads(incident_log.read_text(encoding="utf-8"))
    assert local["reason"] == "LOCAL_ML_ANOMALY"
    assert local["action"] == "SAFE_MODE_REPORTED"
    assert local["reference"] is None

    edge_agent.analyze_devices(messages)
    next_iteration = [dict(message, iteration=2) for message in messages]
    next_iteration[2]["payload"] = dict(messages[2]["payload"], prediction=1)
    reference, decisions = edge_agent.analyze_devices(next_iteration)

    assert reference == 25.0
    assert decisions["node-03"]["collaborative_alert"] is True
    assert decisions["node-03"]["b2_prediction"] is True
    assert edge_agent.isolated_devices_by_session == {"session-1": {"node-03"}}
    incidents = [
        json.loads(line) for line in incident_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(incidents) == 2
    collaborative = incidents[1]
    assert set(collaborative) == set(local)
    assert collaborative["reason"] == "SENSOR_INCONSISTENCY"
    assert collaborative["action"] == "ISOLATE"
    assert collaborative["reference"] == 25.0
    assert collaborative["temperature"] == 28.0
    assert collaborative["device_id"] == "node-03"
    assert collaborative["session_id"] == "session-1"


def test_edge_b2_matches_reference_predictions(incident_log):
    groups = defaultdict(list)
    path = ROOT / "results" / "collaborative_b2_predictions.csv"
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            groups[row["session_id"], int(row["iteration"])].append(row)

    assert sum(map(len, groups.values())) == 600
    for (session, iteration), rows in groups.items():
        messages = [
            measurement(
                row["device_id"], float(row["temperature"]),
                int(row["b1_prediction"]), session, iteration,
            )
            for row in rows
        ]
        reference, decisions = edge_agent.analyze_devices(messages)
        for row in rows:
            decision = decisions[row["device_id"]]
            assert reference == float(row["group_median"])
            assert decision["collaborative_alert"] == int(row["collaborative_alert"])
            assert decision["b2_prediction"] == int(row["b2_prediction"])
