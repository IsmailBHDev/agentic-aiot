"""MQTT-SN v1.2 : encodage des paquets et client asyncio minimal (UDP).

Sous-ensemble utilise par le projet : CONNECT, REGISTER, PUBLISH (QoS 0/1),
SUBSCRIBE, PINGREQ et DISCONNECT, avec des noms de topics normaux.
Ce module n'a aucune dependance externe ; il sert au simulateur de noeuds
(device) et a la passerelle (edge). Sur ESP32, le meme protocole sera code
en C++ en semaine 2.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger("mqttsn")

# Types de messages (specification MQTT-SN v1.2, section 5.2.2)
CONNECT = 0x04
CONNACK = 0x05
REGISTER = 0x0A
REGACK = 0x0B
PUBLISH = 0x0C
PUBACK = 0x0D
SUBSCRIBE = 0x12
SUBACK = 0x13
PINGREQ = 0x16
PINGRESP = 0x17
DISCONNECT = 0x18

NAMES = {
    CONNECT: "CONNECT", CONNACK: "CONNACK", REGISTER: "REGISTER", REGACK: "REGACK",
    PUBLISH: "PUBLISH", PUBACK: "PUBACK", SUBSCRIBE: "SUBSCRIBE", SUBACK: "SUBACK",
    PINGREQ: "PINGREQ", PINGRESP: "PINGRESP", DISCONNECT: "DISCONNECT",
}

# Codes de retour
ACCEPTED = 0x00
REJ_INVALID_TOPIC = 0x02

# Drapeaux
FLAG_DUP = 0x80
FLAG_RETAIN = 0x10
FLAG_CLEAN = 0x04
PROTOCOL_ID = 0x01


class PacketError(ValueError):
    pass


def qos_flags(qos: int) -> int:
    return (qos & 0x03) << 5


def flags_qos(flags: int) -> int:
    return (flags >> 5) & 0x03


def frame(msg_type: int, body: bytes = b"") -> bytes:
    """Ajoute l'en-tete : longueur sur 1 octet, ou 0x01 + 2 octets au-dela de 255."""
    length = len(body) + 2
    if length <= 255:
        return bytes([length, msg_type]) + body
    length += 2
    if length > 0xFFFF:
        raise PacketError("paquet trop long")
    return b"\x01" + struct.pack("!H", length) + bytes([msg_type]) + body


def parse(data: bytes) -> tuple[int, bytes]:
    """Retourne (type, corps) ; verifie la longueur annoncee."""
    if len(data) < 2:
        raise PacketError("paquet trop court")
    if data[0] == 0x01:
        if len(data) < 4:
            raise PacketError("en-tete long incomplet")
        length = struct.unpack("!H", data[1:3])[0]
        header = 3
    else:
        length = data[0]
        header = 1
    if length != len(data):
        raise PacketError(f"longueur annoncee {length} != recue {len(data)}")
    return data[header], data[header + 1:]


# --- Constructeurs de paquets -------------------------------------------------

def connect(client_id: str, keepalive: int = 60, clean: bool = True) -> bytes:
    flags = FLAG_CLEAN if clean else 0
    return frame(CONNECT, struct.pack("!BBH", flags, PROTOCOL_ID, keepalive) + client_id.encode())


def connack(code: int = ACCEPTED) -> bytes:
    return frame(CONNACK, bytes([code]))


def register(topic_id: int, msg_id: int, topic: str) -> bytes:
    return frame(REGISTER, struct.pack("!HH", topic_id, msg_id) + topic.encode())


def regack(topic_id: int, msg_id: int, code: int = ACCEPTED) -> bytes:
    return frame(REGACK, struct.pack("!HHB", topic_id, msg_id, code))


def publish(topic_id: int, msg_id: int, data: bytes, qos: int = 0, retain: bool = False) -> bytes:
    flags = qos_flags(qos) | (FLAG_RETAIN if retain else 0)
    return frame(PUBLISH, struct.pack("!BHH", flags, topic_id, msg_id) + data)


def puback(topic_id: int, msg_id: int, code: int = ACCEPTED) -> bytes:
    return frame(PUBACK, struct.pack("!HHB", topic_id, msg_id, code))


