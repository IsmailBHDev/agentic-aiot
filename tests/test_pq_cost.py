"""IOT-178 : cohérence des mesures de coût (version courte, sans valeur de référence)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_pq_cost  # noqa: E402


def test_sizes_follow_the_standards_and_grow_with_post_quantum_signatures():
    sizes = evaluate_pq_cost.message_sizes()
    telemetry = sizes["telemetry_message"]
    incident = sizes["sealed_incident"]

    assert telemetry["none"]["overhead_bytes"] == 0
    assert 0 < telemetry["ed25519"]["overhead_bytes"] < telemetry["ml-dsa-44"]["overhead_bytes"]
    assert telemetry["ml-dsa-44"]["bytes"] < telemetry["ml-dsa-65"]["bytes"] < telemetry["ml-dsa-87"]["bytes"]
    assert incident["x25519"]["bytes"] < incident["ml-kem-768"]["bytes"]
    assert incident["ml-kem-768"]["bytes"] < incident["x25519+ml-kem-768"]["bytes"]


def test_primitive_measurements_report_standard_sizes():
    results = evaluate_pq_cost.primitives(repetitions=3)

    assert results["ml-dsa-44"]["signature_bytes"] == 2420
    assert results["ml-kem-768"]["ciphertext_bytes"] == 1088
    assert results["ed25519"]["sign"]["n"] == 3


def test_edge_processing_accepts_every_signed_message():
    results = evaluate_pq_cost.edge_processing(repetitions=1, limit=5)

    for algorithm in evaluate_pq_cost.EDGE_CONFIGURATIONS:
        assert results[algorithm]["messages"] == 15
