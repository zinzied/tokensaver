#!/usr/bin/env python3
"""Local integration test for the request compression proxy.

This starts a fake OpenAI-compatible upstream on localhost, starts the real
generated proxy against it, and compares the original request with the body
received by the upstream.  It never contacts a real provider and uses no API
key.  Run from the repository root with:

    python proxy_self_test.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import shutil
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def free_server() -> ThreadingHTTPServer:
    """Bind an ephemeral localhost server and return it."""
    return ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)


class UpstreamHandler(BaseHTTPRequestHandler):
    received: list[bytes] = []

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/models":
            payload = b'{"object":"list","data":[]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.received.append(body)
        payload = json.dumps(
            {
                "id": "local-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    # Deliberately labelled approximate: the proxy uses
                    # chars/4 for estimates, while providers use tokenizers.
                    "approx_input_tokens": len(body) // 4,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        return


def load_token_saver():
    spec = importlib.util.spec_from_file_location("token_saver_for_test", ROOT / "token-saver.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load token-saver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post_json(url: str, payload: dict) -> dict:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local-test"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())


def main() -> int:
    token_saver = load_token_saver()
    work_dir = ROOT / ".proxy-self-test"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()

    upstream = free_server()
    upstream_port = upstream.server_address[1]
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    # Isolate proxy metadata and make the provider default point at our fake
    # server.  No OpenCode config is rewritten and no external network is used.
    token_saver.COMPRESS_DIR = work_dir
    token_saver.PROXY_CONFIG = work_dir / "proxy.json"
    token_saver.COST_PRICING_PATH = work_dir / "proxy_pricing.json"
    token_saver.PROVIDER_DEFAULT_BASE_URLS = dict(token_saver.PROVIDER_DEFAULT_BASE_URLS)
    token_saver.PROVIDER_DEFAULT_BASE_URLS["openai"] = f"http://127.0.0.1:{upstream_port}"
    token_saver.get_user_models = lambda: ({}, [])

    # Close the port-probe server immediately; start_server performs its own
    # bind and the tiny race is harmless for this local test.
    probe = free_server()
    proxy_port = probe.server_address[1]
    probe.server_close()

    proxy_started = False
    try:
        proxy_started = token_saver.CompressionProxy.start_server(
            proxy_port,
            provider="openai",
            configure_opencode=False,
            no_frost=True,
        )
        if not proxy_started:
            raise RuntimeError("Proxy failed to start; inspect proxy_stderr.log")

        proxy_url = f"http://127.0.0.1:{proxy_port}/v1/chat/completions"
        repeated_logs = "\n".join(
            f"2026-08-07T12:00:00Z INFO worker completed request id={i % 4}"
            for i in range(240)
        )
        compressible = {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "You are a careful coding assistant. " * 180},
                {"role": "user", "content": repeated_logs},
            ],
        }
        large = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "x" * 2200} for _ in range(60)],
        }

        UpstreamHandler.received.clear()
        raw_small = len(json.dumps(compressible, separators=(",", ":")).encode())
        post_json(proxy_url, compressible)
        time.sleep(0.1)
        if len(UpstreamHandler.received) != 1:
            raise AssertionError("upstream did not receive the compressible request")
        forwarded_small = len(UpstreamHandler.received[-1])
        small_saved = raw_small - forwarded_small
        if small_saved <= 0:
            raise AssertionError(f"compressible request was not reduced: {raw_small} -> {forwarded_small} bytes")

        raw_large = len(json.dumps(large, separators=(",", ":")).encode())
        post_json(proxy_url, large)
        time.sleep(0.1)
        forwarded_large = len(UpstreamHandler.received[-1])
        # Large conversations use the sliding window: the most recent 15
        # messages keep normal caps while older messages are compressed with
        # the tightest caps. Message count and structure must be preserved —
        # only content strings may shrink, never grow.
        if forwarded_large >= raw_large:
            raise AssertionError(f"large sliding-window did not reduce payload: {raw_large} -> {forwarded_large} bytes")
        fwd_large_body = json.loads(UpstreamHandler.received[-1])
        if len(fwd_large_body.get("messages", [])) != 60:
            raise AssertionError("sliding window dropped messages instead of only shrinking content")

        # Anthropic-shaped request: system string must gain a native cache
        # breakpoint (content untouched), messages preserved, tool output
        # with repeated IDs normalized. Body is large enough that the
        # breakpoint (~70B) cannot trip the never-expand fallback.
        anthropic = {
            "model": "test-model",
            "system": "You are a careful coding assistant. " * 40,
            "messages": [
                {"role": "user", "content": "trace 550e8400-e29b-41d4-a716-446655440000 " * 30},
                {"role": "user", "content": "\n".join(
                    "2026-08-07T12:00:00Z INFO worker completed request id=%d" % (i % 4)
                    for i in range(120)
                )},
            ],
        }
        raw_anthropic = len(json.dumps(anthropic, separators=(",", ":")).encode())
        n_before = len(UpstreamHandler.received)
        post_json(f"http://127.0.0.1:{proxy_port}/v1/messages", anthropic)
        time.sleep(0.1)
        if len(UpstreamHandler.received) != n_before + 1:
            raise AssertionError("upstream did not receive the /messages request")
        fwd_anthropic = json.loads(UpstreamHandler.received[-1])
        sys_blocks = fwd_anthropic.get("system")
        if not isinstance(sys_blocks, list) or not sys_blocks:
            raise AssertionError("system string was not converted to blocks: %r" % type(sys_blocks))
        if sys_blocks[-1].get("cache_control") != {"type": "ephemeral"}:
            raise AssertionError("last system block is missing the cache breakpoint")
        if "careful coding assistant" not in sys_blocks[-1].get("text", ""):
            raise AssertionError("system content was altered while adding the breakpoint")
        if len(fwd_anthropic.get("messages", [])) != 2:
            raise AssertionError("messages were dropped from the /messages request")
        forwarded_anthropic = len(UpstreamHandler.received[-1])
        if forwarded_anthropic >= raw_anthropic:
            raise AssertionError(f"/messages request was not reduced: {raw_anthropic} -> {forwarded_anthropic} bytes")

        # Client-set breakpoints must be respected, never duplicated.
        preset = {
            "model": "test-model",
            "system": [
                {"type": "text", "text": "Stable preamble. " * 60,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "Trailing note."},
            ],
            "messages": [{"role": "user", "content": "hello " * 100}],
        }
        n_before = len(UpstreamHandler.received)
        post_json(f"http://127.0.0.1:{proxy_port}/v1/messages", preset)
        time.sleep(0.1)
        fwd_preset = json.loads(UpstreamHandler.received[-1])
        ccs = [b.get("cache_control") for b in fwd_preset.get("system", [])
               if isinstance(b, dict) and "cache_control" in b]
        if ccs != [{"type": "ephemeral"}]:
            raise AssertionError("client cache breakpoints were altered: %r" % ccs)

        # Non-JSON request body: json.loads fails, so `data` is never bound in
        # do_POST. The proxy must answer with the upstream response instead of
        # crashing the request thread (UnboundLocalError) and dropping the
        # connection, which opencode sees as a dead proxy.
        n_before = len(UpstreamHandler.received)
        raw_req = urllib.request.Request(
            proxy_url,
            data=b"this is not json at all",
            headers={"Content-Type": "application/json", "Authorization": "Bearer local-test"},
            method="POST",
        )
        with urllib.request.urlopen(raw_req, timeout=15) as response:
            non_json_resp = response.read()
        json.loads(non_json_resp)  # must be a real HTTP response, not a dead connection
        time.sleep(0.1)
        if len(UpstreamHandler.received) != n_before + 1:
            raise AssertionError("non-JSON body was not forwarded upstream")
        if UpstreamHandler.received[-1] != b"this is not json at all":
            raise AssertionError("non-JSON body was altered: %r" % UpstreamHandler.received[-1])

        # Responses-API shaped request (/v1/responses, used by opencode Zen and
        # Codex): structure must survive compression — same item count and
        # types, reasoning blocks untouched, and the body must shrink.
        responses = {
            "model": "test-model",
            "input": [
                {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "Explain this log:\n" + repeated_logs}]},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "I will look at the output. " * 400}],
                 "reasoning": [{"type": "encrypted_content", "encrypted_content": "abc123"}]},
                {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
            ],
            "stream": False,
        }
        n_before = len(UpstreamHandler.received)
        post_json(f"http://127.0.0.1:{proxy_port}/v1/responses", responses)
        time.sleep(0.1)
        if len(UpstreamHandler.received) != n_before + 1:
            raise AssertionError("upstream did not receive the /v1/responses request")
        fwd_responses = json.loads(UpstreamHandler.received[-1])
        items = fwd_responses.get("input", [])
        if len(items) != 3:
            raise AssertionError("responses input items were dropped: %d" % len(items))
        if [it.get("type") for it in items] != ["message", "message", "function_call_output"]:
            raise AssertionError("responses item types changed: %r" % [it.get("type") for it in items])
        if items[1].get("reasoning") != [{"type": "encrypted_content", "encrypted_content": "abc123"}]:
            raise AssertionError("assistant reasoning block was altered")
        raw_responses = len(json.dumps(responses, separators=(",", ":")).encode())
        if len(UpstreamHandler.received[-1]) >= raw_responses:
            raise AssertionError(f"/v1/responses request was not reduced: {raw_responses} -> {len(UpstreamHandler.received[-1])} bytes")

        generated = (work_dir / "_proxy_server.py").read_text(encoding="utf-8")
        if "allow_stateless_marker" not in generated:
            raise AssertionError("generated proxy is missing the FROST safety gate")

        print("Proxy self-test: PASS")
        print(f"  compressible request: {raw_small:,} -> {forwarded_small:,} bytes ({small_saved:,} saved, {small_saved / raw_small * 100:.1f}%)")
        print(f"  large-request sliding window: {raw_large:,} -> {forwarded_large:,} bytes (60 msgs preserved, content shrunk)")
        print(f"  anthropic /messages: {raw_anthropic:,} -> {forwarded_anthropic:,} bytes (cache breakpoint set, system intact)")
        print("  client breakpoints: respected, never duplicated")
        print("  non-JSON body: forwarded untouched, request thread not crashed")
        print("  responses /v1/responses: structure + reasoning preserved, body reduced")
        print("  FROST safety gate: present in generated proxy")
        print("  Note: bytes are a transport measurement; provider billing must be verified with that provider's usage data.")
        return 0
    finally:
        if proxy_started:
            proxy_pid = token_saver.CompressionProxy.config().get("pid")
            token_saver.CompressionProxy.stop_server()
            # The production stop command uses taskkill on Windows.  Keep the
            # test hermetic if a detached child survives that first attempt.
            if proxy_pid:
                try:
                    os.kill(int(proxy_pid), signal.SIGTERM)
                except (OSError, ValueError, TypeError):
                    pass
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=2)
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
