
import asyncio
import json

from aiocoap import resource, Message, Code, Context
from edge_agent import (
    process_message,
    analyze_devices,
    save_incident
)

HOST = "127.0.0.1"
PORT = 5683

pending_iterations = {}

class HealthResource(resource.Resource):

    async def render_get(self, request):
        return Message(
            code=Code.CONTENT,
            payload=json.dumps({
                "status": "ok",
                "agent": "edge-coordinator"
            }).encode("utf-8")
        )
class TelemetryResource(resource.Resource):

    async def render_post(self, request):
        try:
            message = json.loads(
                request.payload.decode("utf-8")
            )

            device_id = message["src"]["agent"]
            iteration = message["iteration"]

            if device_id not in {
                "node-01", "node-02", "node-03"
            } or not isinstance(iteration, int):
                return Message(
                    code=Code.BAD_REQUEST,
                    payload=b"Invalid device or iteration"
                )

            # Traitement individuel
            process_message(message)

            # Regroupement par iteration
            if iteration not in pending_iterations:
                pending_iterations[iteration] = {}

            pending_iterations[iteration][device_id] = message

            print(
                f"COAP EDGE : {device_id} recu "
                f"({len(pending_iterations[iteration])}/3) "
                f"iteration {iteration}"
            )

            if len(pending_iterations[iteration]) == 3:

                print(
                    f"\nCOAP EDGE : Analyse collective "
                    f"iteration {iteration}"
                )

                messages = list(
                    pending_iterations[iteration].values()
                )

                analyze_devices(messages)

                del pending_iterations[iteration]

            return Message(
                code=Code.CHANGED,
                payload=b"Telemetry processed"
            )

        except (ValueError, KeyError, TypeError):
            return Message(
                code=Code.BAD_REQUEST,
                payload=b"Invalid telemetry message"
            )
class AlertResource(resource.Resource):

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
        TelemetryResource()
    )

    protocol = await Context.create_server_context(
        root,
        bind=(HOST, PORT)
    )

    print(
        f"COAP EDGE : Serveur demarre sur "
        f"coap://{HOST}:{PORT}/telemetry"
    )

    try:
        await asyncio.Event().wait()
    finally:
        await protocol.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCOAP EDGE : Serveur arrete")
