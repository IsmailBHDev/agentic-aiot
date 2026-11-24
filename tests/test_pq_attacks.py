"""IOT-175 : les attaques S1 à S3 dégradent C0 et sont neutralisées en C1 et C2.

Version courte (20 itérations du test historique) de src/evaluate_pq_attacks.py.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import evaluate_pq_attacks  # noqa: E402
import mqtt_edge_adapter  # noqa: E402

DETECTION = ("tp", "fp", "fn", "tn", "no_decision")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    saved = {name: getattr(mqtt_edge_adapter, name) for name in (
        *evaluate_pq_attacks.STATE, "collection_metrics", "message_verifier", "analyze_devices",
    )}
    saved_edge = {name: getattr(edge_agent, name) for name in (
        "DATA_DIR", "INCIDENT_FILE", "isolated_devices_by_session",
    )}
    try:
        yield evaluate_pq_attacks.evaluate(limit=20, workdir=tmp_path_factory.mktemp("attacks"))
    finally:
        for name, value in saved.items():
            setattr(mqtt_edge_adapter, name, value)
        for name, value in saved_edge.items():
            setattr(edge_agent, name, value)


def detection(metrics):
    return {key: metrics[key] for key in DETECTION}


def test_signatures_do_not_change_the_baseline(results):
    baseline = results["baseline"]
    assert detection(baseline["ed25519"]) == detection(baseline["none"])
    assert detection(baseline["ml-dsa-44"]) == detection(baseline["none"])
    assert baseline["ml-dsa-44"]["messages_auth_rejected"] == 0


@pytest.mark.parametrize("scenario", ["S1_forged_pair", "S2_replay"])
def test_attacks_degrade_c0_and_are_blocked_by_signatures(results, scenario):
    baseline = detection(results["baseline"]["none"])
    attacked = results[scenario]

    assert detection(attacked["none"]) != baseline
    assert attacked["none"]["fp"] + attacked["none"]["fn"] > baseline["fp"] + baseline["fn"]
    for algorithm in ("ed25519", "ml-dsa-44"):
        assert detection(attacked[algorithm]) == baseline
        assert attacked[algorithm]["messages_auth_rejected"] > 0


def test_fake_local_alerts_create_incidents_only_without_signatures(results):
    fake = results["S3_fake_alerts"]
    assert fake["none"]["incidents_created"] == evaluate_pq_attacks.FAKE_ALERTS
    assert fake["ed25519"]["incidents_created"] == 0
    assert fake["ml-dsa-44"]["incidents_created"] == 0
