import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from chef import ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._tmp.name, "chef-ledger.jsonl")
        self._patch = unittest.mock.patch.object(ledger, "LEDGER_PATH", __import__("pathlib").Path(self._path))
        self._patch.start()
        ledger.reset()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _rec(self, ts, usd=0.0, chars=0, tokens=0):
        ledger.record({
            "ts": ts, "model_requested": "gpt-5", "model_routed": "deepseek:free",
            "chars_saved": chars, "frost_saved_tokens": 0,
            "tokens_saved": tokens, "usd_saved": usd,
        })

    def test_roundtrip_and_reset(self):
        ledger.record({"ts": "2026-08-09T10:00:00", "model_requested": "gpt-5", "chars_saved": 100})
        self.assertEqual(len(ledger.read()), 1)
        ledger.reset()
        self.assertEqual(ledger.read(), [])

    def test_today_aggregates_current_day_only(self):
        now = datetime.now()
        self._rec(now.isoformat(timespec="seconds"), usd=0.0012, chars=400, tokens=100)
        self._rec(now.isoformat(timespec="seconds"), usd=0.0003, chars=100, tokens=25)
        self._rec((now - timedelta(days=1)).isoformat(timespec="seconds"), usd=9.9, chars=999, tokens=999)
        t = ledger.today()
        self.assertEqual(t["requests"], 2)
        self.assertEqual(t["chars_saved"], 500)
        self.assertEqual(t["tokens_saved"], 125)
        self.assertAlmostEqual(t["usd_saved"], 0.0015, places=6)

    def test_week_series_zero_filled_and_ordered(self):
        now = datetime.now()
        self._rec(now.isoformat(timespec="seconds"), usd=0.5)
        week = ledger.week_series(7)
        self.assertEqual(len(week), 7)
        self.assertEqual(week[-1]["date"], date.today().isoformat())
        self.assertEqual(week[-1]["requests"], 1)
        self.assertEqual(week[-1]["usd_saved"], 0.5)
        self.assertEqual(week[0]["requests"], 0)

    def test_recent_returns_last_n(self):
        for i in range(5):
            self._rec("2026-08-09T10:00:%02d" % i)
        entries = ledger.recent(2)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["ts"], "2026-08-09T10:00:04")

    def test_record_never_raises_on_bad_path(self):
        with unittest.mock.patch.object(ledger, "LEDGER_PATH", __import__("pathlib").Path("Z:/nope/ledger.jsonl")):
            try:
                ledger.record({"a": 1})
            except Exception as exc:  # pragma: no cover
                self.fail("record raised: %s" % exc)

    def test_missing_ts_defaults_to_now(self):
        ledger.record({"chars_saved": 10})
        e = ledger.read()[0]
        self.assertIn("ts", e)
        self.assertEqual(e["chars_saved"], 10)


if __name__ == "__main__":
    unittest.main()
