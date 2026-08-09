import unittest

from chef.catalog import CATALOG_BY_ID, MODELS, DEFAULT, resolve_candidates


class TestRouter(unittest.TestCase):
    def test_gpt5_routes_to_free_oss(self):
        cands = resolve_candidates("gpt-5")
        self.assertEqual(cands[0], ("openrouter", "openai/gpt-oss-20b:free"))

    def test_gpt4o_routes_to_free(self):
        cands = resolve_candidates("gpt-4o")
        self.assertEqual(cands[0][0], "openrouter")
        self.assertIn(":free", cands[0][1])

    def test_claude_routes_to_free(self):
        cands = resolve_candidates("claude-3-5-sonnet")
        self.assertEqual(cands[0][0], "openrouter")
        self.assertIn(":free", cands[0][1])

    def test_o1_routes_to_reasoner(self):
        cands = resolve_candidates("o1-preview")
        self.assertEqual(cands[0], ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"))

    def test_gemini_routes_to_free_flash(self):
        cands = resolve_candidates("gemini-2.5-pro")
        self.assertEqual(cands[0][1], "google/gemma-4-31b-it:free")

    def test_direct_chef_id(self):
        self.assertEqual(resolve_candidates("chef/qwen-coder"), [("openrouter", "cohere/north-mini-code:free")])

    def test_free_passthrough(self):
        self.assertEqual(resolve_candidates("some/model:free"), [("openrouter", "some/model:free")])

    def test_empty_uses_default(self):
        self.assertEqual(resolve_candidates(""), resolve_candidates(DEFAULT))

    def test_candidates_limited_and_unique(self):
        cands = resolve_candidates("gpt-5")
        self.assertLessEqual(len(cands), 3)
        keys = {(p, r) for p, r in cands}
        self.assertEqual(len(keys), len(cands))

    def test_catalog_wellformed(self):
        for m in MODELS:
            self.assertIn(m["id"], CATALOG_BY_ID)
            self.assertIn("provider", m)
            self.assertIn("route", m)


if __name__ == "__main__":
    unittest.main()
