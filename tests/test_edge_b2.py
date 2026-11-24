import asyncio
import csv
import json
import os
import socket
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiocoap import Code, Context, Message, resource

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent
import mqtt_edge_adapter
from coap_server import AlertResource, TelemetryResource
from mqtt_bus import LocalBus, PahoBus


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


@pytest.mark.parametrize(
    ("temperature", "expected_alert"),
    [
        (22.4999, True),
        (22.50, False),
        (22.5001, False),
        (27.4999, False),
        (27.50, False),
        (27.5001, True),
    ],
)
def test_calculate_b2_collaborative_threshold_in_both_directions(
    temperature, expected_alert
):
    messages = [
        measurement("node-01", 25.0),
        measurement("node-02", 25.0),
        measurement("node-03", temperature),
    ]

    reference, decisions = edge_agent.calculate_b2(messages)

    assert reference == 25.0
    assert decisions["node-03"]["collaborative_alert"] is expected_alert
    assert decisions["node-03"]["b2_prediction"] is expected_alert


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
    assert local["iteration"] == 1

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
    assert collaborative["iteration"] == 1


def test_save_incident_preserves_legacy_format_without_iteration(incident_log):
    edge_agent.save_incident("node-01", 28.0, None, "COAP_UNKNOWN", "coap-session")

    incident = json.loads(incident_log.read_text(encoding="utf-8"))
    assert set(incident) == {
        "id", "timestamp", "session_id", "device_id", "temperature",
        "reference", "reason", "action",
    }
    assert incident["reason"] == "COAP_UNKNOWN"
    assert incident["action"] == "SAFE_MODE_REPORTED"
    assert datetime.fromisoformat(incident["timestamp"]).tzinfo == timezone.utc


def test_mqtt_records_local_alert_before_the_batch_is_complete(
    incident_log, monkeypatch
):
    for name in (
        "pending_iterations", "iteration_start_times",
        "processed_message_ids", "completed_iterations",
    ):
        monkeypatch.setattr(mqtt_edge_adapter, name, {})

    message = measurement("node-01", 28.0, prediction=1)
    message["id"] = "local-alert"
    message["ts"] = datetime.now(timezone.utc).isoformat()
    asyncio.run(
        mqtt_edge_adapter.on_message(
            "aiot/telemetry/node-01", json.dumps(message).encode("utf-8")
        )
    )

    key = ("session-1", 1)
    assert mqtt_edge_adapter.pending_iterations == {key: {"node-01": message}}
    assert key not in mqtt_edge_adapter.completed_iterations
    incident = json.loads(incident_log.read_text(encoding="utf-8"))
    assert incident["reason"] == "LOCAL_ML_ANOMALY"
    assert incident["device_id"] == "node-01"
    assert incident["session_id"] == "session-1"
    assert incident["reference"] is None
    assert edge_agent.isolated_devices_by_session == {"session-1": set()}


def test_mqtt_expires_incomplete_batch_and_retains_local_alert(
    incident_log, monkeypatch
):
    for name in (
        "pending_iterations", "iteration_start_times",
        "processed_message_ids", "completed_iterations",
    ):
        monkeypatch.setattr(mqtt_edge_adapter, name, {})

    async def send(device_id, prediction):
        message = measurement(device_id, 28.0, prediction=prediction)
        message["id"] = device_id
        message["ts"] = datetime.now(timezone.utc).isoformat()
        await mqtt_edge_adapter.on_message(
            f"aiot/telemetry/{device_id}", json.dumps(message).encode("utf-8")
        )

    key = ("session-1", 1)

    async def run():
        await send("node-01", prediction=1)
        mqtt_edge_adapter.iteration_start_times[key] -= (
            mqtt_edge_adapter.ITERATION_TIMEOUT_SECONDS
        )

        sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])
        with monkeypatch.context() as patch:
            patch.setattr(mqtt_edge_adapter.asyncio, "sleep", sleep)
            with pytest.raises(asyncio.CancelledError):
                await mqtt_edge_adapter.monitor_timeouts()
        assert sleep.await_count == 3

        await send("node-02", prediction=0)
        await send("node-03", prediction=0)

    asyncio.run(run())

    assert key not in mqtt_edge_adapter.pending_iterations
    assert key not in mqtt_edge_adapter.iteration_start_times
    assert isinstance(mqtt_edge_adapter.completed_iterations[key], float)
    incident = json.loads(incident_log.read_text(encoding="utf-8"))
    assert incident["reason"] == "LOCAL_ML_ANOMALY"
    assert incident["iteration"] == 1


