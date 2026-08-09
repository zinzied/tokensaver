import json
import os
import tempfile
import unittest
from unittest import mock

import chef.config as _cfg
from chef import frost as _frost

from chef import proxy
from chef.catalog import input_price_usd


def _no_frost(tmpdir):
    return mock.patch.object(_frost, "_CONFIG_PATH", os.path.join(tmpdir, "nope", "proxy.json"))


class TestCompressThreshold(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._frost = _no_frost(self._tmp.name)
        self._frost.start()
        proxy._total_saved["chars"] = 0
        proxy._total_saved["frost"] = 0

    def tearDown(self):
        self._frost.stop()
        self._tmp.cleanup()

    def _body(self, n=4000):
        return {"messages": [{"role": "system", "content": "z" * n}]}

    def test_large_request_is_compressed(self):
        body = self._body(4000)
        with mock.patch.object(_cfg, "COMPRESS", True), mock.patch.object(_cfg, "COMPRESS_MIN_TOKENS", 200):
            m = proxy._maybe_compress(body, "gpt-5")
        self.assertGreater(m["chars_saved"], 0)
        self.assertLess(len(body["messages"][0]["content"]), 4000)

    def test_tiny_request_skips_compression(self):
        body = self._body(4000)
        with mock.patch.object(_cfg, "COMPRESS", True), mock.patch.object(_cfg, "COMPRESS_MIN_TOKENS", 10 ** 9):
            m = proxy._maybe_compress(body, "gpt-5")
        self.assertEqual(m["chars_saved"], 0)
        self.assertEqual(len(body["messages"][0]["content"]), 4000)
        self.assertEqual(m["chars_before"], m["chars_after"])

    def test_metrics_keys_and_totals(self):
        body = self._body(4000)
        with mock.patch.object(_cfg, "COMPRESS", True), mock.patch.object(_cfg, "COMPRESS_MIN_TOKENS", 200):
            m = proxy._maybe_compress(body, "gpt-5")
        for k in ("chars_before", "chars_after", "chars_saved", "frost_tokens_saved"):
            self.assertIn(k, m)
        self.assertEqual(m["chars_before"] - m["chars_after"], m["chars_saved"])
        self.assertEqual(proxy._total_saved["chars"], m["chars_saved"])

    def test_non_dict_returns_zeros(self):
        with mock.patch.object(_cfg, "COMPRESS", True):
            self.assertEqual(proxy._maybe_compress(None, "x")["chars_saved"], 0)
            self.assertEqual(proxy._maybe_compress("str", "x")["chars_saved"], 0)


class TestInputPrice(unittest.TestCase):
    def test_known_models(self):
        self.assertEqual(input_price_usd("gpt-5"), 1.25)
        self.assertEqual(input_price_usd("openai/gpt-5"), 1.25)
        self.assertEqual(input_price_usd("paid/claude-sonnet"), 3.0)
        self.assertEqual(input_price_usd("anthropic/claude-sonnet-4-5"), 3.0)
        self.assertEqual(input_price_usd("paid/deepseek-chat"), 0.14)
        self.assertEqual(input_price_usd("gpt-5-mini"), 0.25)

    def test_free_and_local_zero(self):
        self.assertEqual(input_price_usd("deepseek/deepseek-chat-v3:free"), 0.0)
        self.assertEqual(input_price_usd("chef/deepseek-chat"), 0.0)
        self.assertEqual(input_price_usd("ollama/qwen3"), 0.0)
        self.assertEqual(input_price_usd(""), 0.0)
        self.assertEqual(input_price_usd(None), 0.0)

    def test_unknown_zero(self):
        self.assertEqual(input_price_usd("some/unknown-model-xyz"), 0.0)


class TestLogRequest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._frost = _no_frost(self._tmp.name)
        self._frost.start()
        proxy._AUDIT[:] = []
        self._recorder = mock.patch.object(proxy.ledger, "record")
        self._mock_record = self._recorder.start()

    def tearDown(self):
        self._recorder.stop()
        self._frost.stop()
        self._tmp.cleanup()

    def test_entry_fields_and_usd(self):
        metrics = {"chars_before": 4000, "chars_after": 400, "chars_saved": 3600, "frost_tokens_saved": 100}
        e = proxy._log_request("chat", "gpt-5", "deepseek/deepseek-chat-v3:free",
                               "build a web app", metrics, "/v1/chat/completions")
        self.assertEqual(e["tokens_saved"], 3600 // 4 + 100)
        self.assertAlmostEqual(e["usd_saved"], round((900 + 100) / 1e6 * 1.25, 6))
        self.assertEqual(e["model_requested"], "gpt-5")
        self.assertEqual(e["model_routed"], "deepseek/deepseek-chat-v3:free")
        snap = proxy.audit_snapshot()
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["ts"], e["ts"])
        self._mock_record.assert_called_once_with(e)

    def test_free_model_no_usd(self):
        metrics = {"chars_before": 100, "chars_after": 10, "chars_saved": 90, "frost_tokens_saved": 0}
        e = proxy._log_request("chat", "groq/llama-70b:free", "groq/llama-70b", "hi", metrics, "/v1/messages")
        self.assertEqual(e["usd_saved"], 0.0)

    def test_audit_ring_buffer_capped(self):
        metrics = {"chars_before": 0, "chars_after": 0, "chars_saved": 0, "frost_tokens_saved": 0}
        for i in range(proxy._MAX_AUDIT + 25):
            proxy._log_request("chat", "gpt-5", "deepseek:free", "x", metrics, "/v1/chat/completions")
        snap = proxy.audit_snapshot(1000)
        self.assertEqual(len(snap), proxy._MAX_AUDIT)
        self.assertEqual(snap[-1]["model_requested"], "gpt-5")

    def test_usd_saved_helper(self):
        metrics = {"chars_saved": 4000, "frost_tokens_saved": 0}
        self.assertEqual(proxy._usd_saved("gpt-5", metrics), round(1000 / 1e6 * 1.25, 6))
        self.assertEqual(proxy._usd_saved("deepseek:free", metrics), 0.0)


if __name__ == "__main__":
    unittest.main()
