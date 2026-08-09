import unittest

from chef.compress import (
    cache_align, compress_log, compress_messages, compress_request, cost_level,
    json_crush,
)


class TestCompress(unittest.TestCase):
    def test_json_crush_hoists_constants(self):
        import json
        out = json_crush(json.dumps([
            {"level": "INFO", "msg": "a" * 30},
            {"level": "INFO", "msg": "b" * 30},
            {"level": "INFO", "msg": "c" * 30},
        ]))
        self.assertIn("[CONSTANTS: level=INFO]", out)
        self.assertIn("[FIELDS: msg]", out)

    def test_json_crush_minifies(self):
        import json
        text = "[\n  1,\n  2,\n  3\n]"
        self.assertEqual(json_crush(text), "[1,2,3]")

    def test_compress_log_dedups_repeats(self):
        logs = "\n".join("2026-01-01 00:00:%02d INFO retrying call" % (i % 3) for i in range(20))
        out = compress_log(logs)
        self.assertLess(len(out), len(logs))
        self.assertIn("repeated", out)

    def test_compress_log_short_untouched(self):
        self.assertEqual(compress_log("one\ntwo\nthree"), "one\ntwo\nthree")

    def test_cache_align_replaces_volatiles(self):
        out = cache_align("id 550e8400-e29b-41d4-a716-446655440000 at 2026-01-01T00:00:00Z")
        self.assertIn("{UUID_0}", out)
        self.assertIn("{TS_", out)

    def test_cost_level(self):
        self.assertEqual(cost_level("gpt-5"), "expensive")
        self.assertEqual(cost_level("deepseek/deepseek-chat-v3:free"), "free")
        self.assertEqual(cost_level("qwen3-max"), "moderate")
        self.assertEqual(cost_level("groq/llama"), "cheap")
        self.assertEqual(cost_level(""), "cheap")

    def test_compress_messages_saves_chars(self):
        messages = [
            {"role": "system", "content": "x" * 5000},
            {"role": "user", "content": "hello"},
        ]
        saved, count = compress_messages(messages, "expensive")
        self.assertGreater(saved, 0)
        self.assertEqual(count, 2)
        self.assertLess(len(messages[0]["content"]), 5000)

    def test_compress_messages_removes_empty_fields(self):
        messages = [{"role": "user", "content": "hi", "name": "", "weight": None, "empty": []}]
        compress_messages(messages, "cheap")
        self.assertNotIn("name", messages[0])
        self.assertNotIn("weight", messages[0])

    def test_compress_messages_keeps_tool_shapes(self):
        messages = [{"role": "user", "content": [{"type": "text", "text": "a" * 400}]}]
        saved, _ = compress_messages(messages, "cheap")
        self.assertGreaterEqual(saved, 0)
        self.assertEqual(messages[0]["content"][0]["type"], "text")

    def test_compress_request_chat(self):
        body = {"model": "gpt-5", "messages": [{"role": "system", "content": "z" * 4000}]}
        saved = compress_request(body, "gpt-5")
        self.assertGreater(saved, 0)
        self.assertLess(len(body["messages"][0]["content"]), 4000)

    def test_compress_request_responses_shape(self):
        body = {"model": "gpt-5", "input": [{"role": "user", "content": "y" * 3000}]}
        saved = compress_request(body, "gpt-5")
        self.assertGreater(saved, 0)
        self.assertLess(len(body["input"][0]["content"]), 3000)

    def test_compress_request_never_raises(self):
        for bad in (None, "string", 42, {"messages": [{"content": []}]}, {"input": 5}):
            try:
                saved = compress_request(bad, "x")
                self.assertGreaterEqual(saved, 0)
            except Exception as exc:  # pragma: no cover
                self.fail("compress_request raised on %r: %s" % (bad, exc))

    def test_compress_request_string_input(self):
        body = {"model": "m", "input": "s" * 5000}
        saved = compress_request(body, "m")
        self.assertGreater(saved, 0)


if __name__ == "__main__":
    unittest.main()
