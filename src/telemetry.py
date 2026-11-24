"""Validation commune des mesures reçues par les transports Edge."""

from datetime import datetime, timezone
from math import isfinite

EXPECTED_DEVICES = {"node-01", "node-02", "node-03"}
ITERATION_TIMEOUT_SECONDS = 5
MAX_MESSAGE_AGE_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 5
MESSAGE_RETENTION_SECONDS = MAX_MESSAGE_AGE_SECONDS + MAX_CLOCK_SKEW_SECONDS
CLEANUP_INTERVAL_SECONDS = 30


def is_message_fresh(message):
    timestamp = message.get("ts")
    if not isinstance(timestamp, str):
        return False
    try:
        message_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if message_time.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - message_time).total_seconds()
    return -MAX_CLOCK_SKEW_SECONDS <= age <= MAX_MESSAGE_AGE_SECONDS


def validate_telemetry(message):
    """Valide une mesure et renvoie sa clé de lot, son capteur et son ID."""
    session_id = message["session_id"]
    iteration = message["iteration"]
    device_id = message["src"]["agent"]
    message_id = message["id"]
    payload = message["payload"]

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Invalid session ID")
    if type(iteration) is not int or iteration < 0:
        raise ValueError("Invalid iteration")
    if device_id not in EXPECTED_DEVICES:
        raise ValueError("Invalid device")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("Invalid message ID")
    if message["type"] not in ("telemetry", "anomaly_alert"):
        raise ValueError("Invalid message type")

    for field in ("temperature", "vibration", "inference_ms"):
        value = payload[field]
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"Invalid {field}")
    prediction = payload["prediction"]
    if type(prediction) is not int or prediction not in (0, 1):
        raise ValueError("Invalid prediction")

    return (session_id, iteration), device_id, message_id
