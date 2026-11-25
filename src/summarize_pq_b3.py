"""IOT-178 : résumé des répétitions du banc B3 en réseau local, par configuration.

Entrée : le fichier JSON Lines écrit par ``tests/test_b3_integration.py`` lorsque
``AIOT_B3_METRICS_FILE`` est défini (une ligne par répétition).
Sortie : un nouveau fichier de résultats daté, sans toucher aux résultats existants.

Usage :
    python -B src/summarize_pq_b3.py artifacts/pq_b3_metrics.jsonl --output results/pq_b3_network_<date>.json
"""

import argparse
import json
import platform
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median

LATENCIES = ("edge_to_cloud", "cloud_to_decision", "edge_to_decision")
VOLUMES = (
    "mqttsn_payload_bytes", "coap_payload_bytes",
    "mcp_request_body_bytes", "a2a_request_body_bytes",
    "mcp_http_requests", "a2a_http_requests",
)
LABELS = {
    ("none", "none"): "C0 — sans protection",
    ("ed25519", "x25519"): "C1 — Ed25519 + X25519",
    ("ml-dsa-44", "ml-kem-768"): "C2 — ML-DSA-44 + ML-KEM-768",
    ("ml-dsa-44", "x25519+ml-kem-768"): "C2 hybride — ML-DSA-44 + X25519/ML-KEM-768",
}


def load(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def summarize(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[run.get("auth_mode", "none"), run.get("channel_mode", "none")].append(run)
    summary = {}
    for (auth, channel), items in groups.items():
        rejected = sum(
            run[part].get("messages_auth_rejected", 0)
            for run in items for part in ("mqtt_collection", "coap_collection")
        )
        summary[f"{auth}|{channel}"] = {
            "label": LABELS.get((auth, channel), f"{auth} + {channel}"),
            "auth_mode": auth,
            "channel_mode": channel,
            "runs": len(items),
            "incidents": sum(run["incidents"] for run in items),
            "decisions": sum(run["decisions"] for run in items),
            "auth_rejected": rejected,
            "latency_mean_ms": {
                name: round(fmean(run["latency_mean_ms"][name] for run in items), 2)
                for name in LATENCIES
            },
            "edge_to_decision_median_ms": round(
                median(run["latency_mean_ms"]["edge_to_decision"] for run in items), 2
            ),
            "edge_to_decision_range_ms": [
                round(min(run["latency_mean_ms"]["edge_to_decision"] for run in items), 2),
                round(max(run["latency_mean_ms"]["edge_to_decision"] for run in items), 2),
            ],
            "per_run_mean": {
                name: round(fmean(run["messages"].get(name, 0) for run in items), 1)
                for name in VOLUMES
            },
        }
    baseline = summary.get("none|none")
    if baseline:
        reference = baseline["edge_to_decision_median_ms"]
        for item in summary.values():
            item["edge_to_decision_median_vs_c0_ms"] = round(
                item["edge_to_decision_median_ms"] - reference, 2
            )
    return summary


def table(summary):
    lines = [
        "| Configuration | Répétitions | Livrés / décisions | Edge → décision, médiane (ms) | Min–max (ms) | Écart médian à C0 (ms) | Charge MQTT-SN + CoAP (octets) | Corps HTTP MCP (octets) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary.values():
        volume = item["per_run_mean"]
        lines.append(
            f"| {item['label']} | {item['runs']} | {item['incidents']}/{item['decisions']} | "
            f"{item['edge_to_decision_median_ms']} | "
            f"{item['edge_to_decision_range_ms'][0]}–{item['edge_to_decision_range_ms'][1]} | "
            f"{item.get('edge_to_decision_median_vs_c0_ms', '—')} | "
            f"{volume['mqttsn_payload_bytes'] + volume['coap_payload_bytes']:.0f} | "
            f"{volume['mcp_request_body_bytes']:.0f} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("metrics")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} existe déjà : choisir une nouvelle destination")
    runs = load(args.metrics)
    summary = summarize(runs)
    document = {
        "ticket": "IOT-178",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Banc B3 en boucle locale (Mosquitto, MQTT-SN, CoAP, MCP, A2A), scrutation de 20 ms.",
        "platform": {"python": platform.python_version(), "platform": platform.platform()},
        "summary": summary,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(summary))


if __name__ == "__main__":
    main()
