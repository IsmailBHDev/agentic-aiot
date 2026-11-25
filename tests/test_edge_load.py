"""IOT-154 : surcharge de l'Edge (version courte) et coût de l'anti-rejeu."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_agent  # noqa: E402
import evaluate_edge_load  # noqa: E402
import message_auth  # noqa: E402
import mqtt_edge_adapter  # noqa: E402


def test_load_evaluation_reports_every_rate_and_restores_the_edge(tmp_path):
    results = evaluate_edge_load.evaluate(
        rates=(200, 400), configurations=("none", "ml-dsa-44"),
        duration=0.3, max_messages=300, workdir=tmp_path,
    )

    for algorithm in ("none", "ml-dsa-44"):
        points = results[algorithm]["points"]
        assert [point["offered_rate"] for point in points] == [200, 400]
        for point in points:
            assert point["messages"] % 3 == 0
            assert point["batches_completed"] == point["messages"] // 3
            assert point["messages_auth_rejected"] == 0
            assert point["messages_invalid"] == 0
    assert mqtt_edge_adapter.message_verifier is None
    assert mqtt_edge_adapter.analyze_devices is edge_agent.analyze_devices


def test_replay_memory_forgets_only_expired_counters():
    """Régression IOT-154 : l'oubli ne parcourt plus tous les compteurs vus."""
    clock = SimpleNamespace(now=0.0)
    private = message_auth.generate_private_key("ed25519")
    signer = message_auth.DeviceSigner("node-01", "ed25519", private)
    verifier = message_auth.EdgeVerifier(
        "ed25519", {"node-01": private.public_key()}, clock=lambda: clock.now
    )
    message = {"src": {"agent": "node-01"}, "payload": {"temperature": 25.0}}

    for step in range(2000):
        clock.now = step * 0.1
        verifier.verify(signer.sign(message))
    # 2 000 messages en 200 s : tous restent dans la fenêtre de 305 s.
    # Une fois la fenêtre dépassée, un seul passage les oublie tous.
    assert len(verifier._seen) == 2000
    clock.now = 200 + message_auth.REPLAY_RETENTION_SECONDS
    verifier.verify(signer.sign(message))
    assert len(verifier._seen) == 1
    assert len(verifier._order) == 1
