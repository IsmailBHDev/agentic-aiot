"""IOT-153 : coupure Device -> Edge (version courte de src/evaluate_device_loss.py)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import evaluate_device_loss  # noqa: E402
import mqtt_edge_adapter  # noqa: E402


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return evaluate_device_loss.evaluate(
        seeds=(7,), loss_rates=(0.0, 0.30), workdir=tmp_path_factory.mktemp("loss"),
    )


def test_without_loss_every_batch_matches_the_reference(results):
    run = results["loss_sweep"]["0.00"][0]
    assert run["batches_completed"] == 200
    assert run["batches_expired"] == 0
    assert run["b2_decisions_matching_reference"] == 600
    assert run["double_decisions"] == 0
    assert run["duplicates_ignored"] > 0  # retransmissions QoS 1 ignorées


def test_losses_expire_batches_without_double_or_wrong_decisions(results):
    run = results["loss_sweep"]["0.30"][0]
    assert run["batches_expired"] > 0
    assert run["double_decisions"] == 0
    assert run["b2_decisions_differing"] == 0
    assert run["b2_decisions"] == 3 * run["batches_completed"]


@pytest.mark.parametrize("rate", ["0.00", "0.30"])
def test_every_received_b1_alert_is_journaled_immediately(results, rate):
    run = results["loss_sweep"][rate][0]
    assert run["local_alerts_journaled"] == run["b1_alerts_received"]


def test_sensor_outage_expires_exactly_the_cut_iterations(results):
    outage = results["sensor_outage"]
    start, end = evaluate_device_loss.OUTAGE_ITERATIONS
    assert outage["batches_expired"] == end - start
    assert outage["observations_missing_at_timeout"] == end - start
    assert outage["batches_completed"] == 200 - (end - start)
    assert outage["b2_decisions_differing"] == 0
    assert outage["double_decisions"] == 0


def test_evaluation_restores_the_edge_state(results):
    assert mqtt_edge_adapter.message_verifier is None
    assert mqtt_edge_adapter.analyze_devices is edge_agent.analyze_devices
    assert mqtt_edge_adapter.time.__name__ == "time"