@pytest.mark.parametrize("transport", ["mqtt", "coap", "mqtt-network", "coap-network"])
def test_transport_retries_interleaving_and_expiration(transport, incident_log, monkeypatch):
    network = transport.endswith("-network")
    if network and os.getenv("AIOT_TEST_NETWORK") != "1":
        pytest.skip("Set AIOT_TEST_NETWORK=1 to exercise local network transports")
    coap = transport.startswith("coap")
    clock = SimpleNamespace(now=100.0)
    collector = TelemetryResource()
    monotonic_clock = SimpleNamespace(monotonic=lambda: clock.now)
    monkeypatch.setattr("coap_server.time", monotonic_clock)
    monkeypatch.setattr(mqtt_edge_adapter, "time", monotonic_clock)
    monkeypatch.setattr(mqtt_edge_adapter, "collection_metrics", Counter())
    for name in (
        "pending_iterations", "iteration_start_times",
        "processed_message_ids", "completed_iterations",
    ):
        monkeypatch.setattr(mqtt_edge_adapter, name, {})
    analyzed = []

    def analyze(messages):
        first = messages[0]
        analyzed.append((first["session_id"], first["iteration"]))
        return edge_agent.analyze_devices(messages)

    monkeypatch.setattr("coap_server.analyze_devices", analyze)
    monkeypatch.setattr(mqtt_edge_adapter, "analyze_devices", analyze)

    async def run():
        test_id = uuid4().hex[:12]
        bus = PahoBus("127.0.0.1", client_id=f"aiot-test-{test_id}") if network and not coap else LocalBus()
        topic_prefix = f"aiot-test/{test_id}/telemetry"
        delivered = asyncio.Event()
        server = None
        client = None
        uri = None

        async def on_message(topic, payload):
            try:
                await mqtt_edge_adapter.on_message(topic, payload)
            finally:
                delivered.set()

        if coap and network:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            site = resource.Site()
            site.add_resource(["telemetry"], collector)
            server = await Context.create_server_context(site, bind=("127.0.0.1", port))
            uri = f"coap://127.0.0.1:{port}/telemetry"
        if not coap:
            await bus.start()
            await bus.subscribe(f"{topic_prefix}/+", on_message, qos=1)
        try:
            if server is not None:
                client = await Context.create_client_context()
            await replay(bus, delivered, topic_prefix, client, uri)
        finally:
            await bus.close()
            if client is not None:
                await client.shutdown()
            if server is not None:
                await server.shutdown()

    async def replay(bus, delivered, topic_prefix, client, uri):
        async def send(session, iteration, device, temperature=25.0, prediction=0):
            message = measurement(device, temperature, prediction, session, iteration)
            message["id"] = f"{session}/{iteration}/{device}"
            message["ts"] = datetime.now(timezone.utc).isoformat()
            payload = json.dumps(message).encode("utf-8")
            if coap:
                request = Message(code=Code.POST, payload=payload, uri=uri)
                if client is None:
                    response = await collector.render_post(request)
                else:
                    response = await asyncio.wait_for(client.request(request).response, timeout=3)
                expected = Code.BAD_REQUEST if isinstance(temperature, str) else Code.CHANGED
                assert response.code == expected
            else:
                delivered.clear()
                await bus.publish(f"{topic_prefix}/{device}", payload, qos=1)
                await asyncio.wait_for(delivered.wait(), timeout=3)

        await send("alpha", 1, "node-03", temperature="invalid")
        await send("alpha", 1, "node-03", temperature=28.0)
        await send("beta", 1, "node-02")
        await send("alpha", 1, "node-03", temperature=28.0)
        await send("alpha", 1, "node-01")
        await send("beta", 1, "node-03")
        clock.now += 1.0
        await send("alpha", 1, "node-02")
        await send("beta", 1, "node-01")

        for device in ("node-02", "node-03", "node-01"):
            await send("alpha", 1, device)
            await send("alpha", 2, device)

        await send("alpha", 3, "node-01", prediction=1)
        # Simulate two missing observations at the collection deadline.
        clock.now += 5.0
        await send("alpha", 3, "node-02")
        await send("alpha", 3, "node-03")

    asyncio.run(run())

    assert analyzed == [("alpha", 1), ("beta", 1), ("alpha", 2)]
    assert edge_agent.isolated_devices_by_session["alpha"] == {"node-03"}
    incidents = [
        json.loads(line) for line in incident_log.read_text(encoding="utf-8").splitlines()
    ]
    assert [(incident["iteration"], incident["reason"]) for incident in incidents] == [
        (1, "SENSOR_INCONSISTENCY"),
        (3, "LOCAL_ML_ANOMALY"),
    ]
    metrics = (
        collector.collection_metrics if coap
        else mqtt_edge_adapter.collection_metrics
    )
    assert metrics == {
        "messages_received": 17,
        "messages_invalid": 1,
        "messages_duplicate": 4,
        "messages_closed_batch": 2,
        "batches_completed": 3,
        "batches_expired": 1,
        "observations_missing_at_timeout": 2,
        "batch_assembly_seconds_total": 2.0,
    }


