# Agentic-AIoT — Autonomous Anomaly Detection for IoT/Edge Systems

## Overview

Agentic-AIoT is an academic prototype exploring autonomous anomaly detection and response in IoT/Edge environments.

The system simulates three industrial IoT devices and an Edge Coordinator. Each device performs local machine learning inference, while the Edge Coordinator analyzes sensor consistency, records incidents, and logically isolates suspicious devices.

## Architecture

- **Device Layer:** Simulated IoT sensors, local ML inference, anomaly detection, and safe-mode activation.
- **Edge Layer:** Multi-device consistency analysis, incident logging, and logical device isolation.
- **Cloud Layer:** Planned for future development.

## Implemented Features

- Three simulated IoT devices
- Temperature and vibration monitoring
- Synthetic dataset generation
- Decision Tree anomaly classifier
- Local ML inference
- False Data Injection (FDI) simulation
- Edge-level anomaly detection using median-based consistency checks
- Incident logging in JSONL format
- Logical isolation of suspicious devices
- ML inference latency measurement

## Initial Performance Results

| Metric | Result |
|---|---|
| Test accuracy (synthetic dataset) | 100% |
| Average inference latency | 2.033 ms |
| Maximum inference latency | 15.2237 ms |
| P95 inference latency | 5.2616 ms |
| Serialized model size | 1,801 bytes |

Performance measurements were obtained from the Python simulation environment. They do not represent ESP32 hardware benchmarks.

## Run the whole chain with Docker

One command starts the broker, the Edge (MQTT-SN gateway, MQTT adapter, CoAP
server, Edge→Cloud bridge) and the Cloud (MCP server, A2A service,
orchestrator). Requires Docker with Compose; ports are published on
127.0.0.1 only.

```bash
docker compose up -d --build                  # Edge + Cloud + broker
docker compose --profile demo run --rm device-sim   # 10 iterations of 3 simulated sensors
docker compose logs -f edge-mqtt cloud-orchestrator # follow incidents and decisions
docker compose down                           # stop while keeping the Edge/Cloud logs
```

| Service | Role | Port on 127.0.0.1 |
|---|---|---|
| `mosquitto` | MQTT broker | 1883/tcp |
| `edge-gateway` | MQTT-SN → MQTT gateway | 10000/udp |
| `edge-mqtt`, `edge-coap` | B2 Edge over MQTT and CoAP | 5683/udp (CoAP) |
| `edge-bridge` | Edge incidents → MCP, resumes from a state file | — |
| `cloud-mcp`, `cloud-a2a`, `cloud-orchestrator` | Cloud storage, rule-based analysis, decisions | 8000, 9000 |
| `device-sim` (profile `demo`) | Three simulated sensors | — |

Edge incidents and Cloud incidents/decisions are kept in the named volumes
`edge-data` and `cloud-data` (`/data/edge`, `/data/cloud` in the containers).
Use `docker compose down -v` only when those journals can be deleted.
The security options (`AIOT_AUTH_MODE`, `AIOT_CHANNEL_MODE`,
`AIOT_MODEL_SIGNING`, `AIOT_EDGE_POLICY_FILE`) stay off by default; enabling
them in containers also requires mounting the keys (`AIOT_KEY_DIR`).
`docker compose up -d mosquitto` still starts the broker alone for the
network tests.

## Installation

Install the required dependencies:

```bash
python -m pip install -r requirements.txt
```

Generate the dataset:

```bash
python src/generate_dataset.py
```

Train the model:

```bash
python src/train_model.py
```

Run the simulation:

```bash
python src/device_simulator.py
```

The simulator sends telemetry through MQTT-SN and the MQTT gateway. CoAP
telemetry uses the CoAP server and can be exercised with the CoAP client.
The TCP server in src/edge_server.py is a historical entry point outside
the active simulation and the B2/B3 experimental results.

### Collection metrics

MQTT and CoAP log cumulative counters every 30 seconds. The counters cover
received and invalid messages, duplicate deliveries, messages for closed
batches, completed batches and expired batches. Each batch has a five-second
collection window, measured from the first accepted observation. The
assembly-time total in seconds divided by the completed-batch count gives the
mean time from the first to the third accepted observation. The number of
observations missing at timeout measures the collection shortfall, which can
include delayed messages as well as losses. The tests simulate this shortfall
by withholding messages until the deadline.

Run the transport checks against a local Mosquitto broker and an ephemeral
CoAP endpoint from PowerShell:

```powershell
$env:AIOT_TEST_NETWORK = '1'
python -m pytest tests/test_edge_b2.py -k transport_retries
```

## Research and reproduction

- [Report figures, algorithms and one-session demo](docs/research_delivery.md)
- [Frozen and multi-session detection protocols](docs/experimental_protocol.md)
- [Cloud and B3 evaluation](README-CLOUD-MVP.md)
- [Literature review](docs/literature_review.md)

## Roadmap

- MQTT-SN and CoAP communication
- Device-to-Edge network integration
- MCP and A2A agent communication
- Cloud-level intelligence and RAG
- Model updates and OTA simulation
- Containerized deployment and demonstration

## Project Status

Academic software prototype. Integration tests exercise MQTT-SN, MQTT, CoAP,
MCP and A2A over loopback. The experimental evaluation uses simulated sensor
inputs and does not include a hardware deployment.
