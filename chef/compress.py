"""Token-compression pipeline for the chef proxy (zero-dependency, stdlib only).

Extracted from the compression-proxy pipeline so the chef proxy can compress
every forwarded request AND difficulty-route it to the cheapest capable model.
All functions are best-effort: they never raise, and they never return output
larger than the input (the caller keeps the original in that case).
"""

import json
import re

_LL = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b", re.IGNORECASE)
_TP = re.compile(r"^\[?\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]?\s*")
_UP = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_TSP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_UX = re.compile(r"\b1[6-9]\d{8}\b")

MSG_LIMITS = {"free": 1500, "cheap": 3000, "moderate": 800, "expensive": 400}
SYS_LIMITS = {"free": 1200, "cheap": 2000, "moderate": 600, "expensive": 250}
MULT_LIMITS = {"free": 800, "cheap": 1500, "moderate": 600, "expensive": 300}
RESP_LIMITS = {"free": 1500, "cheap": 3000, "moderate": 800, "expensive": 400}

_EXPENSIVE = re.compile(r"(gpt-5|gpt-4o|claude-opus|claude-sonnet|o1|o3|o4|o5)", re.I)
_MODERATE = re.compile(r"(gpt-4|claude-|gemini-2\.5-pro|deepseek-chat|qwen3-max)", re.I)


def cost_level(model_id):
    """Coarse per-model compression budget tier (mirrors the compression proxy)."""
    if not model_id:
        return "cheap"
    if ":free" in model_id.lower():
        return "free"
    if _EXPENSIVE.search(model_id):
        return "expensive"
    if _MODERATE.search(model_id):
        return "moderate"
    return "cheap"


def json_crush(text):
    """Compress a JSON array of dicts by hoisting constant fields to headers."""
    try:
        d = json.loads(text)
        if isinstance(d, list) and len(d) >= 2 and all(isinstance(x, dict) for x in d):
            fields = list(dict.fromkeys(k for x in d for k in x))
            consts = {}
            for f in list(fields):
                vals = [json.dumps(x.get(f), separators=(",", ":")) for x in d]
                if len(set(vals)) == 1:
                    consts[f] = d[0].get(f)
                    fields.remove(f)
            if consts or len(fields) < len(list(dict.fromkeys(k for x in d for k in x))):
                lines = []
                if consts:
                    lines.append("[CONSTANTS: " + ", ".join("%s=%s" % (k, v) for k, v in consts.items()) + "]")
                if fields:
                    lines.append("[FIELDS: " + ", ".join(fields) + "]")
                for x in d:
                    lines.append(" | ".join(str(x.get(f, "")) for f in fields))
                return "\n".join(lines)
        minified = json.dumps(d, separators=(",", ":"))
        if "\n" in text and len(minified) < len(text) * 0.85:
            return minified
    except Exception:
        pass
    return text


def compress_log(text):
    """Deduplicate repetitive log lines; keep important/error lines."""
    lines = text.split("\n")
    if len(lines) < 8:
        return text
    log_hits = sum(1 for l in lines[:20] if _LL.search(l) or _TP.match(l))
    if log_hits < 3:
        return text
    important = re.compile(r"\b(error|exception|traceback|failed|fatal|critical|panic)\b", re.I)
    out = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if important.search(l):
            out.append(l)
            i += 1
            continue
        norm = _TP.sub("", l).strip()
        norm = re.sub(r"\d+", "N", norm)
        run_start = i
        while i + 1 < len(lines):
            n2 = _TP.sub("", lines[i + 1]).strip()
            n2 = re.sub(r"\d+", "N", n2)
            if n2 == norm:
                i += 1
            else:
                break
        run_len = i - run_start + 1
        if run_len >= 5:
            out.append(lines[run_start])
            if run_len > 2:
                out.append("  [... repeated %d more times ...]" % (run_len - 2))
            if run_len > 1:
                out.append(lines[i])
        else:
            for j in range(run_start, i + 1):
                out.append(lines[j])
        i += 1
    return "\n".join(out)


