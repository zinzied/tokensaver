"""FROST: System Prompt Freeze for the chef proxy (zero-dependency, stdlib only).

Port of the compression-proxy FROST feature: an unchanged system prompt is
replaced with a tiny marker instead of being re-sent on every request.

Safety model (inherited from the compression proxy): standard chat-completions
APIs are stateless between HTTP requests, so an upstream model cannot recover a
prompt replaced by a marker. ``enabled`` alone is intentionally insufficient;
the user must explicitly opt in via ``allow_stateless_marker`` in the FROST
config. Re-send guards: the system text must be byte-identical (SHA256), fewer
than ``refresh_after_tokens`` non-system tokens may have flowed since the last
full send, and the conversation must not have shrunk. Any miss -> full prompt
re-sent. All functions are best-effort and never raise.
"""

import hashlib
import json
from pathlib import Path

_FROST_MARKER = "[FROST] system prompt unchanged - instructions from earlier in this conversation still apply."
_FROST_DEFAULT_THRESHOLD = 50000
_CONFIG_PATH = Path.home() / ".config" / "opencode" / "compress" / "proxy.json"

_state = {}
_total_saved = 0


def reset():
    _state.clear()
    global _total_saved
    _total_saved = 0


def total_saved():
    return _total_saved


def frost_cfg():
    try:
        with open(str(_CONFIG_PATH), encoding="utf-8") as f:
            return (json.load(f).get("frost") or {}) or {}
    except Exception:
        return {}


def _session_key(model_id, msgs):
    """Session identity = model + first non-system message (stable across turns)."""
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        seed = json.dumps({"role": m.get("role"), "content": m.get("content")}, separators=(",", ":"))
        return hashlib.sha256((model_id + seed).encode("utf-8")).hexdigest()
    return ""


def _system_block(data, path_only):
    """Return (kind, value) for the system block: 'openai'|'anthropic'|None."""
    p = path_only.split("?", 1)[0]
    if (p.endswith("/messages") or data.get("system") is not None) and data.get("system") is not None:
        return ("anthropic", data["system"])
    msgs = data.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "system":
                return ("openai", m.get("content", ""))
    return (None, None)


def _replace(data, path_only, marker):
    kind, val = _system_block(data, path_only)
    if kind == "openai":
        for m in data.get("messages", []):
            if isinstance(m, dict) and m.get("role") == "system":
                m["content"] = marker
                return len(val) if isinstance(val, str) else len(json.dumps(val, ensure_ascii=False))
    elif kind == "anthropic":
        data["system"] = marker
        return len(val) if isinstance(val, str) else len(json.dumps(val, ensure_ascii=False))
    return 0


def frost_apply(data, model_id, path_only):
    """Replace an unchanged system prompt with a marker. Returns tokens saved (0 if not applied)."""
    global _total_saved
    if not isinstance(data, dict):
        return 0
    kind, val = _system_block(data, path_only)
    if not kind:
        return 0
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        return 0
    sess = _session_key(model_id, msgs)
    if not sess:
        return 0
    try:
        sys_text = val if isinstance(val, str) else json.dumps(val, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return 0
    sys_hash = hashlib.sha256(sys_text.encode("utf-8")).hexdigest()
    fcfg = frost_cfg()
    if not fcfg.get("enabled", False) or not fcfg.get("allow_stateless_marker", False):
        return 0
    threshold = int(fcfg.get("refresh_after_tokens", _FROST_DEFAULT_THRESHOLD))
    non_sys = sum(len(json.dumps(m.get("content", ""), ensure_ascii=False)) // 4
                  for m in msgs if isinstance(m, dict) and m.get("role") != "system")
    n_msgs = len(msgs)
    st = _state.get(sess)
    if st and st.get("sys_hash") == sys_hash and st.get("since_tokens", 0) < threshold and n_msgs >= st.get("last_msgs", 0):
        saved_chars = _replace(data, path_only, _FROST_MARKER)
        st["since_tokens"] = st.get("since_tokens", 0) + non_sys
        st["last_msgs"] = n_msgs
        _total_saved += saved_chars // 4
        return saved_chars // 4
    _state[sess] = {"sys_hash": sys_hash, "since_tokens": non_sys, "last_msgs": n_msgs}
    if len(_state) > 50:
        for k in list(_state)[:25]:
            _state.pop(k, None)
    return 0
