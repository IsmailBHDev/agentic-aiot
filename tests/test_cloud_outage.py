"""IOT-152 : perte du Cloud.

Hors réseau : le Cloud est simulé par ``cloud_store.report_incident`` derrière
une fonction d'envoi qui échoue tant qu'il est « arrêté ». On vérifie que
l'Edge continue B1, B2 et la journalisation, que le pont transmet ensuite tous
les incidents en attente, une seule fois chacun et dans l'ordre, et qu'il
reprend après son propre redémarrage grâce à son fichier d'état.
"""

import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cloud_store  # noqa: E402
import edge_agent  # noqa: E402
import edge_cloud_bridge  # noqa: E402

INTERVAL = 0.01
MAX_BACKOFF = 0.05


class FakeCloud:
    """Cloud MCP simulé : stocke via cloud_store, ou échoue s'il est arrêté."""

    def __init__(self, fail_on_calls=()):
        self.up = True
        self.calls = 0
        self.fail_on_calls = set(fail_on_calls)

    async def send(self, incident, url):
        self.calls += 1
        if not self.up or self.calls in self.fail_on_calls:
            raise ConnectionError("Cloud MCP unavailable")
        cloud_store.report_incident(incident)


def cloud_ids(cloud_file):
    if not cloud_file.exists():
        return []
    return [json.loads(line)["id"] for line in cloud_file.read_text(encoding="utf-8").splitlines()]


def edge_ids(edge_file):
    if not edge_file.exists():
        return []
    return [json.loads(line)["id"] for line in edge_file.read_text(encoding="utf-8").splitlines()]


def write_incident(edge_file, number):
    with edge_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "id": f"edge-{number}", "device_id": "node-03", "session_id": "s",
            "reason": "SENSOR_INCONSISTENCY", "temperature": 28.0, "reference": 25.0,
        }) + "\n")


