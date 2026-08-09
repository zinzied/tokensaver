import unittest
from unittest import mock

import chef.config as _cfg
_cfg.OPENROUTER_API_KEY = "sk-test"  # enable openrouter provider for routing tests

from chef.proxy import _last_user_text
from chef.upstream import complete


class TestLastUserText(unittest.TestCase):
    def test_string_content(self):
        body = {"messages": [{"role": "user", "content": "fix the typo"}]}
        self.assertEqual(_last_user_text(body), "fix the typo")

    def test_last_user_wins(self):
        body = {"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
        ]}
        self.assertEqual(_last_user_text(body), "second")

    def test_tool_result_ignored(self):
        body = {"messages": [{"role": "user", "content": [{"type": "tool_result", "content": "x"}]}]}
        self.assertEqual(_last_user_text(body), "")


class TestCompleteDifficultyRouting(unittest.TestCase):
    def _run(self, text):
        payload = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}
        with mock.patch("chef.upstream._request") as req:
            req.return_value = mock.MagicMock()
            req.return_value.read.return_value = b'{"choices": [{"message": {"content": "ok"}}]}'
            complete(payload, text=text)
            return req.call_args[0][2]

    def test_hard_uses_paid_route(self):
        called = self._run(
            "redesign the distributed microservice architecture and fix the deadlock in k8s")
        self.assertNotIn(":free", called["model"])
        self.assertTrue(called["model"].startswith("openai/") or called["model"].startswith("anthropic/"))

    def test_easy_uses_free_route(self):
        called = self._run("rename the typo in the comment")
        self.assertIn(":free", called["model"])

    def test_medium_uses_free_code_model(self):
        called = self._run("fix the login bug in the auth module")
        self.assertEqual(called["model"], "cohere/north-mini-code:free")

    def test_explicit_model_ignores_difficulty(self):
        called = self._run_with_hint("chef/deepseek-chat", "hard architecture redesign")
        self.assertEqual(called["model"], "openai/gpt-oss-20b:free")

    def _run_with_hint(self, model, text):
        payload = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}
        with mock.patch("chef.upstream._request") as req:
            req.return_value = mock.MagicMock()
            req.return_value.read.return_value = b'{"choices": [{"message": {"content": "ok"}}]}'
            complete(payload, model_hint=model, text=text)
            return req.call_args[0][2]


if __name__ == "__main__":
    unittest.main()
