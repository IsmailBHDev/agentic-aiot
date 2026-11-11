
import asyncio
import json
import logging
import time
from mqtt_bus import PahoBus
from edge_agent import process_message, analyze_devices

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC = "aiot/telemetry/+"

# Delai maximal pour completer une iteration
ITERATION_TIMEOUT_SECONDS = 5

# Date de reception du premier message de chaque groupe
iteration_start_times = {}

EXPECTED_DEVICES = {"node-01", "node-02", "node-03"}

# Messages regroupés par numéro d'itération
pending_iterations = {}
# Identifiants des messages deja traites
processed_message_ids = set()

# Iterations deja analysees
completed_iterations = set()


async def monitor_timeouts():
    """Surveille les iterations incompletes."""

    while True:
        await asyncio.sleep(1)

        current_time = time.monotonic()

        for key, start_time in list(iteration_start_times.items()):

            elapsed = current_time - start_time

            if elapsed < ITERATION_TIMEOUT_SECONDS:
                continue

            session_id, iteration = key

            # Recuperer les mesures recues
            batch = pending_iterations.get(key, {})

            # Identifier les capteurs manquants
            received_devices = set(batch.keys())
            missing_devices = EXPECTED_DEVICES - received_devices

            print(
                f"\nEDGE MQTT : TIMEOUT - "
                f"Session {session_id}, iteration {iteration}"
            )

            print(
                f"EDGE MQTT : Capteurs manquants : "
                f"{sorted(missing_devices)}"
            )

            # Empecher le retraitement de cette iteration
            completed_iterations.add(key)

            # Liberer la memoire temporaire
            pending_iterations.pop(key, None)
            iteration_start_times.pop(key, None)


async def on_message(topic, data):
    try:
        message = json.loads(data.decode("utf-8"))

        device_id = message["src"]["agent"]
        iteration = message["iteration"]
        session_id = message["session_id"]
        message_id = message["id"]

        if device_id not in EXPECTED_DEVICES:
            return

        key = (session_id, iteration)

        # 1. Ignorer les messages deja traites
        if message_id in processed_message_ids:
            print(
                f"EDGE MQTT : Message duplique ignore : {message_id}"
            )
            return

        # 2. Ignorer les iterations deja terminees
        if key in completed_iterations:
            print(
                f"EDGE MQTT : Iteration {iteration} deja analysee "
                f"pour la session {session_id}"
            )
            return

        # 3. Recuperer le groupe de mesures
        batch = pending_iterations.setdefault(key, {})
        
        # Memoriser le debut de l'iteration
        iteration_start_times.setdefault(key, time.monotonic())
        
        # 4. Eviter plusieurs mesures du meme capteur
        if device_id in batch:
            print(
                f"EDGE MQTT : Mesure supplementaire ignoree "
                f"pour {device_id}, iteration {iteration}"
            )
            return

        # 5. Memoriser le message avant son traitement
        processed_message_ids.add(message_id)

        # 6. Traiter la mesure individuelle
        process_message(message)

        batch[device_id] = message

        # 7. Analyser lorsque les 3 capteurs sont presents
        if EXPECTED_DEVICES.issubset(batch.keys()):

            print(
                f"\n===== EDGE : SESSION {session_id} "
                f"- ITERATION {iteration} ====="
            )

            analyze_devices(list(batch.values()))

            completed_iterations.add(key)

            # Nettoyer les donnees temporaires
            del pending_iterations[key]
            iteration_start_times.pop(key, None)

    except (ValueError, KeyError, TypeError) as error:
        print(f"EDGE MQTT : Message invalide : {error}")


async def main():
    logging.basicConfig(level=logging.INFO)

    bus = PahoBus(
        BROKER_HOST,
        BROKER_PORT,
        client_id="mqtt-edge-adapter-local"
    )

    await bus.subscribe(TOPIC, on_message)
    await bus.start()

    # Demarrer la surveillance des timeouts
    timeout_task = asyncio.create_task(monitor_timeouts())

    print("EDGE MQTT : En attente des mesures IoT...")
    print(
        f"EDGE MQTT : Timeout configure a "
        f"{ITERATION_TIMEOUT_SECONDS} secondes"
    )

    try:
        await asyncio.Event().wait()

    finally:
        # Arreter proprement la surveillance
        timeout_task.cancel()

        try:
            await timeout_task
        except asyncio.CancelledError:
            pass

        # Fermer la connexion MQTT
        await bus.close()

        print("EDGE MQTT : Arret propre termine")

if __name__ == "__main__":
    asyncio.run(main())
