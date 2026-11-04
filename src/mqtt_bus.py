"""Bus de publication/abonnement cote Edge.

- PahoBus : connexion reelle au broker MQTT (Mosquitto), via paho-mqtt.
- LocalBus : bus en memoire, pour les tests sans broker.

La passerelle MQTT-SN et le coordonnateur ne dependent que de l'interface
commune : publish(topic, data, qos) et subscribe(filtre, callback).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("bus")

Callback = Callable[[str, bytes], Awaitable[None] | None]


def topic_matches(pattern: str, topic: str) -> bool:
    """Correspondance MQTT : '+' = un niveau, '#' = tous les niveaux restants."""
    p_parts, t_parts = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p_parts):
        if part == "#":
            return True
        if i >= len(t_parts):
            return False
        if part != "+" and part != t_parts[i]:
            return False
    return len(p_parts) == len(t_parts)


async def _call(cb: Callback, topic: str, data: bytes) -> None:
    try:
        result = cb(topic, data)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # un abonne defaillant ne doit pas bloquer le bus
        log.exception("erreur dans un abonne de %s", topic)


class LocalBus:
    """Bus en memoire (meme processus)."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Callback]] = []

    async def start(self) -> None:
        return None

    async def publish(self, topic: str, data: bytes, qos: int = 0) -> None:
        for pattern, cb in list(self._subs):
            if topic_matches(pattern, topic):
                asyncio.get_running_loop().create_task(_call(cb, topic, data))

    async def subscribe(self, pattern: str, cb: Callback, qos: int = 0) -> None:
        self._subs.append((pattern, cb))

    async def close(self) -> None:
        self._subs.clear()


class PahoBus:
    """Client MQTT reel (paho-mqtt 2.x), relie a la boucle asyncio."""

    def __init__(self, host: str, port: int = 1883, client_id: str = "edge") -> None:
        import paho.mqtt.client as mqtt  # import local : inutile pour LocalBus

        self._mqtt = mqtt
        self.host, self.port = host, port
        self._subs: list[tuple[str, int, Callback]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = asyncio.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

    # Callbacks paho (thread reseau de paho)
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        log.info("MQTT connecte a %s:%d (%s)", self.host, self.port, reason_code)
        for pattern, qos, _ in self._subs:  # re-abonnement apres reconnexion
            client.subscribe(pattern, qos)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        log.warning("MQTT deconnecte (%s)", reason_code)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.clear)

    def _on_message(self, client, userdata, msg) -> None:
        if not self._loop:
            return
        for pattern, _, cb in self._subs:
            if topic_matches(pattern, msg.topic):
                asyncio.run_coroutine_threadsafe(_call(cb, msg.topic, msg.payload), self._loop)

    # API commune
    async def start(self, timeout: float = 30.0) -> None:
        self._loop = asyncio.get_running_loop()
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        await asyncio.wait_for(self._connected.wait(), timeout)

    async def publish(self, topic: str, data: bytes, qos: int = 0) -> None:
        self.client.publish(topic, data, qos=qos)

    async def subscribe(self, pattern: str, cb: Callback, qos: int = 0) -> None:
        self._subs.append((pattern, qos, cb))
        if self._connected.is_set():
            self.client.subscribe(pattern, qos)

    async def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
