#!/usr/bin/env python3
"""Token Saver Dashboard Server - spawned as a subprocess by token-saver.py
Usage: python _dashboard_server.py <config_path.json>

Config JSON should contain:
  content_cache, content_store, ledger, budget, proxy_config,
  fallback, config, dashboard_config, quota_tracker, accounts, log_file
"""
import json, os, sys, http.server, time, urllib.parse, io, urllib.request, traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta

def rough(s): return len(s) // 4

# ---- Load paths from config ----
def load_paths(config_path):
    with open(config_path, "r") as f:
        return json.load(f)

PATHS = {}

# ---- Inline helpers: Format Translator ----
FORMATS = {
    "OPENAI": "openai", "CLAUDE": "claude", "GEMINI": "gemini",
    "OPENAI_RESPONSES": "openai-responses", "VERTEX": "vertex",
}

def detect_format(body):
    if not body:
        return FORMATS["OPENAI"]
    if body.get("system") is not None or body.get("anthropic_version"):
        return FORMATS["CLAUDE"]
    if isinstance(body.get("contents"), list):
        return FORMATS["GEMINI"]
    if isinstance(body.get("input"), (list, str)):
        return FORMATS["OPENAI_RESPONSES"]
    return FORMATS["OPENAI"]

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
                    data = c["image_url"]["url"].split(",")[-1] if "," in c["image_url"]["url"] else c["image_url"]["url"]
                    parts.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
            claude_msg["content"] = parts
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                claude_msg["content"].append({"type": "tool_use", "id": tc.get("id",""),
                    "name": tc.get("function",{}).get("name",""), "input": tc.get("function",{}).get("arguments",{})})
        if m.get("role") == "tool":
            claude_msg["role"] = "user"
            claude_msg["content"] = [{"type": "tool_result", "tool_use_id": m.get("tool_call_id",""), "content": m.get("content","")}]
        messages.append(claude_msg)
    result["messages"] = messages
    if body.get("max_tokens"): result["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None: result["temperature"] = body["temperature"]
    return result

def translate_claude_to_openai(body):
    messages = []
    if isinstance(body.get("system"), str):
        messages.append({"role": "system", "content": body["system"]})
    elif isinstance(body.get("system"), list):
        text = " ".join(b.get("text","") for b in body["system"] if isinstance(b,dict) and b.get("type")=="text")
        if text: messages.append({"role": "system", "content": text})
    for m in body.get("messages", []):
        role = m.get("role", "")
        openai_role = "assistant" if role == "assistant" else "user"
        content = m.get("content", "")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        text_parts, tool_calls = [], []
        for c in (content if isinstance(content, list) else []):
            if c.get("type") == "text": text_parts.append(c["text"])
            elif c.get("type") == "tool_use":
                tool_calls.append({"id": c.get("id",""), "type": "function",
                    "function": {"name": c.get("name",""), "arguments": json.dumps(c.get("input",{}))}})
            elif c.get("type") == "tool_result":
                messages.append({"role": "tool", "tool_call_id": c.get("tool_use_id",""), "content": c.get("content","")})
                continue
        msg = {"role": openai_role, "content": "\n".join(text_parts) if text_parts else ""}
        if tool_calls: msg["tool_calls"] = tool_calls
        messages.append(msg)
    result = {"messages": messages}
    if body.get("max_tokens"): result["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None: result["temperature"] = body["temperature"]
    return result

def translate_request(source_format, target_format, body):
    if source_format == target_format: return body
    fmt_map = {"openai": FORMATS["OPENAI"], "claude": FORMATS["CLAUDE"], "gemini": FORMATS["GEMINI"]}
    sf = fmt_map.get(source_format, FORMATS["OPENAI"])
    tf = fmt_map.get(target_format, FORMATS["OPENAI"])
    if sf == FORMATS["OPENAI"] and tf == FORMATS["CLAUDE"]:
        return translate_openai_to_claude(body)
    if sf == FORMATS["CLAUDE"] and tf == FORMATS["OPENAI"]:
        return translate_claude_to_openai(body)
    if sf != FORMATS["OPENAI"]:
        body = translate_claude_to_openai(body) if sf == FORMATS["CLAUDE"] else body
    if tf != FORMATS["OPENAI"]:
        body = translate_openai_to_claude(body) if tf == FORMATS["CLAUDE"] else body
    return body

# ---- Inline provider tier data ----
PROVIDER_TIERS = {
    "subscription": {
        "claude-code": {"name": "Claude Code", "cost": "$20-200/mo", "priority": 0},
        "codex": {"name": "Codex CLI", "cost": "$20-200/mo", "priority": 1},
        "github-copilot": {"name": "GitHub Copilot", "cost": "$10-19/mo", "priority": 2},
        "cursor": {"name": "Cursor IDE", "cost": "$20/mo", "priority": 3},
        "gemini-cli": {"name": "Gemini CLI", "cost": "$20/mo", "priority": 4},
    },
    "cheap": {
        "glm": {"name": "GLM-5.1", "cost": "$0.6/1M", "priority": 0},
        "minimax": {"name": "MiniMax M2.7", "cost": "$0.2/1M", "priority": 1},
        "kimi": {"name": "Kimi K2.5", "cost": "$9/mo flat", "priority": 2},
    },
    "free": {
        "kiro": {"name": "Kiro AI", "cost": "Free", "priority": 0},
        "opencode-free": {"name": "OpenCode Free", "cost": "Free", "priority": 1},
        "vertex": {"name": "Vertex AI ($300 credits)", "cost": "Free credits", "priority": 2},
        "iflow": {"name": "iFlow", "cost": "Free", "priority": 3},
        "qwen": {"name": "Qwen", "cost": "Free", "priority": 4},
    },
}

PROVIDER_ENDPOINTS = {
    "claude-code": {"base_url": "https://api.anthropic.com", "format": "claude"},
    "codex": {"base_url": "https://api.openai.com", "format": "openai"},
    "github-copilot": {"base_url": "https://api.githubcopilot.com", "format": "openai"},
    "cursor": {"base_url": "https://api.cursor.com", "format": "openai"},
    "gemini-cli": {"base_url": "https://generativelanguage.googleapis.com", "format": "gemini"},
    "glm": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "format": "openai"},
    "minimax": {"base_url": "https://api.minimax.chat/v1", "format": "openai"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "format": "openai"},
    "kiro": {"base_url": "https://api.kiro.ai/v1", "format": "openai"},
    "opencode-free": {"base_url": "https://api.opencode.ai/v1", "format": "openai"},
    "vertex": {"base_url": "https://us-central1-aiplatform.googleapis.com/v1", "format": "vertex"},
    "iflow": {"base_url": "https://api.iflow.ai/v1", "format": "openai"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/api/v1", "format": "openai"},
}

PROVIDER_MODELS = {
    "claude-code": ["claude-sonnet-4-5", "claude-sonnet-4"],
    "codex": ["gpt-4o", "o3-mini", "o4-mini"],
    "github-copilot": ["gpt-4o"],
    "cursor": ["gpt-4o"],
    "gemini-cli": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "glm": ["glm-5.1"],
    "minimax": ["minimax-m2.7"],
    "kimi": ["kimi-k2.5"],
    "kiro": ["kiro-claude-sonnet"],
    "opencode-free": ["opencode-gpt-4o"],
    "vertex": ["gemini-2.5-pro"],
    "iflow": ["iflow-default"],
    "qwen": ["qwen-max", "qwen-plus"],
}

# ---- Inline log ring buffer ----
_log_ring = []
_log_max = 500

def _add_log(level, message):
    ts = datetime.now().strftime("%H:%M:%S")
    _log_ring.append({"time": ts, "level": level, "message": message})
    if len(_log_ring) > _log_max:
        _log_ring.pop(0)

# ---- Request handler ----
class DH(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._serve_html()
        elif path == "/api/stats":
            self._serve_stats()
        elif path == "/api/usage":
            self._serve_usage()
        elif path == "/api/quota":
            self._serve_quota()
        elif path == "/api/routing":
            self._serve_routing()
        elif path == "/api/providers":
            self._serve_providers()
        elif path == "/api/logs":
            self._serve_logs()
        elif path == "/api/settings":
            self._serve_settings()
        elif path == "/api/settings/export":
            self._serve_export()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            if path == "/api/translate/detect":
                self._handle_translate_detect(body)
            elif path.startswith("/api/translate/"):
                target = path.split("/")[-1]
                self._handle_translate(target, body)
            elif path == "/api/chat":
                self._handle_chat(body)
            elif path == "/api/logs/clear":
                self._handle_log_clear()
            elif path.startswith("/api/providers/test/"):
                pid = path.split("/")[-1]
                self._handle_provider_test(pid)
            elif path == "/api/routing/apply":
                self._handle_routing_apply(body)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _serve_html(self):
        html_path = Path(__file__).parent / "_dashboard.html"
        if html_path.exists():
            content = html_path.read_bytes()
        else:
            content = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Cache-Control","no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_stats(self):
        stats = {"cache": {}, "savings": {}, "proxy": {}, "budget": {},
                 "store": {}, "model": {}, "fallback": {}, "rtk": {}, "quota": {}, "timestamp": datetime.now().isoformat()}
        # Cache
        cache_dir = PATHS.get("content_cache","")
        if cache_dir and os.path.exists(cache_dir):
            try:
                import glob as g; now=time.time(); ts=0; tf=0; v=0
                for f in g.glob(os.path.join(cache_dir,"*.json")):
                    try:
                        d=json.load(open(f,encoding="utf-8"))
                        if now-d.get("cached_at",0)>3600: continue
                        v+=1; ts+=d.get("saved_tokens",0); tf+=d.get("compressed_tokens",0)+d.get("saved_tokens",0)
                    except: pass
                stats["cache"]={"cached_files":v,"total_savings_tokens":ts,"total_savings_pct":round(ts/tf*100,1) if tf>0 else 0}
            except: pass
        # Ledger
        ledger = PATHS.get("ledger","")
        if ledger and os.path.exists(ledger):
            try:
                e=json.load(open(ledger,encoding="utf-8")); ts2=sum(x.get("saved_tokens",0) for x in e); tr=sum(x.get("raw_tokens",0) for x in e)
                stats["savings"]={"total_entries":len(e),"total_saved_tokens":ts2,"compression_pct":round(ts2/tr*100,1) if tr>0 else 0}
            except: pass
        # Proxy
        proxy_cfg = PATHS.get("proxy_config","")
        if proxy_cfg and os.path.exists(proxy_cfg):
            try:
                p=json.load(open(proxy_cfg,encoding="utf-8")); rn=False
                try: urllib.request.urlopen("http://127.0.0.1:"+str(p.get("port",8199)),timeout=2); rn=True
                except: pass
                frost = p.get("frost", {}) or {}
                stats["proxy"]={"enabled":p.get("enabled",False),"running":rn,"port":p.get("port",8199),"total_saved_tokens":p.get("total_saved_tokens",0),"frost_total_saved_tokens":p.get("frost_total_saved_tokens",0),"frost_enabled":bool(frost.get("enabled",False) and frost.get("allow_stateless_marker",False)),"requests_served":len(p.get("history",[]))}
            except: pass
        # Budget
        budget = PATHS.get("budget","")
        if budget and os.path.exists(budget):
            try:
                b=json.load(open(budget,encoding="utf-8"))
                stats["budget"]={"has_plan":bool(b),"budget_limit":b.get("budget_limit",0),"total_allocated":b.get("total_allocated",0)}
            except: pass
        # Fallback
        fallback = PATHS.get("fallback","")
        if fallback and os.path.exists(fallback):
            try: stats["fallback"]={"chains":len(json.load(open(fallback,encoding="utf-8")))}
            except: pass
        # Config
        config = PATHS.get("config","")
        if config and os.path.exists(config):
            try:
                import re; t=re.sub(r'^\s*//.*','',open(config,encoding="utf-8").read(),flags=re.MULTILINE); t=re.sub(r'/\*[\s\S]*?\*/','',t)
                mc=json.loads(t); stats["model"]={"model":mc.get("model",""),"small_model":mc.get("small_model","")}
            except: pass
        # Store
        store = PATHS.get("content_store","")
        if store and os.path.exists(store):
            try: stats["store"]={"entries":len(os.listdir(store)),"total_bytes":sum(os.path.getsize(os.path.join(store,f)) for f in os.listdir(store) if os.path.isfile(os.path.join(store,f)))}
            except: pass
        # RTK stats
        stats["rtk"]={"filters":12}
        # Quota summary
        qt = PATHS.get("quota_tracker","")
        if qt and os.path.exists(qt):
            try:
                qd=json.load(open(qt,encoding="utf-8"))
                providers=qd.get("providers",{})
                rl=sum(1 for p in providers.values() if p.get("rate_limited_until"))
                tc=sum(p.get("total_cost",0) for p in providers.values())
                stats["quota"]={"tracked":len(providers),"rate_limited":rl,"total_cost":round(tc,4)}
            except: pass
        self._json_response(stats)

    def _serve_usage(self):
        result = {"cards": {}, "details": []}
        qt = PATHS.get("quota_tracker","")
        if qt and os.path.exists(qt):
            try:
                qd=json.load(open(qt,encoding="utf-8"))
                providers=qd.get("providers",{})
                total_in=sum(p.get("total_tokens_in",0) for p in providers.values())
                total_out=sum(p.get("total_tokens_out",0) for p in providers.values())
                total_cost=sum(p.get("total_cost",0) for p in providers.values())
                total_req=sum(p.get("request_count",0) for p in providers.values())
                result["cards"]={
                    "Total Requests": str(total_req),
                    "Tokens In": f"{total_in:,}",
                    "Tokens Out": f"{total_out:,}",
                    "Total Saved": f"${total_cost:.4f}",
                    "Active Providers": str(len([p for p in providers.values() if not p.get("rate_limited_until")])),
                    "Rate Limited": str(len([p for p in providers.values() if p.get("rate_limited_until")])),
                }
                for prov, data in providers.items():
                    result["details"].append({
                        "provider": prov,
                        "model": data.get("last_model","-"),
                        "tokens_in": data.get("total_tokens_in",0),
                        "tokens_out": data.get("total_tokens_out",0),
                        "cost": round(data.get("total_cost",0),4),
                        "requests": data.get("request_count",0),
                        "last": data.get("last_request","")[:19] if data.get("last_request") else "",
                    })
            except: pass
        self._json_response(result)

    def _serve_quota(self):
        result = []
        qt = PATHS.get("quota_tracker","")
        if qt and os.path.exists(qt):
            try:
                qd=json.load(open(qt,encoding="utf-8"))
                for prov, data in qd.get("providers",{}).items():
                    remaining = data.get("remaining")
                    total = data.get("total_quota")
                    reset_in = None
                    reset_at = data.get("reset_at")
                    if reset_at:
                        try:
                            reset_dt = datetime.fromisoformat(reset_at)
                            rem = reset_dt - datetime.now(timezone.utc)
                            if rem.total_seconds() <= 0: reset_in = "resetting now"
                            else:
                                total_sec = int(rem.total_seconds()); h, m = divmod(total_sec, 3600); m, s = divmod(m, 60)
                                parts = []
                                if h: parts.append(f"{h}h")
                                if m: parts.append(f"{m}m")
                                parts.append(f"{s}s")
                                reset_in = "reset in " + " ".join(parts)
                        except: pass
                    rl = data.get("rate_limited_until")
                    is_rl = False
                    if rl:
                        try: is_rl = datetime.fromisoformat(rl) > datetime.now(timezone.utc)
                        except: pass
                    entry = {"provider": prov, "remaining": remaining or 0, "total": total or 0,
                             "reset_in": reset_in, "rate_limited": is_rl,
                             "cost": round(data.get("total_cost",0),4), "requests": data.get("request_count",0)}
                    result.append(entry)
            except: pass
        self._json_response(result)

    def _serve_routing(self):
        result = {}
        accounts_file = PATHS.get("accounts","")
        accts = []
        if accounts_file and os.path.exists(accounts_file):
            try:
                ad=json.load(open(accounts_file,encoding="utf-8"))
                accts = ad.get("accounts",[])
            except: pass
        for tier_name, providers in PROVIDER_TIERS.items():
            result[tier_name] = []
            for pid, pdata in providers.items():
                tier_accts = [a for a in accts if a.get("provider") == pid]
                endpoint = PROVIDER_ENDPOINTS.get(pid, {})
                result[tier_name].append({
                    "id": pid,
                    "name": pdata["name"],
                    "cost": pdata["cost"],
                    "tier": tier_name,
                    "endpoint": endpoint.get("base_url",""),
                    "format": endpoint.get("format",""),
                    "accounts": len(tier_accts),
                })
        self._json_response(result)

    def _serve_providers(self):
        result = []
        config = PATHS.get("config","")
        cfg = {}
        if config and os.path.exists(config):
            try:
                import re; t=re.sub(r'^\s*//.*','',open(config,encoding="utf-8").read(),flags=re.MULTILINE); t=re.sub(r'/\*[\s\S]*?\*/','',t)
                cfg=json.loads(t)
            except: pass
        for tier_name, providers in PROVIDER_TIERS.items():
            for pid, pdata in providers.items():
                models = PROVIDER_MODELS.get(pid, [])
                # Check if API key is configured (check env vars and config)
                has_key = False
                env_names = [f"{pid.upper().replace('-','_')}_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
                for ev in env_names:
                    if os.environ.get(ev):
                        has_key = True
                        break
                if not has_key:
                    # Check config file for api_keys
                    api_keys = cfg.get("api_keys", cfg.get("providers", {}))
                    if isinstance(api_keys, dict) and (api_keys.get(pid) or api_keys.get("api_key")):
                        has_key = True
                result.append({
                    "id": pid,
                    "name": pdata["name"],
                    "tier": tier_name,
                    "configured": has_key,
                    "models": len(models),
                    "cost": pdata.get("cost",""),
                })
        self._json_response(result)

    def _serve_logs(self):
        self._json_response({"lines": list(_log_ring[-50:])})

    def _serve_settings(self):
        result = {}
        proxy_cfg = PATHS.get("proxy_config","")
        if proxy_cfg and os.path.exists(proxy_cfg):
            try:
                p=json.load(open(proxy_cfg,encoding="utf-8"))
                rn=False
                try: urllib.request.urlopen("http://127.0.0.1:"+str(p.get("port",8199)),timeout=2); rn=True
                except: pass
                result["proxyRunning"]=rn; result["proxyPort"]=p.get("port",8199)
                result["proxyRequests"]=len(p.get("history",[])); result["proxySaved"]=p.get("total_saved_tokens",0)
            except: pass
        accounts_file = PATHS.get("accounts","")
        if accounts_file and os.path.exists(accounts_file):
            try:
                ad=json.load(open(accounts_file,encoding="utf-8"))
                result["accounts"]=len(ad.get("accounts",[]))
            except: pass
        fallback = PATHS.get("fallback","")
        if fallback and os.path.exists(fallback):
            try: result["fallbackChains"]=len(json.load(open(fallback,encoding="utf-8")))
            except: pass
        cache_dir = PATHS.get("content_cache","")
        if cache_dir and os.path.exists(cache_dir):
            try: result["cacheEntries"]=len([f for f in os.listdir(cache_dir) if f.endswith(".json")])
            except: pass
        ledger = PATHS.get("ledger","")
        if ledger and os.path.exists(ledger):
            try: result["ledgerEntries"]=len(json.load(open(ledger,encoding="utf-8")))
            except: pass
        self._json_response(result)

    def _serve_export(self):
        backup = {}
        ledger = PATHS.get("ledger","")
        budget = PATHS.get("budget","")
        accounts_file = PATHS.get("accounts","")
        quota = PATHS.get("quota_tracker","")
        for name, path in [("ledger", ledger), ("budget", budget), ("accounts", accounts_file), ("quota_tracker", quota)]:
            if path and os.path.exists(path):
                try: backup[name]=json.load(open(path,encoding="utf-8"))
                except: pass
        data = json.dumps(backup, indent=2, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Disposition","attachment; filename=token-saver-backup.json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- POST handlers ----
    def _handle_translate_detect(self, body):
        try:
            data = json.loads(body) if body else {}
            fmt = detect_format(data)
            self._json_response({"format": fmt})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _handle_translate(self, target, body):
        try:
            data = json.loads(body) if body else {}
            src_fmt = detect_format(data)
            result = translate_request(src_fmt, target, data)
            self._json_response({"result": result, "source_format": src_fmt, "target_format": target})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _handle_chat(self, body):
        try:
            data = json.loads(body)
            provider = data.get("provider","")
            model = data.get("model","")
            message = data.get("message","")
            if not provider or not message:
                self._json_response({"error": "provider and message required"})
                return
            # Build a simple chat request
            endpoint = PROVIDER_ENDPOINTS.get(provider, {})
            base_url = endpoint.get("base_url","")
            fmt = endpoint.get("format","openai")
            if not base_url:
                self._json_response({"error": f"No endpoint for provider {provider}"})
                return
            # Check for API key in env
            env_names = [f"{provider.upper().replace('-','_')}_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
            api_key = ""
            for ev in env_names:
                v = os.environ.get(ev)
                if v:
                    api_key = v
                    break
            if not api_key:
                # Check config
                config = PATHS.get("config","")
                if config and os.path.exists(config):
                    try:
                        import re
                        t=re.sub(r'^\s*//.*','',open(config,encoding="utf-8").read(),flags=re.MULTILINE); t=re.sub(r'/\*[\s\S]*?\*/','',t)
                        cfg=json.loads(t)
                        ak = cfg.get("api_keys",{})
                        if isinstance(ak, dict): api_key = ak.get(provider, ak.get("api_key",""))
                    except: pass
            if not api_key:
                self._json_response({"error": f"No API key found for {provider}"})
                return
            _add_log("INFO", f"Chat request -> {provider}/{model}")
            # Build request body based on format
            if fmt == "claude":
                url = f"{base_url}/v1/messages"
                req_body = {"model": model or "claude-sonnet-4-5", "max_tokens": 1024,
                           "messages": [{"role": "user", "content": message}]}
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            else:
                url = f"{base_url}/chat/completions"
                req_body = {"model": model or "gpt-4o", "max_tokens": 1024,
                           "messages": [{"role": "user", "content": message}]}
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            # Send request
            data_bytes = json.dumps(req_body).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=30)
                resp_data = json.loads(resp.read().decode("utf-8"))
                # Extract response text
                if fmt == "claude":
                    text = resp_data.get("content",[{}])[0].get("text","No response")
                else:
                    text = resp_data.get("choices",[{}])[0].get("message",{}).get("content","No response")
                _add_log("INFO", f"Chat response from {provider}: {len(text)} chars")
                self._json_response({"response": text})
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8","replace")[:500]
                _add_log("ERROR", f"Chat error from {provider}: {e.code} {err_body[:200]}")
                self._json_response({"error": f"HTTP {e.code}: {err_body[:200]}"})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _handle_log_clear(self):
        global _log_ring
        _log_ring = []
        self._json_response({"ok": True})

    def _handle_provider_test(self, provider_id):
        endpoint = PROVIDER_ENDPOINTS.get(provider_id, {})
        if not endpoint:
            self._json_response({"ok": False, "error": f"Unknown provider {provider_id}"})
            return
        base_url = endpoint.get("base_url","")
        fmt = endpoint.get("format","openai")
        # Check for API key
        env_names = [f"{provider_id.upper().replace('-','_')}_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
        api_key = ""
        for ev in env_names:
            v = os.environ.get(ev)
            if v:
                api_key = v
                break
        if not api_key:
            config = PATHS.get("config","")
            if config and os.path.exists(config):
                try:
                    import re
                    t=re.sub(r'^\s*//.*','',open(config,encoding="utf-8").read(),flags=re.MULTILINE); t=re.sub(r'/\*[\s\S]*?\*/','',t)
                    cfg=json.loads(t)
                    ak = cfg.get("api_keys",{})
                    if isinstance(ak, dict): api_key = ak.get(provider_id, ak.get("api_key",""))
                except: pass
        if not api_key:
            self._json_response({"ok": False, "error": "No API key configured"})
            return
        # Simple test: send a minimal request
        _add_log("INFO", f"Testing provider {provider_id}")
        try:
            if fmt == "claude":
                url = f"{base_url}/v1/messages"
                req_body = {"model": "claude-haiku-3-5", "max_tokens": 10, "messages": [{"role": "user", "content": "Say hi"}]}
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            else:
                url = f"{base_url}/chat/completions"
                req_body = {"model": "gpt-4o-mini", "max_tokens": 10, "messages": [{"role": "user", "content": "Say hi"}]}
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            data_bytes = json.dumps(req_body).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=10)
            resp_data = json.loads(resp.read().decode("utf-8"))
            model_used = resp_data.get("model", resp_data.get("choices",[{}])[0].get("model","unknown") if "choices" in resp_data else resp_data.get("model","unknown"))
            _add_log("INFO", f"Provider {provider_id} OK (model: {model_used})")
            self._json_response({"ok": True, "model": model_used})
        except urllib.error.HTTPError as e:
            _add_log("ERROR", f"Provider {provider_id} test failed: HTTP {e.code}")
            self._json_response({"ok": False, "error": f"HTTP {e.code}"})
        except Exception as e:
            _add_log("ERROR", f"Provider {provider_id} test failed: {e}")
            self._json_response({"ok": False, "error": str(e)})

    def _handle_routing_apply(self, body):
        try:
            data = json.loads(body) if body else {}
            preset_name = data.get("preset", "")
            
            PRESETS = {
                "maximize-claude": [
                    {"provider": "claude-code", "model": "claude-opus-4-7", "tier": "subscription"},
                    {"provider": "glm", "model": "glm-5.1", "tier": "cheap"},
                    {"provider": "kiro", "model": "claude-sonnet-4.5", "tier": "free"}
                ],
                "free-forever": [
                    {"provider": "kiro", "model": "claude-sonnet-4.5", "tier": "free"},
                    {"provider": "kiro", "model": "glm-5", "tier": "free"},
                    {"provider": "opencode-free", "model": "auto", "tier": "free"}
                ],
                "always-on": [
                    {"provider": "claude-code", "model": "claude-opus-4-7", "tier": "subscription"},
                    {"provider": "codex", "model": "gpt-5.5", "tier": "subscription"},
                    {"provider": "glm", "model": "glm-5.1", "tier": "cheap"},
                    {"provider": "minimax", "model": "MiniMax-M2.7", "tier": "cheap"},
                    {"provider": "kiro", "model": "claude-sonnet-4.5", "tier": "free"}
                ],
                "openclaw-free": [
                    {"provider": "kiro", "model": "claude-sonnet-4.5", "tier": "free"},
                    {"provider": "kiro", "model": "glm-5", "tier": "free"},
                    {"provider": "kiro", "model": "MiniMax-M2.5", "tier": "free"}
                ]
            }
            
            if preset_name not in PRESETS:
                self._json_response({"error": f"Unknown preset: {preset_name}"})
                return
            
            chain = PRESETS[preset_name]
            
            # Save the active chain to fallback.json
            fallback_path = PATHS.get("fallback", "")
            if fallback_path:
                try:
                    with open(fallback_path, "w") as f:
                        json.dump(chain, f, indent=2)
                    _add_log("INFO", f"Applied preset '{preset_name}' with {len(chain)} providers")
                    self._json_response({"ok": True, "preset": preset_name, "chain": chain})
                except Exception as e:
                    self._json_response({"error": f"Failed to save: {e}"})
            else:
                self._json_response({"error": "Fallback path not configured"})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _json_response(self, data):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-cache")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, f, *a): pass

# ---- HTML template (read from file or inline) ----
HTML = ""

def main():
    global PATHS, HTML
    if len(sys.argv) < 2:
        print("Usage: python _dashboard_server.py <config_path.json>", file=sys.stderr)
        sys.exit(1)
    config_path = sys.argv[1]
    PATHS = load_paths(config_path)
    # Load HTML
    html_path = Path(__file__).parent / "_dashboard.html"
    if html_path.exists():
        HTML = html_path.read_text(encoding="utf-8")
    else:
        HTML = "<html><body><h1>Dashboard HTML not found</h1><p>Expected: {}</p></body></html>".format(html_path)
    port = int(PATHS.get("port", 8200))
    _add_log("INFO", f"Dashboard server starting on port {port}")
    try:
        srv = http.server.HTTPServer(("127.0.0.1", port), DH)
        dash_cfg = PATHS.get("dashboard_config","")
        if dash_cfg:
            json.dump({"port": port, "enabled": True, "pid": os.getpid()}, open(dash_cfg, "w"))
        print(f"Dashboard running at http://127.0.0.1:{port}")
        srv.serve_forever()
    except Exception as e:
        dash_cfg = PATHS.get("dashboard_config","")
        if dash_cfg:
            json.dump({"port": port, "enabled": False, "error": str(e)}, open(dash_cfg, "w"))
        print(f"Dashboard failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
