
import asyncio
import json

from aiocoap import resource, Message, Code, Context
from edge_agent import process_message, analyze_devices


HOST = "127.0.0.1"
PORT = 5683

pending_iterations = {}


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


async def main():

    root = resource.Site()
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
