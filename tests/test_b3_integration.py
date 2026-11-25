"""Local network replay for the Edge, MCP and A2A pipeline."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytestmark = pytest.mark.skipif(
    os.getenv("AIOT_TEST_NETWORK") != "1", reason="Requires local Mosquitto"
)


def read_records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def telemetry(session, index):
    return {
        "id": str(uuid4()),
        "session_id": session,
        "iteration": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "telemetry",
        "src": {"agent": f"node-0{index}"},
        "payload": {
            "temperature": 28.0 if index == 3 else 25.0,
            "prediction": 0,
            "vibration": 0.3,
            "inference_ms": 1.0,
        },
    }


@pytest.mark.parametrize("run_number", [1, 2, 3])
def test_b3_replay_mqttsn_and_coap(tmp_path, monkeypatch, run_number):
    # IOT-178 : configurations C0 à C2 choisies par AIOT_AUTH_MODE et AIOT_CHANNEL_MODE.
    # Sans ces variables, le banc reste en C0, comme avant. Les clés de chaque
    # répétition sont créées AVANT d'importer l'Edge et le pont, qui les chargent
    # dès leur import.
    import message_auth
    import secure_channel

    devices = ("node-01", "node-02", "node-03")
    auth_mode = message_auth.auth_mode()
    channel_mode = secure_channel.channel_mode()
    monkeypatch.setenv(message_auth.KEY_DIR_ENV, str(tmp_path / "keys"))
    if auth_mode != message_auth.NO_AUTH:
        message_auth.create_keyring(auth_mode, devices)
    if channel_mode != secure_channel.NO_CHANNEL:
        secure_channel.create_channel_keys(channel_mode)
    signers = (
        {device: message_auth.load_signer(device, auth_mode) for device in devices}
        if auth_mode != message_auth.NO_AUTH else {}
    )

    import uvicorn
    from aiocoap import Code, Context, Message, resource

    import cloud_orchestrator as orchestrator
    import edge_agent
    import mqtt_edge_adapter as mqtt_edge
    from cloud_a2a_server import app
    from cloud_mcp_server import create_mcp
    from coap_server import AlertResource, TelemetryResource
    from edge_cloud_bridge import watch_incidents
    from mqtt_bus import PahoBus
    from mqttsn import MqttSnClient
    from mqttsn_gateway import start_gateway
    transport_counts = Counter()
    poll_counts = Counter()
    transport_metrics = []
    repetitions = 8

    edge_file = tmp_path / "edge.jsonl"
    cloud_file = tmp_path / "cloud.jsonl"
    decision_file = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("AIOT_CLOUD_INCIDENT_FILE", str(cloud_file))
    monkeypatch.setattr(edge_agent, "INCIDENT_FILE", edge_file)
    monkeypatch.setattr(edge_agent, "isolated_devices_by_session", {})
    monkeypatch.setattr(mqtt_edge, "collection_metrics", Counter())
    for name in (
        "pending_iterations", "iteration_start_times",
        "processed_message_ids", "completed_iterations",
    ):
        monkeypatch.setattr(mqtt_edge, name, {})
    monkeypatch.setattr(orchestrator, "INCIDENTS_FILE", cloud_file)
    monkeypatch.setattr(orchestrator, "DECISIONS_FILE", decision_file)

    # IOT-178 : vérificateur, scellement et ouverture liés aux clés de cette répétition
    import cloud_store
    import edge_cloud_bridge

    monkeypatch.setattr(mqtt_edge, "message_verifier", message_auth.verifier_from_env(devices))
    monkeypatch.setattr(edge_cloud_bridge, "edge_sealer", secure_channel.sealer_from_env())
    monkeypatch.setattr(cloud_store, "_opener_cache", {})

    def sign(message):
        signer = signers.get(message["src"]["agent"])
        return signer.sign(message) if signer else message

    async def run():
        test_id = uuid4().hex[:12]
        topic_prefix = f"aiot-test/{test_id}"
        mqtt = PahoBus("127.0.0.1", client_id=f"b3-test-{test_id}")
        servers = []
        sockets = []
        udp_gateway = None
        coap_server = None
        coap_client = None
        bridge = None

        async def start_http(application, service):
            async def measured_app(scope, receive, send):
                if scope["type"] != "http":
                    await application(scope, receive, send)
                    return
                transport_counts[f"{service}_http_requests"] += 1

                async def measured_receive():
                    message = await receive()
                    transport_counts[f"{service}_request_body_bytes"] += len(message.get("body", b""))
                    return message

                async def measured_send(message):
                    transport_counts[f"{service}_response_body_bytes"] += len(message.get("body", b""))
                    await send(message)

                await application(scope, measured_receive, measured_send)

            sock = socket.socket()
            sockets.append(sock)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(measured_app, log_level="warning"))
            task = asyncio.create_task(server.serve(sockets=[sock]))
            servers.append((server, task))
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("HTTP service stopped before startup")
                    await asyncio.sleep(0.01)
            return f"http://127.0.0.1:{port}"

        try:
            mcp_url = await start_http(create_mcp().streamable_http_app(), "mcp") + "/mcp"
            monkeypatch.setattr(orchestrator, "A2A_URL", await start_http(app, "a2a") + "/")
            await mqtt.subscribe(f"{topic_prefix}/+", mqtt_edge.on_message, qos=1)
            await mqtt.start(timeout=5)
            udp_gateway = await start_gateway(mqtt, host="127.0.0.1", port=0)
            gateway_port = udp_gateway.transport.get_extra_info("sockname")[1]

            site = resource.Site()
            collector = TelemetryResource()
            site.add_resource(["telemetry"], collector)
            site.add_resource(["alert"], AlertResource())
            # Sous Windows, un port libéré peut être refusé à la réouverture
            # (WinError 10013, plages réservées par Hyper-V ou Docker) : on réessaie.
            for attempt in range(20):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    coap_port = reservation.getsockname()[1]
                try:
                    coap_server = await Context.create_server_context(
                        site, bind=("127.0.0.1", coap_port)
                    )
                    break
                except OSError:
                    if attempt == 19:
                        raise
                    transport_counts["coap_bind_retries"] += 1
            coap_client = await Context.create_client_context()
            bridge = asyncio.create_task(watch_incidents(edge_file, mcp_url, interval=0.02))
            await asyncio.sleep(0)

            async def post_coap(route, message):
                payload = json.dumps(message).encode()
                transport_counts["coap_posts"] += 1
                transport_counts["coap_payload_bytes"] += len(payload)
                request = Message(
                    code=Code.POST, uri=f"coap://127.0.0.1:{coap_port}/{route}",
                    payload=payload,
                )
                response = await asyncio.wait_for(coap_client.request(request).response, 3)
                assert response.code == Code.CHANGED

            async with asyncio.timeout(15):
                for index in (2, 3, 1):
                    node = MqttSnClient(client_id=f"b3-{test_id}-{index}")
                    try:
                        await node.connect("127.0.0.1", gateway_port)
                        for group in range(repetitions):
                            payload = json.dumps(sign(telemetry(f"mqtt-sn-session-{group}", index))).encode()
                            transport_counts["mqttsn_publishes"] += 1
                            transport_counts["mqttsn_payload_bytes"] += len(payload)
                            await node.publish(f"{topic_prefix}/node-0{index}", payload, qos=1)
                            await post_coap("telemetry", sign(telemetry(f"coap-session-{group}", index)))
                    finally:
                        await node.close()

                local = telemetry("coap-local-session", 1)
                local["type"] = "anomaly_alert"
                local["payload"]["prediction"] = 1
                await post_coap("telemetry", sign(local))
                await post_coap("alert", sign({
                    "type": "anomaly_alert", "src": {"agent": "node-02"},
                    "session_id": "coap-unknown-session",
                    "payload": {"temperature": 28.0},
                }))

                while len(read_records(decision_file)) < 2 * repetitions + 2:
                    processed = await asyncio.to_thread(orchestrator.process_pending_incidents)
                    poll_counts["orchestrator_polls"] += 1
                    if not processed:
                        poll_counts["orchestrator_empty_polls"] += 1
                    await asyncio.sleep(0.02)
                transport_metrics.extend((dict(mqtt_edge.collection_metrics), dict(collector.collection_metrics)))
        finally:
            if bridge is not None:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            if coap_client is not None:
                await coap_client.shutdown()
            if coap_server is not None:
                await coap_server.shutdown()
            if udp_gateway is not None:
                udp_gateway.transport.close()
            await mqtt.close()
            for server, _ in servers:
                server.should_exit = True
            await asyncio.gather(*(task for _, task in servers))
            for sock in sockets:
                sock.close()

    asyncio.run(run())

    restart = subprocess.run(
        [sys.executable, "-B", str(Path(orchestrator.__file__))],
        env={**os.environ, "AIOT_CLOUD_DECISION_FILE": str(decision_file)},
        capture_output=True, text=True, timeout=5, check=True,
    )
    assert "0 incident(s)" in restart.stdout

    edge = {incident["id"]: incident for incident in read_records(edge_file)}
    cloud = {incident["cloud_incident_id"]: incident for incident in read_records(cloud_file)}
    decisions = read_records(decision_file)
    assert len(edge) == len(cloud) == len(decisions) == 2 * repetitions + 2
    assert {d["session_id"] for d in decisions} == (
        {f"{transport}-session-{group}" for group in range(repetitions)
         for transport in ("mqtt-sn", "coap")}
        | {"coap-local-session", "coap-unknown-session"}
    )
    expected = {
        "SENSOR_INCONSISTENCY": ("HIGH", "maintain logical isolation"),
        "LOCAL_ML_ANOMALY": ("HIGH", "maintain safe mode"),
        "COAP_UNKNOWN": ("MEDIUM", "Escalate incident"),
    }
    assert Counter(decision["reason"] for decision in decisions) == {
        "SENSOR_INCONSISTENCY": 2 * repetitions,
        "LOCAL_ML_ANOMALY": 1,
        "COAP_UNKNOWN": 1,
    }
    example_sessions = {"mqtt-sn-session-0", "coap-session-0"}
    latencies = []
    for decision in decisions:
        stored = cloud[decision["cloud_incident_id"]]
        incident = edge[decision["incident_id"]]
        assert stored["id"] == incident["id"]
        for field in ("session_id", "iteration", "device_id", "reason", "temperature", "reference"):
            assert decision.get(field) == stored.get(field) == incident.get(field)
        severity, recommendation = expected[incident["reason"]]
        assert decision["analysis_method"] == "rule_based_v1"
        assert decision["severity"] == severity
        assert recommendation in decision["recommendation"]
        if incident["reason"] == "SENSOR_INCONSISTENCY":
            assert incident["temperature"] - incident["reference"] == 3.0
            assert incident["iteration"] == 1
        if incident["session_id"] in example_sessions:
            print("B3_TRACE " + json.dumps({
                "session_id": incident["session_id"],
                "iteration": incident["iteration"],
                "device_id": incident["device_id"],
                "temperature": incident["temperature"],
                "reference": incident["reference"],
                "edge_incident_id": incident["id"],
                "cloud_incident_id": decision["cloud_incident_id"],
                "reason": decision["reason"],
                "severity": decision["severity"],
                "recommendation": decision["recommendation"],
            }))
        edge_at, cloud_at, decision_at = map(datetime.fromisoformat, (
            incident["timestamp"], stored["cloud_received_at"], decision["decision_timestamp"],
        ))
        latencies.append((
            (cloud_at - edge_at).total_seconds() * 1000,
            (decision_at - cloud_at).total_seconds() * 1000,
            (decision_at - edge_at).total_seconds() * 1000,
        ))

    metrics = {
        "run": run_number,
        "auth_mode": auth_mode,
        "channel_mode": channel_mode,
        "incidents": len(edge),
        "cloud_copies": len(cloud),
        "decisions": len(decisions),
        "latency_mean_ms": dict(zip(
            ("edge_to_cloud", "cloud_to_decision", "edge_to_decision"),
            map(mean, zip(*latencies)),
        )),
        "messages": dict(transport_counts | poll_counts),
        "mqtt_collection": transport_metrics[0],
        "coap_collection": transport_metrics[1],
    }
    print("B3_METRICS " + json.dumps(metrics))
    metrics_file = os.getenv("AIOT_B3_METRICS_FILE")
    if metrics_file:
        with open(metrics_file, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(metrics) + "\n")
