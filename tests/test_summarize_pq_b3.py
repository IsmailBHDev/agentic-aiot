"""IOT-178 : agrégation des métriques du banc B3 (sans réseau)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import summarize_pq_b3  # noqa: E402


def run(auth, channel, latency, mqtt_bytes, rejected=0):
    return {
        "run": 1, "auth_mode": auth, "channel_mode": channel,
        "incidents": 18, "cloud_copies": 18, "decisions": 18,
        "latency_mean_ms": {
            "edge_to_cloud": latency - 60, "cloud_to_decision": 60, "edge_to_decision": latency,
        },
        "messages": {
            "mqttsn_payload_bytes": mqtt_bytes, "coap_payload_bytes": 100,
            "mcp_request_body_bytes": 1000, "a2a_request_body_bytes": 500,
            "mcp_http_requests": 108, "a2a_http_requests": 18,
        },
        "mqtt_collection": {"messages_auth_rejected": rejected},
        "coap_collection": {},
    }


def test_summary_groups_configurations_and_compares_to_c0():
    summary = summarize_pq_b3.summarize([
        run("none", "none", 500.0, 6000),
        run("none", "none", 520.0, 6000),
        run("ml-dsa-44", "ml-kem-768", 530.0, 80000),
    ])

    c0 = summary["none|none"]
    c2 = summary["ml-dsa-44|ml-kem-768"]
    assert c0["runs"] == 2 and c0["incidents"] == 36
    assert c0["latency_mean_ms"]["edge_to_decision"] == 510.0
    assert c2["edge_to_decision_vs_c0_ms"] == 20.0
    assert c2["per_run_mean"]["mqttsn_payload_bytes"] == 80000
    assert c2["label"].startswith("C2")


def test_rejections_are_counted_and_table_is_rendered():
    summary = summarize_pq_b3.summarize([run("ed25519", "x25519", 505.0, 9000, rejected=2)])

    assert summary["ed25519|x25519"]["auth_rejected"] == 2
    assert "C1" in summarize_pq_b3.table(summary)
