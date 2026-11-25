"""IOT-155 : benchmark des trois niveaux (version courte)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_tiers  # noqa: E402


def test_every_tier_is_measured(tmp_path):
    results = evaluate_tiers.evaluate(repetitions=20, workdir=tmp_path)

    device, edge, cloud = results["device"], results["edge"], results["cloud"]
    assert device["model_bytes"] > 0
    assert device["inference_with_dataframe"]["n"] == 20
    assert set(device["message_signing"]) == {"ed25519", "ml-dsa-44"}
    assert set(edge["on_message"]) == {"none", "ml-dsa-44"}
    assert edge["b2_batch_calculation"]["mean_ms"] > 0
    assert cloud["store_incident"]["n"] == 20
    assert cloud["open_sealed_incident_ml_kem_768"]["n"] == 20
    assert "mean_ms" in cloud["a2a_rule_analysis"] or "skipped" in cloud["a2a_rule_analysis"]
    assert cloud["rag_supervisor"] is None
    assert "| Edge |" in evaluate_tiers.table(results)
