import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cloud_orchestrator
from cloud_a2a_server import analyze_incident
from cloud_store import report_incident


def test_orchestrator_retries_failures_after_poll_and_skips_saved_ids(
    tmp_path, monkeypatch
):
    cloud = tmp_path / "cloud.jsonl"
    decisions = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("AIOT_CLOUD_INCIDENT_FILE", str(cloud))
    monkeypatch.setattr(cloud_orchestrator, "INCIDENTS_FILE", cloud)
    monkeypatch.setattr(cloud_orchestrator, "DECISIONS_FILE", decisions)

    edge_incident = {
        "id": "edge-1", "device_id": "node-03", "session_id": "s1",
        "iteration": 1, "reason": "SENSOR_INCONSISTENCY",
    }
    first_id = report_incident(edge_incident)["incident_id"]
    second_id = report_incident(edge_incident)["incident_id"]
    assert first_id != second_id
    first_row = cloud.read_text(encoding="utf-8").splitlines()[0]
    with cloud.open("a", encoding="utf-8") as stream:
        stream.write(first_row + "\n")

    calls = []
    outage = True

    def send(incident):
        cloud_id = incident["cloud_incident_id"]
        calls.append(cloud_id)
        if outage and cloud_id == first_id:
            raise httpx.ConnectError("A2A unavailable")
        analysis = analyze_incident(incident)
        if outage:
            analysis["cloud_incident_id"] = "unrelated-cloud-id"
        return {"result": {
            "id": "task-" + cloud_id,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": json.dumps(analysis)}]}],
        }}

    monkeypatch.setattr(cloud_orchestrator, "send_to_a2a", send)
    assert cloud_orchestrator.process_pending_incidents() == 0
    assert not decisions.exists()

    outage = False
    calls.clear()
    assert cloud_orchestrator.process_pending_incidents() == 2
    assert calls == [first_id, second_id]

    calls.clear()
    assert cloud_orchestrator.process_pending_incidents() == 0
    assert calls == []
    records = [json.loads(line) for line in decisions.read_text(encoding="utf-8").splitlines()]
    assert [record["cloud_incident_id"] for record in records] == [first_id, second_id]
    assert {record["incident_id"] for record in records} == {"edge-1"}
