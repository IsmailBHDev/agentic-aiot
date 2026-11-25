
import asyncio
import json
import time
from collections import Counter

from aiocoap import resource, Message, Code, Context
import edge_policy
from message_auth import AuthError, verifier_from_env
from edge_agent import (
    process_message,
    analyze_devices,
    save_incident
)
from telemetry import (
    CLEANUP_INTERVAL_SECONDS,
    EXPECTED_DEVICES,
    MESSAGE_RETENTION_SECONDS,
    is_message_fresh,
    validate_telemetry,
)

HOST = "127.0.0.1"
PORT = 5683

class HealthResource(resource.Resource):

    async def render_get(self, request):
        return Message(
            code=Code.CONTENT,
            payload=json.dumps({
                "status": "ok",
                "agent": "edge-coordinator"
            }).encode("utf-8")
        )
_FROM_ENV = object()


class TelemetryResource(resource.Resource):

    def __init__(self, verifier=_FROM_ENV):
        super().__init__()
        # IOT-174 : None en C0 (sans authentification)
        self.verifier = (
            verifier_from_env(EXPECTED_DEVICES) if verifier is _FROM_ENV else verifier
        )
        self.pending = {}
        self.closed = {}
        self.seen_ids = {}
        self.collection_metrics = Counter()

    def expire_batch(self, key, now):
        started, batch = self.pending[key]
        # IOT-159 : délai fixé par la politique Edge (5 s par défaut)
        if now - started >= edge_policy.batch_timeout_seconds():
            del self.pending[key]
            self.closed[key] = now
            missing_devices = EXPECTED_DEVICES - batch.keys()
            self.collection_metrics["batches_expired"] += 1
            self.collection_metrics["observations_missing_at_timeout"] += len(missing_devices)
            print(f"COAP EDGE : TIMEOUT {key}, capteurs manquants : "
                  f"{sorted(missing_devices)}")

    async def monitor_timeouts(self):
        next_cleanup = time.monotonic() + CLEANUP_INTERVAL_SECONDS
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for key in list(self.pending):
                self.expire_batch(key, now)
            if now < next_cleanup:
                continue
            for records in (self.closed, self.seen_ids):
                for key, timestamp in list(records.items()):
                    if now - timestamp >= MESSAGE_RETENTION_SECONDS:
                        del records[key]
            print(f"COAP EDGE : Collecte {dict(self.collection_metrics)}")
            next_cleanup = now + CLEANUP_INTERVAL_SECONDS

    async def render_post(self, request):
        self.collection_metrics["messages_received"] += 1
        try:
            message = json.loads(
                request.payload.decode("utf-8")
            )

            key, device_id, message_id = validate_telemetry(message)
            if not is_message_fresh(message):
                raise ValueError("Stale or invalid timestamp")

            now = time.monotonic()
            if key in self.pending:
                self.expire_batch(key, now)
            started, batch = self.pending.get(key, (now, {}))
            if message_id in self.seen_ids or device_id in batch:
                self.collection_metrics["messages_duplicate"] += 1
                return Message(code=Code.CHANGED, payload=b"Telemetry already handled")
            if key in self.closed:
                self.collection_metrics["messages_closed_batch"] += 1
                return Message(code=Code.CHANGED, payload=b"Telemetry already handled")

            if self.verifier is not None:
                self.verifier.verify(message)

            process_message(message)
            self.seen_ids[message_id] = now
            batch[device_id] = message
            self.pending[key] = (started, batch)
            if batch.keys() == EXPECTED_DEVICES:
                analyze_devices(list(batch.values()))
                self.collection_metrics["batches_completed"] += 1
                self.collection_metrics["batch_assembly_seconds_total"] += now - started
                self.closed[key] = now
                del self.pending[key]

            return Message(
                code=Code.CHANGED,
                payload=b"Telemetry processed"
            )

        except AuthError as error:
            self.collection_metrics["messages_auth_rejected"] += 1
            self.collection_metrics[f"auth_rejected_{error.reason}"] += 1
            return Message(
                code=Code.UNAUTHORIZED,
                payload=b"Unauthenticated telemetry"
            )

        except (ValueError, KeyError, TypeError, OverflowError):
            self.collection_metrics["messages_invalid"] += 1
            return Message(
                code=Code.BAD_REQUEST,
                payload=b"Invalid telemetry message"
            )
class AlertResource(resource.Resource):

    def __init__(self, verifier=_FROM_ENV):
        super().__init__()
        # IOT-174 : une alerte locale doit aussi prouver son origine
        self.verifier = (
            verifier_from_env(EXPECTED_DEVICES) if verifier is _FROM_ENV else verifier
        )

    async def render_post(self, request):
        try:
            message = json.loads(
                request.payload.decode("utf-8")
            )

            if message.get("type") != "anomaly_alert":
                return Message(
                    code=Code.BAD_REQUEST,
                    payload=b"Invalid alert type"
                )

            source = message.get("src", {})
            device_id = source.get("agent")

            if device_id not in {
                "node-01", "node-02", "node-03"
            }:
                return Message(
                    code=Code.BAD_REQUEST,
                    payload=b"Invalid device"
                )

            if self.verifier is not None:
                try:
                    self.verifier.verify(message)
                except AuthError:
                    return Message(
                        code=Code.UNAUTHORIZED,
                        payload=b"Unauthenticated alert"
                    )

            print(
                f"COAP ALERT : Alerte recue de {device_id}"
            )
            print(
                json.dumps(message, indent=2)
            )
            payload = message.get("payload", {})

            if not isinstance(payload, dict):
                return Message(
                    code=Code.BAD_REQUEST,
                    payload=b"Invalid alert payload"
                )

            temperature = payload.get("temperature")
            anomaly_type = payload.get("anomaly_type", "unknown")

            session_id = message.get(
                "session_id",
                "coap-session"
            )

            save_incident(
                device_id=device_id,
                temperature=temperature,
                reference=None,
                reason="COAP_" + str(anomaly_type).upper(),
                session_id=session_id
            )
            return Message(
                code=Code.CHANGED,
                payload=b"Alert received"
            )

        except (ValueError, TypeError, AttributeError):
            return Message(
                code=Code.BAD_REQUEST,
                payload=b"Invalid JSON"
            )

async def main():

    root = resource.Site()
    telemetry = TelemetryResource()
    root.add_resource(
        ["alert"],
        AlertResource()
    )
    root.add_resource(
        ["health"],
        HealthResource()
    )
    root.add_resource(
        ["telemetry"],
        telemetry
    )

    protocol = await Context.create_server_context(
        root,
        bind=(HOST, PORT)
    )

    policy = edge_policy.apply_from_environment()
    print(
        f"COAP EDGE : politique v{policy.version}, timeout "
        f"{policy.batch_timeout_seconds} s, isolement {policy.isolation}"
    )
    print(
        f"COAP EDGE : Serveur demarre sur "
        f"coap://{HOST}:{PORT}/telemetry"
    )

    timeout_task = asyncio.create_task(telemetry.monitor_timeouts())
    try:
        await asyncio.Event().wait()
    finally:
        timeout_task.cancel()
        await asyncio.gather(timeout_task, return_exceptions=True)
        await protocol.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCOAP EDGE : Serveur arrete")
