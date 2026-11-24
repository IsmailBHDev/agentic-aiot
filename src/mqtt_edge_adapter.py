import asyncio
import json
import logging
import time
from collections import Counter
from message_auth import AuthError, verifier_from_env
from mqtt_bus import PahoBus
from edge_agent import process_message, analyze_devices
from telemetry import (
    CLEANUP_INTERVAL_SECONDS,
    EXPECTED_DEVICES,
    ITERATION_TIMEOUT_SECONDS,
    MESSAGE_RETENTION_SECONDS,
    is_message_fresh,
    validate_telemetry,
)

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC = "aiot/telemetry/+"

# Date de reception du premier message de chaque groupe
iteration_start_times = {}

# Messages regroupés par numéro d'itération
pending_iterations = {}

# Messages deja traites : message_id -> horodatage
processed_message_ids = {}

# Iterations terminees : (session_id, iteration) -> horodatage
completed_iterations = {}
collection_metrics = Counter()

# IOT-174 : vérification des signatures (None en C0, sans authentification)
message_verifier = verifier_from_env(EXPECTED_DEVICES)

def expire_iteration(key, current_time):
    """Clôture un lot arrivé à échéance, y compris entre deux scrutations."""
    start_time = iteration_start_times.get(key)
    if start_time is None or current_time - start_time < ITERATION_TIMEOUT_SECONDS:
        return
    batch = pending_iterations.pop(key)
    missing_devices = EXPECTED_DEVICES - batch.keys()
    collection_metrics["batches_expired"] += 1
    collection_metrics["observations_missing_at_timeout"] += len(missing_devices)
    print(f"EDGE MQTT : TIMEOUT {key}, capteurs manquants : {sorted(missing_devices)}")
    completed_iterations[key] = current_time
    del iteration_start_times[key]


async def monitor_timeouts():
    """Surveille les iterations incompletes."""
    while True:
        await asyncio.sleep(1)
        current_time = time.monotonic()
        for key in list(iteration_start_times):
            expire_iteration(key, current_time)


async def on_message(topic, data):
    collection_metrics["messages_received"] += 1
    try:
        message = json.loads(data.decode("utf-8"))
        key, device_id, message_id = validate_telemetry(message)
        # Verifier la fraicheur du message avant son traitement
        if not is_message_fresh(message):
            collection_metrics["messages_invalid"] += 1
            print(
                "EDGE MQTT : Message rejete "
                "(horodatage absent, invalide ou expire)"
            )
            return
        session_id, iteration = key
        now = time.monotonic()
        expire_iteration(key, now)

        # 1. Ignorer les messages deja traites
        if message_id in processed_message_ids:
            collection_metrics["messages_duplicate"] += 1
            print(
                f"EDGE MQTT : Message duplique ignore : {message_id}"
            )
            return

        # 2. Ignorer les iterations deja terminees
        if key in completed_iterations:
            collection_metrics["messages_closed_batch"] += 1
            print(
                f"EDGE MQTT : Iteration {iteration} deja analysee "
                f"pour la session {session_id}"
            )
            return

        # 3. Recuperer le groupe de mesures
        batch = pending_iterations.get(key, {})

        # 4. Eviter plusieurs mesures du meme capteur
        if device_id in batch:
            collection_metrics["messages_duplicate"] += 1
            print(
                f"EDGE MQTT : Mesure supplementaire ignoree "
                f"pour {device_id}, iteration {iteration}"
            )
            return

        # 5. Vérifier l'origine et l'intégrité avant tout effet (IOT-174)
        if message_verifier is not None:
            message_verifier.verify(message)

        # Traiter la mesure individuelle avant de marquer son ID comme traité.
        process_message(message)

        processed_message_ids[message_id] = now
        iteration_start_times.setdefault(key, now)
        pending_iterations[key] = batch
        batch[device_id] = message

        # 7. Analyser lorsque les 3 capteurs sont presents
        if EXPECTED_DEVICES.issubset(batch.keys()):

            print(
                f"\n===== EDGE : SESSION {session_id} "
                f"- ITERATION {iteration} ====="
            )

            analyze_devices(list(batch.values()))

            duration = now - iteration_start_times[key]
            collection_metrics["batches_completed"] += 1
            collection_metrics["batch_assembly_seconds_total"] += duration
            completed_iterations[key] = time.monotonic()

            # Nettoyer les donnees temporaires
            del pending_iterations[key]
            iteration_start_times.pop(key, None)

    except AuthError as error:
        collection_metrics["messages_auth_rejected"] += 1
        collection_metrics[f"auth_rejected_{error.reason}"] += 1
        print(f"EDGE MQTT : Message non authentifie ({error.reason})")

    except (ValueError, KeyError, TypeError, OverflowError) as error:
        collection_metrics["messages_invalid"] += 1
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
        print(f"EDGE MQTT : Collecte {dict(collection_metrics)}")


async def main():
    logging.basicConfig(level=logging.INFO)

    bus = PahoBus(
        BROKER_HOST,
        BROKER_PORT,
        client_id="mqtt-edge-adapter-local"
    )

    await bus.subscribe(TOPIC, on_message, qos=1)
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
