"""Passerelle MQTT-SN (UDP) -> MQTT (TCP), transparente et legere.

Chaque noeud parle MQTT-SN en UDP a la passerelle ; la passerelle relaie
vers le broker MQTT (Mosquitto) et renvoie aux noeuds les messages des
topics auxquels ils sont abonnes (commandes de l'Edge).

Remplacable par Eclipse Paho MQTT-SN Gateway en production : le protocole
cote noeud reste identique.

Lancement :  python -m edge.mqttsn_gateway --broker mosquitto --port 10000
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field

import mqttsn as sn

log = logging.getLogger("gateway")


@dataclass
class Session:
    client_id: str
    addr: tuple
    subscriptions: dict[str, int] = field(default_factory=dict)  # nom -> qos


class MqttSnGateway(asyncio.DatagramProtocol):
    def __init__(self, bus) -> None:
        self.bus = bus
        self.transport: asyncio.DatagramTransport | None = None
        self.sessions: dict[tuple, Session] = {}
        self.topic_ids: dict[str, int] = {}   # registre global nom -> id
        self.topic_names: dict[int, str] = {}
        self._upstream_subs: set[str] = set()
        self._msg_id = 0
        self.stats = {"rx": 0, "tx": 0, "to_broker": 0, "to_nodes": 0}

    # Outils
    def _topic_id(self, name: str) -> int:
        if name not in self.topic_ids:
            new_id = len(self.topic_ids) + 1
            self.topic_ids[name] = new_id
            self.topic_names[new_id] = name
        return self.topic_ids[name]

    def _send(self, packet: bytes, addr) -> None:
        if self.transport:
            self.transport.sendto(packet, addr)
            self.stats["tx"] += 1

    def _next_id(self) -> int:
        self._msg_id = self._msg_id % 0xFFFF + 1
        return self._msg_id

    # Reception UDP
    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        self.stats["rx"] += 1
        try:
            msg_type, body = sn.parse(data)
            self._handle(msg_type, body, addr)
        except (sn.PacketError, ValueError, UnicodeDecodeError) as exc:
            log.warning("paquet invalide de %s : %s", addr, exc)

    def _handle(self, msg_type: int, body: bytes, addr) -> None:
        if msg_type == sn.CONNECT:
            _, _, client_id = sn.read_connect(body)
            self.sessions[addr] = Session(client_id, addr)
            log.info("CONNECT %s depuis %s", client_id, addr)
            self._send(sn.connack(sn.ACCEPTED), addr)
            return

        session = self.sessions.get(addr)
        if session is None:
            # Noeud inconnu (ex. redemarrage de la passerelle) : il doit se reconnecter.
            self._send(sn.disconnect(), addr)
            return

        if msg_type == sn.REGISTER:
            _, msg_id, name = sn.read_register(body)
            if not name or "+" in name or "#" in name:
                self._send(sn.regack(0, msg_id, sn.REJ_INVALID_TOPIC), addr)
                return
            self._send(sn.regack(self._topic_id(name), msg_id), addr)

        elif msg_type == sn.PUBLISH:
            flags, topic_id, msg_id, data = sn.read_publish(body)
            qos = sn.flags_qos(flags)
            name = self.topic_names.get(topic_id)
            if name is None:
                if qos == 1:
                    self._send(sn.puback(topic_id, msg_id, sn.REJ_INVALID_TOPIC), addr)
                return
            asyncio.get_running_loop().create_task(self.bus.publish(name, data, min(qos, 1)))
            self.stats["to_broker"] += 1
            if qos == 1:
                self._send(sn.puback(topic_id, msg_id), addr)

        elif msg_type == sn.SUBSCRIBE:
            flags, msg_id, name = sn.read_subscribe(body)
            qos = min(sn.flags_qos(flags), 1)
            topic_id = self._topic_id(name)
            session.subscriptions[name] = qos
            if name not in self._upstream_subs:
                self._upstream_subs.add(name)
                asyncio.get_running_loop().create_task(self.bus.subscribe(name, self._from_broker, qos))
            log.info("SUBSCRIBE %s -> %s", session.client_id, name)
            self._send(sn.suback(topic_id, msg_id, qos), addr)

        elif msg_type == sn.PUBACK:
            pass  # accuse d'un PUBLISH QoS 1 envoye au noeud

        elif msg_type == sn.PINGREQ:
            self._send(sn.pingresp(), addr)

        elif msg_type == sn.DISCONNECT:
            log.info("DISCONNECT %s", session.client_id)
            self.sessions.pop(addr, None)
            self._send(sn.disconnect(), addr)

    # Broker -> noeuds
    async def _from_broker(self, topic: str, data: bytes) -> None:
        topic_id = self._topic_id(topic)
        for session in list(self.sessions.values()):
            qos = session.subscriptions.get(topic)
            if qos is None:
                continue
            msg_id = self._next_id() if qos else 0
            self._send(sn.publish(topic_id, msg_id, data, qos=qos), session.addr)
            self.stats["to_nodes"] += 1


async def start_gateway(bus, host: str = "0.0.0.0", port: int = 10000) -> MqttSnGateway:
    loop = asyncio.get_running_loop()
    _, gateway = await loop.create_datagram_endpoint(lambda: MqttSnGateway(bus), local_addr=(host, port))
    log.info("passerelle MQTT-SN a l'ecoute sur udp://%s:%d", host, port)
    return gateway


async def main() -> None:
    from mqtt_bus import PahoBus

    parser = argparse.ArgumentParser(description="Passerelle MQTT-SN -> MQTT")
    parser.add_argument("--broker", default=os.getenv("MQTT_HOST", "localhost"))
    parser.add_argument("--broker-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTTSN_PORT", "10000")))
    args = parser.parse_args()

    bus = PahoBus(args.broker, args.broker_port, client_id="mqttsn-gateway-local")
    await bus.start()
    gateway = await start_gateway(bus, port=args.port)
    while True:
        await asyncio.sleep(60)
        log.info("stats %s, noeuds connectes : %d", gateway.stats, len(gateway.sessions))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(main())
