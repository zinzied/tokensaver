import unittest

from chef.compress import (
    _rtk_compress, cache_align, compress_log, compress_messages,
    compress_request, cost_level, json_crush,
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
        text = ("id 550e8400-e29b-41d4-a716-446655440000 at 2026-01-01T00:00:00Z "
                "req 550e8400-e29b-41d4-a716-446655440001 at 2026-01-02T00:00:00Z " * 4)
        out = cache_align(text)
        self.assertLess(len(out), len(text))
        self.assertIn("{UUID_0}", out)
        self.assertIn("{TS_", out)
        self.assertIn("# Dynamic values:", out)

    def test_cache_align_skips_short_text(self):
        self.assertEqual(cache_align("id 550e8400-e29b-41d4-a716-446655440000"), "id 550e8400-e29b-41d4-a716-446655440000")

    def test_cache_align_net_win_guard(self):
        # One UUID + filler: ledger would cost more than markers save.
        text = "see id 550e8400-e29b-41d4-a716-446655440000 for details. " + "filler words here. " * 12
        self.assertGreaterEqual(len(text), 200)
        self.assertEqual(cache_align(text), text)

    def test_cache_align_never_raises(self):
        for bad in (None, 42, ["x"], {"a": 1}):
            self.assertEqual(cache_align(bad), bad)

    def test_cache_align_in_pipeline(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        body = {"model": "m", "messages": [{"role": "tool", "content": ("trace %s " % uid) * 40}]}
        saved = compress_request(body, "m")
        self.assertGreater(saved, 0)
        self.assertIn("{UUID_", body["messages"][0]["content"])

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


class TestRtkStage(unittest.TestCase):
    def test_git_diff_hunks_capped(self):
        diff = "diff --git a/f.py b/f.py\n@@ -1,3 +1,200 @@\n" + "\n".join("+line%d" % i for i in range(300))
        out = _rtk_compress(diff)
        self.assertLess(len(out), len(diff))
        self.assertIn("hunk truncated", out)

    def test_grep_per_file_capped(self):
        grep_out = "\n".join("src/a.py:%d: match %d" % (i, i) for i in range(40))
        grep_out += "\n" + "x" * 600  # push over the 500-char minimum
        out = _rtk_compress(grep_out)
        self.assertLess(len(out), len(grep_out))
        self.assertIn("further matches capped", out)

    def test_build_output_keeps_errors(self):
        build = "\n".join("Compiling pkg%d v1.0" % i for i in range(30))
        build += "\nERROR: linker failed for target foo\n" + "ok line\n" * 10
        build += "y" * 600
        out = _rtk_compress(build)
        self.assertLess(len(out), len(build))
        self.assertIn("linker failed", out)

    def test_never_expands(self):
        for text in ("short", "x" * 400, "random prose " * 60):
            self.assertLessEqual(len(_rtk_compress(text)), len(text))
        self.assertEqual(_rtk_compress(""), "")

    def test_timestamped_logs_not_treated_as_grep(self):
        logs = "\n".join("2026-08-07T12:00:%02dZ INFO worker %d did thing %d" % (i % 60, i, i) for i in range(30))
        logs += "\n" + "z" * 600
        out = _rtk_compress(logs)
        self.assertNotIn("further matches capped", out)
        self.assertLessEqual(len(out), len(logs))

    def test_rtk_wired_into_pipeline(self):
        diff = "diff --git a/f.py b/f.py\n@@ -1,3 +1,200 @@\n" + "\n".join("+line%d" % i for i in range(300))
        body = {"model": "m", "messages": [{"role": "tool", "content": diff}]}
        saved = compress_request(body, "m")
        self.assertGreater(saved, 0)


class TestSlidingWindow(unittest.TestCase):
    def test_large_history_compresses_without_dropping(self):
        messages = [{"role": "user", "content": "x" * 2200} for _ in range(60)]
        saved, count = compress_messages(messages, "cheap")
        self.assertEqual(count, 60)
        self.assertEqual(len(messages), 60)
        self.assertGreater(saved, 0)

    def test_large_history_preserves_tool_shapes(self):
        messages = [
            {"role": "user", "content": "tool dump %d " % i + "y" * 2000,
             "tool_calls": [{"id": "t%d" % i, "type": "function"}]}
            for i in range(60)
        ]
        saved, _ = compress_messages(messages, "cheap")
        self.assertGreater(saved, 0)
        for m in messages:
            self.assertIn("tool_calls", m)
            self.assertIn("role", m)

    def test_small_history_unaffected(self):
        messages = [{"role": "user", "content": "hi"}]
        saved, count = compress_messages(messages, "cheap")
        self.assertEqual(count, 1)
        self.assertEqual(messages[0]["content"], "hi")
        self.assertEqual(saved, 0)

    def test_recent_messages_keep_normal_caps(self):
        old = [{"role": "user", "content": "o" * 3000} for _ in range(50)]
        recent = [{"role": "user", "content": "r" * 3000} for _ in range(10)]
        messages = old + recent
        compress_messages(messages, "cheap")
        # Old messages use tightest caps (<=400 chars + marker), recent keep
        # cheap-tier caps (<=3000).
        self.assertLessEqual(len(messages[0]["content"]), 600)
        self.assertGreater(len(messages[-1]["content"]), len(messages[0]["content"]))


if __name__ == "__main__":
    unittest.main()
