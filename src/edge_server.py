
import socket
import json

from edge_agent import process_message, analyze_devices

HOST = "127.0.0.1"
PORT = 5000

# Stocker les messages par iteration
pending_iterations = {}


def handle_message(message):

    # Traitement individuel
    process_message(message)

    iteration = message.get("iteration")

    if iteration is None:
        print("EDGE : Message sans iteration")
        return

    # Initialiser le groupe
    if iteration not in pending_iterations:
        pending_iterations[iteration] = {}

    device_id = message["src"]["agent"]

    # Conserver un message par Device
    pending_iterations[iteration][device_id] = message

    # Attendre les trois Devices
    if len(pending_iterations[iteration]) == 3:

        print(
            f"\nEDGE : Analyse collective "
            f"iteration {iteration}"
        )

        messages = list(
            pending_iterations[iteration].values()
        )

        analyze_devices(messages)

        # Liberer la memoire
        del pending_iterations[iteration]


def start_server():

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as server:

        server.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        server.bind((HOST, PORT))
        server.listen()

        print(
            f"EDGE : Serveur demarre sur "
            f"{HOST}:{PORT}"
        )

        try:
            while True:

                connection, address = server.accept()

                print(
                    f"EDGE : Connexion de {address}"
                )

                with connection:
                    with connection.makefile(
                        "r", encoding="utf-8"
                    ) as stream:

                        for line in stream:

                            try:
                                message = json.loads(line)
                                handle_message(message)

                            except json.JSONDecodeError:
                                print(
                                    "EDGE : JSON invalide"
                                )

                            except (KeyError, TypeError) as error:
                                print(
                                    f"EDGE : Message mal forme : {error}"
                                )

        except KeyboardInterrupt:
            print("\nEDGE : Arret du serveur")


if __name__ == "__main__":
    start_server()