def cache_align(text):
    """Replace volatile values (UUIDs, timestamps, numeric IDs) with stable markers."""
    dyn = {}
    result = text
    c = 0
    for match in _UP.finditer(result):
        p = "{UUID_%d}" % c
        dyn[p] = match.group()
        result = result.replace(match.group(), p, 1)
        c += 1
    for match in _TSP.finditer(result):
        p = "{TS_%d}" % c
        dyn[p] = match.group()
        result = result.replace(match.group(), p, 1)
        c += 1
    for match in _UX.finditer(result):
        p = "{TS_%d}" % c
        dyn[p] = match.group()
        result = result.replace(match.group(), p, 1)
        c += 1
    if dyn:
        result += "\n# Dynamic values: " + json.dumps(dyn)
    return result


def _clean_msg(m):
    return {k: v for k, v in m.items() if not (v is None or v == [] or (isinstance(v, str) and v == ""))}


def _truncate(text, cap):
    if len(text) <= cap:
        return text
    lines = text.splitlines()
    keep = max(5, int(cap * 0.6) // 40)
    if len(lines) > keep * 2:
        return "\n".join(lines[:keep] + ["# ... %d lines omitted" % (len(lines) - keep * 2)] + lines[-keep:])
    return text[:cap] + "\n# ... truncated (%d chars)" % (len(text) - cap)


def compress_text(text, cap):
    """Full content pipeline: crush -> log-dedup -> truncate to cap."""
    if not isinstance(text, str) or len(text) <= 200:
        return text
    out = json_crush(text)
    if len(out) > 200:
        out = compress_log(out)
    if len(out) > cap:
        out = _truncate(out, cap)
    return out


def compress_messages(messages, level="cheap"):
    """Apply the pipeline to an OpenAI-style messages list, in place.
    Returns (saved_chars, msg_count)."""
    if not isinstance(messages, list):
        return 0, 0
    msg_cap = MSG_LIMITS.get(level, 3000)
    sys_cap = SYS_LIMITS.get(level, 4000)
    mult_cap = MULT_LIMITS.get(level, 2000)
    tool_result_count = 0
    before = len(json.dumps(messages, ensure_ascii=False))
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "")
        c = m.get("content", "")
        if isinstance(c, str):
            is_tool = role in ("user", "tool") or (tool_result_count > 0 and role == "user")
            cap = sys_cap if role == "system" else msg_cap
            s = compress_text(c, cap)
            if is_tool:
                tool_result_count += 1
            m["content"] = s
            for k in list(m.keys()):
                if m[k] is None or m[k] == [] or (isinstance(m[k], str) and m[k] == ""):
                    del m[k]
        elif isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = b.get("text", "")
                    if len(t) > 200:
                        t = json_crush(t)
                    if len(t) > 200:
                        t = compress_log(t)
                    if len(t) > mult_cap:
                        t = t[:int(mult_cap * 0.6)] + "\n... truncated (%d chars)" % (len(t) - int(mult_cap * 0.6))
                    parts.append({"type": "text", "text": t})
                else:
                    parts.append(b)
            m["content"] = parts
            for k in list(m.keys()):
                if m[k] is None or m[k] == [] or (isinstance(m[k], str) and m[k] == ""):
                    del m[k]
    after = len(json.dumps(messages, ensure_ascii=False))
    return max(0, before - after), len(messages)


def compress_request(data, model_id=""):
    """Compress a chat-completions request dict in place.
    Returns saved chars. Never raises; returns 0 on any failure."""
    if not isinstance(data, dict):
        return 0
    level = cost_level(model_id)
    before = len(json.dumps(data, ensure_ascii=False))
    try:
        if data.get("input") is not None:
            resp_cap = RESP_LIMITS.get(level, 3000)
            inp = data["input"]
            if isinstance(inp, str):
                data["input"] = compress_text(inp, resp_cap)
            elif isinstance(inp, list):
                for item in inp:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content")
                    if isinstance(content, str):
                        item["content"] = compress_text(content, resp_cap)
                    elif isinstance(content, list):
                        for block in content:
                            if (isinstance(block, dict) and block.get("type") in ("input_text", "output_text", "text")
                                    and isinstance(block.get("text"), str)):
                                block["text"] = compress_text(block["text"], resp_cap)
        if isinstance(data.get("messages"), list):
            compress_messages(data["messages"], level)
    except Exception:
        return 0
    after = len(json.dumps(data, ensure_ascii=False))
    return max(0, before - after)
