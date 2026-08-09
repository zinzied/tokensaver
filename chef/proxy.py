import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, ledger
from .catalog import (
    CATALOG_BY_ID, MODELS, PAID_MODELS, input_price_usd,
    resolve_candidates, resolve_difficulty_candidates,
)
from .upstream import ConfigError, UpstreamError, complete, last_route, stream_first


_total_saved = {"chars": 0, "frost": 0}
_AUDIT = []
_AUDIT_LOCK = threading.Lock()
_MAX_AUDIT = 100


def _maybe_compress(data, model_id, path_only=""):
    """Best-effort token compression + FROST. Returns a metrics dict.

    Keys: chars_before, chars_after, chars_saved, frost_tokens_saved.
    Compression is skipped for requests under config.COMPRESS_MIN_TOKENS (too
    small to save anything); FROST still applies. Never raises.
    """
    m = {"chars_before": 0, "chars_after": 0, "chars_saved": 0, "frost_tokens_saved": 0}
    if not isinstance(data, dict):
        return m
    before = len(json.dumps(data, ensure_ascii=False))
    if config.COMPRESS and before // 4 >= config.COMPRESS_MIN_TOKENS:
        from .compress import compress_request
        compress_request(data, model_id)
    from .frost import frost_apply
    m["frost_tokens_saved"] = frost_apply(data, model_id, path_only)
    after = len(json.dumps(data, ensure_ascii=False))
    m["chars_before"] = before
    m["chars_after"] = after
    m["chars_saved"] = max(0, before - after)
    _total_saved["chars"] += m["chars_saved"]
    _total_saved["frost"] += m["frost_tokens_saved"]
    return m


def _usd_saved(model_requested, metrics):
    """Estimate $ saved by routing + compression on this request (input tokens only)."""
    price = input_price_usd(model_requested)
    if price <= 0:
        return 0.0
    tokens = metrics["chars_saved"] // 4 + metrics["frost_tokens_saved"]
    return round(tokens / 1e6 * price, 6)


def _log_request(kind, model_requested, model_routed, text, metrics, endpoint):
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "endpoint": endpoint,
        "model_requested": model_requested,
        "model_routed": model_routed or "",
        "text": (text or "")[:120],
        "chars_before": metrics["chars_before"],
        "chars_after": metrics["chars_after"],
        "chars_saved": metrics["chars_saved"],
        "frost_saved_tokens": metrics["frost_tokens_saved"],
        "tokens_saved": metrics["chars_saved"] // 4 + metrics["frost_tokens_saved"],
        "usd_saved": _usd_saved(model_requested, metrics),
    }
    with _AUDIT_LOCK:
        _AUDIT.append(entry)
        if len(_AUDIT) > _MAX_AUDIT:
            del _AUDIT[:len(_AUDIT) - _MAX_AUDIT]
    ledger.record(entry)
    return entry


def audit_snapshot(n=100):
    """Last `n` audit entries (newest last)."""
    with _AUDIT_LOCK:
        return list(_AUDIT)[-n:]


