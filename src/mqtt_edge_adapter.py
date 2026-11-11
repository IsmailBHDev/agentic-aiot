from datetime import datetime, timezone
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
# Parametres du nettoyage memoire
MESSAGE_RETENTION_SECONDS = 300
CLEANUP_INTERVAL_SECONDS = 30

# Parametres de verification des horodatages
MAX_MESSAGE_AGE_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 5
# Date de reception du premier message de chaque groupe
iteration_start_times = {}

EXPECTED_DEVICES = {"node-01", "node-02", "node-03"}

# Messages regroupés par numéro d'itération
pending_iterations = {}

# Messages deja traites : message_id -> horodatage
processed_message_ids = {}

# Iterations terminees : (session_id, iteration) -> horodatage
completed_iterations = {}

def is_message_fresh(message):
    """Verifie si l'horodatage du message est acceptable."""

    timestamp = message.get("ts")

    if not isinstance(timestamp, str):
        return False

    try:
        message_time = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )

        # Refuser les dates sans fuseau horaire
        if message_time.tzinfo is None:
            return False

        now = datetime.now(timezone.utc)
        age = (now - message_time).total_seconds()

        return (
            -MAX_CLOCK_SKEW_SECONDS
            <= age
            <= MAX_MESSAGE_AGE_SECONDS
        )

    except ValueError:
        return False


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
        # Verifier la fraicheur du message avant son traitement
        if not is_message_fresh(message):
            print(
                "EDGE MQTT : Message rejete "
                "(horodatage absent, invalide ou expire)"
            )
            return
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
        processed_message_ids[message_id] = time.monotonic()

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

            completed_iterations[key] = time.monotonic()

            # Nettoyer les donnees temporaires
            del pending_iterations[key]
            iteration_start_times.pop(key, None)

    except (ValueError, KeyError, TypeError) as error:
        print(f"EDGE MQTT : Message invalide : {error}")


async def cleanup_expired_entries():
    """Nettoie periodiquement les identifiants expires."""

    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

        current_time = time.monotonic()

        # 1. Supprimer les identifiants de messages expires
        expired_messages = [
            message_id
            for message_id, timestamp
            in processed_message_ids.items()
            if current_time - timestamp
            >= MESSAGE_RETENTION_SECONDS
        ]

        for message_id in expired_messages:
            del processed_message_ids[message_id]

        # 2. Supprimer les iterations terminees expirees
        expired_iterations = [
            key
            for key, timestamp
            in completed_iterations.items()
            if current_time - timestamp
            >= MESSAGE_RETENTION_SECONDS
        ]

        for key in expired_iterations:
            del completed_iterations[key]

        print(
            f"EDGE MQTT : Nettoyage termine - "
            f"{len(expired_messages)} messages supprimes, "
            f"{len(expired_iterations)} iterations supprimees"
        )

        print(
            f"EDGE MQTT : Memoire actuelle - "
            f"{len(processed_message_ids)} messages, "
            f"{len(completed_iterations)} iterations"
        )


async def main():
    logging.basicConfig(level=logging.INFO)

    bus = PahoBus(
        BROKER_HOST,
        BROKER_PORT,
        client_id="mqtt-edge-adapter-local"
    )

    await bus.subscribe(TOPIC, on_message)
    await bus.start()

    # Demarrer les taches de surveillance
    timeout_task = asyncio.create_task(
        monitor_timeouts()
    )

    cleanup_task = asyncio.create_task(
        cleanup_expired_entries()
    )

    print("EDGE MQTT : En attente des mesures IoT...")
    print(
        f"EDGE MQTT : Timeout configure a "
        f"{ITERATION_TIMEOUT_SECONDS} secondes"
    )
    print(
        f"EDGE MQTT : Nettoyage toutes les "
        f"{CLEANUP_INTERVAL_SECONDS} secondes"
    )

    try:
        await asyncio.Event().wait()

    finally:
        # Arreter les deux taches
        timeout_task.cancel()
        cleanup_task.cancel()

        await asyncio.gather(
            timeout_task,
            cleanup_task,
            return_exceptions=True
        )

        # Fermer la connexion MQTT
        await bus.close()

        print("EDGE MQTT : Arret propre termine")


if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())