def subscribe(msg_id: int, topic: str, qos: int = 1) -> bytes:
    return frame(SUBSCRIBE, struct.pack("!BH", qos_flags(qos), msg_id) + topic.encode())


def suback(topic_id: int, msg_id: int, qos: int = 1, code: int = ACCEPTED) -> bytes:
    return frame(SUBACK, struct.pack("!BHHB", qos_flags(qos), topic_id, msg_id, code))


def pingreq(client_id: str = "") -> bytes:
    return frame(PINGREQ, client_id.encode())


def pingresp() -> bytes:
    return frame(PINGRESP)


def disconnect() -> bytes:
    return frame(DISCONNECT)


# --- Decodeurs de corps ------------------------------------------------------

def read_connect(body: bytes) -> tuple[int, int, str]:
    flags, proto, keepalive = struct.unpack("!BBH", body[:4])
    if proto != PROTOCOL_ID:
        raise PacketError("ProtocolId invalide")
    return flags, keepalive, body[4:].decode()


def read_register(body: bytes) -> tuple[int, int, str]:
    topic_id, msg_id = struct.unpack("!HH", body[:4])
    return topic_id, msg_id, body[4:].decode()


def read_ack(body: bytes) -> tuple[int, int, int]:
    """REGACK et PUBACK : (topic_id, msg_id, code)."""
    return struct.unpack("!HHB", body[:5])


def read_publish(body: bytes) -> tuple[int, int, int, bytes]:
    flags, topic_id, msg_id = struct.unpack("!BHH", body[:5])
    return flags, topic_id, msg_id, body[5:]


def read_subscribe(body: bytes) -> tuple[int, int, str]:
    flags, msg_id = struct.unpack("!BH", body[:3])
    return flags, msg_id, body[3:].decode()


def read_suback(body: bytes) -> tuple[int, int, int, int]:
    flags, topic_id, msg_id, code = struct.unpack("!BHHB", body[:6])
    return flags, topic_id, msg_id, code


# --- Client asyncio ----------------------------------------------------------

Handler = Callable[[str, bytes], Awaitable[None] | None]


@dataclass
class _Pending:
    future: asyncio.Future
    expect: int


