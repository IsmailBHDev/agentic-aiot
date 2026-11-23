
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src")
)

try:
    from fastapi.testclient import TestClient
    from cloud_a2a_server import app
except ImportError:
    TestClient = None
    app = None


@unittest.skipIf(
    TestClient is None,
    "Install cloud dependencies"
)
class A2ATests(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_agent_card(self):
        response = self.client.get(
            "/.well-known/agent-card.json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["skills"][0]["id"],
            "incident_analysis"
        )

    def test_message_send(self):
        incident = {
            "cloud_incident_id": "test-incident-001",
            "device_id": "node-02",
            "reason": "SENSOR_INCONSISTENCY"
        }

        response = self.client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "parts": [
                            {
                                "type": "text",
                                "text": json.dumps(incident)
                            }
                        ]
                    }
                }
            }
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertIn("result", data)

        self.assertEqual(
            data["result"]["status"]["state"],
            "completed"
        )

        analysis_text = (
            data["result"]["artifacts"][0]["parts"][0]["text"]
        )

        analysis = json.loads(analysis_text)

        self.assertEqual(
            analysis["device_id"],
            "node-02"
        )

        self.assertEqual(
            analysis["reason"],
            "SENSOR_INCONSISTENCY"
        )

        self.assertEqual(
            analysis["severity"],
            "HIGH"
        )

        self.assertEqual(
            analysis["analysis_method"],
            "rule_based_v1"
        )

    def test_unknown_method(self):
        response = self.client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "unknown",
                "params": {}
            }
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json()["error"]["code"],
            -32601
        )


if __name__ == "__main__":
    unittest.main()
