import json
import unittest

from chef.proxy import anth_request_to_oai, oai_to_anth


class TestAnthropicToOpenAI(unittest.TestCase):
    def test_basic(self):
        body = {
            "model": "claude-3-5-sonnet",
            "max_tokens": 2048,
            "system": "be concise",
            "messages": [{"role": "user", "content": "hello"}],
        }
        oai = anth_request_to_oai(body, "deepseek/deepseek-chat-v3-0324:free", True)
        self.assertEqual(oai["model"], "deepseek/deepseek-chat-v3-0324:free")
        self.assertEqual(oai["stream"], True)
        self.assertEqual(oai["messages"][0], {"role": "system", "content": "be concise"})
        self.assertEqual(oai["messages"][1], {"role": "user", "content": "hello"})

    def test_tool_use_and_result(self):
        body = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "text", "text": "calling tool"},
                    {"type": "tool_use", "id": "toolu_01", "name": "read", "input": {"file": "a.txt"}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "file contents"},
                    {"type": "text", "text": "now what?"},
                ]},
            ],
        }
        oai = anth_request_to_oai(body, "m", True)
        self.assertEqual(oai["messages"][0]["tool_calls"][0]["function"]["name"], "read")
        self.assertEqual(oai["messages"][1]["role"], "tool")
        self.assertEqual(oai["messages"][2], {"role": "user", "content": "now what?"})

    def test_tools_translated(self):
        body = {"tools": [{"name": "read", "description": "read a file", "input_schema": {"type": "object"}}]}
        oai = anth_request_to_oai(body, "m", True)
        self.assertEqual(oai["tools"][0]["type"], "function")
        self.assertEqual(oai["tools"][0]["function"]["name"], "read")

    def test_tool_choice_any(self):
        oai = anth_request_to_oai({"tool_choice": {"type": "any"}}, "m", True)
        self.assertEqual(oai["tool_choice"], "required")


class TestOpenAIToAnthropic(unittest.TestCase):
    def test_compact(self):
        oai = {
            "id": "chatcmpl_1",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }],
        }
        anth = oai_to_anth(oai, "claude-3-5-sonnet")
        self.assertEqual(anth["model"], "claude-3-5-sonnet")
        self.assertEqual(anth["content"], [{"type": "text", "text": "hi"}])
        self.assertEqual(anth["stop_reason"], "end_turn")

    def test_tool_calls(self):
        oai = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {"name": "read", "arguments": '{"file": "a.txt"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        anth = oai_to_anth(oai, "m")
        self.assertEqual(anth["content"][0]["type"], "tool_use")
        self.assertEqual(anth["content"][0]["input"], {"file": "a.txt"})
        self.assertEqual(anth["stop_reason"], "tool_use")


if __name__ == "__main__":
    unittest.main()
