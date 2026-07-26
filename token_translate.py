import json

FORMATS = {
    "OPENAI": "openai",
    "OPENAI_RESPONSES": "openai-responses",
    "CLAUDE": "claude",
    "GEMINI": "gemini",
    "GEMINI_CLI": "gemini-cli",
    "VERTEX": "vertex",
    "CODEX": "codex",
    "ANTIGRAVITY": "antigravity",
    "KIRO": "kiro",
    "CURSOR": "cursor",
    "OLLAMA": "ollama",
    "COMMANDCODE": "commandcode",
}


_request_registry = {}
_response_registry = {}


def register(from_fmt, to_fmt, request_fn=None, response_fn=None):
    key = f"{from_fmt}:{to_fmt}"
    if request_fn:
        _request_registry[key] = request_fn
    if response_fn:
        _response_registry[key] = response_fn
    return key


def detect_format(body):
    if not body:
        return FORMATS["OPENAI"]
    if body.get("system") is not None or body.get("anthropic_version"):
        return FORMATS["CLAUDE"]
    if isinstance(body.get("contents"), list):
        return FORMATS["GEMINI"]
    if isinstance(body.get("request"), dict) and isinstance(body.get("request", {}).get("contents"), list):
        return FORMATS["ANTIGRAVITY"]
    if isinstance(body.get("input"), (list, str)):
        return FORMATS["OPENAI_RESPONSES"]
    return FORMATS["OPENAI"]


def translate_request(source_format, target_format, body):
    if source_format == target_format:
        return body

    result = body

    direct_key = f"{source_format}:{target_format}"
    if direct_key in _request_registry:
        return _request_registry[direct_key](result)

    if source_format != FORMATS["OPENAI"]:
        to_openai = _request_registry.get(f"{source_format}:{FORMATS['OPENAI']}")
        if to_openai:
            result = to_openai(result)

    if target_format != FORMATS["OPENAI"]:
        from_openai = _request_registry.get(f"{FORMATS['OPENAI']}:{target_format}")
        if from_openai:
            result = from_openai(result)

    return result


def translate_response(target_format, source_format, chunk, state=None):
    if source_format == target_format:
        return [chunk]

    results = [chunk]

    direct_key = f"{target_format}:{source_format}"
    if direct_key in _response_registry:
        converted = _response_registry[direct_key](chunk, state)
        if isinstance(converted, list):
            return converted
        return [converted] if converted else []

    if target_format != FORMATS["OPENAI"]:
        to_openai = _response_registry.get(f"{target_format}:{FORMATS['OPENAI']}")
        if to_openai:
            converted = to_openai(chunk, state)
            if converted:
                results = converted if isinstance(converted, list) else [converted]

    if source_format != FORMATS["OPENAI"]:
        from_openai = _response_registry.get(f"{FORMATS['OPENAI']}:{source_format}")
        if from_openai:
            final = []
            for r in results:
                converted = from_openai(r, state)
                if converted:
                    if isinstance(converted, list):
                        final.extend(converted)
                    else:
                        final.append(converted)
            results = final

    return results


def translate_openai_to_claude(body):
    result = {}
    if isinstance(body.get("system"), str):
        result["system"] = body["system"]
    elif isinstance(body.get("messages"), list):
        for m in body["messages"]:
            if m.get("role") == "system" and isinstance(m.get("content"), str):
                result["system"] = m["content"]
                break

    messages = []
    for m in body.get("messages", []):
        role = m.get("role", "")
        if role == "system":
            continue
        claude_msg = {"role": "assistant" if role == "assistant" else "user"}
        content = m.get("content", "")

        if isinstance(content, str):
            claude_msg["content"] = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            parts = []
            for c in content:
                if c.get("type") == "text":
                    parts.append({"type": "text", "text": c["text"]})
                elif c.get("type") == "image_url":
                    parts.append({"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": c["image_url"]["url"].split(",")[-1] if "," in c["image_url"]["url"] else c["image_url"]["url"]
                    }})
            claude_msg["content"] = parts

        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                claude_msg["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "input": tc.get("function", {}).get("arguments", {})
                })

        if m.get("role") == "tool":
            claude_msg["role"] = "user"
            claude_msg["content"] = [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": m.get("content", "")
            }]

        messages.append(claude_msg)

    result["messages"] = messages
    result["max_tokens"] = body.get("max_tokens", 4096)
    if body.get("temperature") is not None:
        result["temperature"] = body["temperature"]

    return result


def translate_claude_to_openai(body):
    messages = []

    if isinstance(body.get("system"), str):
        messages.append({"role": "system", "content": body["system"]})
    elif isinstance(body.get("system"), list):
        text = " ".join(b.get("text", "") for b in body["system"] if isinstance(b, dict) and b.get("type") == "text")
        if text:
            messages.append({"role": "system", "content": text})

    for m in body.get("messages", []):
        role = m.get("role", "")
        if role == "assistant":
            openai_role = "assistant"
        else:
            openai_role = "user"

        content = m.get("content", "")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]

        text_parts = []
        tool_calls = []
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "text":
                text_parts.append(c["text"])
            elif c.get("type") == "tool_use":
                tool_calls.append({
                    "id": c.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": c.get("name", ""),
                        "arguments": json.dumps(c.get("input", {}))
                    }
                })
            elif c.get("type") == "tool_result":
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.get("tool_use_id", ""),
                    "content": c.get("content", "")
                })
                continue

        msg = {"role": openai_role, "content": "\n".join(text_parts) if text_parts else ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)

    result = {"messages": messages}
    if body.get("max_tokens"):
        result["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        result["temperature"] = body["temperature"]

    return result


register(FORMATS["OPENAI"], FORMATS["CLAUDE"], request_fn=translate_openai_to_claude)
register(FORMATS["CLAUDE"], FORMATS["OPENAI"], request_fn=translate_claude_to_openai,
         response_fn=translate_claude_to_openai)
