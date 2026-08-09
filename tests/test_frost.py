import json
import os
import tempfile
import unittest
from unittest import mock

from chef import frost


def _body(system="S" * 300, user="hello"):
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}


class TestFrost(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cfg = os.path.join(self._tmp.name, "proxy.json")
        os.makedirs(os.path.dirname(self._cfg), exist_ok=True)
        self._path_patch = mock.patch.object(frost, "_CONFIG_PATH", self._cfg)
        self._path_patch.start()
        frost.reset()
        self._write_cfg({"frost": {"enabled": True, "allow_stateless_marker": True, "refresh_after_tokens": 50000}})

    def tearDown(self):
        self._path_patch.stop()
        self._tmp.cleanup()

    def _write_cfg(self, cfg):
        with open(self._cfg, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def test_second_identical_request_frozen(self):
        body1 = _body()
        body2 = _body()
        self.assertEqual(frost.frost_apply(body1, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(body1["messages"][0]["content"], "S" * 300)
        saved = frost.frost_apply(body2, "m1", "/v1/chat/completions")
        self.assertGreater(saved, 0)
        self.assertIn("[FROST]", body2["messages"][0]["content"])
        self.assertGreater(frost.total_saved(), 0)

    def test_disabled_never_frozen(self):
        self._write_cfg({"frost": {"enabled": False, "allow_stateless_marker": False}})
        body1 = _body()
        body2 = _body()
        self.assertEqual(frost.frost_apply(body1, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(frost.frost_apply(body2, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(body2["messages"][0]["content"], "S" * 300)

    def test_changed_system_not_frozen(self):
        frost.frost_apply(_body(system="AAA"), "m1", "/v1/chat/completions")
        body = _body(system="BBB")
        self.assertEqual(frost.frost_apply(body, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(body["messages"][0]["content"], "BBB")

    def test_different_model_not_frozen(self):
        frost.frost_apply(_body(), "m1", "/v1/chat/completions")
        body = _body()
        self.assertEqual(frost.frost_apply(body, "m2", "/v1/chat/completions"), 0)
        self.assertEqual(body["messages"][0]["content"], "S" * 300)

    def test_anthropic_system_frozen(self):
        a1 = {"system": "SY" * 300, "messages": [{"role": "user", "content": "hi"}]}
        a2 = {"system": "SY" * 300, "messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(frost.frost_apply(a1, "m1", "/v1/messages"), 0)
        saved = frost.frost_apply(a2, "m1", "/v1/messages")
        self.assertGreater(saved, 0)
        self.assertIn("[FROST]", a2["system"])

    def test_threshold_retriggers_full_send(self):
        body1 = _body()
        body2 = _body()
        self.assertEqual(frost.frost_apply(body1, "m1", "/v1/chat/completions"), 0)
        self._write_cfg({"frost": {"enabled": True, "allow_stateless_marker": True, "refresh_after_tokens": 1}})
        body3 = _body()
        self.assertEqual(frost.frost_apply(body3, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(body3["messages"][0]["content"], "S" * 300)

    def test_no_system_returns_zero(self):
        self.assertEqual(frost.frost_apply({"messages": [{"role": "user", "content": "x"}]}, "m1", "/v1/chat/completions"), 0)
        self.assertEqual(frost.frost_apply(None, "m1", "/v1/chat/completions"), 0)

    def test_no_config_file_returns_zero(self):
        os.remove(self._cfg)
        self.assertEqual(frost.frost_apply(_body(), "m1", "/v1/chat/completions"), 0)


if __name__ == "__main__":
    unittest.main()