def test_coap_alert_is_independent_of_telemetry(incident_log):
    message = {
        "type": "anomaly_alert",
        "src": {"agent": "node-01"},
        "payload": {"temperature": 28.0, "anomaly_type": "local"},
    }
    request = Message(code=Code.POST, payload=json.dumps(message).encode("utf-8"))

    response = asyncio.run(AlertResource().render_post(request))

    assert response.code == Code.CHANGED
    incident = json.loads(incident_log.read_text(encoding="utf-8"))
    assert incident["reason"] == "COAP_LOCAL"
    assert incident["device_id"] == "node-01"
    assert incident["reference"] is None


def test_edge_dual_signal_produces_one_prediction_and_two_incidents(incident_log):
    messages = [
        measurement("node-01", 25.0),
        measurement("node-02", 25.0),
        measurement("node-03", 28.0, prediction=1),
    ]
    for message in messages:
        edge_agent.process_message(message)

    local = json.loads(incident_log.read_text(encoding="utf-8"))
    assert local["reason"] == "LOCAL_ML_ANOMALY"
    assert local["action"] == "SAFE_MODE_REPORTED"
    assert edge_agent.isolated_devices_by_session == {"session-1": set()}

    _, decisions = edge_agent.analyze_devices(messages)

    assert decisions["node-03"]["b1_prediction"] == 1
    assert decisions["node-03"]["collaborative_alert"] is True
    assert [
        device_id for device_id, decision in decisions.items()
        if decision["b2_prediction"]
    ] == ["node-03"]

    incidents = [
        json.loads(line) for line in incident_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(incidents) == 2
    assert incidents[0] == local
    collaborative = incidents[1]
    assert collaborative["reason"] == "SENSOR_INCONSISTENCY"
    assert collaborative["action"] == "ISOLATE"
    assert collaborative["id"] != local["id"]
    for field in ("device_id", "session_id", "iteration", "temperature"):
        assert collaborative[field] == local[field]
    assert edge_agent.isolated_devices_by_session == {"session-1": {"node-03"}}


def test_isolated_sensor_can_supply_the_next_group_median(incident_log):
    first_group = [
        measurement("node-01", 25.0),
        measurement("node-02", 25.0),
        measurement("node-03", 28.0),
    ]
    edge_agent.analyze_devices(first_group)
    assert edge_agent.isolated_devices_by_session == {"session-1": {"node-03"}}

    second_group = [
        measurement("node-01", 22.0, iteration=2),
        measurement("node-02", 26.0, iteration=2),
        measurement("node-03", 25.0, iteration=2),
    ]
    reference, decisions = edge_agent.analyze_devices(second_group)

    assert reference == 25.0
    assert decisions["node-03"]["deviation"] == 0.0
    assert decisions["node-01"]["b2_prediction"] is True
    assert decisions["node-02"]["b2_prediction"] is False
    assert edge_agent.isolated_devices_by_session == {
        "session-1": {"node-01", "node-03"}
    }
    incidents = [
        json.loads(line) for line in incident_log.read_text(encoding="utf-8").splitlines()
    ]
    assert [incident["device_id"] for incident in incidents] == ["node-03", "node-01"]
    assert incidents[1]["reference"] == reference


def test_normal_batch_does_not_create_incidents_or_isolate(incident_log):
    messages = [
        measurement("node-01", 24.0),
        measurement("node-02", 25.0),
        measurement("node-03", 26.0),
    ]
    for message in messages:
        edge_agent.process_message(message)

    reference, decisions = edge_agent.analyze_devices(messages)

    assert reference == 25.0
    assert all(not decision["b2_prediction"] for decision in decisions.values())
    assert edge_agent.isolated_devices_by_session == {"session-1": set()}
    assert not incident_log.exists()


def test_isolation_is_independent_for_batches_in_distinct_sessions(incident_log):
    for session in ("session-1", "session-2"):
        messages = [
            measurement("node-01", 25.0, session=session),
            measurement("node-02", 25.0, session=session),
            measurement("node-03", 28.0, session=session),
        ]
        _, decisions = edge_agent.analyze_devices(messages)
        assert decisions["node-03"]["b2_prediction"] is True

    assert edge_agent.isolated_devices_by_session == {
        "session-1": {"node-03"},
        "session-2": {"node-03"},
    }
    incidents = [
        json.loads(line) for line in incident_log.read_text(encoding="utf-8").splitlines()
    ]
    assert [incident["session_id"] for incident in incidents] == ["session-1", "session-2"]
    assert all(incident["device_id"] == "node-03" for incident in incidents)


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
