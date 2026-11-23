"""Cloud incident store, independent of networking frameworks."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'cloud_incidents.jsonl'


def storage_path():
    return Path(os.environ.get('AIOT_CLOUD_INCIDENT_FILE', str(DEFAULT_PATH)))


def report_incident(incident: dict) -> dict:
    if not isinstance(incident, dict):
        raise ValueError('incident must be a JSON object')
    if not isinstance(incident.get('device_id'), str) or not incident['device_id'].strip():
        raise ValueError('device_id is required')
    if not isinstance(incident.get('reason'), str) or not incident['reason'].strip():
        raise ValueError('reason is required')
    record = dict(incident)
    record['cloud_incident_id'] = str(uuid.uuid4())
    record['cloud_received_at'] = datetime.now(timezone.utc).isoformat()
    path = storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    return {'status': 'accepted', 'incident_id': record['cloud_incident_id']}


def list_incidents(limit: int = 10) -> list[dict]:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit must be an integer between 1 and 100')
    path = storage_path()
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as stream:
        lines = stream.readlines()
    return [json.loads(line) for line in lines[-limit:] if line.strip()][::-1]


def request_model_update(device_id: str) -> dict:
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError('device_id is required')
    return {'status': 'acknowledged', 'device_id': device_id, 'note': 'MVP acknowledgement only; no OTA performed'}
