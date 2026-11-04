
import asyncio
import logging

from mqttsn import MqttSnClient


async def main():
    client = MqttSnClient(client_id="test-node-01")

    try:
        # Connexion à notre passerelle MQTT-SN locale
        await client.connect("127.0.0.1", 10001)
        print("Connexion MQTT-SN réussie")

        # Publication d'un message sur Mosquitto via la passerelle
        topic = "aiot/test-mqttsn"
        message = b"Hello Agentic-AIoT"

        await client.publish(topic, message, qos=1)

        print(f"Message publié sur {topic}: {message.decode()}")

        # Laisser le temps à la passerelle de transmettre le message
        await asyncio.sleep(1)

    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
