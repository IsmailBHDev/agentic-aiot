"""IOT-156 : contrainte TinyML simulée pour B1."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_tinyml  # noqa: E402


@pytest.fixture(scope="module")
def results():
    return evaluate_tinyml.evaluate(repetitions=1)


def test_retrained_b1_matches_the_reference(results):
    assert results["reference_check"]["retrained_matches_reference_predictions"]
    assert results["variants"]["sklearn_joblib"]["f1_test"] == 0.8493


@pytest.mark.parametrize("variant", ["pruned_float64", "pruned_int32_milli", "pruned_int16_centi"])
def test_compressed_variants_keep_every_prediction(results, variant):
    item = results["variants"][variant]
    assert item["agreement_test"] == 600
    assert item["agreement_train"] == 2400
    assert item["f1_test"] == results["variants"]["sklearn_joblib"]["f1_test"]


def test_compression_reduces_nodes_and_bytes(results):
    variants = results["variants"]
    assert variants["pruned_float64"]["nodes"] < variants["sklearn_joblib"]["nodes"]
    assert (variants["pruned_int16_centi"]["bytes"] < variants["pruned_int32_milli"]["bytes"]
            < variants["pruned_float64"]["bytes"] < variants["sklearn_joblib"]["bytes"])


def test_pruning_never_changes_a_prediction():
    model, train, _ = evaluate_tinyml.train_reference()
    nodes = evaluate_tinyml.tree_nodes(model)
    pruned = evaluate_tinyml.prune(nodes)
    for values in train[evaluate_tinyml.FEATURES].to_numpy().tolist():
        assert evaluate_tinyml.predict(nodes, values) == evaluate_tinyml.predict(pruned, values)


def test_deployed_simulator_model_is_reported(results):
    deployed = results["deployed_simulator_model"]
    assert deployed is not None
    assert deployed["agreement_with_reference_b1_test"] <= 600
