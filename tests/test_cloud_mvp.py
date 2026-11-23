import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cloud_store import report_incident, list_incidents, request_model_update


class CloudStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'AIOT_CLOUD_INCIDENT_FILE': str(Path(self.tmp.name) / 'cloud.jsonl')})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_report_and_list(self):
        result = report_incident({'device_id': 'node-02', 'reason': 'SENSOR_INCONSISTENCY', 'session_id': 'test-1'})
        self.assertEqual(result['status'], 'accepted')
        records = list_incidents(10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['device_id'], 'node-02')
        self.assertEqual(records[0]['cloud_incident_id'], result['incident_id'])

    def test_invalid_report(self):
        with self.assertRaises(ValueError):
            report_incident({'device_id': 'node-01'})

    def test_update_ack_is_not_ota(self):
        result = request_model_update('node-03')
        self.assertEqual(result['status'], 'acknowledged')
        self.assertIn('no OTA', result['note'])


if __name__ == '__main__':
    unittest.main()
