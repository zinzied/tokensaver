import unittest
from unittest import mock

import chef.config as _cfg
_cfg.OPENROUTER_API_KEY = "sk-test"

from chef.catalog import (
    TIER_EFFORT, TIER_ORDER, TIER_FREE, escalate, model_for_tier, next_tier,
    recommend, tier_for_model, tier_for_score,
)
from chef.difficulty import is_uncertain
from chef.verify import verify


class TestTierLadder(unittest.TestCase):
    def test_tier_for_score(self):
        self.assertEqual(tier_for_score(10), "bulk")
        self.assertEqual(tier_for_score(42), "worker")
        self.assertEqual(tier_for_score(90), "expert")

    def test_tier_for_model(self):
        self.assertEqual(tier_for_model("chef/deepseek-chat"), "bulk")
        self.assertEqual(tier_for_model("chef/qwen-coder"), "worker")
        self.assertEqual(tier_for_model("chef/deepseek-reasoner"), "expert")
        self.assertEqual(tier_for_model("paid/gpt-5"), "expert")
        self.assertIsNone(tier_for_model("weird/model"))

    def test_next_tier(self):
        self.assertEqual(next_tier("bulk"), "worker")
        self.assertEqual(next_tier("worker"), "expert")
        self.assertIsNone(next_tier("expert"))
        self.assertIsNone(next_tier("nope"))

    def test_model_for_tier(self):
        self.assertEqual(model_for_tier("bulk"), "chef/deepseek-chat")
        self.assertEqual(model_for_tier("worker"), "chef/qwen-coder")
        self.assertEqual(model_for_tier("expert", 0.01), "chef/deepseek-reasoner")
        self.assertEqual(model_for_tier("expert", 0.2), "paid/deepseek-chat")

    def test_tier_effort_mapping(self):
        for tier in TIER_ORDER:
            self.assertIn(TIER_EFFORT[tier], ("low", "high", "max"))

    def test_recommend_easy(self):
        rec = recommend("rename the typo in the comment")
        self.assertEqual(rec["tier"], "bulk")
        self.assertEqual(rec["effort"], "low")
        self.assertEqual(rec["cost"], "free")
        self.assertEqual(rec["model_id"], "chef/deepseek-chat")

    def test_recommend_medium(self):
        rec = recommend("fix the login bug in the auth module")
        self.assertEqual(rec["tier"], "worker")
        self.assertEqual(rec["effort"], "high")
        self.assertEqual(rec["model_id"], "chef/qwen-coder")

    def test_recommend_hard_paid(self):
        rec = recommend("redesign the distributed microservice architecture and fix the deadlock in k8s")
        self.assertEqual(rec["tier"], "expert")
        self.assertEqual(rec["effort"], "max")
        self.assertEqual(rec["cost"], "paid")
        self.assertEqual(rec["model_id"], "paid/gpt-5")

    def test_recommend_hard_budget_floor(self):
        rec = recommend("redesign the distributed microservice architecture and fix the deadlock in k8s", 0.01)
        self.assertEqual(rec["tier"], "expert")
        self.assertEqual(rec["cost"], "free")
        self.assertEqual(rec["model_id"], "chef/deepseek-reasoner")

    def test_escalate(self):
        self.assertEqual(escalate("rename the typo"), "chef/qwen-coder")
        self.assertEqual(escalate("fix the login bug in auth"), "paid/gpt-5")
        self.assertIsNone(escalate("redesign the distributed architecture and fix the deadlock"))

    def test_recommend_has_chain(self):
        rec = recommend("rename the typo")
        self.assertTrue(len(rec["chain"]) >= 1)


class TestIsUncertain(unittest.TestCase):
    def test_detects_uncertainty(self):
        self.assertTrue(is_uncertain("I'm not sure this works"))
        self.assertTrue(is_uncertain("UNCERTAIN about that"))
        self.assertTrue(is_uncertain("I don't know the answer"))
        self.assertTrue(is_uncertain("cannot determine from the information given"))

    def test_does_not_false_positive(self):
        self.assertFalse(is_uncertain("here is the working solution"))
        self.assertFalse(is_uncertain("the variable is renamed"))
        self.assertFalse(is_uncertain(""))


class TestVerify(unittest.TestCase):
    def _patch_ask(self, raw):
        return mock.patch("chef.verify.ask", return_value=raw)

    def test_verdict_pass(self):
        with self._patch_ask("VERDICT: PASS\n\nFINDINGS:\nnone"):
            res = verify("add a login form", "login form added")
        self.assertEqual(res["verdict"], "PASS")

    def test_verdict_fail(self):
        with self._patch_ask("VERDICT: FAIL\n\nFINDINGS:\n- missing CSRF"):
            res = verify("add a login form", "login form added")
        self.assertEqual(res["verdict"], "FAIL")

    def test_verdict_unknown(self):
        with self._patch_ask("not sure what to say"):
            res = verify("task", "work")
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_fail_wins_over_pass_scan(self):
        with self._patch_ask("VERDICT: PASS\nbut actually VERDICT: FAIL"):
            res = verify("task", "work")
        self.assertEqual(res["verdict"], "FAIL")


class TestReasoningEffortPassthrough(unittest.TestCase):
    def _payload_called(self, effort):
        from chef.ask import ask
        with mock.patch("chef.upstream._request") as req:
            req.return_value = mock.MagicMock()
            req.return_value.read.return_value = b'{"choices": [{"message": {"content": "ok"}}]}'
            ask("rename the typo", reasoning_effort=effort)
            return req.call_args[0][2]

    def test_effort_injected_when_set(self):
        self.assertEqual(self._payload_called("low").get("reasoning_effort"), "low")

    def test_effort_absent_when_not_set(self):
        self.assertIsNone(self._payload_called(None).get("reasoning_effort"))


if __name__ == "__main__":
    unittest.main()