def _render_chart(week):
    max_usd = max([w["usd_saved"] for w in week] + [0.001])
    rows = ""
    for w in week:
        pct = int(w["usd_saved"] / max_usd * 100) if max_usd else 0
        rows += (
            "<div class='day'><div class='lab'>%s</div>"
            "<div class='bar' style='width:%d%%' title='%s'></div>"
            "<div class='val'>$%.4f</div><div class='n'>%d req, %d tok</div></div>"
        ) % (w["date"][5:], pct, json.dumps(w), w["usd_saved"], w["requests"], w["tokens_saved"])
    today = ledger.today()
    usd_today = "%.4f" % today["usd_saved"]
    tokens_today = "{:,}".format(today["tokens_saved"])
    reqs_today = "{:,}".format(today["requests"])
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Chef Proxy Savings</title>
<style>
body{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;padding:32px;max-width:720px;margin:0 auto}
h1{font-size:20px;color:#58a6ff}h2{font-size:15px;color:#8b949e;margin-top:24px}
.cards{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;min-width:120px}
.card .v{font-size:22px;color:#3fb950}.card .k{font-size:12px;color:#8b949e}
.chart{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-top:12px}
.day{display:flex;align-items:center;gap:10px;margin:6px 0}
.lab{width:40px;font-size:12px;color:#8b949e}
.bar{height:14px;background:linear-gradient(90deg,#238636,#3fb950);border-radius:3px;min-width:2px}
.val{width:64px;font-size:12px;color:#3fb950;text-align:right}
.n{font-size:11px;color:#8b949e}
</style></head><body>
<h1>Chef Agent Proxy &middot; Savings</h1>
<div class="cards">
<div class="card"><div class="v">$%s</div><div class="k">saved today</div></div>
<div class="card"><div class="v">%s</div><div class="k">tokens today</div></div>
<div class="card"><div class="v">%s</div><div class="k">requests today</div></div>
</div>
<h2>Last 7 days (estimated USD saved)</h2>
<div class="chart">%s</div>
<p style="color:#8b949e;font-size:12px">Estimated from input tokens avoided &times; requested model $/M. Audit log: <a href="/log">/log</a></p>
</body></html>""" % (usd_today, tokens_today, reqs_today, rows)


def _last_user_text(body):
    """Extract the most recent user text so difficulty routing can score the task."""
    for msg in reversed(body.get("messages") or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if parts:
                return "\n".join(parts)
    return ""


def _sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data))


def anth_request_to_oai(body, model_route, stream):
    out = {
        "model": model_route,
        "stream": stream,
        "max_tokens": body.get("max_tokens", 8192),
    }
    for key in ("temperature", "top_p", "stop_sequences", "presence_penalty", "frequency_penalty"):
        if key in body:
            out[key] = body[key]
    messages = []
    system = body.get("system")
    if system:
        if isinstance(system, list):
            system = "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
        messages.append({"role": "system", "content": system})
    for msg in body.get("messages", []):
        messages.extend(_anth_message_to_openai(msg))
    out["messages"] = messages
    tools = []
    for tool in body.get("tools", []):
        tools.append({
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        })
    if tools:
        out["tools"] = tools
    tool_choice = body.get("tool_choice")
    if tool_choice:
        ttype = tool_choice.get("type")
        if ttype == "any":
            out["tool_choice"] = "required"
        elif ttype == "auto":
            out["tool_choice"] = "auto"
        elif ttype == "tool":
            out["tool_choice"] = {"type": "function", "function": {"name": tool_choice.get("name")}}
    return out


def _anth_message_to_openai(msg):
    role = msg.get("role")
    content = msg.get("content")
    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if role == "user":
        out = []
        text = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text.append(block.get("text", ""))
            elif btype == "image":
                if text:
                    out.append({"role": "user", "content": "\n".join(text)})
                    text = []
                src = block.get("source", {})
                if src.get("type") == "base64":
                    url = "data:%s;base64,%s" % (src.get("media_type", "image/png"), src.get("data", ""))
                    out.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]})
            elif btype == "tool_result":
                if text:
                    out.append({"role": "user", "content": "\n".join(text)})
                    text = []
                result = block.get("content")
                if isinstance(result, list):
                    result = "\n".join(x.get("text", "") for x in result if isinstance(x, dict))
                out.append({"role": "tool", "tool_call_id": block.get("tool_use_id"), "content": result or ""})
        if text:
            out.append({"role": "user", "content": "\n".join(text)})
        return out or [{"role": "user", "content": ""}]
    if role == "assistant":
        text = ""
        calls = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text += block.get("text", "")
            elif btype == "tool_use":
                calls.append({
                    "id": block.get("id") or ("call_" + str(time.time_ns())),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
        msg_out = {"role": "assistant"}
        if text:
            msg_out["content"] = text
        if calls:
            msg_out["tool_calls"] = calls
        return [msg_out]
    return [{"role": role, "content": content}]


def oai_to_anth(oai, requested_model):
    choice = oai["choices"][0]
    msg = choice.get("message", {})
    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls", []):
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (ValueError, TypeError):
            args = {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id") or ("toolu_%012d" % time.time_ns()),
            "name": fn.get("name"),
            "input": args,
        })
    stop_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    return {
        "id": "msg_" + str(oai.get("id", time.time_ns())),
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content,
        "stop_reason": stop_map.get(choice.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def oai_stream_to_anth(resp, requested_model):
    """Translate OpenAI SSE lines from upstream into Anthropic SSE events."""
    block_index = 0
    text_started = False
    stop_sent = False
    tool_ids = {}
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_" + str(time.time_ns()),
            "type": "message",
            "role": "assistant",
            "model": requested_model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except (ValueError, TypeError):
            continue
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", 0)
                fn = tc.get("function", {})
                if index not in tool_ids:
                    tool_ids[index] = tc.get("id") or ("toolu_%012d" % time.time_ns())
                    block_index += 1
                    yield _sse("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {"type": "tool_use", "id": tool_ids[index], "name": fn.get("name") or "unknown", "input": {}},
                    })
                args = fn.get("arguments")
                if args:
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "input_json_delta", "partial_json": args},
                    })
            text = delta.get("content")
            if text:
                if not text_started:
                    block_index += 1
                    text_started = True
                    yield _sse("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {"type": "text", "text": ""},
                    })
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {"type": "text_delta", "text": text},
                })
            finish = choice.get("finish_reason")
            if finish:
                for i in range(1, block_index + 1):
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": i})
                stop_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
                yield _sse("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_map.get(finish, "end_turn"), "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                })
                yield _sse("message_stop", {"type": "message_stop"})
                stop_sent = True
    if not stop_sent:
        for i in range(1, block_index + 1):
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": i})
        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        })
        yield _sse("message_stop", {"type": "message_stop"})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "ChefProxy/0.1"

    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return {}

    def _send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status, message, anthropic=False):
        if anthropic:
            self._send_json({"type": "error", "error": {"type": "api_error", "message": message}}, status)
        else:
            self._send_json({"error": {"type": "api_error", "message": message}}, status)

    def _relay_stream(self, resp, saved=0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Chef-Compressed-Chars", str(saved))
        self.end_headers()
        while True:
            line = resp.readline()
            if not line:
                break
            self.wfile.write(line)
            self.wfile.flush()
        resp.close()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            self._send_json({
                "service": "chef-agent-proxy",
                "status": "ok",
                "compress": config.COMPRESS,
                "min_compress_tokens": config.COMPRESS_MIN_TOKENS,
                "saved_chars": _total_saved["chars"],
                "frost_saved_tokens": _total_saved["frost"],
                "providers": {
                    "openrouter": bool(config.OPENROUTER_API_KEY),
                    "groq": bool(config.GROQ_API_KEY),
                    "gemini": bool(config.GEMINI_API_KEY),
                    "ollama": config.OLLAMA_HOST,
                },
                "ledger": {
                    "path": str(ledger.LEDGER_PATH),
                    "today": ledger.today(),
                },
            })
        elif path == "/log":
            n = 100
            try:
                n = max(1, min(int(self.path.split("?")[1].split("=")[1]), 1000))
            except Exception:
                pass
            self._send_json({
                "count": len(audit_snapshot(1000)),
                "entries": audit_snapshot(n),
            })
        elif path == "/stats":
            self._send_json({
                "today": ledger.today(),
                "week": ledger.week_series(7),
                "audit_count": len(audit_snapshot(1000)),
            })
        elif path == "/chart":
            body = _render_chart(ledger.week_series(7)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/v1/models":
            data = []
            for m in MODELS:
                data.append({"id": m["id"], "object": "model", "owned_by": m["provider"], "tags": m["tags"]})
            for m in PAID_MODELS:
                data.append({"id": m["id"], "object": "model", "owned_by": m["provider"], "tags": m["tags"]})
            data.append({"id": "gpt-5", "object": "model", "owned_by": "proxy (difficulty-routed)"})
            data.append({"id": "claude-3-5-sonnet", "object": "model", "owned_by": "proxy (difficulty-routed)"})
            self._send_json({"object": "list", "data": data})
        else:
            self._send_error_json(404, "not found")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/v1/chat/completions":
            self._chat()
        elif path == "/v1/messages":
            self._anthropic()
        else:
            self._send_error_json(404, "unknown endpoint")

    def _chat(self):
        body = self._read_json()
        model = body.get("model") or "chef/deepseek-chat"
        text = _last_user_text(body)
        metrics = _maybe_compress(body, model, self.path)
        try:
            _, routed, resp = stream_first(body, model, text=text)
        except (UpstreamError, ConfigError) as exc:
            self._send_error_json(502, str(exc))
            return
        _log_request("chat", model, routed, text, metrics, self.path.split("?")[0])
        self._relay_stream(resp, metrics["chars_saved"])

    def _anthropic(self):
        body = self._read_json()
        model = body.get("model") or "chef/deepseek-chat"
        stream = bool(body.get("stream", True))
        text = _last_user_text(body)
        oai_body = anth_request_to_oai(body, "x", stream)
        metrics = _maybe_compress(oai_body, model, self.path)
        routed_for_log = ""
        try:
            if stream:
                _, routed_for_log, resp = stream_first(oai_body, model, text=text)
            else:
                data = complete(oai_body, model, text=text)
                routed_for_log = last_route()[1]
        except (UpstreamError, ConfigError) as exc:
            self._send_error_json(502, str(exc), anthropic=True)
            return
        _log_request("anthropic", model, routed_for_log, text, metrics, self.path.split("?")[0])
        if not stream:
            self._send_json(oai_to_anth(data, model), extra_headers={"anthropic-version": "2023-06-01"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("anthropic-version", "2023-06-01")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event in oai_stream_to_anth(resp, model):
                self.wfile.write(event.encode())
                self.wfile.flush()
        finally:
            resp.close()


def serve(host=config.HOST, port=config.PORT):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print("Chef Agent Proxy listening on http://%s:%d" % (host, port))
    print("OpenAI-compatible:  %s/v1/chat/completions" % ("http://%s:%d" % (host, port)))
    print("Anthropic-compatible: %s/v1/messages" % ("http://%s:%d" % (host, port)))
    print("Compression: %s (json crush + log dedup + caps + FROST, min %d tokens); toggle CHEF_COMPRESS=0" % (
        "ON" if config.COMPRESS else "OFF", config.COMPRESS_MIN_TOKENS))
    print("Savings ledger: %s  (see /stats and /chart)" % ledger.LEDGER_PATH)
    print("Providers: openrouter=%s groq=%s gemini=%s ollama=%s" % (
        bool(config.OPENROUTER_API_KEY), bool(config.GROQ_API_KEY),
        bool(config.GEMINI_API_KEY), config.OLLAMA_HOST))
    mode = "FREE-ONLY (hard tasks use best free reasoning model)" if config.FREE_ONLY else \
        "paid (max $%.2f/M in), easy -> free (threshold %d)" % (
        config.MAX_PAID_PER_M, config.DIFFICULTY_THRESHOLD)
    print("Difficulty routing: hard tasks -> %s" % mode)
    if config.FREE_ONLY:
        print("  (no paid spend; hard tasks fall back to the best free reasoning model across your providers)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