async def wait_until(condition, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition not reached before timeout")
        await asyncio.sleep(INTERVAL)


async def stop(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.fixture
def files(tmp_path, monkeypatch):
    edge_file = tmp_path / "edge.jsonl"
    cloud_file = tmp_path / "cloud.jsonl"
    monkeypatch.setenv("AIOT_CLOUD_INCIDENT_FILE", str(cloud_file))
    monkeypatch.delenv("AIOT_CHANNEL_MODE", raising=False)
    monkeypatch.delenv(edge_cloud_bridge.BRIDGE_STATE_ENV, raising=False)
    monkeypatch.setattr(cloud_store, "_opener_cache", {})
    monkeypatch.setattr(edge_cloud_bridge, "edge_sealer", None)
    monkeypatch.setattr(edge_cloud_bridge, "bridge_metrics", Counter())
    monkeypatch.setattr(edge_agent, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edge_agent, "INCIDENT_FILE", edge_file)
    monkeypatch.setattr(edge_agent, "isolated_devices_by_session", {})
    return edge_file, cloud_file, tmp_path


def watch(edge_file, state_file=None):
    return asyncio.create_task(edge_cloud_bridge.watch_incidents(
        edge_file, "http://cloud.invalid/mcp", interval=INTERVAL,
        state_file=state_file, max_backoff=MAX_BACKOFF,
    ))


def reference_groups():
    groups = defaultdict(list)
    path = ROOT / "results" / "collaborative_b2_predictions.csv"
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            groups[row["session_id"], int(row["iteration"])].append(row)
    return groups


def test_edge_keeps_detecting_during_cloud_outage_and_delivers_backlog(files, monkeypatch):
    edge_file, cloud_file, _ = files
    cloud = FakeCloud()
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", cloud.send)

    async def scenario():
        bridge = watch(edge_file)
        try:
            await asyncio.sleep(INTERVAL)
            cloud.up = False

            # Rejeu des 600 observations de référence pendant la panne : B1 et B2
            # continuent à l'Edge, qui journalise ses incidents localement.
            checked = 0
            for (session, iteration), rows in reference_groups().items():
                messages = [{
                    "type": "anomaly_alert" if int(row["b1_prediction"]) else "telemetry",
                    "src": {"agent": row["device_id"]},
                    "session_id": session, "iteration": iteration,
                    "payload": {
                        "temperature": float(row["temperature"]),
                        "prediction": int(row["b1_prediction"]),
                        "vibration": 0.3, "inference_ms": 0.5,
                    },
                } for row in rows]
                for message in messages:
                    edge_agent.process_message(message)
                reference, decisions = edge_agent.analyze_devices(messages)
                for row in rows:
                    assert reference == float(row["group_median"])
                    assert decisions[row["device_id"]]["b2_prediction"] == int(row["b2_prediction"])
                    checked += 1
            assert checked == 600

            await wait_until(lambda: edge_cloud_bridge.bridge_metrics["send_failures"] >= 3)
            assert cloud_ids(cloud_file) == []
            produced = edge_ids(edge_file)
            assert produced

            cloud.up = True
            await wait_until(lambda: len(cloud_ids(cloud_file)) == len(produced))
            await asyncio.sleep(5 * INTERVAL)
            return produced
        finally:
            await stop(bridge)

    produced = asyncio.run(scenario())

    assert cloud_ids(cloud_file) == produced  # tous, une seule fois, dans l'ordre
    assert edge_cloud_bridge.bridge_metrics["recoveries"] >= 1
    assert edge_cloud_bridge.bridge_metrics["incidents_sent"] == len(produced)


def test_failure_in_the_middle_of_a_batch_does_not_resend_delivered_incidents(files, monkeypatch):
    edge_file, cloud_file, _ = files
    cloud = FakeCloud(fail_on_calls={3})
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", cloud.send)

    async def scenario():
        bridge = watch(edge_file)
        try:
            await asyncio.sleep(INTERVAL)
            for number in range(1, 6):
                write_incident(edge_file, number)
            await wait_until(lambda: len(cloud_ids(cloud_file)) == 5)
            await asyncio.sleep(5 * INTERVAL)
        finally:
            await stop(bridge)

    asyncio.run(scenario())

    assert cloud_ids(cloud_file) == [f"edge-{n}" for n in range(1, 6)]
    assert edge_cloud_bridge.bridge_metrics["send_failures"] == 1


def test_bridge_restart_resumes_from_state_file(files, monkeypatch):
    edge_file, cloud_file, tmp_path = files
    state_file = tmp_path / "bridge-state.json"
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", FakeCloud().send)

    async def scenario():
        bridge = watch(edge_file, state_file)
        await asyncio.sleep(INTERVAL)
        write_incident(edge_file, 1)
        write_incident(edge_file, 2)
        await wait_until(lambda: len(cloud_ids(cloud_file)) == 2)
        await stop(bridge)

        # L'Edge continue pendant que le pont est arrêté.
        for number in (3, 4, 5):
            write_incident(edge_file, number)

        bridge = watch(edge_file, state_file)
        try:
            await wait_until(lambda: len(cloud_ids(cloud_file)) == 5)
            await asyncio.sleep(5 * INTERVAL)
        finally:
            await stop(bridge)

    asyncio.run(scenario())

    assert cloud_ids(cloud_file) == [f"edge-{n}" for n in range(1, 6)]


def test_without_state_file_restart_keeps_historical_start_at_end_of_log(files, monkeypatch):
    """Comportement historique documenté : sans fichier d'état, le pont repart
    de la fin du journal et ne transmet pas ce qui a été écrit pendant son arrêt."""
    edge_file, cloud_file, _ = files
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", FakeCloud().send)
    write_incident(edge_file, 1)

    async def scenario():
        bridge = watch(edge_file)
        try:
            await asyncio.sleep(5 * INTERVAL)
            write_incident(edge_file, 2)
            await wait_until(lambda: len(cloud_ids(cloud_file)) == 1)
        finally:
            await stop(bridge)

    asyncio.run(scenario())

    assert cloud_ids(cloud_file) == ["edge-2"]


def test_invalid_and_partial_lines(files, monkeypatch):
    edge_file, cloud_file, _ = files
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", FakeCloud().send)

    async def scenario():
        bridge = watch(edge_file)
        try:
            await asyncio.sleep(INTERVAL)
            with edge_file.open("a", encoding="utf-8") as stream:
                stream.write("{pas du json}\n")
                stream.write('{"id": "edge-partial", "device_id": "node-01", "reason": "LOCAL_ML_ANOMALY"')
            await asyncio.sleep(10 * INTERVAL)
            assert cloud_ids(cloud_file) == []  # ligne incomplète : attendue
            with edge_file.open("a", encoding="utf-8") as stream:
                stream.write("}\n")
            await wait_until(lambda: len(cloud_ids(cloud_file)) == 1)
        finally:
            await stop(bridge)

    asyncio.run(scenario())

    assert cloud_ids(cloud_file) == ["edge-partial"]
    assert edge_cloud_bridge.bridge_metrics["incidents_invalid"] == 1


def test_backoff_is_bounded(files, monkeypatch):
    edge_file, _, _ = files
    cloud = FakeCloud()
    cloud.up = False
    monkeypatch.setattr(edge_cloud_bridge, "send_mcp", cloud.send)
    delays = []
    real_sleep = asyncio.sleep

    async def recording_sleep(seconds):
        delays.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(edge_cloud_bridge.asyncio, "sleep", recording_sleep)

    async def scenario():
        write_incident(edge_file, 0)
        bridge = asyncio.create_task(edge_cloud_bridge.watch_incidents(
            edge_file, "http://cloud.invalid/mcp", interval=INTERVAL,
            max_backoff=MAX_BACKOFF,
        ))
        await real_sleep(0)
        write_incident(edge_file, 1)
        while len(delays) < 8:
            await real_sleep(0)
        await stop(bridge)

    asyncio.run(scenario())

    assert delays[0] == INTERVAL
    assert max(delays) == MAX_BACKOFF
    assert delays == sorted(delays)
