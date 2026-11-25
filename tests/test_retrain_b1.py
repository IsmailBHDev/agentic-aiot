"""IOT-157 : réentraînement de B1 à partir des journaux Edge, puis publication OTA."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evaluate_e07  # noqa: E402
import evaluate_tinyml  # noqa: E402
import message_auth  # noqa: E402
import ota  # noqa: E402
import retrain_b1  # noqa: E402

ALGORITHM = "ed25519"


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Pipeline complet : v1 de référence publiée, réentraînement, v2 publiée et installée."""
    root = tmp_path_factory.mktemp("retrain")
    private_key = message_auth.generate_private_key(ALGORITHM)
    repo = root / "repo"
    reference, _, _ = evaluate_tinyml.train_reference()
    ota.publish_release(repo, reference, 1, ALGORITHM, private_key)
    device = ota.DeviceOta(root / "device", ALGORITHM, private_key.public_key())
    assert device.update(repo)["status"] == "installed"
    results = retrain_b1.run_pipeline(root, repo, ALGORITHM, private_key)
    return results, repo, device


def test_sessions_never_touch_the_historical_test_or_e07():
    seeds = {*retrain_b1.FEEDBACK_SEEDS, retrain_b1.VALIDATION_SEED, retrain_b1.TEST_SEED}
    assert len(seeds) == 4
    assert not seeds & {42, *evaluate_e07.SEEDS}


def test_pipeline_reports_both_label_sources(pipeline):
    results, _, _ = pipeline
    assert results["sessions"]["historical_test_used"] is False
    assert set(results["candidates"]) == {"incidents", "annotated"}
    for record in results["candidates"].values():
        assert record["feedback_rows"] == 6000
        assert record["training_rows"] == 2400 + 6000
        assert len(record["dataset_sha256"]) == len(record["model_sha256"]) == 64
        assert record["validation"]["b1"]["n"] == record["test"]["b1"]["n"] == 3000


def test_collection_goes_through_the_edge(pipeline):
    results, _, _ = pipeline
    for item in results["collection"].values():
        assert item["measurements"] == 3000
        assert item["incidents"] == sum(item["incidents_by_reason"].values()) > 0


def test_incident_labels_are_imperfect(pipeline):
    """Les incidents ne couvrent pas toutes les anomalies (isolement, B1 imparfait)."""
    quality = pipeline[0]["incident_label_quality"]
    assert quality["n"] == 6000
    assert 0 < quality["recall"] < 1


def test_promotion_requires_no_validation_regression(pipeline):
    results, _, _ = pipeline
    active = results["active_v1"]["validation"]["b1"]["f1"]
    for record in results["candidates"].values():
        assert record["promoted"] == (record["validation"]["b1"]["f1"] >= active)


def test_promoted_model_is_published_and_installed_by_ota(pipeline):
    results, repo, device = pipeline
    if results["published"] is None:
        pytest.skip("aucun candidat promu")
    assert results["published"]["version"] == 2
    release = ota.latest_release(repo)
    assert release["version"] == 2 and release["alg"] == ALGORITHM
    source = results["published"]["label_source"]
    assert release["metadata"]["model_sha256"] == results["candidates"][source]["model_sha256"]
    assert device.update(repo)["status"] == "installed"
    assert device.active_version == 2


def row(iteration, device, label):
    return {"session_id": "s", "iteration": iteration, "device_id": device,
            "temperature": 25.0, "vibration": 0.3, "label": label}


def test_dataset_joins_incidents_and_annotations():
    truth = pd.DataFrame([row(1, "node-01", 1), row(1, "node-02", 0), row(2, "node-01", 1)])
    telemetry = truth[retrain_b1.KEY + retrain_b1.FEATURES].assign(b1_prediction=[1, 0, 0])
    incidents = [{"session_id": "s", "iteration": 1, "device_id": "node-01", "reason": "LOCAL_ML_ANOMALY"}]

    by_incident = retrain_b1.build_dataset(telemetry, incidents, truth, "incidents")
    assert by_incident["train_label"].tolist() == [1, 0, 0]
    annotated = retrain_b1.build_dataset(telemetry, incidents, truth, "annotated")
    assert annotated["train_label"].tolist() == [1, 0, 1]
    with pytest.raises(ValueError):
        retrain_b1.build_dataset(telemetry, incidents, truth.iloc[:2], "annotated")


def test_dataset_hash_is_deterministic():
    frame = pd.DataFrame([row(1, "node-01", 1)])
    assert retrain_b1.sha256_frame(frame) == retrain_b1.sha256_frame(frame.copy())
