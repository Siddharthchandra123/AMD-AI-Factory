"""Offline smoke tests of timestamp and percentile logic."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from diagnose_latency_v0_6 import iso_seconds, percentiles

class TestTiming(unittest.TestCase):
    def test_timestamp_delta(self):
        self.assertEqual(iso_seconds('2026-10-26T10:11:56+00:00','2026-10-26T10:11:58+00:00'), 2)
    def test_empty_delta(self):
        self.assertIsNone(iso_seconds(None, None))
    def test_p50(self):
        self.assertEqual(percentiles([1,2,3], .5), 2)
    def test_p95(self):
        self.assertEqual(percentiles([0,10], .95), 9.5)
    def test_empty_percentile(self):
        self.assertIsNone(percentiles([], .95))

if __name__ == '__main__':
    unittest.main()
