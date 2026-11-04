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

## Roadmap

- MQTT-SN and CoAP communication
- Device-to-Edge network integration
- MCP and A2A agent communication
- Cloud-level intelligence and RAG
- Model updates and OTA simulation
- Containerized deployment and demonstration

## Project Status

Academic proof of concept under active development. The current implementation runs locally in Python; hardware deployment and real network communication are not yet implemented.
