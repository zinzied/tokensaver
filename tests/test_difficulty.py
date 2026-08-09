import unittest
from unittest import mock

from chef.difficulty import classify
from chef.catalog import (
    PAID_CATALOG_BY_ID, PAID_MODELS, FREE_BY_LABEL, free_chain, paid_candidates,
    resolve_difficulty_candidates,
)


class TestClassify(unittest.TestCase):
    def test_easy_task(self):
        d = classify("rename the variable and fix the typo in the comment")
        self.assertEqual(d["label"], "EASY")
        self.assertLess(d["score"], 35)

    def test_trivial_question(self):
        d = classify("what is the capital of France")
        self.assertEqual(d["label"], "EASY")

    def test_medium_bug(self):
        d = classify("fix the login bug in the auth module")
        self.assertEqual(d["label"], "MEDIUM")
        self.assertGreaterEqual(d["score"], 35)

    def test_hard_task(self):
        d = classify(
            "redesign the distributed payment microservice architecture, "
            "fix the deadlock in the k8s deployment and add sharding to the production database"
        )
        self.assertEqual(d["label"], "HARD")
        self.assertGreaterEqual(d["score"], 65)

    def test_score_bounds(self):
        for text in ["", "a", "x" * 5000]:
            d = classify(text)
            self.assertIn(d["label"], ("EASY", "MEDIUM", "HARD"))
            self.assertLessEqual(d["score"], 100)
            self.assertGreaterEqual(d["score"], 0)

    def test_case_insensitive(self):
        self.assertEqual(classify("FIX THE TYPO").get("score"), classify("fix the typo").get("score"))


class TestDifficultyRouting(unittest.TestCase):
    def test_easy_routes_to_free_chat(self):
        cands = resolve_difficulty_candidates("rename the typo in the comment", "")
        self.assertEqual(cands[0], ("openrouter", "openai/gpt-oss-20b:free"))

    def test_hard_routes_to_paid_first(self):
        cands = resolve_difficulty_candidates(
            "redesign the distributed microservice architecture and fix the deadlock in k8s", "")
        self.assertEqual(cands[0][0], "openrouter")
        self.assertNotIn(":free", cands[0][1])
        self.assertTrue(cands[0][1].startswith("openai/") or cands[0][1].startswith("anthropic/"))

    def test_explicit_chef_id_honored(self):
        cands = resolve_difficulty_candidates("any text", "chef/qwen-coder")
        self.assertEqual(cands, [("openrouter", "cohere/north-mini-code:free")])

    def test_explicit_paid_id_honored(self):
        cands = resolve_difficulty_candidates("any text", "paid/gpt-5")
        self.assertEqual(cands, [("openrouter", "openai/gpt-5")])

    def test_free_passthrough_honored(self):
        cands = resolve_difficulty_candidates("hard architecture", "some/model:free")
        self.assertEqual(cands, [("openrouter", "some/model:free")])

    def test_budget_caps_paid_chain(self):
        cands = resolve_difficulty_candidates(
            "redesign the distributed microservice architecture and fix the deadlock in k8s", "")
        paid_routes = {m["route"]: m for m in PAID_MODELS}
        for prov, route in cands:
            if route in paid_routes:
                self.assertLessEqual(paid_routes[route]["usd_per_m_input"], 20.0)

    def test_free_chain_len_and_unique(self):
        chain = free_chain("chef/deepseek-reasoner")
        self.assertLessEqual(len(chain), 3)
        self.assertEqual(len({(p, r) for p, r in chain}), len(chain))

    def test_paid_catalog_wellformed(self):
        for m in PAID_MODELS:
            self.assertIn(m["id"], PAID_CATALOG_BY_ID)
            self.assertIn("provider", m)
            self.assertIn("route", m)
            self.assertGreater(m["usd_per_m_input"], 0)

    def test_paid_candidates_budget(self):
        cheap = paid_candidates(0.2)
        for _, _, m in cheap:
            self.assertLessEqual(m["usd_per_m_input"], 0.2)
        all_paid = paid_candidates(1000)
        self.assertEqual(len(all_paid), len(PAID_MODELS))

    def test_free_by_label_valid(self):
        from chef.catalog import CATALOG_BY_ID
        for label, mid in FREE_BY_LABEL.items():
            self.assertIn(label, ("EASY", "MEDIUM", "HARD"))
            self.assertIn(mid, CATALOG_BY_ID)


class TestFreeOnlyRouting(unittest.TestCase):
    def test_groq_only_expert_routes_to_groq_llama70b(self):
        import chef.config as _cfg
        from chef.upstream import candidates_for_difficulty
        with mock.patch.object(_cfg, "OPENROUTER_API_KEY", ""), \
             mock.patch.object(_cfg, "GEMINI_API_KEY", ""), \
             mock.patch.object(_cfg, "GROQ_API_KEY", "mock-key"):
            cands = candidates_for_difficulty(
                "", "redesign the distributed microservice architecture and fix the deadlock in k8s")
        self.assertEqual(cands[0], ("groq", "llama-3.3-70b-versatile"))

    def test_free_only_with_paid_key_uses_free_reasoning(self):
        import chef.config as _cfg
        from chef.catalog import model_for_tier, recommend
        with mock.patch.object(_cfg, "OPENROUTER_API_KEY", "mock-key"), \
             mock.patch.object(_cfg, "FREE_ONLY", True):
            self.assertEqual(model_for_tier("expert"), "chef/deepseek-reasoner")
            rec = recommend("redesign the distributed microservice architecture and fix the deadlock in k8s")
        self.assertEqual(rec["cost"], "free")
        self.assertEqual(rec["model_id"], "chef/deepseek-reasoner")

    def test_model_for_tier_budget_floor_uses_best_available_free(self):
        import chef.config as _cfg
        from chef.catalog import model_for_tier
        with mock.patch.object(_cfg, "OPENROUTER_API_KEY", "mock-key"):
            self.assertEqual(model_for_tier("expert", 0.01), "chef/deepseek-reasoner")


if __name__ == "__main__":
    unittest.main()