@dataclass
class MqttSnClient(asyncio.DatagramProtocol):
    """Client MQTT-SN minimal pour un noeud (reel ou simule)."""

    client_id: str
    keepalive: int = 60
    timeout: float = 3.0
    retries: int = 3
    topics: dict[str, int] = field(default_factory=dict)       # nom -> id
    names: dict[int, str] = field(default_factory=dict)        # id -> nom
    handlers: dict[str, Handler] = field(default_factory=dict)  # nom -> callback

    def __post_init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._pending: dict[tuple[int, int], _Pending] = {}
        self._connack: asyncio.Future | None = None
        self._msg_id = 0
        self._ping_task: asyncio.Task | None = None
        self.connected = False

    # Plomberie asyncio
    def connection_made(self, transport) -> None:  # type: ignore[override]
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        try:
            msg_type, body = parse(data)
        except PacketError as exc:
            log.warning("%s : paquet ignore (%s)", self.client_id, exc)
            return
        if msg_type == CONNACK and self._connack and not self._connack.done():
            self._connack.set_result(body[0])
        elif msg_type in (REGACK, PUBACK):
            topic_id, msg_id, code = read_ack(body)
            self._resolve(msg_type, msg_id, (topic_id, code))
        elif msg_type == SUBACK:
            _, topic_id, msg_id, code = read_suback(body)
            self._resolve(SUBACK, msg_id, (topic_id, code))
        elif msg_type == REGISTER:
            # La passerelle annonce un topic avant de publier dessus.
            topic_id, msg_id, name = read_register(body)
            self.names[topic_id] = name
            self.topics[name] = topic_id
            self._send(regack(topic_id, msg_id))
        elif msg_type == PUBLISH:
            self._on_publish(body)
        elif msg_type == DISCONNECT:
            self.connected = False

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        log.warning("%s : erreur UDP %s", self.client_id, exc)

    def _resolve(self, msg_type: int, msg_id: int, value) -> None:
        pending = self._pending.pop((msg_type, msg_id), None)
        if pending and not pending.future.done():
            pending.future.set_result(value)

    def _on_publish(self, body: bytes) -> None:
        flags, topic_id, msg_id, data = read_publish(body)
        if flags_qos(flags) == 1:
            self._send(puback(topic_id, msg_id))
        name = self.names.get(topic_id)
        handler = self.handlers.get(name) if name else None
        if handler is None:
            log.warning("%s : PUBLISH sur topic inconnu %s", self.client_id, topic_id)
            return
        result = handler(name, data)
        if asyncio.iscoroutine(result):
            asyncio.ensure_future(result)

    def _send(self, packet: bytes) -> None:
        if self._transport is None:
            raise ConnectionError("client non connecte")
        self._transport.sendto(packet)

    def _next_id(self) -> int:
        self._msg_id = self._msg_id % 0xFFFF + 1
        return self._msg_id

    async def _request(self, packet: bytes, expect: int, msg_id: int):
        """Envoie et attend l'accuse de reception, avec retransmission."""
        loop = asyncio.get_running_loop()
        for attempt in range(1, self.retries + 1):
            fut = loop.create_future()
            self._pending[(expect, msg_id)] = _Pending(fut, expect)
            self._send(packet)
            try:
                return await asyncio.wait_for(fut, self.timeout)
            except asyncio.TimeoutError:
                log.debug("%s : %s sans reponse (essai %d)", self.client_id, NAMES[expect], attempt)
            finally:
                self._pending.pop((expect, msg_id), None)
        raise TimeoutError(f"{self.client_id} : pas de {NAMES[expect]}")

    # API publique
    async def connect(self, host: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, remote_addr=(host, port))
        for attempt in range(1, self.retries + 1):
            self._connack = loop.create_future()
            self._send(connect(self.client_id, self.keepalive))
            try:
                code = await asyncio.wait_for(self._connack, self.timeout)
            except asyncio.TimeoutError:
                continue
            if code != ACCEPTED:
                raise ConnectionError(f"connexion refusee (code {code})")
            self.connected = True
            self._ping_task = asyncio.create_task(self._ping_loop())
            log.info("%s : connecte a la passerelle %s:%d", self.client_id, host, port)
            return
        raise TimeoutError(f"{self.client_id} : passerelle injoignable {host}:{port}")

    async def register(self, topic: str) -> int:
        if topic in self.topics:
            return self.topics[topic]
        msg_id = self._next_id()
        topic_id, code = await self._request(register(0, msg_id, topic), REGACK, msg_id)
        if code != ACCEPTED:
            raise ConnectionError(f"REGISTER refuse pour {topic} (code {code})")
        self.topics[topic] = topic_id
        self.names[topic_id] = topic
        return topic_id

    async def publish(self, topic: str, data: bytes, qos: int = 0) -> None:
        topic_id = await self.register(topic)
        if qos == 0:
            self._send(publish(topic_id, 0, data, qos=0))
            return
        msg_id = self._next_id()
        _, code = await self._request(publish(topic_id, msg_id, data, qos=1), PUBACK, msg_id)
        if code != ACCEPTED:
            raise ConnectionError(f"PUBLISH refuse sur {topic} (code {code})")

    async def subscribe(self, topic: str, handler: Handler, qos: int = 1) -> int:
        self.handlers[topic] = handler
        msg_id = self._next_id()
        topic_id, code = await self._request(subscribe(msg_id, topic, qos), SUBACK, msg_id)
        if code != ACCEPTED:
            raise ConnectionError(f"SUBSCRIBE refuse pour {topic} (code {code})")
        self.topics[topic] = topic_id
        self.names[topic_id] = topic
        return topic_id

    async def _ping_loop(self) -> None:
        while self.connected:
            await asyncio.sleep(max(self.keepalive / 2, 1))
            try:
                self._send(pingreq(self.client_id))
            except ConnectionError:
                return

    async def close(self) -> None:
        if self._ping_task:
            self._ping_task.cancel()
        if self._transport:
            try:
                self._send(disconnect())
            finally:
                self._transport.close()
        self.connected = False
