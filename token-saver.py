#!/usr/bin/env python3
"""Token Saver CLI v9.0 — Compare providers, compress context, save tokens (lean-ctx + ctxrs/ctx inspired)"""

import json, os, re, sys, shutil, subprocess, time, glob, concurrent.futures, hashlib, threading, io, struct, tempfile, http.server
from pathlib import Path
from datetime import datetime, timedelta

# SQLite FTS5 index (inspired by ctxrs/ctx)
try:
    from token_index import (
        init_db as _init_index, search_events, search_files, sql_query,
        stats_summary as index_stats, import_from_legacy, verify_ledger as index_verify,
        log_event as _index_log_event, log_cache_hit as _index_log_cache,
        log_proxy_request as _index_log_proxy, DB_PATH as INDEX_DB_PATH,
    )
    INDEX_AVAILABLE = True
except ImportError:
    INDEX_AVAILABLE = False

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    import requests
except ImportError:
    print("Missing deps: pip install rich click requests")
    sys.exit(1)


try:
    if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

CONFIG_PATH = Path.home() / ".config" / "opencode" / "opencode.jsonc"
BACKUP_PATH = CONFIG_PATH.with_suffix(".jsonc.backup")
CACHE_PATH  = CONFIG_PATH.parent / "models_cache.json"
SNAPSHOT_PATH = CONFIG_PATH.parent / "models_snapshot.json"
CACHE_TTL   = 86400
MAX_BACKUPS = 5
BACKUP_DIR  = CONFIG_PATH.parent
TS_VERSION  = "9.0"

COMPRESS_DIR    = CONFIG_PATH.parent / "compress"
CONTENT_CACHE   = COMPRESS_DIR / "cache"
CONTENT_STORE   = COMPRESS_DIR / "store"
LEDGER_PATH     = COMPRESS_DIR / "savings_ledger.json"
BUDGET_PATH     = COMPRESS_DIR / "budget.json"
PROXY_CONFIG    = COMPRESS_DIR / "proxy.json"
FALLBACK_PATH   = COMPRESS_DIR / "fallback.json"
DASHBOARD_CONFIG = COMPRESS_DIR / "dashboard.json"
COST_PRICING_PATH = COMPRESS_DIR / "proxy_pricing.json"
SAVER_POLICY_PATH = COMPRESS_DIR / "saver_policy.json"
COMPRESS_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_CACHE.mkdir(parents=True, exist_ok=True)
CONTENT_STORE.mkdir(parents=True, exist_ok=True)

console = Console(legacy_windows=False)

KNOWN_PROVIDER_ENV_VARS = {
    "openai": ["OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_BASE_URL"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY"],
    "vertex": ["VERTEX_CREDENTIALS", "VERTEX_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS"],
    "aws": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    "azure": ["AZURE_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_API_BASE"],
    "cohere": ["COHERE_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "fireworks": ["FIREWORKS_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "replicate": ["REPLICATE_API_TOKEN", "REPLICATE_API_KEY"],
    "huggingface": ["HUGGINGFACE_API_KEY", "HUGGINGFACE_TOKEN", "HF_API_KEY"],
    "xai": ["XAI_API_KEY"],
    "github": ["GITHUB_TOKEN", "GITHUB_API_KEY"],
    "github_models": ["GITHUB_TOKEN"],
    "claudinio": ["CLAUDINIO_API_KEY"],
    "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
    "siliconflow": ["SILICONFLOW_API_KEY"],
    "deepinfra": ["DEEPINFRA_API_KEY"],
    "novita": ["NOVITA_API_KEY"],
    "sambanova": ["SAMBANOVA_API_KEY"],
    "nvidia": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"],
    "zenmux": ["ZENMUX_API_KEY"],
    "nara": ["NARA_API_KEY"],
    "venice": ["VENICE_API_KEY"],
    "llmgateway": ["LLMGATEWAY_API_KEY", "LLM_GATEWAY_API_KEY"],
    "zai": ["ZAI_API_KEY"],
    "nano_gpt": ["NANO_GPT_API_KEY", "NANOGPT_API_KEY"],
    "opencode": ["OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"],
}

API_KEY_ENV_PATTERNS = [
    (r'_API_KEY$', lambda name: name.replace('_API_KEY', '').lower()),
    (r'_AUTH_TOKEN$', lambda name: name.replace('_AUTH_TOKEN', '').lower()),
    (r'_API_TOKEN$', lambda name: name.replace('_API_TOKEN', '').lower()),
    (r'_TOKEN$', lambda name: name.replace('_TOKEN', '').lower()),
]

def get_providers_from_env() -> list[str]:
    detected = set()
    for provider_id, env_vars in KNOWN_PROVIDER_ENV_VARS.items():
        for var in env_vars:
            val = os.environ.get(var, "")
            if val and len(val.strip()) > 0:
                detected.add(provider_id)
                break
    for key, val in os.environ.items():
        if not val or not val.strip():
            continue
        upper = key.upper()
        for pattern, extract in API_KEY_ENV_PATTERNS:
            import re
            if re.search(pattern, upper):
                provider = extract(key)
                if provider in ('', 'api', 'secret', 'key', 'auth', 'token', 'bearer'):
                    continue
                detected.add(provider)
                break
    return sorted(detected)

def get_providers_from_model_history() -> list[str]:
    model_path = CONFIG_PATH.parent.parent / "state" / "opencode" / "model.json"
    alt_path = Path.home() / ".local" / "state" / "opencode" / "model.json"
    providers = set()
    for path in [model_path, alt_path]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for entry in data.get("recent", []):
                    pid = entry.get("providerID", "")
                    if pid: providers.add(pid)
                for entry in data.get("favorite", []):
                    pid = entry.get("providerID", "")
                    if pid: providers.add(pid)
                for key in data.get("variant", {}).keys():
                    if "/" in key:
                        pid = key.split("/")[0]
                        if pid: providers.add(pid)
            except: pass
    return sorted(providers)

def get_providers_from_catalog_crossref() -> list[str]:
    detected = set()
    catalog = None
    if CACHE_PATH.exists():
        try:
            catalog = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except: pass
    if not catalog:
        return []
    catalog_provider_ids = list(catalog.keys())
    env_apikeys = {}
    for key, val in os.environ.items():
        if not val or not val.strip():
            continue
        upper = key.upper()
        for suffix in ['_API_KEY', '_AUTH_TOKEN', '_API_TOKEN', '_TOKEN',
                       '_API_SECRET', '_SECRET_KEY', '_ACCESS_KEY',
                       '_API', '_BASE_URL', '_ENDPOINT', '_KEY']:
            if upper.endswith(suffix):
                provider_name = key.replace(suffix, '').lower()
                provider_name = provider_name.replace('-', '_').replace(' ', '_')
                env_apikeys[key] = provider_name
                break
        if 'API' in upper and ('KEY' in upper or 'TOKEN' in upper or 'SECRET' in upper):
            parts = key.lower().split('_')
            generic = {'api', 'key', 'token', 'secret', 'auth', 'bearer',
                      'access', 'endpoint', 'base', 'url', 'org', 'id',
                      'application', 'credentials', 'service', 'account'}
            meaningful = [p for p in parts if p not in generic and len(p) > 1]
            if meaningful:
                for potential in meaningful:
                    env_apikeys[f"{key}::{potential}"] = potential
    for var_name, extracted_name in env_apikeys.items():
        if extracted_name in catalog_provider_ids:
            detected.add(extracted_name)
        clean = extracted_name.replace('_', '')
        for cpid in catalog_provider_ids:
            if clean == cpid.replace('_', '').replace('-', ''):
                detected.add(cpid)
                break
        for cpid, pdata in catalog.items():
            if not isinstance(pdata, dict): continue
            pname = (pdata.get("name", "") or "").lower().replace(' ', '_').replace('-', '_')
            if extracted_name in pname or pname in extracted_name:
                detected.add(cpid)
                break
    history_path = CONFIG_PATH.parent.parent / "state" / "opencode" / "prompt-history.jsonl"
    alt_hist = Path.home() / ".local" / "state" / "opencode" / "prompt-history.jsonl"
    for hpath in [history_path, alt_hist]:
        if hpath.exists():
            try:
                text = hpath.read_text(encoding="utf-8", errors="ignore")
                for cpid in catalog_provider_ids:
                    if cpid.lower() in text.lower():
                        detected.add(cpid)
            except: pass
    return sorted(detected)

def strip_jsonc(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r'^\s*//.*', '', line))
    joined = '\n'.join(lines)
    return re.sub(r'/\*[\s\S]*?\*/', '', joined)

def read_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    # utf-8-sig strips a UTF-8 BOM if Windows tools rewrote the file
    clean = strip_jsonc(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return None

def write_config(model_id: str, small_id: str):
    existing = read_config() or {}
    con = {
        "model": model_id,
        "small_model": small_id,
        "compaction": {"auto": True, "prune": True, "reserved": 10000},
    }
    if "provider" in existing:
        con["provider"] = existing["provider"]
    else:
        con["provider"] = {}
    for pid in list(con["provider"].keys()):
        if isinstance(con["provider"][pid], dict):
            opts = con["provider"][pid].get("options", {})
            opts.setdefault("timeout", 300000)
            opts.setdefault("chunkTimeout", 60000)
            con["provider"][pid]["options"] = opts
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        rotate_backup()
    text = json.dumps(con, indent=2)
    CONFIG_PATH.write_text(text + '\n', encoding="utf-8")

def rotate_backup():
    if not CONFIG_PATH.exists(): return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"opencode.jsonc.{ts}.backup"
    shutil.copy2(CONFIG_PATH, backup)
    old = sorted(BACKUP_DIR.glob("opencode.jsonc.*.backup"), reverse=True)
    for f in old[MAX_BACKUPS:]: f.unlink(missing_ok=True)

def list_backups() -> list[tuple[str, str]]:
    result = []
    for f in sorted(BACKUP_DIR.glob("opencode.jsonc.*.backup"), reverse=True):
        parts = f.name.split(".")
        if len(parts) >= 3:
            ts = parts[2]
            try:
                dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                label = dt.strftime("%b %d %H:%M")
            except: label = ts
            result.append((label, str(f)))
    return result

def get_configured_providers() -> list[str]:
    configured = set()
    cfg = read_config()
    if cfg and "provider" in cfg:
        configured.update(cfg["provider"].keys())
    configured.update(get_providers_from_env())
    configured.update(get_providers_from_model_history())
    configured.update(get_providers_from_catalog_crossref())
    return sorted(configured)

def get_explicit_provider_ids() -> list[str]:
    """Providers with an explicit config entry or current API-key env var."""
    configured = set()
    cfg = read_config()
    if cfg and isinstance(cfg.get("provider"), dict):
        configured.update(cfg["provider"].keys())
    configured.update(get_providers_from_env())
    return sorted(configured)

def fetch_catalog() -> tuple[dict | None, list[dict]]:
    if CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < CACHE_TTL:
            try:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8")), []
            except: pass
    try:
        r = requests.get("https://models.dev/api.json", timeout=15)
        r.raise_for_status()
        data = r.json()
        CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
        old_snap = load_snapshot()
        new_models = diff_new_models(old_snap, data) if old_snap else []
        save_snapshot(data)
        return data, new_models
    except Exception as e:
        if CACHE_PATH.exists():
            try:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8")), []
            except: pass
        console.print(f"  [red][ERR] Could not fetch models.dev data: {e}[/]")
        return None, []

def build_snapshot(catalog: dict) -> dict:
    snap = {}
    for provider_id, pdata in catalog.items():
        if not isinstance(pdata, dict) or "models" not in pdata: continue
        mids = sorted(pdata["models"].keys())
        if mids: snap[provider_id] = mids
    return snap

def load_snapshot() -> dict | None:
    if SNAPSHOT_PATH.exists():
        try: return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except: pass
    return None

def save_snapshot(catalog: dict):
    SNAPSHOT_PATH.write_text(json.dumps(build_snapshot(catalog)), encoding="utf-8")

def diff_new_models(old_snap: dict, catalog: dict) -> list[dict]:
    new = []
    for provider_id, pdata in catalog.items():
        if not isinstance(pdata, dict) or "models" not in pdata: continue
        cur = set(pdata["models"].keys())
        prv = set(old_snap.get(provider_id, []))
        for mid in sorted(cur - prv):
            m = pdata["models"][mid]
            if not isinstance(m, dict): continue
            cst = m.get("cost", {})
            inp = cst.get("input", 0)
            outp = cst.get("output", 0)
            new.append({
                "provider": pdata.get("name", provider_id),
                "model_name": m.get("name", mid),
                "input_price": inp, "output_price": outp,
                "context": m.get("limit", {}).get("context", 0),
                "tool_call": m.get("tool_call", False),
                "is_free": inp == 0 and outp == 0,
            })
    return new

def get_user_models() -> tuple[dict | None, list[dict]]:
    catalog, new_models = fetch_catalog()
    if not catalog: return None, []
    configured = get_configured_providers()
    result = {}
    for provider_id, pdata in catalog.items():
        if not isinstance(pdata, dict) or "models" not in pdata: continue
        models = pdata.get("models", {})
        if not models: continue
        provider_name = pdata.get("name", provider_id)
        provider_key = f"{provider_id} ({provider_name})" if provider_name != provider_id else provider_id
        is_configured = provider_id in configured
        model_list = []
        for model_id, mdata in models.items():
            if not isinstance(mdata, dict): continue
            cost = mdata.get("cost", {})
            inp = cost.get("input", 0)
            outp = cost.get("output", 0)
            cache = cost.get("cache_read", None)
            is_free = inp == 0 and outp == 0
            model_list.append({
                "id": f"{provider_id}/{model_id}",
                "name": mdata.get("name", model_id),
                "provider": provider_id,
                "input_price": inp, "output_price": outp, "cache_price": cache,
                "context": mdata.get("limit", {}).get("context", 0),
                "output_limit": mdata.get("limit", {}).get("output", 0),
                "is_free": is_free,
                "tool_call": mdata.get("tool_call", False),
                "reasoning": mdata.get("reasoning", False),
                "open_weights": mdata.get("open_weights", False),
            })
        if model_list:
            model_list.sort(key=lambda x: (x["input_price"] + x["output_price"]))
            result[provider_key] = {
                "id": provider_id, "configured": is_configured,
                "name": provider_name, "models": model_list,
            }
    return result, new_models

def find_model_in_catalog(catalog: dict, model_id: str) -> dict | None:
    if not catalog: return None
    for key, pd in catalog.items():
        for m in pd["models"]:
            if m["id"] == model_id: return m
    return None

def model_total_cost(model: dict) -> float:
    return float(model.get("input_price", 0) or 0) + float(model.get("output_price", 0) or 0)

def read_saver_policy() -> dict:
    default = {
        "mode": "paid",
        "daily_budget_usd": 1.0,
        "free_daily_token_limit": 100000,
        "max_paid_cost_per_million": 5.0,
        "last_applied": None,
    }
    if SAVER_POLICY_PATH.exists():
        try:
            saved = json.loads(SAVER_POLICY_PATH.read_text(encoding="utf-8"))
            return {**default, **saved}
        except: pass
    return default

def write_saver_policy(policy: dict):
    SAVER_POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVER_POLICY_PATH.write_text(json.dumps(policy, indent=2), encoding="utf-8")

def normalize_provider_filter(provider: str | None) -> str | None:
    if provider is None:
        return None
    provider = provider.strip().lower()
    if provider in ("", "any", "all", "*", "none", "no"):
        return None
    return provider

def configured_model_list(catalog: dict, strict: bool = False) -> list[dict]:
    explicit = set(get_explicit_provider_ids()) if strict else None
    return [
        m for _key, pd in catalog.items()
        if (pd.get("id") in explicit if strict else pd.get("configured"))
        for m in pd.get("models", [])
    ]

def choose_saver_models(catalog: dict, mode: str, task: str, max_paid_cost: float, provider: str | None = None, strict: bool = False) -> dict:
    provider = normalize_provider_filter(provider)
    configured = configured_model_list(catalog, strict=strict)
    if provider:
        configured = [m for m in configured if m.get("provider") == provider or m["id"].startswith(provider + "/")]
    if not configured:
        msg = "No usable providers found. Add an API key/provider config first."
        if provider:
            msg = f"No usable models found for provider '{provider}'. Add its API key/config first."
        return {"error": msg}

    configured.sort(key=model_total_cost)
    free_models = [m for m in configured if m.get("is_free")]
    paid_allowed = [m for m in configured if not m.get("is_free") and model_total_cost(m) <= max_paid_cost]
    cheap_pool = free_models + paid_allowed
    if mode == "free":
        candidate_pool = free_models or paid_allowed or configured[:3]
    else:
        candidate_pool = cheap_pool or configured[:3]

    if task in ("coding", "review"):
        tool_candidates = [m for m in candidate_pool if m.get("tool_call")]
        if tool_candidates:
            candidate_pool = tool_candidates
    if task in ("review", "planning"):
        reasoning_candidates = [m for m in candidate_pool if m.get("reasoning")]
        if reasoning_candidates:
            candidate_pool = reasoning_candidates

    candidate_pool.sort(key=lambda m: (not m.get("is_free") if mode == "free" else False, model_total_cost(m), -int(m.get("context", 0) or 0)))
    main_model = candidate_pool[0]

    small_pool = free_models if free_models else configured
    small_pool = [m for m in small_pool if m["id"] != main_model["id"]] or small_pool
    small_pool.sort(key=lambda m: (not m.get("is_free") if mode == "free" else False, model_total_cost(m)))
    small_model = small_pool[0]

    fallback_pool = [m for m in cheap_pool if m["id"] not in {main_model["id"], small_model["id"]}]
    fallback_pool.sort(key=lambda m: (not m.get("is_free") if mode == "free" else False, model_total_cost(m)))
    fallbacks = [m["id"] for m in fallback_pool[:3]]

    return {
        "main": main_model,
        "small": small_model,
        "fallbacks": fallbacks,
        "configured_count": len(configured),
        "free_count": len(free_models),
        "paid_allowed_count": len(paid_allowed),
    }

def banner():
    console.print(f"  [cyan]+{'='*50}+[/]")
    console.print(f"  [cyan]|[/]  [bold cyan]OpenCode Token Saver CLI v{TS_VERSION}[/]              [cyan]|[/]")
    console.print(f"  [cyan]|[/]  [cyan]Compare - Compress - Cache - Proxy - Search[/]     [cyan]|[/]")
    console.print(f"  [cyan]|[/]  [dim]SQLite FTS5 index + MCP + Agent skills[/]        [cyan]|[/]")
    console.print(f"  [cyan]+{'='*50}+[/]")

def status_panel():
    cfg = read_config()
    if not cfg: return Panel("[red]No config found[/]", box=box.SIMPLE)
    lines = []
    model_id = cfg.get("model", "(not set)")
    small_id = cfg.get("small_model", "(not set)")
    model_name = model_id
    small_name = small_id
    if CACHE_PATH.exists():
        try:
            catalog, _ = get_user_models()
            if catalog:
                m = find_model_in_catalog(catalog, model_id)
                if m: model_name = m["name"]
                s = find_model_in_catalog(catalog, small_id)
                if s: small_name = s["name"]
        except: pass
    lines.append(f"Model    : {model_name}")
    lines.append(f"Small    : {small_name}")
    c = cfg.get("compaction", {})
    a = "ON" if c.get("auto") else "OFF"
    p = "ON" if c.get("prune") else "OFF"
    r = c.get("reserved", "-")
    lines.append(f"Compact  : auto={a}  prune={p}  reserved={r}")
    try:
        policy = read_saver_policy()
        lines.append(f"Save mode: {policy.get('mode', 'paid')}  max_paid=${policy.get('max_paid_cost_per_million', 5.0)}/M")
    except: pass
    try:
        cc = ContentCache.stats()
        if cc["cached_files"] > 0:
            lines.append(f"Compress : {cc['cached_files']} cached  ~{cc['total_savings_pct']:.0f}% savings")
    except: pass
    return Panel("\n".join(lines), title="Current Status", box=box.SIMPLE, border_style="yellow")

def menu(title: str, items: list, current_id: str | None = None) -> dict | None:
    import msvcrt
    idx = 0
    if current_id:
        for i, it in enumerate(items):
            if it["id"] == current_id: idx = i; break
    while True:
        console.clear()
        banner()
        console.print(f"\n  [yellow]{title}[/]\n")
        tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        for i, it in enumerate(items):
            prefix = ">" if i == idx else " "
            label = it["name"]
            if "tag" in it: label += f"  [{it['tag']}]"
            if "desc" in it and it["desc"]: label += f"  {it['desc']}"
            sel = " (active)" if it["id"] == current_id else ""
            txt = Text()
            txt.append(f"  {prefix} ", style="cyan" if i == idx else "dim")
            txt.append(label, style="white" if i == idx else "grey50")
            if sel: txt.append(sel, style="green")
            tbl.add_row(txt)
        console.print(tbl)
        console.print("\n  [dim]Up/Down Navigate | Enter Select | Esc Back[/]")
        key = msvcrt.getch()
        if key == b'\xe0':
            k2 = msvcrt.getch()
            if k2 == b'H': idx = max(0, idx - 1)
            elif k2 == b'P': idx = min(len(items) - 1, idx + 1)
        elif key in (b'\r', b'\n'): return items[idx]
        elif key == b'\x1b': return None

def confirm(msg: str) -> bool:
    console.print(f"\n  [yellow]{msg} [y/n][/] ", end="")
    import msvcrt
    while True:
        k = msvcrt.getch().lower()
        if k == b'y': return True
        if k == b'n': return False

def press_any():
    if not sys.stdin.isatty():
        return
    console.print("\n  [dim]Press any key to continue...[/]", end="")
    import msvcrt
    msvcrt.getch()

def show_models_table(provider_data: dict, title: str = "Models"):
    if not provider_data:
        console.print("  [red]No data.[/]")
        return
    providers_list = list(provider_data.values())
    providers_list.sort(key=lambda x: (not x["configured"], x["name"]))
    for pd in providers_list:
        config_badge = " [green](CONFIGURED)[/]" if pd["configured"] else ""
        table = Table(title=f"{pd['name']}{config_badge}", box=box.SIMPLE, show_lines=False, header_style="bold cyan")
        table.add_column("Model", style="white")
        table.add_column("In $/M", justify="right", style="yellow")
        table.add_column("Out $/M", justify="right", style="yellow")
        table.add_column("Cache $/M", justify="right", style="dim")
        table.add_column("Context", justify="right", style="cyan")
        table.add_column("Tools", justify="center", style="blue")
        table.add_column("Free?", justify="center", style="green")
        for m in pd["models"]:
            in_s = f"" if m['input_price'] > 0 else "[green]FREE[/]"
            out_s = f"" if m['output_price'] > 0 else "[green]FREE[/]"
            cache_s = f"" if m['cache_price'] else "-"
            ctx = f"{m['context']:,}" if m['context'] else "-"
            tools = "[green]Y[/]" if m['tool_call'] else "[dim]N[/]"
            free = "[bold green]FREE[/]" if m['is_free'] else "-"
            table.add_row(m["name"], in_s, out_s, cache_s, ctx, tools, free)
        console.print(table)
        console.print("")

def show_new_models(new_models: list[dict]):
    if not new_models: return
    tbl = Table(title="[bold green]New Models Detected![/]", box=box.SIMPLE, header_style="bold green")
    tbl.add_column("Provider", style="green")
    tbl.add_column("Model", style="white")
    tbl.add_column("In $/M", justify="right", style="yellow")
    tbl.add_column("Out $/M", justify="right", style="yellow")
    tbl.add_column("Context", justify="right", style="cyan")
    tbl.add_column("Tools", justify="center", style="blue")
    for m in new_models:
        in_s = f"" if m['input_price'] > 0 else "[green]FREE[/]"
        out_s = f"" if m['output_price'] > 0 else "[green]FREE[/]"
        ctx = f"{m['context']:,}" if m['context'] else "-"
        tools = "[green]Y[/]" if m['tool_call'] else "[dim]N[/]"
        tbl.add_row(m["provider"], m["model_name"], in_s, out_s, ctx, tools)
    console.print("")
    console.print(tbl)
    console.print("")

def select_model_from_provider(catalog: dict, current_id: str | None = None, title: str = "Select Model", configured_only: bool = True) -> dict | None:
    if not catalog: return None
    current_provider_id = None
    if current_id:
        for key, pd in catalog.items():
            for m in pd["models"]:
                if m["id"] == current_id: current_provider_id = pd["id"]; break
            if current_provider_id: break
    provider_list = []
    for key, pd in sorted(catalog.items()):
        if configured_only and not pd["configured"]: continue
        config_badge = "CONFIGURED" if pd["configured"] else "NO API KEY"
        provider_list.append({"id": pd["id"], "name": f"{pd['name']}  [{config_badge}]  ({len(pd['models'])} models)"})
    if not provider_list: return None
    selected = menu(f"{title} - Choose Provider", provider_list, current_provider_id)
    if not selected: return None
    provider_data = None
    for key, pd in catalog.items():
        if pd["id"] == selected["id"]: provider_data = pd; break
    if not provider_data: return None
    model_items = []
    for m in provider_data["models"]:
        price_str = "FREE" if m['is_free'] else f"${m['input_price']:.4f}/${m['output_price']:.4f}"
        model_items.append({"id": m["id"], "name": f"{m['name']}  ({price_str})"})
    return menu(f"{title} - {provider_data['name']}", model_items, current_id)

HEALTH_ENDPOINTS: dict[str, tuple[str, str, dict | None]] = {
    "openai":      ("GET", "https://api.openai.com/v1/models", None),
    "anthropic":   ("GET", "https://api.anthropic.com/v1/models", None),
    "google":      ("GET", "https://generativelanguage.googleapis.com/v1/models", None),
    "deepseek":    ("GET", "https://api.deepseek.com/v1/models", None),
    "mistral":     ("GET", "https://api.mistral.ai/v1/models", None),
    "cohere":      ("GET", "https://api.cohere.ai/v1/models", None),
    "groq":        ("GET", "https://api.groq.com/openai/v1/models", None),
    "openrouter":  ("GET", "https://openrouter.ai/api/v1/models", None),
    "together":    ("GET", "https://api.together.xyz/v1/models", None),
    "fireworks":   ("GET", "https://api.fireworks.ai/inference/v1/models", None),
    "xai":         ("GET", "https://api.x.ai/v1/models", None),
    "perplexity":  ("GET", "https://api.perplexity.ai/models", None),
    "deepinfra":   ("GET", "https://api.deepinfra.com/v1/models", None),
    "nvidia":      ("GET", "https://api.nvcf.nvidia.com/v1/models", None),
    "cerebras":    ("GET", "https://api.cerebras.ai/public/v1/models", None),
    "siliconflow": ("GET", "https://api.siliconflow.cn/v1/models", None),
    "huggingface": ("GET", "https://huggingface.co/api/models", None),
    "venice":      ("GET", "https://api.venice.ai/api/v1/models", None),
    "zenmux":      ("GET", "https://zenmux.ai/api/v1/models", None),
    "ollama":      ("GET", "https://ollama.com/api/tags", None),
    "opencode":    ("GET", "https://opencode.ai/zen/v1/models", None),
    "zai":         ("GET", "https://api.z.ai/api/paas/v4/models", None),
    "iflowcn":     ("GET", "https://apis.iflow.cn/v1/models", None),
    "anyapi":      ("GET", "https://api.anyapi.ai/v1/models", None),
    "llama":       ("GET", "https://llama.developer.meta.com/api/v1/models", None),
}

# Default API base URLs per provider (used as fallback so the proxy always
# knows the real upstream even if OpenCode config only points at the proxy).
PROVIDER_DEFAULT_BASE_URLS = {
    pid: url.rsplit("/models", 1)[0]
    for pid, (_, url, _) in HEALTH_ENDPOINTS.items()
}
# Override for providers where the inference API base URL differs from
# what HEALTH_ENDPOINTS derives. HEALTH_ENDPOINTS uses a model-listing
# endpoint for connectivity checks, but the OpenAI-compatible chat endpoint
# may live at a different host/path.
INFERENCE_BASE_URL_OVERRIDES: dict[str, str] = {
    "huggingface": "https://api-inference.huggingface.co/v1",
}
# Apply overrides on top of the default map
PROVIDER_DEFAULT_BASE_URLS.update(INFERENCE_BASE_URL_OVERRIDES)

def provider_health(provider_id: str) -> tuple[str, str]:
    info = HEALTH_ENDPOINTS.get(provider_id)
    if not info: return ("no_check", "")
    method, url, headers_extra = info
    env_vars = KNOWN_PROVIDER_ENV_VARS.get(provider_id, [])
    api_key = next((os.environ.get(v, "") for v in env_vars if os.environ.get(v, "")), None)
    if not api_key:
        cfg = read_config()
        if cfg and "provider" in cfg and provider_id in cfg["provider"]:
            pconf = cfg["provider"][provider_id]
            api_key = pconf.get("apiKey", "") or pconf.get("api_key", "") or ""
    if not api_key: return ("no_key", "")
    headers = {"Authorization": f"Bearer {api_key}"}
    if headers_extra: headers.update(headers_extra)
    try:
        r = requests.request(method, url, headers=headers, timeout=3)
        if r.ok: return ("up", "")
        msg = ""
        try:
            body = r.json()
            msg = body.get("error", {}).get("message", "") or body.get("error", "") or ""
        except: pass
        if not msg: msg = f"HTTP {r.status_code}"
        return ("err", msg[:80])
    except requests.Timeout:
        return ("down", "timeout")
    except requests.ConnectionError:
        return ("down", "connection refused")
    except requests.RequestException as e:
        return ("down", str(e)[:60])

def show_health_check(catalog: dict):
    configured_pids = set()
    for key, pd in catalog.items():
        if pd["configured"]: configured_pids.add(pd["id"])
    if not configured_pids:
        console.print("  [yellow]No configured providers to check.[/]"); return
    console.print("\n  [yellow]Checking provider connectivity (3s timeout)...[/]")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut = {ex.submit(provider_health, pid): pid for pid in configured_pids}
        for f in concurrent.futures.as_completed(fut):
            pid = fut[f]
            try: results[pid] = f.result()
            except Exception as e: results[pid] = ("down", str(e)[:40])
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Provider"); tbl.add_column("Status")
    for pid in sorted(configured_pids):
        status, msg = results.get(pid, ("no_check", ""))
        icons = {
            "up": "[green]UP[/]", "down": "[red]DOWN[/]", "err": "[yellow]ERR[/]",
            "no_key": "[dim]NO KEY[/]", "no_check": "[dim]SKIP[/]",
        }
        label = icons.get(status, f"[dim]{status}[/]")
        if msg: label += f"  [dim]{msg}[/]"
        tbl.add_row(f"  [cyan]{pid}[/]", label)
    console.print(tbl)

def clean_invalid_keys(catalog: dict):
    configured_pids = set()
    for key, pd in catalog.items():
        if pd["configured"]: configured_pids.add(pd["id"])
    if not configured_pids:
        console.print("  [yellow]No configured providers to check.[/]"); return
    console.print("\n  [yellow]Checking provider connectivity (3s timeout)...[/]")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut = {ex.submit(provider_health, pid): pid for pid in configured_pids}
        for f in concurrent.futures.as_completed(fut):
            pid = fut[f]
            try: results[pid] = f.result()
            except Exception as e: results[pid] = ("down", str(e)[:40])
    bad = {}
    for pid in sorted(configured_pids):
        status, msg = results.get(pid, ("no_check", ""))
        if status in ("err", "down", "no_key"):
            bad[pid] = (status, msg)
    if not bad:
        console.print("  [green]All configured providers are healthy![/]")
        return
    console.print("\n  [yellow]Providers with invalid keys or errors:[/]\n")
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Provider"); tbl.add_column("Status")
    for pid, (status, msg) in bad.items():
        icons = {"down": "[red]DOWN[/]", "err": "[yellow]ERR[/]", "no_key": "[dim]NO KEY[/]"}
        label = icons.get(status, status)
        if msg: label += f"  [dim]{msg}[/]"
        tbl.add_row(f"  [cyan]{pid}[/]", label)
    console.print(tbl)
    if not confirm("Remove these providers from config?"):
        console.print("  [dim]Skipped.[/]"); return
    cfg = read_config()
    removed = []
    env_only = []
    for pid in bad:
        if cfg and "provider" in cfg and pid in cfg["provider"]:
            del cfg["provider"][pid]
            removed.append(pid)
        else:
            env_only.append(pid)
    if removed:
        write_config(cfg.get("model", ""), cfg.get("small_model", ""))
        for pid in removed:
            console.print(f"  [green]Removed {pid} from config.[/]")
        console.print("  [green]Config updated. Restart opencode to apply.[/]")
    if env_only:
        console.print("\n  [yellow]These providers were detected from environment variables:[/]")
        env_actions = []
        for pid in env_only:
            env_vars = KNOWN_PROVIDER_ENV_VARS.get(pid, [])
            active = [v for v in env_vars if os.environ.get(v, "")]
            if active:
                for v in active:
                    env_actions.append((pid, v))
        if env_actions:
            console.print("")
            for pid, v in env_actions:
                console.print(f"  [cyan]{pid}[/]  ->  {v}={os.environ.get(v,'')[:60]}")
            if confirm("Clear these env vars via setx?"):
                for pid, v in env_actions:
                    r = subprocess.run(["setx", v, ""], capture_output=True)
                    if r.returncode == 0:
                        console.print(f"  [green]Cleared {v} for {pid}.[/]")
                    else:
                        msg = r.stderr.decode("utf-8", errors="replace").strip()
                        console.print(f"  [red]Failed to clear {v}: {msg}[/]")
                console.print("  [green]Env vars cleared. Restart your terminal to take effect.[/]")
                console.print("  [yellow]Run health check again after restart to confirm.[/]")
            else:
                console.print("  [dim]Skipped. Run setx manually to clear them.[/]")
        else:
            console.print("  [yellow]No known env vars found. Check your system environment variables.[/]")

TASK_TEMPLATES: dict[str, list[dict]] = {
    "coding": [
        {"tag": "strong", "desc": "Best quality, higher cost", "weight": -1},
        {"tag": "balanced", "desc": "Good quality, moderate cost", "weight": 0},
    ],
    "review": [
        {"tag": "cheap", "desc": "Fast & cheap, good for diffs", "weight": 0},
        {"tag": "balanced", "desc": "Balanced quality/speed", "weight": 1},
    ],
    "planning": [
        {"tag": "balanced", "desc": "Good reasoning, moderate cost", "weight": 0},
        {"tag": "strong", "desc": "Best reasoning, higher cost", "weight": 1},
    ],
}

def recommend_models(catalog: dict, task: str):
    configured = []
    for key, pd in catalog.items():
        if pd["configured"]: configured.extend(pd["models"])
    if not configured:
        console.print("  [yellow]No configured providers.[/]"); return
    templates = TASK_TEMPLATES.get(task, TASK_TEMPLATES["coding"])
    seen = set()
    for tpl in templates:
        desc = tpl["desc"]
        if tpl["weight"] == -1:
            candidates = sorted(configured, key=lambda x: -(x["input_price"] + x["output_price"]))
        elif tpl["weight"] == 1:
            mid = len(configured) // 2
            candidates = configured[mid:]
        else:
            candidates = sorted(configured, key=lambda x: x["input_price"] + x["output_price"])
        for m in candidates:
            if m["id"] not in seen:
                seen.add(m["id"])
                price = "FREE" if m["is_free"] else f"${m['input_price']:.4f}/${m['output_price']:.4f}"
                console.print(f"    [cyan]{m['name']}[/]  [dim]({price})[/]  {desc}")
                break

def show_heatmap(catalog: dict):
    configured = []
    for key, pd in catalog.items():
        if pd["configured"]: configured.extend(pd["models"])
    if not configured:
        console.print("  [yellow]No configured providers.[/]"); return
    caps = {
        "Cheapest overall":     lambda m: m["input_price"] + m["output_price"],
        "Cheapest w/ tools":    lambda m: m["input_price"] + m["output_price"] if m["tool_call"] else float("inf"),
        "Cheapest 128k+ ctx":   lambda m: m["input_price"] + m["output_price"] if m["context"] >= 128000 else float("inf"),
        "Cheapest reasoning":   lambda m: m["input_price"] + m["output_price"] if m["reasoning"] else float("inf"),
        "Largest context":      lambda m: -m["context"],
    }
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Capability"); tbl.add_column("Model"); tbl.add_column("In/Out $/M"); tbl.add_column("Provider")
    for label, key_fn in caps.items():
        best = min(configured, key=key_fn)
        if best["input_price"] + best["output_price"] == float("inf"): continue
        price = "FREE" if best["is_free"] else f"${best['input_price']:.4f}/${best['output_price']:.4f}"
        tbl.add_row(f"  [yellow]{label}[/]", best["name"], price, best["provider"])
    console.print("\n  [yellow]Best model per capability[/]")
    console.print(tbl)

def show_cost_projection(catalog: dict, model_id: str, small_id: str):
    m = find_model_in_catalog(catalog, model_id) if model_id else None
    s = find_model_in_catalog(catalog, small_id) if small_id else None
    scenarios = [
        ("Light session",   100_000, 20_000),
        ("Medium session",  500_000, 100_000),
        ("Heavy session",  2_000_000, 500_000),
    ]
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("Scenario"); tbl.add_column("Main model", justify="right"); tbl.add_column("Small model", justify="right")
    tbl.add_column("Savings", justify="right")
    for label, inp, outp in scenarios:
        if m:
            inp_cost = m["input_price"] * inp / 1_000_000
            outp_cost = m["output_price"] * outp / 1_000_000
            main_cost = inp_cost + outp_cost
            main_s = f"${main_cost:.2f}" if main_cost > 0 else "[green]FREE[/]"
        else: main_s = "[dim]N/A[/]"
        if s:
            inp_cost_s = s["input_price"] * inp / 1_000_000
            outp_cost_s = s["output_price"] * outp / 1_000_000
            small_cost = inp_cost_s + outp_cost_s
            small_s = f"${small_cost:.2f}" if small_cost > 0 else "[green]FREE[/]"
            if m and main_cost > 0 and small_cost > 0:
                saved = main_cost - small_cost
                pct = (saved / main_cost) * 100 if main_cost > 0 else 0
                savings = f"[green] ({pct:.0f}%)[/]" if saved > 0 else "[dim]-[/]"
            else: savings = "[dim]-[/]"
        else:
            small_s = "[dim]N/A[/]"; savings = "[dim]-[/]"
        tbl.add_row(label, main_s, small_s, savings)
    console.print("\n  [yellow]Cost projection (input / output tokens)[/]")
    console.print(tbl)
    if m or s: console.print("  [green]+ compaction saves ~30-50% more[/]")
    if m or s: console.print("  [green]+ compression saves 60-90% on reads/shell[/]")

@click.group()
def cli():
    """Token Saver - Compare providers & models, compress context, save tokens.
    Commands: set, save-max, save-money, compare, free, providers, verify,
    restore, health, recommend, heatmap, compress, cache, proxy, budget,
    savings, store, fallback, dashboard, search, sql, stats, mcp, skill, upgrade
    """
    pass

@cli.command(name="set")
@click.argument("tier", type=click.Choice(["cheapest", "cheap", "balanced", "strong"], case_sensitive=False))
@click.option("--provider", "-p", help="Filter to a specific provider (e.g. openai)")
def set_cmd(tier: str, provider: str | None):
    """Quick-set model from your configured providers: cheapest, cheap, balanced, strong"""
    with console.status("[yellow]Fetching model catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog:
        console.print("  [red]Could not fetch model data.[/]")
        return
    all_models = []
    for key, pd in catalog.items():
        if not pd["configured"]: continue
        if provider and provider.lower() not in pd["id"].lower(): continue
        for m in pd["models"]: all_models.append(m)
    if not all_models:
        console.print("  [red]No configured providers found. Add API keys first.[/]")
        return
    all_models.sort(key=lambda x: x["input_price"] + x["output_price"])
    tier_lower = tier.lower()
    if tier_lower == "cheapest": selected = all_models[0]
    elif tier_lower == "cheap": selected = all_models[max(0, len(all_models) // 4)]
    elif tier_lower == "balanced": selected = all_models[len(all_models) // 2]
    elif tier_lower == "strong": selected = all_models[-1]
    else:
        console.print(f"  [red]Unknown tier: {tier}[/]")
        return
    cfg = read_config()
    small = cfg["small_model"] if cfg and cfg.get("small_model") else ""
    write_config(selected["id"], small)
    console.print(f"\n  [green][OK] Model set to {selected['name']} ({selected['id']})[/]")
    console.print(f"  [dim]Input: ${selected['input_price']:.4f}/M  Output: ${selected['output_price']:.4f}/M[/]")
    console.print("  [yellow]Restart opencode to take effect.[/]")

@cli.command(name="save-max")
@click.option("--no-proxy", is_flag=True, help="Skip starting the proxy")
def save_max(no_proxy: bool):
    """Maximize token savings — auto-pick cheapest models, enable compaction, set fallbacks, start proxy"""
    console.clear(); banner()
    with console.status("[yellow]Fetching model catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog:
        console.print("  [red]Could not fetch model data.[/]"); return
    configured = [m for k, pd in catalog.items() if pd["configured"] for m in pd["models"]]
    if not configured:
        console.print("  [red]No configured providers. Add API keys first.[/]"); return
    configured.sort(key=lambda x: x["input_price"] + x["output_price"])
    main_candidates = [m for m in configured if m["tool_call"]]
    if not main_candidates: main_candidates = configured
    main_model = main_candidates[0]
    small_model = configured[0]
    small_model = configured[1] if len(configured) > 1 and configured[1]["id"] != main_model["id"] else small_model
    write_config(main_model["id"], small_model["id"])
    console.print(f"\n  [yellow]Optimizing for maximum token savings...[/]")
    steps = []
    steps.append(("Main model", f"{main_model['name']}  ${main_model['input_price']+main_model['output_price']:.4f}/M"))
    steps.append(("Small model", f"{small_model['name']}  ${small_model['input_price']+small_model['output_price']:.4f}/M"))
    steps.append(("Compaction", "auto=ON  prune=ON  reserved=10000"))
    expensive = [m for m in configured[3:] if m["input_price"] + m["output_price"] > 5]
    for em in expensive[:3]:
        fallbacks = [m["id"] for m in configured[:3] if m["id"] != em["id"]]
        if fallbacks:
            FallbackChain.set_chain(em["id"], fallbacks)
            steps.append((f"Fallback: {em['name']}", f"-> {fallbacks[0]}"))
    if not no_proxy:
        s = CompressionProxy.status()
        if s.get("running"):
            steps.append(("Proxy", "already running"))
        elif CompressionProxy.start_server():
            steps.append(("Proxy", "started (adaptive — works with any provider)"))
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Setting", style="cyan"); tbl.add_column("Value", style="green")
    for label, val in steps: tbl.add_row(f"  {label}", val)
    console.print(f"\n  [yellow]Optimizations Applied[/]\n"); console.print(tbl)
    cost = main_model["input_price"] + main_model["output_price"]
    if cost > 0:
        console.print(f"  [red]WARNING:[/] Selected model costs ${cost:.4f}/M tokens — not free.")
        console.print(f"  [yellow]  To save more, set an API key for a free provider (e.g. OPENAI_API_KEY for free tier).[/]")
    est_total = (main_model["input_price"] + main_model["output_price"]) * 2
    est_small = (small_model["input_price"] + small_model["output_price"]) * 2
    savings = (est_total - est_small) / est_total * 100 if est_total > 0 else 0
    console.print(f"\n  [cyan]Estimated savings:[/] [green]{savings:.0f}% on small model usage[/]")
    console.print(f"  [cyan]Proxy compression:[/] [green]+40-70% on API requests[/]")
    console.print(f"\n  [yellow]>>> MUST RESTART opencode for model + proxy changes to take effect <<<[/]")

@cli.command(name="save-money")
@click.option("--mode", "save_mode", type=click.Choice(["free", "paid"], case_sensitive=False), default="paid", show_default=True, help="free preserves limited free tokens; paid minimizes dollar spend")
@click.option("--task", type=click.Choice(["coding", "review", "planning"], case_sensitive=False), default="coding", show_default=True, help="Bias model choice for the work type")
@click.option("--max-paid-cost", default=5.0, show_default=True, type=float, help="Maximum input+output $/M allowed for paid candidates")
@click.option("--daily-budget", default=1.0, show_default=True, type=float, help="Soft daily budget stored for reports/guardrails")
@click.option("--free-token-limit", default=100000, show_default=True, type=int, help="Soft daily free-tier token limit stored for guardrails")
@click.option("--provider", help="Only choose models from this provider, e.g. openai, anthropic, openrouter")
@click.option("--apply", is_flag=True, help="Apply the selected models and fallback chain")
@click.option("--no-proxy", is_flag=True, help="Do not start/configure compression proxy when applying")
def save_money(save_mode: str, task: str, max_paid_cost: float, daily_budget: float, free_token_limit: int, provider: str | None, apply: bool, no_proxy: bool):
    """Practical saver mode for paid spend or limited free-tier tokens."""
    provider = normalize_provider_filter(provider)
    console.clear(); banner()
    with console.status("[yellow]Finding cheapest practical model setup...[/]"):
        catalog, _ = get_user_models()
    if not catalog:
        console.print("  [red]Could not fetch model data.[/]")
        return

    choice = choose_saver_models(catalog, save_mode.lower(), task.lower(), max_paid_cost, provider=provider, strict=True)
    if "error" in choice:
        console.print(f"  [red]{choice['error']}[/]")
        return

    main_model = choice["main"]
    small_model = choice["small"]
    main_cost = model_total_cost(main_model)
    small_cost = model_total_cost(small_model)

    policy = read_saver_policy()
    policy.update({
        "mode": save_mode.lower(),
        "task": task.lower(),
        "daily_budget_usd": daily_budget,
        "free_daily_token_limit": free_token_limit,
        "max_paid_cost_per_million": max_paid_cost,
        "provider": provider,
        "last_recommendation": {
            "main_model": main_model["id"],
            "small_model": small_model["id"],
            "fallbacks": choice["fallbacks"],
        },
    })

    console.print(f"\n  [yellow]Practical saver recommendation[/]\n")
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Setting", style="cyan")
    tbl.add_column("Value", style="white")
    tbl.add_row("  Mode", f"{save_mode.lower()} ({'avoid paid models first' if save_mode.lower() == 'free' else 'cap paid model cost'})")
    tbl.add_row("  Provider filter", provider or "[dim]any explicit provider when applying[/]")
    tbl.add_row("  Main model", f"{main_model['name']}  [dim]{main_model['id']}[/]  {'[green]FREE[/]' if main_model.get('is_free') else f'${main_cost:.4f}/M'}")
    tbl.add_row("  Small model", f"{small_model['name']}  [dim]{small_model['id']}[/]  {'[green]FREE[/]' if small_model.get('is_free') else f'${small_cost:.4f}/M'}")
    tbl.add_row("  Free models available", str(choice["free_count"]))
    tbl.add_row("  Paid cap", f"${max_paid_cost:.4f}/M input+output")
    tbl.add_row("  Compaction", "auto=ON  prune=ON  reserved=10000")
    tbl.add_row("  Fallbacks", " -> ".join(choice["fallbacks"]) if choice["fallbacks"] else "[dim]none[/]")
    console.print(tbl)

    if save_mode.lower() == "free" and not main_model.get("is_free"):
        console.print("\n  [yellow]No configured free model matched this task, so the recommendation uses the cheapest paid candidate under your cap.[/]")
    if not apply:
        console.print("\n  [cyan]Dry run only.[/] Add [yellow]--apply[/] to write OpenCode config and fallback settings.")
        console.print("  [dim]Example: python token-saver.py save-money --mode free --apply[/]")
        return

    write_config(main_model["id"], small_model["id"])
    if choice["fallbacks"]:
        FallbackChain.set_chain(main_model["id"], choice["fallbacks"])
    expensive = [m for m in configured_model_list(catalog, strict=True) if model_total_cost(m) > max_paid_cost and m["id"] != main_model["id"]]
    cheap_fallbacks = [main_model["id"]] + choice["fallbacks"]
    for model in expensive[:10]:
        FallbackChain.set_chain(model["id"], cheap_fallbacks[:3])

    policy["last_applied"] = datetime.now().isoformat()
    write_saver_policy(policy)

    proxy_status = "skipped"
    if not no_proxy:
        if CompressionProxy.start_server():
            proxy_status = "started"
        else:
            proxy_status = "already running or unavailable"

    console.print("\n  [green][OK] Saver settings applied.[/]")
    console.print(f"  [cyan]Proxy:[/] {proxy_status}")
    console.print("  [yellow]Restart opencode for model/proxy changes to take effect.[/]")

def find_opencode() -> str | None:
    import shutil
    p = shutil.which("opencode")
    if p: return p
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidate = Path(appdata) / "npm" / "opencode.ps1"
        if candidate.exists(): return str(candidate)
    return None

@cli.command()
def verify():
    """Check if all token-saver settings are active"""
    console.clear(); banner()
    oc = find_opencode()
    if not oc:
        console.print("  [red][ERR] opencode not found. Install via `npm install -g opencode` or add to PATH.[/]")
        return
    console.print(f"\n  [yellow]Verifying config with opencode...[/]")
    try: r = subprocess.run([oc, "debug", "config"], capture_output=True, text=True)
    except FileNotFoundError:
        console.print(f"  [red][ERR] opencode not found at: {oc}[/]"); return
    if r.returncode != 0:
        console.print(f"  [red][ERR] opencode returned exit code {r.returncode}[/]"); return
    try: parsed = json.loads(r.stdout)
    except json.JSONDecodeError:
        console.print("  [red][ERR] Could not parse opencode output[/]"); return
    checks = [
        ("compaction.auto", parsed.get("compaction", {}).get("auto") == True),
        ("compaction.prune", parsed.get("compaction", {}).get("prune") == True),
        ("compaction.reserved", parsed.get("compaction", {}).get("reserved", 0) > 0),
        ("small_model", bool(parsed.get("small_model"))),
        ("model", bool(parsed.get("model"))),
    ]
    console.print("")
    all_ok = True
    for name, ok in checks:
        s = "[OK]" if ok else "[ERR]"
        c = "green" if ok else "red"
        console.print(f"  [{c}]{s}[/]  {name}")
        if not ok: all_ok = False
    if all_ok: console.print("\n  [green]All settings active! Restart opencode to apply.[/]")
    else: console.print("\n  [yellow]Some settings missing. Run without subcommand to fix.[/]")

@cli.command()
@click.option("--list", "-l", "list_flag", is_flag=True, help="List available backups")
@click.option("--idx", type=int, default=1, help="Backup index to restore (1 = most recent)")
def restore(list_flag: bool, idx: int):
    """Restore config from backup"""
    if list_flag:
        backups = list_backups()
        if not backups:
            console.print("  [red]No backups found[/]"); return
        console.print("\n  [yellow]Available backups:[/]\n")
        for i, (label, path) in enumerate(backups, 1):
            sel = " (active)" if path == str(BACKUP_PATH) else ""
            console.print(f"  {i}. {label}{sel}")
        return
    backups = list_backups()
    if not backups:
        console.print("  [red]No backups found[/]"); return
    if idx < 1 or idx > len(backups):
        console.print(f"  [red]Invalid index. Choose 1-{len(backups)}[/]"); return
    _, path = backups[idx - 1]
    if confirm(f"Restore backup from {backups[idx-1][0]}?"):
        shutil.copy2(path, CONFIG_PATH)
        console.print(f"  [green][OK] Config restored from {backups[idx-1][0]}[/]")

@cli.command()
def providers():
    """List all providers and their API key status"""
    console.clear(); banner()
    with console.status("[yellow]Fetching provider catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog:
        console.print("  [red]Could not fetch provider data.[/]"); press_any(); return
    configured = get_configured_providers()
    total = len(catalog); configured_count = len(configured)
    console.print(f"\n  [yellow]All Providers ({total} found | {configured_count} configured)[/]\n")
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Provider"); tbl.add_column("Status"); tbl.add_column("Models"); tbl.add_column("Details")
    for key, pd in sorted(catalog.items()):
        pid = pd["id"]
        status = "[green]CONFIGURED[/]" if pd["configured"] else "[red]NO API KEY[/]"
        model_count = str(len(pd["models"]))
        detail = ""
        if pd["configured"]:
            pconf = read_config().get("provider", {}).get(pid, {})
            opts = pconf.get("options", {})
            detail = f"timeout={opts.get('timeout','-')}ms"
        tbl.add_row(f"  [cyan]{pd['name']}[/]", status, model_count, detail)
    console.print(tbl)
    console.print("\n  [dim]Tip: Add API keys via /connect in opencode or set env vars.[/]")
    press_any()

@cli.command()
@click.option("--free", is_flag=True, help="Show only free models")
@click.option("--cheap", is_flag=True, help="Show only cheapest models per provider")
@click.option("--provider", "-p", help="Filter by provider ID (e.g. openai, anthropic)")
@click.option("--refresh", is_flag=True, help="Force refresh cache")
@click.option("--tools", is_flag=True, help="Only models with tool-call support")
@click.option("--reasoning", is_flag=True, help="Only models with reasoning capability")
@click.option("--context", type=int, metavar="MIN_CTX", help="Minimum context window (e.g. 128000 for 128k)")
@click.option("--compress", "do_compress", is_flag=True, help="Show estimated savings from compression")
def compare(free: bool, cheap: bool, provider: str, refresh: bool, tools: bool, reasoning: bool, context: int | None, do_compress: bool):
    """Compare models & pricing across all providers"""
    console.clear(); banner()
    if refresh and CACHE_PATH.exists(): CACHE_PATH.unlink()
    with console.status("[yellow]Fetching model data from models.dev...[/]"):
        catalog, new_models = get_user_models()
    if not catalog:
        console.print("\n  [red]Could not fetch model data. Check your internet connection.[/]"); return
    show_new_models(new_models)
    configured = get_configured_providers()
    filtered = {}
    unconfigured_free = {}
    for key, pd in catalog.items():
        if provider and provider.lower() not in pd["id"].lower(): continue
        models = pd["models"]
        if tools: models = [m for m in models if m["tool_call"]]
        if reasoning: models = [m for m in models if m["reasoning"]]
        if context: models = [m for m in models if m["context"] >= context]
        if free:
            free_models = [m for m in models if m["is_free"]]
            if not free_models: continue
            if pd["configured"]:
                filtered[key] = {**pd, "models": free_models}
            else:
                unconfigured_free[key] = {**pd, "models": free_models}
        else:
            if cheap:
                paid = [m for m in models if not m["is_free"]]
                free_m = [m for m in models if m["is_free"]]
                models = free_m + paid[:3]
            if models: filtered[key] = {**pd, "models": models}
    if not filtered:
        console.print("\n  [yellow]No models match your filters.[/]"); press_any(); return
    if free:
        total = sum(len(pd["models"]) for pd in filtered.values())
        console.print(f"\n  [green]Free models from your configured providers: {total}[/]\n")
    else:
        total_free = sum(1 for pd in filtered.values() for m in pd["models"] if m["is_free"])
        total_paid = sum(1 for pd in filtered.values() for m in pd["models"] if not m["is_free"])
        console.print(f"\n  [yellow]Found {len(filtered)} providers | {total_free} free models | {total_paid} paid models[/]\n")
    for p in configured: console.print(f"  [green]> CONFIGURED:[/] {p}")
    show_models_table(filtered)

    if do_compress:
        try:
            cc = ContentCache.stats()
            sl = SavingsLedger.summary()
            console.print(f"\n  [yellow]Compression Savings (from content cache):[/]")
            tbl2 = Table(box=box.SIMPLE, show_header=False)
            tbl2.add_column("Metric"); tbl2.add_column("Value")
            tbl2.add_row("  Cached files", str(cc["cached_files"]))
            tbl2.add_row("  Total savings", f"{cc['total_savings_tokens']:,} tokens")
            tbl2.add_row("  Avg compression", f"{cc['total_savings_pct']:.1f}%")
            if sl["total_entries"] > 0:
                tbl2.add_row("  Ledger entries", str(sl["total_entries"]))
                tbl2.add_row("  Ledger total saved", f"{sl['total_saved_tokens']:,} tokens")
            console.print(tbl2)
        except: pass

    if unconfigured_free:
        console.print("\n  [yellow]Providers with free models (add API key to enable):[/]")
        sno = sorted(unconfigured_free.items(), key=lambda x: -len(x[1]["models"]))
        for key, pd in sno:
            console.print(f"    [cyan]{pd['name']}[/]  [dim]({len(pd['models'])} free models)[/]")
        console.print("  [dim]Set env vars like OPENAI_API_KEY, ANTHROPIC_API_KEY etc.[/]")
    console.print(f"\n  [dim]Tip:[/]  [yellow]python token-saver.py compare --free[/]  [dim]for free models only[/]")
    console.print(f"  [dim]      [/]  [yellow]python token-saver.py compare --compress[/] [dim]show compression savings[/]")
    press_any()

@cli.command()
def free():
    """Show only completely free models across all providers"""
    ctx = click.get_current_context()
    ctx.invoke(compare, free=True, cheap=False, provider=None, refresh=False, tools=False, reasoning=False, context=None, do_compress=False)

@cli.command(name="health")
def health():
    """Check connectivity to configured providers"""
    console.clear(); banner()
    with console.status("[yellow]Fetching catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog: return
    show_health_check(catalog)
    press_any()

@cli.command(name="recommend")
@click.argument("task", type=click.Choice(["coding", "review", "planning"], case_sensitive=False))
def recommend(task: str):
    """Recommend models for a task: coding, review, planning"""
    console.clear(); banner()
    with console.status("[yellow]Fetching catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog: return
    title_map = {"coding": "Coding", "review": "Code Review", "planning": "Architecture/Planning"}
    console.print(f"\n  [yellow]Recommended models for [bold]{title_map.get(task, task)}[/][/]\n")
    recommend_models(catalog, task)
    press_any()

@cli.command(name="heatmap")
def heatmap():
    """Show cheapest model per capability across configured providers"""
    console.clear(); banner()
    with console.status("[yellow]Fetching catalog...[/]"):
        catalog, _ = get_user_models()
    if not catalog: return
    show_heatmap(catalog)
    press_any()

# ============================================================================
# LEAN-CTX INSPIRED COMPRESSION ENGINE
# ============================================================================

def rough_token_count(text: str) -> int:
    return len(text) // 4

# Bounce tracking: detect when compressed reads get re-read in full
_BOUNCE_DATA: dict = {"reads": [], "by_ext": {}}
_BOUNCE_PATH = COMPRESS_DIR / "bounce.json"
_BOUNCE_WINDOW = 10
_BOUNCE_RATIO = 0.30

def _load_bounce():
    global _BOUNCE_DATA
    if _BOUNCE_PATH.exists():
        try: _BOUNCE_DATA = json.loads(_BOUNCE_PATH.read_text("utf-8"))
        except: _BOUNCE_DATA = {"reads": [], "by_ext": {}}

def _save_bounce():
    _BOUNCE_PATH.write_text(json.dumps(_BOUNCE_DATA, indent=2), "utf-8")

def _record_read(path: str, mode: str, compressed: bool):
    _load_bounce()
    ext = Path(path).suffix.lower()
    entry = {"path": path, "ext": ext, "mode": mode, "compressed": compressed, "ts": time.time()}
    _BOUNCE_DATA.setdefault("reads", []).append(entry)
    _BOUNCE_DATA["reads"] = _BOUNCE_DATA["reads"][-_BOUNCE_WINDOW*3:]
    _save_bounce()

def _check_bounce(path: str) -> str | None:
    _load_bounce()
    ext = Path(path).suffix.lower()
    reads = [r for r in _BOUNCE_DATA.get("reads", []) if r.get("ext") == ext]
    compressed = [r for r in reads if r.get("compressed") and r.get("path") == path]
    full = [r for r in reads if not r.get("compressed") and r.get("path") == path]
    if compressed and full:
        last_c = max(r["ts"] for r in compressed)
        last_f = max(r["ts"] for r in full)
        if last_f > last_c and (last_f - last_c) < 120:
            by_ext = _BOUNCE_DATA.setdefault("by_ext", {})
            ext_bounces = by_ext.setdefault(ext, {"compressed": 0, "full": 0, "upgraded": False})
            ext_bounces["full"] += 1
            if ext_bounces["full"] / max(ext_bounces["compressed"], 1) > _BOUNCE_RATIO and not ext_bounces["upgraded"]:
                ext_bounces["upgraded"] = True
                _save_bounce()
                return "full"
    by_ext = _BOUNCE_DATA.setdefault("by_ext", {})
    ext_bounces = by_ext.setdefault(ext, {"compressed": 0, "full": 0, "upgraded": False})
    ext_bounces["compressed"] += 1
    _save_bounce()
    return None

class ContentStore:
    @staticmethod
    def put(data: str) -> str:
        h = hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]
        (CONTENT_STORE / h).write_text(data, encoding="utf-8")
        return h

    @staticmethod
    def get(hash_id: str) -> str | None:
        p = CONTENT_STORE / hash_id
        if p.exists():
            return p.read_text(encoding="utf-8")
        for f in CONTENT_STORE.iterdir():
            if f.name.startswith(hash_id):
                return f.read_text(encoding="utf-8")
        return None

    @staticmethod
    def stats() -> dict:
        files = list(CONTENT_STORE.iterdir())
        total_bytes = sum(f.stat().st_size for f in files if f.is_file())
        return {"entries": len(files), "total_bytes": total_bytes}

# ---- Kompact-inspired transform pipeline (public API) ----
_LOG_LEVELS = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b", re.IGNORECASE)
_TIMESTAMP_PREFIX = re.compile(r"^\[?\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]?\s*")
_UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_TS_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_UNIX_TS = re.compile(r"\b1[6-9]\d{8}\b")

def json_crush(text: str) -> str:
    """Statistical JSON array compression: extract constants/fields, flatten rows."""
    try:
        d = json.loads(text)
        if isinstance(d, list) and len(d) >= 2 and all(isinstance(x, dict) for x in d):
            fields = list(dict.fromkeys(k for x in d for k in x))
            consts = {}
            for f in list(fields):
                vals = [json.dumps(x.get(f), separators=(",",":")) for x in d]
                if len(set(vals)) == 1: consts[f] = d[0].get(f); fields.remove(f)
            if consts or len(fields) < len(list(dict.fromkeys(k for x in d for k in x))):
                lines = []
                if consts: lines.append("[CONSTANTS: " + ", ".join(f"{k}={v}" for k,v in consts.items()) + "]")
                if fields: lines.append("[FIELDS: " + ", ".join(fields) + "]")
                for x in d: lines.append(" | ".join(str(x.get(f,"")) for f in fields))
                return "\n".join(lines)
        minified = json.dumps(d, separators=(",",":"))
        if "\n" in text and len(minified) < len(text) * 0.85: return minified
    except: pass
    return text

def compress_log(lines_text: str) -> str:
    """Deduplicate repetitive log lines (first + count + last)."""
    lines = lines_text.split("\n")
    if len(lines) < 8: return lines_text
    log_hits = sum(1 for l in lines[:20] if _LOG_LEVELS.search(l) or _TIMESTAMP_PREFIX.match(l))
    if log_hits < 3: return lines_text
    out = []; i = 0; important = re.compile(r"\b(error|exception|traceback|failed|fatal|critical|panic)\b", re.I)
    while i < len(lines):
        l = lines[i]
        if important.search(l): out.append(l); i += 1; continue
        norm = _TIMESTAMP_PREFIX.sub("", l).strip()
        norm = re.sub(r"\d+", "N", norm)
        run_start = i
        while i + 1 < len(lines):
            n2 = _TIMESTAMP_PREFIX.sub("", lines[i+1]).strip()
            n2 = re.sub(r"\d+", "N", n2)
            if n2 == norm: i += 1
            else: break
        run_len = i - run_start + 1
        if run_len >= 5:
            out.append(lines[run_start])
            if run_len > 2: out.append(f"  [... repeated {run_len - 2} more times ...]")
            if run_len > 1: out.append(lines[i])
        else:
            for j in range(run_start, i + 1): out.append(lines[j])
        i += 1
    return "\n".join(out)

def cache_align(text: str) -> str:
    """Replace volatile UUIDs/timestamps with placeholders for KV-cache reuse."""
    dyn = {}; result = text; c = 0
    for match in _UUID_PATTERN.finditer(result):
        p = f"{{UUID_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
    for match in _TS_PATTERN.finditer(result):
        p = f"{{TS_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
    for match in _UNIX_TS.finditer(result):
        p = f"{{TS_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
    if dyn: result += "\n# Dynamic values: " + json.dumps(dyn)
    return result

class FileReadCompressor:
    READ_MODES = ["full", "map", "signatures", "density", "diff", "lines", "stats", "semantic"]

    @staticmethod
    def read(file_path: str, mode: str = "map", **kwargs) -> dict:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "mode": mode, "tokens": 0, "compressed_tokens": 0}
        raw = path.read_text(encoding="utf-8", errors="replace")
        raw_tokens = rough_token_count(raw)
        lines = raw.splitlines()
        ext = path.suffix.lower()
        result = {"file": str(path), "mode": mode, "size_bytes": len(raw), "lines": len(lines), "language": ext}

        if mode == "full":
            result["content"] = raw
            result["compressed_tokens"] = raw_tokens
            result["compression_pct"] = 0.0

        elif mode == "stats":
            byte_count = len(raw)
            lines_count = len(lines)
            non_empty = sum(1 for l in lines if l.strip())
            code_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "--")))
            result["content"] = json.dumps({
                "path": str(path), "bytes": byte_count, "lines": lines_count,
                "non_empty_lines": non_empty, "code_lines": code_lines,
                "extension": ext, "size_kb": round(byte_count / 1024, 1),
                "estimated_tokens": rough_token_count(raw),
            }, indent=2)
            result["compressed_tokens"] = rough_token_count(result["content"])

        elif mode == "map":
            extracted = FileReadCompressor._extract_map(lines, ext)
            result["content"] = "\n".join(extracted)
            result["compressed_tokens"] = rough_token_count(result["content"])

        elif mode == "signatures":
            extracted = FileReadCompressor._extract_signatures(lines, ext)
            result["content"] = "\n".join(extracted) if extracted else raw[:2000]
            result["compressed_tokens"] = rough_token_count(result["content"])

        elif mode.startswith("density"):
            ratio = 0.4
            try:
                if ":" in mode:
                    ratio = float(mode.split(":")[1])
            except: pass
            result["content"] = FileReadCompressor._density_compress(lines, ratio)
            result["compressed_tokens"] = rough_token_count(result["content"])

        elif mode.startswith("lines"):
            start, end = 1, len(lines)
            try:
                parts = mode.replace("lines:", "").split("-")
                if len(parts) == 2:
                    start = max(1, int(parts[0]))
                    end = min(len(lines), int(parts[1]))
            except: pass
            selected = lines[start-1:end]
            selected.insert(0, f"# lines {start}-{end} of {len(lines)}")
            result["content"] = "\n".join(selected)
            result["compressed_tokens"] = rough_token_count(result["content"])

        elif mode == "diff":
            ref = kwargs.get("ref", "HEAD")
            try:
                r = subprocess.run(["git", "diff", ref, "--", str(path)], capture_output=True, text=True, timeout=10)
                diff_out = r.stdout
            except:
                diff_out = "# git diff not available — showing last 10 lines\n" + "\n".join(lines[-10:])
            result["content"] = diff_out
            result["compressed_tokens"] = rough_token_count(diff_out)

        else:
            result["content"] = raw
            result["compressed_tokens"] = raw_tokens
            result["compression_pct"] = 0.0

        if raw_tokens > 0 and "compression_pct" not in result:
            result["compression_pct"] = max(0, (1 - result["compressed_tokens"] / raw_tokens) * 100)
        result["saved_tokens"] = raw_tokens - result["compressed_tokens"]
        return result

    @staticmethod
    def _extract_map(lines: list[str], ext: str) -> list[str]:
        out = []
        imports = []; classes = []; funcs = []; constants = []; types = []; exports = []
        for i, l in enumerate(lines):
            s = l.strip()
            if not s: continue
            if ext in (".py",):
                if s.startswith(("import ", "from ")): imports.append(s)
                elif s.startswith("class "): classes.append(f"  {s}  # L{i+1}")
                elif s.startswith(("def ", "async def ")): funcs.append(f"  {s}  # L{i+1}")
                elif s.startswith("@"): out.append(f"  {s}")
                elif re.match(r'^[A-Z_][A-Z0-9_]+\s*=', s): constants.append(f"  {s}")
            elif ext in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
                if s.startswith("import "): imports.append(s)
                elif s.startswith("export "): exports.append(s)
                elif s.startswith(("function ", "async function ")): funcs.append(f"  {s}  # L{i+1}")
                elif s.startswith("class "): classes.append(f"  {s}  # L{i+1}")
                elif s.startswith(("interface ", "type ")): types.append(f"  {s}  # L{i+1}")
                else: constants.append(f"  {s}")
            elif ext in (".rs", ".go", ".java", ".kt", ".scala"):
                if re.search(r'\b(pub\s+)?(fn|func|def|fun|class|struct|enum|trait|impl|interface)\b', s):
                    if "fn " in s or "func " in s: funcs.append(f"  {s}  # L{i+1}")
                    elif "class " in s or "struct " in s: classes.append(f"  {s}  # L{i+1}")
                    elif "enum " in s or "trait " in s: types.append(f"  {s}  # L{i+1}")
                elif "use " in s or "import " in s: imports.append(s)
            else:
                if re.match(r'^(\w+\s+)?(function|def|class|struct|enum|trait|interface|impl|const|let|var|import|export|use)\b', s):
                    if s.startswith(("import ", "use ")): imports.append(s[:120])
                    elif s.startswith("export "): exports.append(s[:120])
                    elif s.startswith(("function ", "def ", "fn ")): funcs.append(f"  {s[:120]}  # L{i+1}")
                    elif s.startswith(("class ", "struct ")): classes.append(f"  {s[:120]}  # L{i+1}")
                    elif s.startswith(("interface ", "type ", "enum ", "trait ")): types.append(f"  {s[:100]}  # L{i+1}")
                    else: constants.append(f"  {s[:120]}")
        if imports:
            out.append("# imports"); out.extend(imports[:30])
            if len(imports) > 30: out.append(f"  # ... {len(imports) - 30} more imports")
        if classes:
            out.append(f"\n# classes ({len(classes)})"); out.extend(classes)
        if funcs:
            out.append(f"\n# functions ({len(funcs)})"); out.extend(funcs[:50])
            if len(funcs) > 50: out.append(f"  # ... {len(funcs) - 50} more functions")
        if types: out.append(f"\n# types"); out.extend(types)
        if constants: out.append(f"\n# constants"); out.extend(constants[:20])
        if exports: out.append(f"\n# exports"); out.extend(exports[:20])
        return out if out else ["# (map mode: no significant symbols found)"] + lines[:30]

    @staticmethod
    def _extract_signatures(lines: list[str], ext: str) -> list[str]:
        out = []
        for i, l in enumerate(lines):
            s = l.strip()
            if not s: continue
            if re.match(
                r'^(def |class |struct |enum |trait |impl |fn |func |function |'
                r'async def |async fn |pub fn |pub async fn |pub |'
                r'export (default )?(function|class)|'
                r'interface |type |abstract class )', s
            ):
                out.append(f"{s}  # L{i+1}")
        return out if out else ["# (signatures mode: no definitions found)"]

    @staticmethod
    def _density_compress(lines: list[str], ratio: float = 0.4) -> str:
        if not lines: return ""
        n = len(lines)
        total = "\n".join(lines)
        codebook = {}
        tokens = re.findall(r'\b[a-zA-Z_]\w*\b', total)
        for t in tokens:
            codebook[t] = codebook.get(t, 0) + 1
        codebook_count = len(codebook)
        scored = []
        for i, l in enumerate(lines):
            s = l.strip()
            if not s:
                score = 0.0
            else:
                # 1) Shannon entropy of line
                char_counts = {}
                for c in s:
                    char_counts[c] = char_counts.get(c, 0) + 1
                h = 0.0
                for c in char_counts.values():
                    p = c / len(s)
                    if p > 0: h -= p * (p and __import__("math").log2(p))
                entropy_signal = min(h / 4.5, 1.0)
                # 2) Positional U-curve weight: first/last lines matter more
                pos = i / max(n - 1, 1)
                pos_weight = 1.0 - 0.6 * abs(pos - 0.4)
                # 3) Structural keyword boost
                struct_score = 0.0
                if re.match(r'^\s*(import |from |use |package |require|const |let |var |def |class |fn |func |function )', l): struct_score = 1.0
                elif re.match(r'^\s*(if |elif |else|for |while |try |except |with |return |yield |raise |throw |switch |case )', l): struct_score = 0.8
                elif re.match(r'^\s*[A-Z][A-Z_0-9]+\s*=', l): struct_score = 0.6
                elif re.match(r'^\s*(public|private|protected|static|final)\s', l): struct_score = 0.7
                elif re.match(r'^\s*(def |fn |func |function )', l): struct_score = 0.9
                elif s.startswith(("#", "//", "/*", "*", "--", "'''", '"""')): struct_score = 0.3
                # 4) Rare-token boost: lines with low-frequency identifiers carry high signal
                line_tokens = re.findall(r'\b[a-zA-Z_]\w*\b', s)
                rare_ratio = sum(1 for t in line_tokens if codebook.get(t, 0) <= max(2, codebook_count * 0.01)) / max(len(line_tokens), 1)
                score = entropy_signal * 0.25 + pos_weight * 0.25 + struct_score * 0.35 + rare_ratio * 0.15
            scored.append((score, i, l))
        scored.sort(key=lambda x: -x[0])
        target = max(1, int(n * ratio))
        kept_indices = set()
        for _, idx, _ in scored[:target]:
            kept_indices.add(idx)
        sorted_kept = sorted(kept_indices)
        result = []; last = -2
        for idx in sorted_kept:
            if idx > last + 1:
                if idx > last + 2: result.append(f"# ... ({idx - last - 1} lines omitted)")
                elif last >= 0: result.append(lines[idx - 1])
            result.append(lines[idx]); last = idx
        result.insert(0, f"# density compression: {ratio:.0%} of {len(lines)} lines -> {len(kept_indices)} lines kept")
        return "\n".join(result)

class ShellOutputCompressor:
    PATTERNS = {
        "git status": {"pattern": r'^git\s+status', "compress": lambda out: ShellOutputCompressor._compress_git_status(out)},
        "git diff": {"pattern": r'^git\s+diff', "compress": lambda out: ShellOutputCompressor._compress_git_diff(out)},
        "git log": {"pattern": r'^git\s+log', "compress": lambda out: ShellOutputCompressor._compress_git_log(out)},
        "git branch": {"pattern": r'^git\s+branch', "compress": lambda out: ShellOutputCompressor._compress_git_branch(out)},
        "npm test": {"pattern": r'^(npm|yarn|pnpm)\s+(test|run\s+test)', "compress": lambda out: ShellOutputCompressor._compress_npm_test(out)},
        "npm install": {"pattern": r'^(npm|yarn|pnpm)\s+(install|add|ci)', "compress": lambda out: ShellOutputCompressor._compress_npm_install(out)},
        "cargo build": {"pattern": r'^cargo\s+(build|check)', "compress": lambda out: ShellOutputCompressor._compress_cargo(out)},
        "cargo test": {"pattern": r'^cargo\s+test', "compress": lambda out: ShellOutputCompressor._compress_cargo_test(out)},
        "docker ps": {"pattern": r'^docker\s+ps', "compress": lambda out: ShellOutputCompressor._compress_docker_ps(out)},
        "docker images": {"pattern": r'^docker\s+images', "compress": lambda out: ShellOutputCompressor._compress_docker_images(out)},
        "kubectl get": {"pattern": r'^kubectl\s+get', "compress": lambda out: ShellOutputCompressor._compress_kubectl_get(out)},
        "pip list": {"pattern": r'^pip\s+(list|freeze)', "compress": lambda out: ShellOutputCompressor._compress_pip_list(out)},
        "ls": {"pattern": r'^ls\s+', "compress": lambda out: ShellOutputCompressor._compress_ls(out)},
        "ps": {"pattern": r'^ps\s+', "compress": lambda out: ShellOutputCompressor._compress_ps(out)},
        "find": {"pattern": r'^find\s+', "compress": lambda out: ShellOutputCompressor._compress_find(out)},
        "terraform plan": {"pattern": r'^terraform\s+plan', "compress": lambda out: ShellOutputCompressor._compress_terraform_plan(out)},
    }

    @staticmethod
    def compress(command: str, output: str) -> dict:
        raw_tokens = rough_token_count(output)
        compressed = output; handler = None; matched_pattern = "generic"
        for name, cfg in ShellOutputCompressor.PATTERNS.items():
            if re.search(cfg["pattern"], command.strip(), re.IGNORECASE):
                try:
                    compressed = cfg["compress"](output); handler = name; matched_pattern = name
                except Exception: compressed = ShellOutputCompressor._compress_generic(output)
                break
        else:
            compressed = ShellOutputCompressor._compress_generic(output)
        compressed_tokens = rough_token_count(compressed)
        return {
            "command": command, "handler": handler or "generic",
            "compressed_output": compressed,
            "raw_tokens": raw_tokens, "compressed_tokens": compressed_tokens,
            "saved_tokens": raw_tokens - compressed_tokens,
            "compression_pct": max(0, (1 - compressed_tokens / raw_tokens) * 100) if raw_tokens > 0 else 0,
        }

    @staticmethod
    def _compress_generic(output: str) -> str:
        lines = output.splitlines()
        if len(lines) <= 30: return output
        compressed = lines[:20]
        omitted = '\n'.join(lines[20:])
        compressed.append(f"# ... {len(lines) - 20} lines omitted ({rough_token_count(omitted)} tokens)")
        compressed.extend(lines[-10:])
        seen_patterns = set(); deduped = []
        for l in compressed:
            key = re.sub(r'\d+', 'N', l)[:60]
            if key not in seen_patterns: seen_patterns.add(key); deduped.append(l)
        return "\n".join(deduped)

    @staticmethod
    def _compress_git_status(output: str) -> str:
        lines = output.splitlines()
        branch = ""; staged = 0; modified = 0; untracked = 0; deleted = 0; renamed = 0; ahead = 0
        for l in lines:
            if l.startswith("On branch "): branch = l.replace("On branch ", "").strip()
            elif l.startswith("Your branch is ahead"):
                m = re.search(r'(\d+) commit', l)
                if m: ahead = int(m.group(1))
            elif l.startswith(("  modified:", "modified:")): modified += 1
            elif l.startswith(("  new file:", "new file:")): staged += 1
            elif l.startswith(("  deleted:", "deleted:")): deleted += 1
            elif l.startswith(("  renamed:", "renamed:")): renamed += 1
            elif l.startswith(("?? ", "\t")): untracked += 1
        parts = [f"* {branch or '(detached)'}"]
        if staged: parts.append(f"{staged} staged")
        if modified: parts.append(f"{modified} modified")
        if deleted: parts.append(f"{deleted} deleted")
        if renamed: parts.append(f"{renamed} renamed")
        if untracked: parts.append(f"{untracked} untracked")
        if ahead: parts.append(f"{ahead} ahead")
        return f"# git status (compressed)\n{' | '.join(parts)}"

    @staticmethod
    def _compress_git_diff(output: str) -> str:
        lines = output.splitlines()
        files_changed = set(); additions = 0; deletions = 0
        for l in lines:
            if l.startswith("diff --git "):
                fname = l.replace("diff --git a/", "").split(" b/")[0] if " b/" in l else l
                files_changed.add(fname.strip())
            elif l.startswith("+") and not l.startswith("+++"): additions += 1
            elif l.startswith("-") and not l.startswith("---"): deletions += 1
        out = [f"# git diff (compressed) — {len(files_changed)} files, +{additions}/-{deletions} lines"]
        for f in sorted(files_changed)[:30]: out.append(f"  {f}")
        if len(files_changed) > 30: out.append(f"  # ... and {len(files_changed) - 30} more files")
        return "\n".join(out)

    @staticmethod
    def _compress_git_log(output: str) -> str:
        lines = output.splitlines()
        out = ["# git log (compressed)"]; count = 0
        for l in lines:
            if count >= 20: break
            out.append(f"  {l[:120]}"); count += 1
        remaining = len(lines) - count
        if remaining > 0: out.append(f"# ... {remaining} more entries omitted")
        return "\n".join(out)

    @staticmethod
    def _compress_git_branch(output: str) -> str:
        lines = output.splitlines()
        current = [l for l in lines if l.startswith("*")]
        others = [l for l in lines if not l.startswith("*")]
        out = [f"# git branch (compressed) — {len(lines)} branches"]
        if current: out.append(f"  {current[0]}")
        for b in others[:20]: out.append(f"  {b.strip()}")
        if len(others) > 20: out.append(f"  # ... {len(others) - 20} more branches")
        return "\n".join(out)

    @staticmethod
    def _compress_npm_test(output: str) -> str:
        lines = output.splitlines()
        fails = [l for l in lines if "FAIL" in l or "fail" in l.lower()]
        passes = [l for l in lines if "PASS" in l or "pass" in l.lower()]
        summary = [l for l in lines if "Tests:" in l or "Suites:" in l or "passed" in l.lower()]
        errors = [l for l in lines if "Error:" in l or "error:" in l.lower() or "ERR!" in l]
        out = [f"# npm test (compressed) — {len(passes)} pass, {len(fails)} fail"]
        if errors: out.append(f"\n# errors ({len(errors)})"); out.extend(errors[:10])
        if fails: out.append(f"\n# failures ({len(fails)})"); out.extend(fails[:10])
        if summary: out.append(f"\n# summary"); out.extend(summary)
        out.append(f"\n# raw: {len(lines)} lines -> {rough_token_count(output)} tokens raw")
        return "\n".join(out) if out else output[:2000]

    @staticmethod
    def _compress_npm_install(output: str) -> str:
        lines = output.splitlines()
        added = [l for l in lines if "added" in l]; removed = [l for l in lines if "removed" in l]
        audited = [l for l in lines if "audited" in l or "audit" in l.lower()]
        vulns = [l for l in lines if "vulnerabilit" in l.lower()]
        errors = [l for l in lines if "ERR!" in l or "error" in l.lower()]
        warnings = [l for l in lines if "warning" in l.lower() or "WARN" in l]
        out = [f"# npm install (compressed) — {len(lines)} lines total"]
        if errors: out.append(f"\n# errors ({len(errors)})"); out.extend(errors[:10])
        if warnings: out.append(f"\n# warnings"); out.extend(warnings[:10])
        out.extend(added[:3] + removed[:3] + audited[:3] + vulns[:3])
        return "\n".join(out)

    @staticmethod
    def _compress_cargo(output: str) -> str:
        lines = output.splitlines()
        errors = [l for l in lines if "error" in l.lower() and ":" in l]
        warnings = [l for l in lines if "warning" in l.lower()]
        compiled = [l for l in lines if "Compiling" in l]
        finished = [l for l in lines if "Finished" in l]
        out = [f"# cargo build (compressed) — {len(compiled)} crates compiled"]
        if errors: out.append(f"\n# errors ({len(errors)})"); out.extend(errors[:15])
        if warnings: out.append(f"\n# warnings ({len(warnings)})"); out.extend(warnings[:10])
        out.extend(finished)
        out.append(f"\n# raw: {len(lines)} lines -> {rough_token_count(output)} tokens")
        return "\n".join(out)

    @staticmethod
    def _compress_cargo_test(output: str) -> str:
        lines = output.splitlines()
        running = [l for l in lines if "running" in l]
        results = [l for l in lines if "test result" in l.lower() or "FAILED" in l or "ok" in l.lower()]
        fails = [l for l in lines if "FAILED" in l or "failed" in l.lower() and ":" in l]
        doc_tests = [l for l in lines if "Doc-tests" in l]
        out = [f"# cargo test (compressed)"]
        if fails: out.append(f"\n# failures ({len(fails)})"); out.extend(fails[:15])
        out.extend(results[:5])
        if doc_tests: out.extend(doc_tests)
        if not fails: out.append(f"\n# all tests passed")
        out.append(f"\n# raw: {len(lines)} lines -> {rough_token_count(output)} tokens")
        return "\n".join(out)

    @staticmethod
    def _compress_docker_ps(output: str) -> str:
        lines = output.splitlines()
        if len(lines) <= 2: return output
        headers = lines[0]; containers = lines[1:]
        out = [f"# docker ps (compressed) — {len(containers)} containers"]
        if headers: out.append(f"  {headers[:100]}")
        for c in containers[:20]: out.append(f"  {c[:120]}")
        if len(containers) > 20: out.append(f"  # ... {len(containers) - 20} more")
        return "\n".join(out)

    @staticmethod
    def _compress_docker_images(output: str) -> str:
        lines = output.splitlines()
        images = lines[1:] if len(lines) > 1 else []
        out = [f"# docker images (compressed) — {len(images)} images"]
        for img in images[:15]: out.append(f"  {img[:120]}")
        if len(images) > 15: out.append(f"  # ... {len(images) - 15} more")
        return "\n".join(out)

    @staticmethod
    def _compress_kubectl_get(output: str) -> str:
        lines = output.splitlines()
        if len(lines) <= 5: return output
        out = [f"# kubectl get (compressed) — {len(lines) - 1} resources"]
        if lines: out.append(f"  {lines[0][:100]}")
        statuses = {}
        for l in lines[1:]:
            if not l.strip(): continue
            parts = l.split()
            status = parts[-1] if len(parts) > 1 else "unknown"
            statuses[status] = statuses.get(status, 0) + 1
        status_summary = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
        out.append(f"  Status: {status_summary}")
        for l in lines[1:6]: out.append(f"  {l[:120]}")
        return "\n".join(out)

    @staticmethod
    def _compress_pip_list(output: str) -> str:
        lines = output.splitlines()
        pkg_lines = [l for l in lines if l.strip() and ("-" in l or (l[0].isalpha() and len(l) > 10))]
        out = [f"# pip list (compressed) — {len(pkg_lines)} packages"]
        if pkg_lines:
            out.append(f"  {pkg_lines[0][:80]}")
            out.append(f"  # ... {len(pkg_lines) - 1} packages omitted")
            out.append(f"  {pkg_lines[-1][:80]}")
        return "\n".join(out)

    @staticmethod
    def _compress_ls(output: str) -> str:
        lines = output.splitlines()
        if len(lines) <= 20: return output
        dirs = [l for l in lines if l.startswith("d")]
        files = [l for l in lines if not l.startswith("d") and len(l) > 10]
        out = [f"# ls (compressed) — {len(dirs)} dirs, {len(files)} files"]
        out.extend(lines[:5]); out.append(f"# ... ({len(lines) - 10} entries omitted)"); out.extend(lines[-5:])
        return "\n".join(out)

    @staticmethod
    def _compress_ps(output: str) -> str:
        lines = output.splitlines()
        if len(lines) <= 5: return output
        header = lines[0] if lines else ""
        out = [f"# ps (compressed) — {len(lines) - 1} processes"]
        if header: out.append(f"  {header[:100]}")
        out.append(f"  # {len(lines) - 1} total, showing top 10")
        for p in lines[1:11]: out.append(f"  {p[:120]}")
        return "\n".join(out)

    @staticmethod
    def _compress_find(output: str) -> str:
        lines = [l for l in output.splitlines() if l.strip()]
        if len(lines) <= 20: return output
        depth_counts = {}
        for l in lines:
            depth = l.count("/")
            depth_counts[depth] = depth_counts.get(depth, 0) + 1
        out = [f"# find (compressed) — {len(lines)} files found"]
        for d in sorted(depth_counts.keys()): out.append(f"  depth {d}: {depth_counts[d]} files")
        out.append(f"\n# sample paths:")
        for l in lines[:10]: out.append(f"  {l}")
        out.append(f"  # ... ({len(lines) - 10} more)")
        return "\n".join(out)

    @staticmethod
    def _compress_terraform_plan(output: str) -> str:
        lines = output.splitlines()
        additions = sum(1 for l in lines if l.strip().startswith("+"))
        changes = sum(1 for l in lines if l.strip().startswith("~"))
        destructions = sum(1 for l in lines if l.strip().startswith("-"))
        summary = [l for l in lines if "Plan:" in l or "to add" in l or "to change" in l or "to destroy" in l]
        resources = [l for l in lines if "#" in l and ":" in l and ("resource" in l or "data" in l or "module" in l)]
        out = [f"# terraform plan (compressed) — +{additions}/~{changes}/-{destructions}"]
        if summary: out.extend(summary)
        out.append(f"\n# resources ({len(resources)}):")
        for r in resources[:20]: out.append(f"  {r.strip()}")
        if len(resources) > 20: out.append(f"  # ... {len(resources) - 20} more")
        out.append(f"\n# raw: {len(lines)} lines -> {rough_token_count(output)} tokens")
        return "\n".join(out)

class SemanticCompressor:
    @staticmethod
    def compress(file_path: str, max_summary_tokens: int = 800) -> dict:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "mode": "semantic", "tokens": 0}
        raw = path.read_text(encoding="utf-8", errors="replace")
        raw_tokens = rough_token_count(raw)
        cfg = read_config() or {}
        model_id = cfg.get("small_model", "") or cfg.get("model", "")
        if not model_id:
            fb = FileReadCompressor.read(file_path, mode="map")
            fb["note"] = "No model configured for summarization, used map mode"
            fb["mode"] = "semantic"
            return fb
        content_for_summary = raw
        if raw_tokens > 1500:
            mapped = FileReadCompressor.read(file_path, mode="map")
            content_for_summary = mapped.get("content", raw[:6000])
        summary = SemanticCompressor._call_llm(content_for_summary[:8000], model_id, max_summary_tokens)
        if summary:
            result = {
                "file": str(path), "mode": "semantic", "size_bytes": len(raw),
                "lines": len(raw.splitlines()), "language": path.suffix.lower(),
                "content": summary, "compressed_tokens": rough_token_count(summary),
                "summary_of": path.name, "model_used": model_id,
            }
            result["compression_pct"] = max(0, (1 - result["compressed_tokens"] / raw_tokens) * 100) if raw_tokens > 0 else 0
            result["saved_tokens"] = raw_tokens - result["compressed_tokens"]
            return result
        fb = FileReadCompressor.read(file_path, mode="map")
        fb["note"] = "Summarization failed, used map mode"
        fb["mode"] = "semantic"
        return fb

    @staticmethod
    def _call_llm(content: str, model_id: str, max_tokens: int) -> str | None:
        if "/" not in model_id:
            return None
        provider_id, model_name = model_id.split("/", 1)
        env_vars = KNOWN_PROVIDER_ENV_VARS.get(provider_id, [])
        api_key = next((os.environ.get(v, "") for v in env_vars if os.environ.get(v, "")), None)
        if not api_key:
            cfg = read_config() or {}
            pconf = cfg.get("provider", {}).get(provider_id, {})
            if isinstance(pconf, dict):
                api_key = pconf.get("apiKey", "") or pconf.get("api_key", "") or ""
        if not api_key:
            return None
        base_url = PROVIDER_DEFAULT_BASE_URLS.get(provider_id, "")
        if not base_url:
            cfg = read_config() or {}
            pconf = cfg.get("provider", {}).get(provider_id, {})
            if isinstance(pconf, dict):
                opts = pconf.get("options", {}) or {}
                base_url = opts.get("baseURL", "")
        if not base_url:
            return None
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "Summarize the following code or file content concisely. Preserve function signatures, class names, imports, key logic, and important details. Output only the summary."},
                    {"role": "user", "content": content},
                ],
                "max_tokens": max_tokens, "temperature": 0.3,
            }
            url = f"{base_url.rstrip('/')}/chat/completions"
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None

class ContentCache:
    CACHE_TTL = 3600

    @staticmethod
    def _cache_key(path: str) -> str:
        abs_path = str(Path(path).resolve())
        return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def get(path: str) -> dict | None:
        key = ContentCache._cache_key(path)
        cp = CONTENT_CACHE / f"{key}.json"
        if not cp.exists(): return None
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            if time.time() - data.get("cached_at", 0) > ContentCache.CACHE_TTL:
                cp.unlink(); return None
            return data
        except: cp.unlink(missing_ok=True); return None

    @staticmethod
    def put(path: str, result: dict):
        key = ContentCache._cache_key(path)
        data = {**result, "cached_at": time.time(), "cache_key": key, "path": str(Path(path).resolve())}
        (CONTENT_CACHE / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def clear() -> int:
        count = 0
        for f in CONTENT_CACHE.glob("*.json"): f.unlink(); count += 1
        return count

    @staticmethod
    def stats() -> dict:
        files = list(CONTENT_CACHE.glob("*.json")); now = time.time()
        total_savings = 0; total_original = 0; valid = 0
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if now - data.get("cached_at", 0) > ContentCache.CACHE_TTL: continue
                valid += 1; total_savings += data.get("saved_tokens", 0)
                total_original += data.get("compressed_tokens", 0) + data.get("saved_tokens", 0)
            except: pass
        return {
            "cached_files": valid, "total_savings_tokens": total_savings,
            "total_original_tokens": total_original,
            "total_savings_pct": (total_savings / total_original * 100) if total_original > 0 else 0,
        }

    @staticmethod
    def cached_read(file_path: str, mode: str = "map", **kwargs) -> dict:
        _load_bounce()
        cached = ContentCache.get(file_path)
        if cached and cached.get("mode") == mode:
            cached["from_cache"] = True
            original_tokens = cached.get("saved_tokens", 0) + cached.get("compressed_tokens", 0)
            cached["compressed_tokens"] = 13
            cached["saved_tokens"] = max(0, original_tokens - 13)
            cached["compression_pct"] = (1 - 13 / original_tokens) * 100 if original_tokens > 0 else 0.0
            _record_read(file_path, mode, compressed=True)
            return cached
        upgrade = _check_bounce(file_path)
        if upgrade and mode != "full":
            effective_mode = upgrade
        else:
            effective_mode = mode
        result = FileReadCompressor.read(file_path, mode=effective_mode, **kwargs)
        if "error" not in result:
            compressing = effective_mode != "full"
            if compressing:
                store_hash = ContentStore.put(result.get("content", ""))
                result["ccr_hash"] = store_hash
                result["ccr_recover"] = f"Use `store get {store_hash}` to recover original compressed content"
            ContentCache.put(file_path, result)
            result["from_cache"] = False
            if effective_mode != mode:
                result["mode"] = mode
                result["upgraded_to"] = effective_mode
                result["note"] = f"Bounce detected: automatically upgraded to '{effective_mode}' mode"
            _record_read(file_path, effective_mode, compressed=compressing)
        return result

class SavingsLedger:
    @staticmethod
    def _load() -> list:
        if LEDGER_PATH.exists():
            try: return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            except: pass
        return []

    @staticmethod
    def _save(entries: list):
        LEDGER_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    @staticmethod
    def log_entry(kind: str, description: str, raw_tokens: int, compressed_tokens: int, metadata: dict = None):
        entries = SavingsLedger._load()
        saved = max(0, raw_tokens - compressed_tokens)
        if saved == 0: return
        entry = {
            "timestamp": datetime.now().isoformat(), "kind": kind,
            "description": description, "raw_tokens": raw_tokens,
            "compressed_tokens": compressed_tokens, "saved_tokens": saved,
            "compression_pct": round((1 - compressed_tokens / raw_tokens) * 100, 1) if raw_tokens > 0 else 0,
            "metadata": metadata or {},
        }
        prev_hash = entries[-1]["hash"] if entries else "0" * 64
        entry["prev_hash"] = prev_hash
        entry_data = json.dumps(entry, sort_keys=True)
        entry["hash"] = hashlib.sha256(entry_data.encode("utf-8")).hexdigest()
        entries.append(entry)
        SavingsLedger._save(entries)
        return entry

    @staticmethod
    def verify() -> dict:
        entries = SavingsLedger._load()
        if not entries: return {"valid": True, "entries": 0, "errors": []}
        errors = []
        for i, entry in enumerate(entries):
            expected_prev = entries[i - 1]["hash"] if i > 0 else "0" * 64
            if entry.get("prev_hash", "") != expected_prev:
                errors.append(f"Entry {i}: hash chain broken")
            entry_copy = {k: v for k, v in entry.items() if k != "hash"}
            expected_hash = hashlib.sha256(json.dumps(entry_copy, sort_keys=True).encode("utf-8")).hexdigest()
            if entry.get("hash", "") != expected_hash:
                errors.append(f"Entry {i}: hash mismatch — data tampered")
        total_saved = sum(e.get("saved_tokens", 0) for e in entries)
        total_raw = sum(e.get("raw_tokens", 0) for e in entries)
        return {
            "valid": len(errors) == 0, "entries": len(entries),
            "total_saved_tokens": total_saved, "total_raw_tokens": total_raw,
            "compression_pct": round(total_saved / total_raw * 100, 1) if total_raw > 0 else 0, "errors": errors,
        }

    @staticmethod
    def summary() -> dict:
        entries = SavingsLedger._load()
        by_kind = {}; total_saved = 0; total_raw = 0
        for e in entries:
            kind = e.get("kind", "unknown")
            by_kind.setdefault(kind, {"count": 0, "saved_tokens": 0, "raw_tokens": 0})
            by_kind[kind]["count"] += 1
            by_kind[kind]["saved_tokens"] += e.get("saved_tokens", 0)
            by_kind[kind]["raw_tokens"] += e.get("raw_tokens", 0)
            total_saved += e.get("saved_tokens", 0); total_raw += e.get("raw_tokens", 0)
        return {
            "total_entries": len(entries), "total_saved_tokens": total_saved,
            "total_raw_tokens": total_raw,
            "compression_pct": round(total_saved / total_raw * 100, 1) if total_raw > 0 else 0,
            "by_kind": by_kind,
        }

class FallbackChain:
    @staticmethod
    def _load() -> dict:
        if FALLBACK_PATH.exists():
            try: return json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
            except: pass
        return {}

    @staticmethod
    def _save(data: dict):
        FALLBACK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def set_chain(model_id: str, fallbacks: list[str]):
        chains = FallbackChain._load()
        chains[model_id] = fallbacks
        FallbackChain._save(chains)

    @staticmethod
    def get_chain(model_id: str) -> list[str]:
        return FallbackChain._load().get(model_id, [])

    @staticmethod
    def remove_chain(model_id: str) -> bool:
        chains = FallbackChain._load()
        if model_id in chains:
            del chains[model_id]
            FallbackChain._save(chains)
            return True
        return False

    @staticmethod
    def list_chains() -> dict:
        return FallbackChain._load()

    @staticmethod
    def resolve(model_id: str) -> list[str]:
        seen = set()
        chain = []
        for mid in [model_id] + FallbackChain.get_chain(model_id):
            if mid not in seen:
                seen.add(mid)
                chain.append(mid)
        return chain

class TokenBudget:
    @staticmethod
    def plan(task_description: str, budget_limit: int = 8000) -> dict:
        allocation = {
            "file_reads": int(budget_limit * 0.35), "shell_commands": int(budget_limit * 0.15),
            "reasoning": int(budget_limit * 0.30), "output": int(budget_limit * 0.20),
        }
        return {
            "task": task_description[:100], "task_tokens": rough_token_count(task_description),
            "budget_limit": budget_limit, "allocation": allocation,
            "total_allocated": sum(allocation.values()),
            "remaining": budget_limit - sum(allocation.values()),
        }

    @staticmethod
    def save_plan(plan: dict): BUDGET_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    @staticmethod
    def load_plan() -> dict | None:
        if BUDGET_PATH.exists():
            try: return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
            except: pass
        return None

    @staticmethod
    def track(used_tokens: int, kind: str = "generic") -> dict:
        plan = TokenBudget.load_plan()
        if not plan: return {"error": "No active budget plan."}
        allocation = plan.get("allocation", {})
        allocated = allocation.get(kind, 0)
        return {
            "kind": kind, "used_tokens": used_tokens, "allocated": allocated,
            "allocated_used_pct": round(used_tokens / allocated * 100, 1) if allocated > 0 else 0,
            "budget_limit": plan["budget_limit"],
            "budget_used_pct": round(used_tokens / plan["budget_limit"] * 100, 1) if plan["budget_limit"] > 0 else 0,
            "remaining": plan["budget_limit"] - used_tokens,
            "over_budget": used_tokens > plan["budget_limit"],
        }

class CompressionProxy:
    PROXY_PORT = 8199

    @staticmethod
    def config() -> dict:
        if PROXY_CONFIG.exists():
            try: return json.loads(PROXY_CONFIG.read_text(encoding="utf-8"))
            except: pass
        return {"port": CompressionProxy.PROXY_PORT, "enabled": False, "pid": None}

    @staticmethod
    def save_config(cfg: dict): PROXY_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    @staticmethod
    def compress_messages(messages: list, model: str = "default") -> dict:
        raw_text = json.dumps(messages); raw_tokens = rough_token_count(raw_text)
        compressed = []
        for msg in messages:
            role = msg.get("role", "unknown"); content = msg.get("content", "")
            if isinstance(content, str):
                compressed.append({"role": role, "content": content[:200] + f"\n# ... (truncated {len(content) - 200} chars)" if len(content) > 500 else content})
            elif isinstance(content, list):
                parts = [{"type": b.get("type"), "text": b.get("text", "")[:200]} if b.get("type") == "text" and len(b.get("text", "")) > 500 else b for b in content]
                compressed.append({"role": role, "content": parts})
            else: compressed.append({"role": role, "content": content})
        compressed_text = json.dumps(compressed); compressed_tokens = rough_token_count(compressed_text)
        return {
            "model": model, "raw_tokens": raw_tokens, "compressed_tokens": compressed_tokens,
            "saved_tokens": raw_tokens - compressed_tokens,
            "compression_pct": max(0, (1 - compressed_tokens / raw_tokens) * 100) if raw_tokens > 0 else 0,
        }

    @staticmethod
    def _apply_opencode_config(port: int):
        oc_cfg = read_config()
        if not oc_cfg:
            console.print("  [yellow]No OpenCode config found — proxy running standalone.[/]")
            return
        proxy_url = f"http://127.0.0.1:{port}/v1"
        proxy_meta = CompressionProxy.config()
        proxy_meta.setdefault("saved_base_urls", {})
        for pid, pconf in oc_cfg.get("provider", {}).items():
            if isinstance(pconf, dict):
                opts = pconf.get("options", {}) or {}
                orig = opts.get("baseURL", "")
                # Skip if already pointing at this proxy (don't save proxy URL as real upstream)
                if orig and f"127.0.0.1:{port}" in orig:
                    continue
                # Even if already pointing at the proxy, refresh the cached
                # upstream URL so it stays correct across restarts.
                real_url = PROVIDER_DEFAULT_BASE_URLS.get(pid, "")
                if real_url and f"127.0.0.1:{port}" not in real_url:
                    proxy_meta["saved_base_urls"][pid] = real_url
                elif orig and f"127.0.0.1:{port}" not in orig:
                    proxy_meta["saved_base_urls"][pid] = orig
                if "options" not in pconf or pconf["options"] is None:
                    pconf["options"] = {}
                pconf["options"]["baseURL"] = proxy_url
        compressed_pids = [pid for pid in oc_cfg.get("provider", {}) if isinstance(oc_cfg["provider"][pid], dict) and oc_cfg["provider"][pid].get("options", {}).get("baseURL") == proxy_url]
        if compressed_pids:
            text = json.dumps(oc_cfg, indent=2)
            CONFIG_PATH.write_text(text + '\n', encoding="utf-8")
            proxy_meta["saved_base_urls"] = {pid: proxy_meta["saved_base_urls"].get(pid, "") for pid in compressed_pids}
            CompressionProxy.save_config(proxy_meta)
            console.print(f"  [green]  -> Auto-configured {len(compressed_pids)} provider(s) to use proxy: {', '.join(compressed_pids)}[/]")
            console.print("  [green]  -> Restart OpenCode for changes to take effect.[/]")
        else:
            # If no providers in config, try to infer from model field
            model_id = oc_cfg.get("model", "") or ""
            inferred_pid = model_id.split("/")[0] if "/" in model_id else ""
            if inferred_pid and inferred_pid in PROVIDER_DEFAULT_BASE_URLS:
                if inferred_pid not in oc_cfg.setdefault("provider", {}):
                    oc_cfg["provider"][inferred_pid] = {}
                pconf = oc_cfg["provider"][inferred_pid]
                if not isinstance(pconf, dict):
                    oc_cfg["provider"][inferred_pid] = {}
                    pconf = oc_cfg["provider"][inferred_pid]
                real_url = pconf.get("options", {}).get("baseURL", "") or PROVIDER_DEFAULT_BASE_URLS.get(inferred_pid, "")
                if real_url and f"127.0.0.1:{port}" not in real_url:
                    proxy_meta["saved_base_urls"][inferred_pid] = real_url
                pconf.setdefault("options", {})
                pconf["options"]["baseURL"] = proxy_url
                text = json.dumps(oc_cfg, indent=2)
                CONFIG_PATH.write_text(text + "\n", encoding="utf-8")
                CompressionProxy.save_config(proxy_meta)
                console.print(f"  [green]  -> Auto-configured provider from model: [bold]{inferred_pid}[/]")
                console.print("  [green]  -> Restart OpenCode for changes to take effect.[/]")
            else:
                CompressionProxy.save_config(proxy_meta)
                console.print("  [yellow]  -> No providers to auto-configure. Add `options.baseURL` manually.[/]")

    @staticmethod
    def _configure_env_providers(port: int, proxy_meta: dict, auto_provider: str | None = None):
        env_providers = []
        configured = get_configured_providers()
        oc_cfg = read_config() or {}
        existing = set(oc_cfg.get("provider", {}).keys())
        for pid in sorted(configured):
            if pid not in existing and pid in PROVIDER_DEFAULT_BASE_URLS:
                env_providers.append(pid)
        if not env_providers:
            console.print("  [yellow]  -> No env-based providers found for proxying.[/]")
            return
        current_model = (oc_cfg.get("model") or "").split("/")[0]
        # Auto-select if provider given
        if auto_provider and auto_provider in env_providers:
            selected = auto_provider
            real_url = PROVIDER_DEFAULT_BASE_URLS.get(selected, "")
            if not real_url:
                console.print(f"  [red]No default upstream URL for {selected}.[/]")
                return
            proxy_url = f"http://127.0.0.1:{port}/v1"
            if selected not in oc_cfg.setdefault("provider", {}):
                oc_cfg["provider"][selected] = {}
            pconf = oc_cfg["provider"][selected]
            if not isinstance(pconf, dict):
                oc_cfg["provider"][selected] = {}
                pconf = oc_cfg["provider"][selected]
            proxy_meta.setdefault("added_providers", []).append(selected)
            pconf.setdefault("options", {})
            pconf["options"]["baseURL"] = proxy_url
            proxy_meta.setdefault("saved_base_urls", {})[selected] = real_url
            text = json.dumps(oc_cfg, indent=2)
            CONFIG_PATH.write_text(text + "\n", encoding="utf-8")
            CompressionProxy.save_config(proxy_meta)
            console.print(f"  [green]  -> Proxying provider: [bold]{selected}[/]  [dim]({real_url} via proxy)[/]")
            console.print("  [green]  -> Restart OpenCode for changes to take effect.[/]")
            return
        # No auto_provider given — adaptive proxy handles all providers at runtime
        if not auto_provider:
            console.print("  [green]  -> Adaptive proxy ready — will auto-detect providers from model names.[/]")
            return
        for i, pid in enumerate(env_providers):
            if pid == current_model:
                default_idx = i
                break
        console.print(f"\n  [yellow]Your current model is from: [bold]{current_model or '(unknown)'}[/][/]")
        console.print("\n  [yellow]Providers detected from environment (not in config):[/]")
        for i, pid in enumerate(env_providers, 1):
            tag = " [green](current model)[/]" if i - 1 == default_idx else ""
            ref = PROVIDER_DEFAULT_BASE_URLS.get(pid, "")
            console.print(f"    {i}. [cyan]{pid}{tag}[/]  [dim]({ref})[/]")
        console.print("\n  [yellow]Note:[/] The proxy can only route through [bold]one[/] provider at a time.")
        console.print("  [dim]Enter the number of the provider to proxy: [/]", end="")
        import msvcrt
        raw = b""
        while True:
            k = msvcrt.getch()
            if k in (b"\r", b"\n") and raw:
                break
            if k == b"0":
                raw = b"0"
                break
            if k.isdigit():
                raw += k
                print(k.decode(), end="", flush=True)
        print()
        if raw == b"0" or not raw:
            console.print("  [dim]Skipped.[/]")
            return
        idx = int(raw.decode()) - 1
        if idx < 0 or idx >= len(env_providers):
            console.print("  [red]Invalid selection.[/]")
            return
        selected = env_providers[idx]
        real_url = PROVIDER_DEFAULT_BASE_URLS.get(selected, "")
        if not real_url:
            console.print(f"  [red]No default upstream URL for {selected}.[/]")
            return
        proxy_url = f"http://127.0.0.1:{port}/v1"
        if selected not in oc_cfg.setdefault("provider", {}):
            oc_cfg["provider"][selected] = {}
        pconf = oc_cfg["provider"][selected]
        if not isinstance(pconf, dict):
            oc_cfg["provider"][selected] = {}
            pconf = oc_cfg["provider"][selected]
        proxy_meta.setdefault("added_providers", []).append(selected)
        pconf.setdefault("options", {})
        pconf["options"]["baseURL"] = proxy_url
        proxy_meta.setdefault("saved_base_urls", {})[selected] = real_url
        text = json.dumps(oc_cfg, indent=2)
        CONFIG_PATH.write_text(text + "\n", encoding="utf-8")
        CompressionProxy.save_config(proxy_meta)
        console.print(f"  [green]  -> Proxying provider: [bold]{selected}[/]  [dim]({real_url})[/]")
        console.print("  [green]  -> Restart OpenCode for changes to take effect.[/]")

    @staticmethod
    def _restore_opencode_config():
        oc_cfg = read_config()
        if not oc_cfg:
            return
        proxy_meta = CompressionProxy.config()
        saved_urls = proxy_meta.get("saved_base_urls", {})
        added_providers = proxy_meta.get("added_providers", [])
        changed = False
        for pid, orig_url in saved_urls.items():
            if pid in oc_cfg.get("provider", {}):
                pconf = oc_cfg["provider"][pid]
                if isinstance(pconf, dict):
                    if "options" not in pconf or pconf["options"] is None:
                        pconf["options"] = {}
                    if orig_url:
                        pconf["options"]["baseURL"] = orig_url
                    else:
                        pconf["options"].pop("baseURL", None)
                    changed = True
        for pid in added_providers:
            if pid in oc_cfg.get("provider", {}):
                del oc_cfg["provider"][pid]
                changed = True
        if changed:
            text = json.dumps(oc_cfg, indent=2)
            CONFIG_PATH.write_text(text + '\n', encoding="utf-8")
            console.print("  [green]  -> Restored original provider URLs in OpenCode config.[/]")
            console.print("  [green]  -> Restart OpenCode for changes to take effect.[/]")
        proxy_meta["saved_base_urls"] = {}
        proxy_meta["added_providers"] = []
        CompressionProxy.save_config(proxy_meta)

    @staticmethod
    def start_server(port: int = None, provider: str | None = None, configure_opencode: bool = True) -> bool:
        cfg = CompressionProxy.config()
        if cfg.get("enabled") and cfg.get("pid"):
            console.print("  [yellow]Proxy is already running.[/]"); return False
        try:
            port = port or cfg.get("port", CompressionProxy.PROXY_PORT)
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", port)); s.close()
            # Write model pricing data so the proxy can be cost-aware
            try:
                cat, _ = get_user_models()
                pricing = {}
                for k, pd in cat.items():
                    for m in pd["models"]:
                        pricing[m["id"]] = {"input": m["input_price"], "output": m["output_price"]}
                COST_PRICING_PATH.write_text(json.dumps(pricing, indent=2), encoding="utf-8")
            except: pass
            script = r'''import json, sys, http.server, hashlib, re, urllib.request, urllib.error, os, pathlib, time
try:
    import requests as _req
except Exception:
    _req = None
# Shared session for connection pooling + Cloudflare bypass + retry
_session = None
def _get_session():
    global _session
    if _session is None:
        # Prefer plain requests (with retry) — cloudscraper sometimes triggers
        # Cloudflare TLS fingerprinting that leads to ConnectionResetError.
        if _req is not None:
            _session = _req.Session()
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            _retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504], allowed_methods=["POST","GET"])
            _adapter = HTTPAdapter(max_retries=_retry, pool_connections=4, pool_maxsize=4)
            _session.mount("http://", _adapter)
            _session.mount("https://", _adapter)
            _session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            })
        else:
            try:
                import cloudscraper
                _session = cloudscraper.create_scraper(browser='chrome', enable_stealth=True, auto_refresh_on_403=True)
            except Exception:
                pass
    return _session
UPSTREAM_MAP = {}
PROVIDER_DEFAULT_BASE_URLS = ''' + repr(PROVIDER_DEFAULT_BASE_URLS) + r'''
_PRICES = {}
_pf = r"''' + str(COST_PRICING_PATH).replace("\\", "\\\\") + r'''"
if os.path.exists(_pf):
    try: _PRICES = json.load(open(_pf))
    except: pass
def _cost_level(mid):
    if not mid: return "cheap"
    p = _PRICES.get(mid) or _PRICES.get(mid.split("/")[-1], {})
    if not p and "/" in mid:
        p = _PRICES.get(mid.split("/", 1)[1], {})
    total = p.get("input", 0) + p.get("output", 0)
    if total == 0: return "free"
    if total < 2: return "cheap"
    if total < 20: return "moderate"
    return "expensive"
class PH(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        raw_tokens = len(body) // 4
        nb = body
        model_id = ""
        _orig_model = ""
        try:
            data = json.loads(body)
            msgs = data.get("messages", [])
            model_id = data.get("model", "")
            _orig_model = model_id  # Keep original for per-request upstream resolution
            # Strip provider/ prefix for upstream APIs that use bare model
            # names. OpenCode Zen expects "mimo-v2.5-free", not
            # "opencode/mimo-v2.5-free" — keeping the prefix makes Console
            # return "Upstream request failed" / ModelError.
            if "/" in model_id:
                prefix = model_id.split("/")[0]
                if prefix in PROVIDER_DEFAULT_BASE_URLS or prefix in ("opencode", "opencode-go"):
                    data["model"] = model_id[len(prefix)+1:]
                    model_id = data["model"]
            # Skip compression for very large conversations (>50 msgs or >100KB)
            # to avoid corrupting tool calls and complex content structures.
            _skip_compress = len(msgs) > 50 or len(body) > 100000
            comp = []
            # 1) JSON Crusher: statistical JSON array compression
            # 2) Log Compressor: deduplicate repetitive log lines
            # 3) Cache Aligner: relocate volatile fields out of cacheable prefix
            # 4) Fallback truncation for oversized plain text
            cl = _cost_level(model_id)
            sys_limit = {"free":1200,"cheap":2000,"moderate":600,"expensive":250}
            def _json_crush(text):
                try:
                    d = json.loads(text)
                    if isinstance(d, list) and len(d) >= 2 and all(isinstance(x, dict) for x in d):
                        fields = list(dict.fromkeys(k for x in d for k in x))
                        consts = {}
                        for f in list(fields):
                            vals = [json.dumps(x.get(f), separators=(",",":")) for x in d]
                            if len(set(vals)) == 1: consts[f] = d[0].get(f); fields.remove(f)
                        if consts or len(fields) < len(list(dict.fromkeys(k for x in d for k in x))):
                            lines = []
                            if consts: lines.append("[CONSTANTS: " + ", ".join(f"{k}={v}" for k,v in consts.items()) + "]")
                            if fields: lines.append("[FIELDS: " + ", ".join(fields) + "]")
                            for x in d: lines.append(" | ".join(str(x.get(f,"")) for f in fields))
                            return "\n".join(lines)
                    minified = json.dumps(d, separators=(",",":"))
                    if "\n" in text and len(minified) < len(text) * 0.85: return minified
                except: pass
                return text
            _LL = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b", re.IGNORECASE)
            _TP = re.compile(r"^\[?\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]?\s*")
            def _compress_log(text):
                lines = text.split("\n")
                if len(lines) < 8: return text
                log_hits = sum(1 for l in lines[:20] if _LL.search(l) or _TP.match(l))
                if log_hits < 3: return text
                out = []; i = 0; important = re.compile(r"\b(error|exception|traceback|failed|fatal|critical|panic)\b", re.I)
                while i < len(lines):
                    l = lines[i]
                    if important.search(l): out.append(l); i += 1; continue
                    norm = _TP.sub("", l).strip()
                    norm = re.sub(r"\d+", "N", norm)
                    run_start = i
                    while i + 1 < len(lines):
                        n2 = _TP.sub("", lines[i+1]).strip()
                        n2 = re.sub(r"\d+", "N", n2)
                        if n2 == norm: i += 1
                        else: break
                    run_len = i - run_start + 1
                    if run_len >= 5:
                        out.append(lines[run_start])
                        if run_len > 2: out.append(f"  [... repeated {run_len - 2} more times ...]")
                        if run_len > 1: out.append(lines[i])
                    else:
                        for j in range(run_start, i + 1): out.append(lines[j])
                    i += 1
                return "\n".join(out)
            _UP = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
            _TSP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
            _UX = re.compile(r"\b1[6-9]\d{8}\b")
            def _cache_align(text):
                dyn = {}; result = text; c = 0
                for match in _UP.finditer(result):
                    p = f"{{UUID_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
                for match in _TSP.finditer(result):
                    p = f"{{TS_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
                for match in _UX.finditer(result):
                    p = f"{{TS_{c}}}"; dyn[p] = match.group(); result = result.replace(match.group(), p, 1); c += 1
                if dyn: result += "\n# Dynamic values: " + json.dumps(dyn)
                return result
            def _clean_msg(m):
                return {k:v for k,v in m.items() if not (v is None or v == [] or (isinstance(v, str) and v == ""))}
            # Apply pipeline to each message content
            comp = []
            tool_result_count = 0
            for m in msgs:
                if _skip_compress:
                    comp.append(m)
                    continue
                role = m.get("role","")
                c = m.get("content","")
                if isinstance(c, str):
                    is_tool = role in ("user", "tool") or (tool_result_count > 0 and role == "user")
                    s = c
                    if len(s) > 200: s = _json_crush(s)
                    if len(s) > 200: s = _compress_log(s)
                    if role == "system" and len(s) > 200: s = _cache_align(s)
                    msg_limits = {"free":1500,"cheap":3000,"moderate":800,"expensive":400}
                    msg_cap = msg_limits.get(cl, 3000)
                    if role == "system": msg_cap = max(msg_cap, sys_limit.get(cl, 4000))
                    if len(s) > msg_cap:
                        lines = s.splitlines()
                        cap50 = int(msg_cap * 0.6)
                        lines_keep = max(5, cap50 // 40)
                        if len(lines) > lines_keep * 2:
                            s = "\n".join(lines[:lines_keep] + [f"# ... {len(lines)-lines_keep*2} lines omitted"] + lines[-lines_keep:])
                        else: s = s[:msg_cap] + f"\n# ... truncated ({len(s)-msg_cap} chars)"
                    if is_tool: tool_result_count += 1
                    comp.append(_clean_msg({"role":role,"content":s}))
                elif isinstance(c, list):
                    parts = []
                    for b in c:
                        if isinstance(b,dict) and b.get("type")=="text":
                            t = b.get("text","")
                            if len(t) > 200: t = _json_crush(t)
                            if len(t) > 200: t = _compress_log(t)
                            mult_limits = {"free":800,"cheap":1500,"moderate":600,"expensive":300}
                            cap2 = mult_limits.get(cl, 2000)
                            if len(t) > cap2: t = t[:int(cap2*0.6)] + f"\n... truncated ({len(t)-int(cap2*0.6)} chars)"
                            parts.append({"type":"text","text":t})
                        else: parts.append(b)
                    comp.append(_clean_msg({"role":role,"content":parts}))
                else: comp.append(_clean_msg(m))
            if not _skip_compress:
                data["messages"] = comp
            nb = json.dumps(data, separators=(",",":"))
            if len(nb) > len(body):
                nb = body
        except: pass
        saved = max(0, raw_tokens - len(nb)//4)
        # Resolve upstream URL (support query strings and bare paths)
        path_only = self.path.split("?", 1)[0]
        upstream = UPSTREAM_MAP.get(path_only) or UPSTREAM_MAP.get(self.path)
        if not upstream:
            # Common OpenAI-compatible path shapes
            if path_only.endswith("/chat/completions"):
                base = UPSTREAM_MAP.get("__base__") or ""
                if base:
                    upstream = base.rstrip("/") + "/chat/completions"
            elif path_only.endswith("/messages"):
                base = UPSTREAM_MAP.get("__base__") or ""
                if base:
                    upstream = base.rstrip("/") + "/messages"
            elif path_only.endswith("/models") or path_only == "/v1/models" or path_only == "/models":
                base = UPSTREAM_MAP.get("__base__") or ""
                if base:
                    upstream = base.rstrip("/") + "/models"
        # Per-request upstream override — adapt to the provider the model belongs to
        try:
            _mp = _orig_model.split("/")[0] if _orig_model and "/" in _orig_model else ""
            if _mp and _mp in _CONFIGURED_PROVIDERS and _mp in _PROVIDER_UPSTREAM:
                _mu = _PROVIDER_UPSTREAM[_mp]
                if _mu and f"127.0.0.1:{_PROXY_PORT}" not in _mu:
                    if path_only.endswith("/chat/completions"):
                        upstream = _mu + "/chat/completions"
                    elif path_only.endswith("/messages"):
                        upstream = _mu + "/messages"
                    elif path_only.endswith("/models"):
                        upstream = _mu + "/models"
        except: pass
        if not upstream or not str(upstream).startswith("http"):
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": {
                    "message": "Proxy has no upstream URL configured for path " + path_only,
                    "type": "proxy_error",
                    "code": "no_upstream",
                }
            }).encode())
            return
        # Forward auth + common provider headers. Skip hop-by-hop headers.
        _skip = {
            "host", "content-length", "connection", "transfer-encoding",
            "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailers", "upgrade", "accept-encoding",
        }
        _prefer = {
            "content-type", "authorization", "x-api-key", "user-agent",
            "accept", "anthropic-version", "anthropic-beta", "openai-organization",
            "openai-project", "x-title", "http-referer",
        }
        hdrs = {}
        for k in self.headers.keys():
            lk = k.lower()
            if lk in _skip:
                continue
            if lk in _prefer or lk.startswith("x-"):
                v = self.headers.get(k)
                if v:
                    hdrs[k] = v
        hdrs.setdefault("Content-Type", "application/json")
        hdrs.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        hdrs.setdefault("Accept", "text/event-stream, application/json")
        _logf = r"''' + str(COMPRESS_DIR / "proxy_debug.log").replace("\\", "\\\\") + r'''"
        def _plog(msg):
            try:
                with open(_logf, "a", encoding="utf-8") as lf:
                    lf.write(msg + "\\n")
            except Exception:
                pass
        _plog("REQ path=%s model_orig=%s model_fwd=%s raw_sz=%d comp_sz=%d msgs=%d" % (self.path, _orig_model, model_id, len(body), len(nb), len(data.get("messages",[])) if isinstance(data, dict) else 0))
        try:
            _sess = _get_session()
            if _sess is not None:
                resp = _sess.post(upstream, data=nb.encode("utf-8"), headers=hdrs, stream=True, timeout=300)
            else:
                _req_up = urllib.request.Request(upstream, data=nb.encode("utf-8"), headers=hdrs, method="POST")
                resp = urllib.request.urlopen(_req_up, timeout=300)
            _up_status = resp.status_code if hasattr(resp, "status_code") else resp.status
            # If 400 and we applied compression, retry with original body
            if _up_status == 400 and nb != body:
                try:
                    resp.close()
                except Exception:
                    pass
                _plog("RETRY_NO_COMPRESS path=%s upstream=%s" % (path_only, upstream))
                if _sess is not None:
                    resp = _sess.post(upstream, data=body.encode("utf-8"), headers=hdrs, stream=True, timeout=300)
                else:
                    _req_up2 = urllib.request.Request(upstream, data=body.encode("utf-8"), headers=hdrs, method="POST")
                    resp = urllib.request.urlopen(_req_up2, timeout=300)
                _up_status = resp.status_code if hasattr(resp, "status_code") else resp.status
            ct = resp.headers.get("Content-Type", "application/json") if resp.headers else "application/json"
            self.send_response(_up_status)
            self.send_header("Content-Type", ct)
            if "text/event-stream" in (ct or ""):
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            _is_err = _up_status >= 400
            _err_body = b""
            try:
                if hasattr(resp, "iter_content"):
                    for chunk in resp.iter_content(chunk_size=4096):
                        if not chunk:
                            continue
                        if _is_err:
                            _err_body += chunk
                        self.wfile.write(chunk)
                        try:
                            self.wfile.flush()
                        except Exception:
                            pass
                else:
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        if _is_err:
                            _err_body += chunk
                        self.wfile.write(chunk)
                        try:
                            self.wfile.flush()
                        except Exception:
                            pass
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if _is_err:
                _plog("HTTP %s path=%s upstream=%s req_model=%s resp=%s" % (_up_status, path_only, upstream, _orig_model, _err_body[:1000].decode("utf-8","replace")))
        except urllib.error.HTTPError as e:
            body_err = e.read()
            try:
                self.send_response(e.code)
                ct = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
                self.send_header("Content-Type", ct)
                self.end_headers()
                self.wfile.write(body_err)
            except Exception:
                pass
            try:
                _plog("HTTPError %s path=%s upstream=%s body=%s" % (e.code, path_only, upstream, body_err[:500].decode("utf-8", "replace")))
            except Exception:
                pass
        except Exception as e:
            try:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err = {"error": {"message": "Proxy upstream failed: %s" % e, "type": "proxy_error", "code": "upstream_failed", "upstream": upstream}}
                self.wfile.write(json.dumps(err).encode())
            except Exception:
                pass
            try:
                _plog("Exception path=%s upstream=%s err=%s" % (path_only, upstream, e))
            except Exception:
                pass
        # Log savings
        cf = r"''' + str(PROXY_CONFIG).replace("\\", "\\\\") + r'''"
        try:
            with open(cf) as f: cg = json.load(f)
        except: cg = {}
        cg.setdefault("history",[]).append({"path":path_only,"model":_orig_model or model_id or "unknown","saved_tokens":saved,"timestamp":__import__("time").time()})
        cg["history"] = cg["history"][-200:]
        cg["total_saved_tokens"] = cg.get("total_saved_tokens",0) + saved
        try:
            with open(cf,"w") as f: json.dump(cg,f,indent=2)
        except: pass
    def do_GET(self):
        path_only = self.path.split("?", 1)[0]
        # Proxy /v1/models so clients can discover real upstream models
        if path_only.endswith("/models"):
            base = UPSTREAM_MAP.get("__base__") or ""
            if base:
                try:
                    url = base.rstrip("/") + "/models"
                    req = urllib.request.Request(url, method="GET")
                    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                    req.add_header("Accept", "application/json")
                    if self.headers.get("Authorization"):
                        req.add_header("Authorization", self.headers.get("Authorization"))
                    if self.headers.get("x-api-key"):
                        req.add_header("x-api-key", self.headers.get("x-api-key"))
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        body = resp.read()
                        self.send_response(resp.status)
                        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                except urllib.error.HTTPError as e:
                    body = e.read()
                    try:
                        self.send_response(e.code)
                        self.send_header("Content-Type", e.headers.get("Content-Type", "application/json") if e.headers else "application/json")
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass
                    return
                except Exception as e:
                    try:
                        self.send_response(502)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode())
                    except Exception:
                        pass
                    return
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status":"running","upstream":UPSTREAM_MAP.get("__base__","")}).encode())
    def log_message(self,f,*a): pass
def setup_upstream(port, cfg):
    upstream = ""
    import os, pathlib
    cfg_provider = (cfg or {}).get("provider", "")
    cfg_upstream = (cfg or {}).get("upstream", "")
    if cfg_upstream:
        upstream = cfg_upstream.rstrip("/")
    elif cfg_provider:
        upstream = PROVIDER_DEFAULT_BASE_URLS.get(cfg_provider, "").rstrip("/")
    # Prefer the real upstream recorded by the proxy (saved_base_urls), so we
    # never forward to the proxy's own URL. Fall back to the OpenCode config,
    # then to provider defaults.
    proxy_meta_path = pathlib.Path.home() / ".config" / "opencode" / "compress" / "proxy.json"
    saved = {}
    if proxy_meta_path.exists():
        try:
            saved = json.load(open(proxy_meta_path)).get("saved_base_urls", {})
        except: saved = {}
    # OpenCode may use opencode.jsonc or opencode.json
    p = pathlib.Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not p.exists():
        p = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
    providers = {}
    if p.exists():
        t = p.read_text("utf-8")
        try:
            import re
            t2 = re.sub(r'^\s*//.*', '', t, flags=re.MULTILINE)
            t2 = re.sub(r'/\*[\s\S]*?\*/', '', t2)
            providers = json.loads(t2).get("provider", {})
        except: pass
    def _is_proxy_url(url):
        if not url: return True
        return f"127.0.0.1:{port}" in url or f"localhost:{port}" in url
    # Prefer saved_base_urls over current config (config may already point at proxy)
    if not upstream:
        for pid, real in (saved or {}).items():
            if real and not _is_proxy_url(real):
                upstream = real.rstrip("/")
                break
    if not upstream:
        for pid, pc in providers.items():
            if isinstance(pc, dict):
                bu = saved.get(pid) or (pc.get("options", {}) or {}).get("baseURL", "")
                if _is_proxy_url(bu):
                    bu = PROVIDER_DEFAULT_BASE_URLS.get(pid, "")
                if bu and not _is_proxy_url(bu):
                    upstream = bu.rstrip("/")
                    break
        # Fallback: extract provider from the model name when provider dict is empty
        if not upstream and p.exists():
            try:
                import re
                t = p.read_text("utf-8")
                t2 = re.sub(r'^\s*//.*', '', t, flags=re.MULTILINE)
                t2 = re.sub(r'/\*[\s\S]*?\*/', '', t2)
                cfgj = json.loads(t2)
                model_id = cfgj.get("model", "") or ""
                if "/" in model_id:
                    pid = model_id.split("/")[0]
                    if pid in PROVIDER_DEFAULT_BASE_URLS:
                        upstream = PROVIDER_DEFAULT_BASE_URLS[pid].rstrip("/")
            except: pass
    if not upstream and cfg_provider:
        upstream = PROVIDER_DEFAULT_BASE_URLS.get(cfg_provider, "").rstrip("/")
    if upstream:
        UPSTREAM_MAP["__base__"] = upstream
        UPSTREAM_MAP["/v1/chat/completions"] = upstream + "/chat/completions"
        UPSTREAM_MAP["/chat/completions"] = upstream + "/chat/completions"
        UPSTREAM_MAP["/v1/messages"] = upstream + "/messages"
        UPSTREAM_MAP["/messages"] = upstream + "/messages"
        UPSTREAM_MAP["/v1/models"] = upstream + "/models"
        UPSTREAM_MAP["/models"] = upstream + "/models"
setup_upstream(''' + str(port) + r''', ''' + repr({"provider": provider or "", "upstream": ""}) + r''')
# Per-request upstream resolution for multi-provider support
_PROXY_PORT = ''' + str(port) + r'''
_PROVIDER_UPSTREAM = {}
_CONFIGURED_PROVIDERS = set()
# 1) From saved_base_urls (original upstreams recorded before proxy rewrites)
try:
    _pmu_path = pathlib.Path.home() / ".config" / "opencode" / "compress" / "proxy.json"
    if _pmu_path.exists():
        _saved = json.load(open(_pmu_path)).get("saved_base_urls", {})
        for _pid, _url in _saved.items():
            if _url and f"127.0.0.1:{_PROXY_PORT}" not in _url:
                _PROVIDER_UPSTREAM[_pid] = _url.rstrip("/")
except: pass
# 2) From OpenCode config (custom upstreams + detect which providers are configured)
try:
    _cfg_path = pathlib.Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not _cfg_path.exists():
        _cfg_path = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
    if _cfg_path.exists():
        _cfg_t = re.sub(r'^\s*//.*', '', _cfg_path.read_text("utf-8"), flags=re.MULTILINE)
        _cfg_t = re.sub(r'/\*[\s\S]*?\*/', '', _cfg_t)
        _cfg = json.loads(_cfg_t)
        for _pid, _pc in (_cfg.get("provider", {}) or {}).items():
            if isinstance(_pc, dict):
                _opts = _pc.get("options", {}) or {}
                _bu = _opts.get("baseURL", "")
                if _bu and f"127.0.0.1:{_PROXY_PORT}" not in _bu and _pid not in _PROVIDER_UPSTREAM:
                    _PROVIDER_UPSTREAM[_pid] = _bu.rstrip("/")
                # Provider is "configured" if it has an entry in the config
                _CONFIGURED_PROVIDERS.add(_pid)
except: pass
# 3) Detect configured providers from environment variables
try:
    _known_env = {'openai':['OPENAI_API_KEY','OPENAI_ORG_ID','OPENAI_BASE_URL'],'anthropic':['ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'],'google':['GOOGLE_API_KEY','GEMINI_API_KEY','GOOGLE_GENAI_API_KEY'],'deepseek':['DEEPSEEK_API_KEY'],'mistral':['MISTRAL_API_KEY'],'cohere':['COHERE_API_KEY'],'groq':['GROQ_API_KEY'],'together':['TOGETHER_API_KEY'],'openrouter':['OPENROUTER_API_KEY'],'fireworks':['FIREWORKS_API_KEY'],'perplexity':['PERPLEXITY_API_KEY'],'xai':['XAI_API_KEY'],'huggingface':['HUGGINGFACE_API_KEY','HUGGINGFACE_TOKEN','HF_API_KEY'],'siliconflow':['SILICONFLOW_API_KEY'],'deepinfra':['DEEPINFRA_API_KEY'],'nvidia':['NVIDIA_API_KEY','NVIDIA_NIM_API_KEY'],'cerebras':['CEREBRAS_API_KEY'],'venice':['VENICE_API_KEY'],'zenmux':['ZENMUX_API_KEY'],'zai':['ZAI_API_KEY'],'iflowcn':['IFLOWCN_API_KEY'],'anyapi':['ANYAPI_API_KEY'],'opencode':['OPENCODE_ZEN_API_KEY','OPENCODE_API_KEY']}
    import os as _os
    for _pid, _vars in _known_env.items():
        for _v in _vars:
            if _os.environ.get(_v, "").strip():
                _CONFIGURED_PROVIDERS.add(_pid)
                break
    # Also scan any env var ending in _API_KEY, _AUTH_TOKEN, _API_TOKEN, _TOKEN
    for _k, _v in _os.environ.items():
        if _v.strip():
            for _suf in ("_API_KEY", "_AUTH_TOKEN", "_API_TOKEN", "_TOKEN"):
                if _k.upper().endswith(_suf):
                    _pid = _k.upper().replace(_suf, "").lower()
                    if _pid not in ("api", "secret", "key", "auth", "token", "bearer", ""):
                        _CONFIGURED_PROVIDERS.add(_pid)
                    break
except: pass
# 4) From PROVIDER_DEFAULT_BASE_URLS (fallback defaults for all known providers)
for _pid, _url in PROVIDER_DEFAULT_BASE_URLS.items():
    if _pid not in _PROVIDER_UPSTREAM:
        _PROVIDER_UPSTREAM[_pid] = _url.rstrip("/")
# 5) If no default upstream was resolved, pick the first configured provider
if not UPSTREAM_MAP.get("__base__", ""):
    for _pid in sorted(_CONFIGURED_PROVIDERS):
        _mu = _PROVIDER_UPSTREAM.get(_pid)
        if _mu and f"127.0.0.1:{_PROXY_PORT}" not in _mu:
            UPSTREAM_MAP["__base__"] = _mu
            UPSTREAM_MAP["/v1/chat/completions"] = _mu + "/chat/completions"
            UPSTREAM_MAP["/chat/completions"] = _mu + "/chat/completions"
            UPSTREAM_MAP["/v1/messages"] = _mu + "/messages"
            UPSTREAM_MAP["/messages"] = _mu + "/messages"
            UPSTREAM_MAP["/v1/models"] = _mu + "/models"
            UPSTREAM_MAP["/models"] = _mu + "/models"
            break
# Validate upstream is reachable before accepting traffic
_base = UPSTREAM_MAP.get("__base__", "")
if _base:
    _vlog = r"''' + str(COMPRESS_DIR / "proxy_debug.log").replace("\\", "\\\\") + r'''"
    try:
        _chk_url = _base.rstrip("/") + "/models"
        _req_u = urllib.request.Request(_chk_url, method="GET")
        _req_u.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        _req_u.add_header("Accept", "application/json")
        with urllib.request.urlopen(_req_u, timeout=10) as _resp:
            _ok = _resp.status < 500
        if not _ok:
            try:
                with open(_vlog, "a", encoding="utf-8") as _lf:
                    _lf.write("WARNING: upstream %s returned error on startup check\\n" % _base)
            except: pass
    except Exception as _ve:
        try:
            with open(_vlog, "a", encoding="utf-8") as _lf:
                _lf.write("WARNING: startup upstream check failed for %s: %s\\n" % (_base, _ve))
        except: pass
# Threading server so streaming chat + status checks do not block each other
try:
    Server = http.server.ThreadingHTTPServer
except AttributeError:
    Server = http.server.HTTPServer
Server(("127.0.0.1",''' + str(port) + r'''),PH).serve_forever()
'''
            script_path = COMPRESS_DIR / "_proxy_server.py"
            script_path.write_text(script, encoding="utf-8")
            proxy_meta = CompressionProxy.config()
            if configure_opencode:
                CompressionProxy._apply_opencode_config(port)
                proxy_meta = CompressionProxy.config()
                if not proxy_meta.get("saved_base_urls"):
                    CompressionProxy._configure_env_providers(port, proxy_meta, provider)
            # Detach on Windows so the proxy survives after this CLI exits.
            # CREATE_NO_WINDOW alone keeps the child in the parent job; when the
            # CLI process ends, Windows can tear the proxy down immediately.
            err_log = COMPRESS_DIR / "proxy_stderr.log"
            err_fh = open(err_log, "ab")
            creationflags = 0
            if sys.platform == "win32":
                creationflags = (
                    getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                )
            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            try:
                err_fh.close()
            except Exception:
                pass
            # Brief settle + liveness check
            import time
            time.sleep(0.4)
            alive = True
            try:
                if proc.poll() is not None:
                    alive = False
            except Exception:
                pass
            if not alive:
                console.print("  [red][ERR] Proxy process exited immediately. See proxy_stderr.log[/]")
                return False
            proxy_meta = CompressionProxy.config()
            proxy_meta["port"] = port
            proxy_meta["enabled"] = True
            proxy_meta["pid"] = proc.pid
            CompressionProxy.save_config(proxy_meta)
            console.print(f"  [green][OK] Compression proxy started on 127.0.0.1:{port}[/]")
            return True
        except Exception as e:
            console.print(f"  [red][ERR] Failed to start proxy: {e}[/]"); return False

    @staticmethod
    def stop_server() -> bool:
        cfg = CompressionProxy.config()
        if cfg.get("pid"):
            try: subprocess.run(["taskkill", "/PID", str(cfg["pid"]), "/F"], capture_output=True)
            except: pass
        CompressionProxy._restore_opencode_config()
        cfg = CompressionProxy.config()
        cfg["enabled"] = False; cfg["pid"] = None
        CompressionProxy.save_config(cfg)
        console.print("  [green][OK] Compression proxy stopped.[/]"); return True

    @staticmethod
    def status() -> dict:
        cfg = CompressionProxy.config()
        running = False
        if cfg.get("enabled") and cfg.get("pid"):
            try: running = requests.get(f"http://127.0.0.1:{cfg.get('port',8199)}", timeout=2).ok
            except: running = False
        history = cfg.get("history", [])
        models = {}
        for h in history:
            m = h.get("model", "unknown")
            if m:
                models.setdefault(m, {"tokens": 0, "requests": 0})
                models[m]["tokens"] += h.get("saved_tokens", 0)
                models[m]["requests"] += 1
        return {
            "enabled": cfg.get("enabled", False), "running": running,
            "port": cfg.get("port", CompressionProxy.PROXY_PORT), "pid": cfg.get("pid"),
            "total_saved_tokens": cfg.get("total_saved_tokens", 0),
            "requests_served": len(history),
            "models": models,
        }

class DashboardServer:
    PORT = 8200

    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Token Saver Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,monospace}
body{background:#1a1a2e;color:#e0e0e0;padding:20px}
.header{text-align:center;padding:20px;border-bottom:1px solid #333;margin-bottom:24px}
.header h1{color:#00d4ff;font-size:24px;margin-bottom:8px}
.header .sub{color:#888;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;max-width:1200px;margin:0 auto}
.card{background:#16213e;border-radius:12px;padding:20px;border:1px solid #0f3460}
.card h2{color:#00d4ff;font-size:14px;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;border-bottom:1px solid #0f3460;padding-bottom:8px}
.card .row{display:flex;justify-content:space-between;padding:6px 0;font-size:13px}
.card .label{color:#888}
.card .value{color:#e0e0e0;font-weight:500}
.card .value.green{color:#00e676}
.card .value.yellow{color:#ffd740}
.card .value.red{color:#ff5252}
.card .value.cyan{color:#00d4ff}
.footer{text-align:center;padding:20px;color:#555;font-size:12px;margin-top:24px}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.green{background:#00e676}
.status-dot.red{background:#ff5252}
.status-dot.yellow{background:#ffd740}
</style>
</head>
<body>
<div class="header">
<h1>&#9632; Token Saver Dashboard</h1>
<div class="sub" id="sub">Model: <span id="model">-</span> &middot; Small: <span id="small">-</span> &middot; <span id="ts">loading...</span></div>
</div>
<div class="grid">
<div class="card"><h2>&#128230; Cache</h2><div id="cache"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128176; Savings</h2><div id="savings"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128274; Proxy</h2><div id="proxy"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128200; Budget</h2><div id="budget"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128451; Store</h2><div id="store"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128279; Fallback Chains</h2><div id="fallback"><div class="row"><span class="label">Loading...</span></div></div></div>
</div>
<div class="footer" id="footer">Auto-refresh every 5s</div>
<script>
async function load(){try{
const r=await fetch('/api/stats');const d=await r.json();
document.getElementById('model').textContent=d.model.model||'-';
document.getElementById('small').textContent=d.model.small_model||'-';
document.getElementById('ts').textContent=new Date(d.timestamp).toLocaleTimeString();
const c=d.cache||{};document.getElementById('cache').innerHTML=
`<div class="row"><span class="label">Cached Files</span><span class="value">${c.cached_files||0}</span></div>
<div class="row"><span class="label">Total Saved</span><span class="value green">${(c.total_savings_tokens||0).toLocaleString()} tokens</span></div>
<div class="row"><span class="label">Avg Compression</span><span class="value yellow">${(c.total_savings_pct||0).toFixed(1)}%</span></div>`;
const s=d.savings||{};document.getElementById('savings').innerHTML=
`<div class="row"><span class="label">Entries</span><span class="value">${s.total_entries||0}</span></div>
<div class="row"><span class="label">Total Saved</span><span class="value green">${(s.total_saved_tokens||0).toLocaleString()} tokens</span></div>
<div class="row"><span class="label">Compression</span><span class="value yellow">${s.compression_pct||0}%</span></div>`;
const p=d.proxy||{};const pStat=p.running?'green':'red';const pTxt=p.running?'Running':'Stopped';
document.getElementById('proxy').innerHTML=
`<div class="row"><span class="label">Status</span><span class="value"><span class="status-dot ${pStat}"></span>${pTxt}</span></div>
<div class="row"><span class="label">Port</span><span class="value">${p.port||'-'}</span></div>
<div class="row"><span class="label">Requests</span><span class="value">${p.requests_served||0}</span></div>
<div class="row"><span class="label">Tokens Saved</span><span class="value green">${(p.total_saved_tokens||0).toLocaleString()}</span></div>`;
const b=d.budget||{};document.getElementById('budget').innerHTML=
`<div class="row"><span class="label">Plan Active</span><span class="value">${b.has_plan?'Yes':'No'}</span></div>
<div class="row"><span class="label">Budget Limit</span><span class="value">${(b.budget_limit||0).toLocaleString()}</span></div>
<div class="row"><span class="label">Allocated</span><span class="value">${(b.total_allocated||0).toLocaleString()}</span></div>`;
const st=d.store||{};document.getElementById('store').innerHTML=
`<div class="row"><span class="label">Entries</span><span class="value">${st.entries||0}</span></div>
<div class="row"><span class="label">Total Bytes</span><span class="value">${(st.total_bytes||0).toLocaleString()}</span></div>`;
const f=d.fallback||{};document.getElementById('fallback').innerHTML=
`<div class="row"><span class="label">Chains</span><span class="value">${f.chains||0}</span></div>`;
}catch(e){document.getElementById('sub').textContent='Error loading stats'}}
load();setInterval(load,5000);
</script>
</body>
</html>"""

    @staticmethod
    def start(port: int = None) -> bool:
        cfg = DashboardServer.config()
        if cfg.get("enabled") and cfg.get("pid"):
            try:
                r = requests.get(f"http://127.0.0.1:{cfg.get('port', DashboardServer.PORT)}", timeout=2)
                if r.ok:
                    console.print("  [yellow]Dashboard is already running.[/]")
                    return False
            except: pass
        port = port or DashboardServer.PORT
        script = r'''import json, os, http.server, sys, time
from pathlib import Path
CACHE = r"''' + str(CONTENT_CACHE).replace("\\", "\\\\") + r'''"
STORE = r"''' + str(CONTENT_STORE).replace("\\", "\\\\") + r'''"
LEDGER = r"''' + str(LEDGER_PATH).replace("\\", "\\\\") + r'''"
BUDGET = r"''' + str(BUDGET_PATH).replace("\\", "\\\\") + r'''"
PROXY_CFG = r"''' + str(PROXY_CONFIG).replace("\\", "\\\\") + r'''"
FALLBACK = r"''' + str(FALLBACK_PATH).replace("\\", "\\\\") + r'''"
CONFIG = r"''' + str(CONFIG_PATH).replace("\\", "\\\\") + r'''"
DASH_CFG = r"''' + str(DASHBOARD_CONFIG).replace("\\", "\\\\") + r'''"
HTML = r"""''' + DashboardServer.DASHBOARD_HTML + r'''"""
def rough(s): return len(s)//4
class DH(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/":
            self.send_response(200); self.send_header("Content-Type","text/html"); self.send_header("Cache-Control","no-cache"); self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif self.path=="/api/stats":
            cfg={};st={};ld={};bd={};px={};fb={};mc={}
            if os.path.exists(CACHE):
                try:
                    import glob as g; now=time.time(); ts=0; tf=0; v=0
                    for f in g.glob(os.path.join(CACHE,"*.json")):
                        try:
                            d=json.load(open(f,encoding="utf-8"))
                            if now-d.get("cached_at",0)>3600: continue
                            v+=1; ts+=d.get("saved_tokens",0); tf+=d.get("compressed_tokens",0)+d.get("saved_tokens",0)
                        except: pass
                    st={"cached_files":v,"total_savings_tokens":ts,"total_savings_pct":round(ts/tf*100,1) if tf>0 else 0}
                except: pass
            if os.path.exists(LEDGER):
                try:
                    e=json.load(open(LEDGER,encoding="utf-8")); ts2=sum(x.get("saved_tokens",0) for x in e); tr=sum(x.get("raw_tokens",0) for x in e)
                    ld={"total_entries":len(e),"total_saved_tokens":ts2,"compression_pct":round(ts2/tr*100,1) if tr>0 else 0}
                except: pass
            if os.path.exists(PROXY_CFG):
                try:
                    p=json.load(open(PROXY_CFG,encoding="utf-8")); rn=False
                    try:
                        import urllib.request
                        urllib.request.urlopen("http://127.0.0.1:"+str(p.get("port",8199)),timeout=2); rn=True
                    except: pass
                    px={"enabled":p.get("enabled",False),"running":rn,"port":p.get("port",8199),"total_saved_tokens":p.get("total_saved_tokens",0),"requests_served":len(p.get("history",[]))}
                except: pass
            if os.path.exists(BUDGET):
                try:
                    b=json.load(open(BUDGET,encoding="utf-8"))
                    bd={"has_plan":bool(b),"budget_limit":b.get("budget_limit",0),"total_allocated":b.get("total_allocated",0)}
                except: pass
            if os.path.exists(FALLBACK):
                try: fb={"chains":len(json.load(open(FALLBACK,encoding="utf-8")))}
                except: pass
            if os.path.exists(CONFIG):
                try:
                    import re; t=re.sub(r'^\s*//.*','',open(CONFIG,encoding="utf-8").read(),flags=re.MULTILINE); t=re.sub(r'/\*[\s\S]*?\*/','',t)
                    mc=json.loads(t)
                except: pass
            ss={"entries":0,"total_bytes":0}
            if os.path.exists(STORE):
                try: ss["entries"]=len(os.listdir(STORE)); ss["total_bytes"]=sum(os.path.getsize(os.path.join(STORE,f)) for f in os.listdir(STORE) if os.path.isfile(os.path.join(STORE,f)))
                except: pass
            stats={"cache":st,"savings":ld,"proxy":px,"budget":bd,"store":ss,"model":{"model":mc.get("model",""),"small_model":mc.get("small_model","")},"fallback":fb,"timestamp":__import__("datetime").datetime.now().isoformat()}
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-cache"); self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))
        else: self.send_response(404); self.end_headers()
    def log_message(self,f,*a): pass
try:
    srv=http.server.HTTPServer(("127.0.0.1",''' + str(port) + r'''),DH)
    json.dump({"port":''' + str(port) + r''',"enabled":True,"pid":os.getpid()},open(DASH_CFG,"w"))
    srv.serve_forever()
except Exception as e:
    json.dump({"port":''' + str(port) + r''',"enabled":False,"error":str(e)},open(DASH_CFG,"w"))
'''
        script_path = COMPRESS_DIR / "_dashboard_server.py"
        script_path.write_text(script, encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            time.sleep(1)
            if proc.poll() is not None:
                console.print(f"  [red][ERR] Dashboard process exited immediately.[/]")
                return False
            DashboardServer.save_config({"port": port, "enabled": True, "pid": proc.pid})
            console.print(f"  [green][OK] Dashboard started at http://127.0.0.1:{port}[/]")
            return True
        except Exception as e:
            console.print(f"  [red][ERR] Failed to start dashboard: {e}[/]")
            return False

    @staticmethod
    def stop() -> bool:
        cfg = DashboardServer.config()
        if cfg.get("pid"):
            try: subprocess.run(["taskkill", "/PID", str(cfg["pid"]), "/F"], capture_output=True)
            except: pass
        DashboardServer.save_config({"port": DashboardServer.PORT, "enabled": False, "pid": None})
        console.print("  [green][OK] Dashboard stopped.[/]")
        return True

    @staticmethod
    def config() -> dict:
        if DASHBOARD_CONFIG.exists():
            try: return json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
            except: pass
        return {"port": DashboardServer.PORT, "enabled": False, "pid": None}

    @staticmethod
    def save_config(cfg: dict):
        DASHBOARD_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    @staticmethod
    def status() -> dict:
        cfg = DashboardServer.config()
        running = False
        if cfg.get("enabled") and cfg.get("pid"):
            try:
                r = requests.get(f"http://127.0.0.1:{cfg.get('port', DashboardServer.PORT)}", timeout=2)
                running = r.ok
            except: running = False
        cfg["running"] = running
        return cfg

# ============================================================================
# NEW COMPRESSION CLI COMMANDS
# ============================================================================

@cli.group()
def compress():
    """Compress file reads and shell output (lean-ctx inspired)"""
    pass

@compress.command(name="read")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--mode", "-m", default="map", help="Read mode (full/map/signatures/density/diff/lines/stats/semantic, or density:0.3, lines:10-50)")
@click.option("--no-cache", is_flag=True, help="Bypass cache")
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
@click.option("--ref", help="Git ref for diff mode")
def compress_read(file_path: str, mode: str, no_cache: bool, json_out: bool, ref: str):
    """Read and compress a file using lean-ctx style modes"""
    kwargs = {"ref": ref} if ref else {}
    result = FileReadCompressor.read(file_path, mode=mode, **kwargs) if no_cache else ContentCache.cached_read(file_path, mode=mode, **kwargs)
    if "error" in result:
        console.print(f"  [red]{result['error']}[/]"); return
    if json_out:
        console.print(json.dumps(result, indent=2, default=str)); return
    cached = result.get("from_cache", False)
    console.print(f"\n  [cyan]File:[/] {result['file']}")
    console.print(f"  [cyan]Mode:[/] {result['mode']}{' [green](cached)[/]' if cached else ''}")
    console.print(f"  [cyan]Size:[/] {result.get('size_bytes', 0):,} bytes  |  Lines: {result.get('lines', 0)}")
    console.print(f"  [cyan]Compression:[/] [green]{result.get('compression_pct', 0):.1f}%[/]  (saved {result.get('saved_tokens', 0):,} tokens)")
    if cached: console.print(f"  [cyan]Cache hit:[/] [green]re-read cost = ~13 tokens[/]")
    console.print(f"\n  [yellow]Content:[/]\n")
    content = result.get("content", "")
    console.print(content if len(content) < 5000 else content[:5000] + f"\n  [dim]... ({len(content) - 5000} more chars)[/]")
    SavingsLedger.log_entry("file_read", f"{result['mode']}:{result['file']}", result.get("size_bytes", 0) // 4, result.get("compressed_tokens", 0), {"file": result['file'], "mode": result['mode'], "cached": cached})

@compress.command(name="shell")
@click.argument("command_str", nargs=-1, required=True)
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
@click.option("--raw", is_flag=True, help="Show raw output instead of compressed")
def compress_shell(command_str: tuple[str], json_out: bool, raw: bool):
    """Compress a shell command output (git, npm, cargo, docker, etc.)"""
    cmd = " ".join(command_str)
    console.print(f"  [yellow]Running:[/] $ {cmd}\n")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        console.print("  [red][ERR] Command timed out (30s)[/]"); return
    except Exception as e:
        console.print(f"  [red][ERR] {e}[/]"); return
    if not output.strip():
        console.print("  [dim](no output)[/]"); return
    if raw: console.print(output[:5000]); return
    result = ShellOutputCompressor.compress(cmd, output)
    if json_out:
        console.print(json.dumps({k: v for k, v in result.items() if k != "raw_output"}, indent=2)); return
    console.print(f"  [cyan]Handler:[/] {result['handler']}")
    console.print(f"  [cyan]Compression:[/] [green]{result['compression_pct']:.1f}%[/]  (saved {result['saved_tokens']:,} tokens)")
    console.print(f"  [cyan]Raw tokens:[/] {result['raw_tokens']:,} -> [green]{result['compressed_tokens']:,}[/]\n")
    console.print(result["compressed_output"])
    SavingsLedger.log_entry("shell", f"{result['handler']}:{cmd[:80]}", result["raw_tokens"], result["compressed_tokens"], {"command": cmd, "handler": result['handler']})

@compress.command(name="messages")
@click.option("--model", default="default", help="Model name")
def compress_messages(model: str):
    """Test message compression for API requests"""
    sample = [
        {"role": "system", "content": "You are a helpful assistant." * 50},
        {"role": "user", "content": "Explain quantum computing in simple terms." * 30},
        {"role": "assistant", "content": "Quantum computing uses qubits." * 20},
    ]
    result = CompressionProxy.compress_messages(sample, model)
    console.print(f"\n  [cyan]Model:[/] {result['model']}")
    console.print(f"  [cyan]Compression:[/] [green]{result['compression_pct']:.1f}%[/]")
    console.print(f"  [cyan]Raw tokens:[/] {result['raw_tokens']:,}")
    console.print(f"  [cyan]Compressed tokens:[/] {result['compressed_tokens']:,}")
    console.print(f"  [cyan]Saved:[/] [green]{result['saved_tokens']:,} tokens[/]")

@compress.command(name="batch")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--mode", "-m", default="map")
@click.option("--recursive", "-r", is_flag=True, help="Recurse into subdirectories")
@click.option("--ext", "-e", help="File extensions to include (comma-separated, e.g. .py,.js)")
@click.option("--exclude", help="Glob patterns to exclude")
@click.option("--json", "json_out", is_flag=True)
def compress_batch(directory: str, mode: str, recursive: bool, ext: str, exclude: str, json_out: bool):
    """Compress all files in a directory"""
    dir_path = Path(directory)
    pattern = "**/*" if recursive else "*"
    exts = [e.strip().lower() for e in ext.split(",")] if ext else None
    exclude_patterns = [p.strip() for p in exclude.split(",")] if exclude else []
    files = []
    for f in dir_path.glob(pattern):
        if f.is_file():
            if exts and f.suffix.lower() not in exts:
                continue
            if any(f.match(p) for p in exclude_patterns):
                continue
            files.append(f)
    if not files:
        console.print("  [yellow]No matching files found.[/]")
        return
    results = []
    total_raw = 0
    total_compressed = 0
    with console.status(f"[yellow]Compressing {len(files)} files..."):
        for f in files:
            result = FileReadCompressor.read(str(f), mode=mode)
            if "error" not in result:
                results.append(result)
                total_raw += result.get("size_bytes", 0) // 4
                total_compressed += result.get("compressed_tokens", 0)
    if json_out:
        console.print(json.dumps({"files": results, "total_raw_tokens": total_raw, "total_compressed_tokens": total_compressed, "total_saved": total_raw - total_compressed}, indent=2))
        return
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("File", style="white")
    tbl.add_column("Mode", style="cyan")
    tbl.add_column("Lines", justify="right", style="dim")
    tbl.add_column("Raw Tokens", justify="right")
    tbl.add_column("Compressed", justify="right")
    tbl.add_column("Saved", justify="right", style="green")
    tbl.add_column("%", justify="right", style="yellow")
    for r in results:
        saved = r.get("saved_tokens", 0)
        pct = r.get("compression_pct", 0)
        tbl.add_row(r.get("file", "?")[:50], r.get("mode", "?"), str(r.get("lines", 0)), str(r.get("size_bytes", 0) // 4), str(r.get("compressed_tokens", 0)), str(saved), f"{pct:.1f}%")
    console.print(f"\n  [yellow]Batch Compression: {len(results)} files[/]\n")
    console.print(tbl)
    total_saved = total_raw - total_compressed
    pct = (1 - total_compressed / total_raw) * 100 if total_raw > 0 else 0
    console.print(f"\n  [cyan]Total raw tokens:[/] {total_raw:,}")
    console.print(f"  [cyan]Total compressed:[/] {total_compressed:,}")
    console.print(f"  [cyan]Total saved:[/] [green]{total_saved:,} tokens ({pct:.1f}%)[/]")
    SavingsLedger.log_entry("batch", f"batch {mode}:{directory}", total_raw, total_compressed, {"directory": directory, "mode": mode, "files": len(results)})

@compress.command(name="semantic")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--max-tokens", default=800, type=int, help="Max summary tokens")
@click.option("--json", "json_out", is_flag=True)
def compress_semantic(file_path: str, max_tokens: int, json_out: bool):
    """Compress a file using AI summarization (small model)"""
    result = SemanticCompressor.compress(file_path, max_tokens)
    if "error" in result:
        console.print(f"  [red]{result['error']}[/]")
        return
    if json_out:
        console.print(json.dumps(result, indent=2, default=str))
        return
    note = result.get("note", "")
    console.print(f"\n  [cyan]File:[/] {result['file']}")
    console.print(f"  [cyan]Mode:[/] semantic{' [dim](' + note + ')[/]' if note else ''}")
    console.print(f"  [cyan]Size:[/] {result.get('size_bytes', 0):,} bytes  |  Lines: {result.get('lines', 0)}")
    console.print(f"  [cyan]Compression:[/] [green]{result.get('compression_pct', 0):.1f}%[/]  (saved {result.get('saved_tokens', 0):,} tokens)")
    if "model_used" in result:
        console.print(f"  [cyan]Model:[/] {result['model_used']}")
    console.print(f"\n  [yellow]Summary:[/]\n")
    content = result.get("content", "")
    console.print(content[:3000] + (f"\n  [dim]... ({len(content) - 3000} more chars)[/]" if len(content) > 3000 else ""))
    SavingsLedger.log_entry("semantic", f"semantic:{result['file']}", result.get("size_bytes", 0) // 4, result.get("compressed_tokens", 0), {"file": result['file'], "model": result.get("model_used", "")})

@cli.group()
def cache():
    """Manage content cache (cached file reads)"""
    pass

@cache.command(name="stats")
def cache_stats():
    """Show cache statistics"""
    s = ContentCache.stats()
    console.print(f"\n  [cyan]Cached files:[/] {s['cached_files']}")
    if s['cached_files'] > 0:
        console.print(f"  [cyan]Original tokens:[/] {s['total_original_tokens']:,}")
        console.print(f"  [cyan]Total savings:[/] [green]{s['total_savings_tokens']:,} tokens[/]")
        console.print(f"  [cyan]Avg compression:[/] {s['total_savings_pct']:.1f}%")
    console.print(f"  [cyan]Store entries:[/] {ContentStore.stats()['entries']}")

@cache.command(name="clear")
def cache_clear():
    """Clear all cached file reads"""
    if confirm("Clear all cached file reads?"):
        console.print(f"  [green][OK] Cleared {ContentCache.clear()} cache entries.[/]")

@cache.command(name="list")
def cache_list():
    """List cached files"""
    files = list(CONTENT_CACHE.glob("*.json"))
    if not files: console.print("  [dim]No cached files.[/]"); return
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("File"); tbl.add_column("Mode"); tbl.add_column("Savings"); tbl.add_column("Cached At")
    now = time.time()
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if now - data.get("cached_at", 0) > ContentCache.CACHE_TTL: continue
            tbl.add_row(data.get("path","?")[:60], data.get("mode","?"), f"{data.get('saved_tokens',0):,}", datetime.fromtimestamp(data.get("cached_at",0)).strftime("%H:%M"))
        except: pass
    if tbl.rows: console.print(tbl)
    else: console.print("  [dim]No valid cache entries.[/]")

@cli.group()
def proxy():
    """Manage request compression proxy"""
    pass

def print_proxy_env(port: int, provider: str):
    proxy_url = f"http://127.0.0.1:{port}/v1"
    key_vars = KNOWN_PROVIDER_ENV_VARS.get(provider, [])
    api_key_var = next((v for v in key_vars if "KEY" in v or "TOKEN" in v), "OPENAI_API_KEY")
    console.print("\n  [yellow]Generic IDE/CLI proxy settings[/]\n")
    tbl = Table(box=box.SIMPLE, show_header=False)
    tbl.add_column("Setting", style="cyan")
    tbl.add_column("Value", style="white")
    tbl.add_row("  Base URL", proxy_url)
    tbl.add_row("  Provider", provider)
    tbl.add_row("  API key env", api_key_var)
    console.print(tbl)
    console.print("\n  [cyan]PowerShell[/]")
    console.print(f"  $env:OPENAI_BASE_URL='{proxy_url}'")
    console.print(f"  $env:OPENAI_API_BASE='{proxy_url}'")
    console.print(f"  $env:{api_key_var}='<your-{provider}-key>'")
    console.print("\n  [cyan]Generic config[/]")
    console.print(f"  base_url: {proxy_url}")
    console.print(f"  api_base: {proxy_url}")
    console.print("  api_key: keep using your normal provider key")
    console.print("\n  [dim]Works with clients that support OpenAI-compatible /v1/chat/completions base URLs.[/]")

@proxy.command(name="start")
@click.option("--port", "-p", default=8199, type=int, help="Port")
@click.option("--provider", help="Provider upstream for generic mode, e.g. openai, anthropic, deepseek, openrouter")
@click.option("--generic", is_flag=True, help="Do not rewrite OpenCode config; print settings for any OpenAI-compatible client")
def proxy_start(port: int, provider: str | None, generic: bool):
    """Start the compression proxy server (auto-detects provider from model names)"""
    console.clear(); banner()
    console.print(f"\n  [yellow]Starting compression proxy on port {port}...[/]")
    if generic and not provider:
        console.print("  [red]Generic mode needs --provider so the proxy knows the real upstream.[/]")
        console.print("  [dim]Example: python token-saver.py proxy start --generic --provider openai[/]")
        return
    if provider and provider not in PROVIDER_DEFAULT_BASE_URLS:
        console.print(f"  [red]Unknown provider: {provider}[/]")
        console.print("  [dim]Run `python token-saver.py providers` to see detected providers.[/]")
        return
    if CompressionProxy.start_server(port, provider=provider, configure_opencode=not generic) and generic:
        print_proxy_env(port, provider)

@proxy.command(name="env")
@click.option("--port", "-p", default=8199, type=int, help="Proxy port")
@click.option("--provider", default="openai", help="Provider whose API key/base vars to show")
def proxy_env(port: int, provider: str):
    """Print env/config hints for VS Code, Hermes, and generic OpenAI-compatible tools."""
    print_proxy_env(port, provider)

@proxy.command(name="stop")
def proxy_stop():
    """Stop the compression proxy server"""
    CompressionProxy.stop_server()

@proxy.command(name="status")
def proxy_status():
    """Show proxy status"""
    s = CompressionProxy.status()
    console.print(f"\n  [cyan]Status:[/] {'[green]Running[/]' if s['running'] else '[red]Stopped[/]'}")
    console.print(f"  [cyan]Port:[/] {s['port']}")
    console.print(f"  [cyan]Requests served:[/] {s['requests_served']}")
    if s['total_saved_tokens'] > 0: console.print(f"  [cyan]Total saved:[/] [green]{s['total_saved_tokens']:,} tokens[/]")
    if s.get("models"):
        console.print(f"\n  [cyan]Models:[/]")
        for model, stats in sorted(s["models"].items(), key=lambda x: -x[1]["tokens"]):
            console.print(f"    [bold]{model}[/]  [dim]{stats['requests']} reqs[/]  [green]{stats['tokens']:,} tokens saved[/]")

@cli.group()
def budget():
    """Token budget planning"""
    pass

@budget.command(name="plan")
@click.argument("task_description", nargs=-1, required=True)
@click.option("--limit", "-l", default=8000, type=int, help="Token budget limit")
def budget_plan(task_description: tuple[str], limit: int):
    """Plan token budget for a task"""
    desc = " ".join(task_description)
    plan = TokenBudget.plan(desc, limit)
    TokenBudget.save_plan(plan)
    console.print(f"\n  [cyan]Task:[/] {plan['task']}")
    console.print(f"  [cyan]Budget limit:[/] {plan['budget_limit']:,} tokens\n")
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("Category"); tbl.add_column("Tokens", justify="right"); tbl.add_column("%", justify="right")
    for k, v in plan["allocation"].items():
        tbl.add_row(f"  {k}", f"{v:,}", f"{round(v/plan['budget_limit']*100,1)}%")
    console.print(tbl)
    console.print(f"\n  [cyan]Remaining:[/] {plan['remaining']:,} tokens")

@budget.command(name="track")
@click.argument("used_tokens", type=int)
@click.option("--kind", "-k", default="generic", help="Category")
def budget_track(used_tokens: int, kind: str):
    """Track token usage against budget"""
    result = TokenBudget.track(used_tokens, kind)
    if "error" in result: console.print(f"  [red]{result['error']}[/]"); return
    console.print(f"\n  [cyan]Category:[/] {result['kind']}")
    console.print(f"  [cyan]Used:[/] {result['used_tokens']:,} / {result['allocated']:,} allocated")
    console.print(f"  [cyan]Category usage:[/] {result['allocated_used_pct']:.1f}%")
    console.print(f"  [cyan]Total budget:[/] {result['budget_used_pct']:.1f}% used")
    if result['over_budget']: console.print("  [red]OVER BUDGET![/]")

@cli.group()
def savings():
    """Token savings ledger (tamper-evident)"""
    pass

@savings.command(name="summary")
def savings_summary():
    """Show savings summary"""
    s = SavingsLedger.summary()
    console.print(f"\n  [cyan]Total entries:[/] {s['total_entries']}")
    if s['total_entries'] > 0:
        console.print(f"  [cyan]Total raw tokens:[/] {s['total_raw_tokens']:,}")
        console.print(f"  [cyan]Total saved tokens:[/] [green]{s['total_saved_tokens']:,}[/]")
        console.print(f"  [cyan]Overall compression:[/] {s['compression_pct']:.1f}%\n")
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        tbl.add_column("Category"); tbl.add_column("Count"); tbl.add_column("Saved"); tbl.add_column("Compression")
        for k, v in sorted(s['by_kind'].items()):
            pct = round(v['saved_tokens'] / v['raw_tokens'] * 100, 1) if v['raw_tokens'] > 0 else 0
            tbl.add_row(f"  {k}", str(v['count']), f"{v['saved_tokens']:,}", f"{pct}%")
        console.print(tbl)

@savings.command(name="verify")
def savings_verify():
    """Verify ledger integrity"""
    v = SavingsLedger.verify()
    if v['entries'] == 0: console.print("  [dim]No ledger entries to verify.[/]"); return
    console.print(f"\n  [cyan]Entries:[/] {v['entries']}")
    console.print(f"  {'[green]Hash chain valid[/]' if v['valid'] else '[red]Integrity errors![/]'}")
    if not v['valid']:
        for e in v['errors']: console.print(f"    [red]{e}[/]")
    console.print(f"  [cyan]Total saved:[/] [green]{v['total_saved_tokens']:,} tokens[/]")

@savings.command(name="ledger")
@click.option("--limit", "-l", default=20, type=int)
def savings_ledger(limit: int):
    """Show recent ledger entries"""
    entries = SavingsLedger._load()
    if not entries: console.print("  [dim]No ledger entries.[/]"); return
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("Time"); tbl.add_column("Kind"); tbl.add_column("Description"); tbl.add_column("Saved")
    for e in entries[-limit:]:
        ts = e.get("timestamp", "")[11:19] if len(e.get("timestamp","")) > 19 else e.get("timestamp","")
        tbl.add_row(ts, e.get("kind","?"), e.get("description","")[:50], f"[green]+{e.get('saved_tokens',0):,}[/]")
    console.print(tbl)

@cli.group()
def store():
    """Content-addressed store (reversible compression)"""
    pass

@store.command(name="put")
@click.argument("text", nargs=-1, required=True)
def store_put(text: tuple[str]):
    """Store content and get its content hash"""
    data = " ".join(text)
    h = ContentStore.put(data)
    console.print(f"  [green]Stored[/]  [dim](hash: {h})[/]")
    console.print(f"  [cyan]Content:[/] {data[:80]}...")
    console.print(f"  [cyan]Estimated tokens:[/] {rough_token_count(data):,}")

@store.command(name="get")
@click.argument("hash_id")
def store_get(hash_id: str):
    """Retrieve content by hash"""
    data = ContentStore.get(hash_id)
    if data is None: console.print(f"  [red]Hash not found: {hash_id}[/]"); return
    console.print(f"  [cyan]Retrieved[/] [dim](hash: {hash_id})[/]")
    console.print(f"  [cyan]Size:[/] {len(data):,} bytes  |  {rough_token_count(data):,} tokens\n")
    console.print(data[:2000])
    if len(data) > 2000: console.print(f"  [dim]... ({len(data) - 2000} more chars)[/]")

@cli.group()
def fallback():
    """Manage auto-fallback chains"""
    pass

@fallback.command(name="set")
@click.argument("model_id")
@click.argument("fallbacks", nargs=-1, required=True)
def fallback_set(model_id: str, fallbacks: tuple[str]):
    """Set fallback chain for a model"""
    flist = list(fallbacks)
    FallbackChain.set_chain(model_id, flist)
    console.print(f"  [green][OK] Fallback chain set for [cyan]{model_id}[/][/]")
    for i, f in enumerate(flist, 1):
        console.print(f"    {i}. {f}")

@fallback.command(name="remove")
@click.argument("model_id")
def fallback_remove(model_id: str):
    """Remove fallback chain for a model"""
    if FallbackChain.remove_chain(model_id):
        console.print(f"  [green][OK] Removed fallback chain for [cyan]{model_id}[/][/]")
    else:
        console.print(f"  [yellow]No fallback chain found for [cyan]{model_id}[/][/]")

@fallback.command(name="list")
def fallback_list():
    """List all fallback chains"""
    chains = FallbackChain.list_chains()
    if not chains:
        console.print("  [dim]No fallback chains configured.[/]")
        return
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("Model", style="cyan")
    tbl.add_column("Chain", style="white")
    for model_id, fallbacks in chains.items():
        chain_str = " -> ".join(fallbacks)
        tbl.add_row(model_id, chain_str)
    console.print(f"\n  [yellow]Fallback Chains ({len(chains)})[/]\n")
    console.print(tbl)

@fallback.command(name="resolve")
@click.argument("model_id")
def fallback_resolve(model_id: str):
    """Show resolved fallback chain for a model"""
    resolved = FallbackChain.resolve(model_id)
    console.print(f"  Resolved chain for [cyan]{model_id}[/]:")
    for i, mid in enumerate(resolved):
        tag = " (primary)" if i == 0 else " (fallback)" if i == 1 else f" (fallback {i})"
        console.print(f"    {i+1}. {mid}[dim]{tag}[/]")

@cli.group()
def dashboard():
    """Start/stop the web dashboard"""
    pass

@dashboard.command(name="start")
@click.option("--port", "-p", default=8200, type=int, help="Dashboard port")
def dashboard_start(port: int):
    """Start the web dashboard"""
    console.clear(); banner()
    DashboardServer.start(port)

@dashboard.command(name="stop")
def dashboard_stop():
    """Stop the web dashboard"""
    DashboardServer.stop()

@dashboard.command(name="status")
def dashboard_status():
    """Show dashboard status"""
    s = DashboardServer.status()
    console.print(f"\n  [cyan]Status:[/] {'[green]Running[/]' if s.get('running') else '[red]Stopped[/]'}")
    console.print(f"  [cyan]Port:[/] {s.get('port', 8200)}")
    if s.get('running'):
        console.print(f"  [cyan]URL:[/] http://127.0.0.1:{s.get('port', 8200)}")

# ============================================================================
# NEW COMMANDS: search, sql, stats, mcp, skill, upgrade (ctxrs/ctx inspired)
# ============================================================================

@cli.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--kind", "-k", help="Filter by event kind: file_read, shell, proxy, cache_hit")
@click.option("--file", "file_query", help="Search touched files instead of events")
@click.option("--since", "-s", help="Time filter: 30d, 7d, 24h, 60m")
@click.option("--limit", "-l", default=10, type=int, help="Max results")
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
def search(query: tuple[str], kind: str, file_query: str, since: str, limit: int, json_out: bool):
    """Search compression history using full-text search (inspired by ctxrs/ctx)"""
    if not INDEX_AVAILABLE:
        console.print("  [red]SQLite index not available. Run: python token_index.py[/]")
        return
    q = " ".join(query)
    if file_query:
        results = search_files(file_query, limit=limit)
        label = f"files matching '{file_query}'"
    else:
        results = search_events(q, limit=limit, kind=kind, since=since)
        label = f"events matching '{q}'"
    if json_out:
        console.print(json.dumps(results, indent=2, default=str))
        return
    if not results:
        console.print(f"  [dim]No {label} found.[/]")
        return
    console.print(f"\n  [yellow]Search results: {label} ({len(results)} found)[/]\n")
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    tbl.add_column("Time", style="dim")
    tbl.add_column("Kind", style="cyan")
    tbl.add_column("Description", style="white")
    tbl.add_column("Saved", justify="right", style="green")
    tbl.add_column("%", justify="right", style="yellow")
    for r in results:
        ts = r.get("timestamp", "")[:19] if r.get("timestamp") else ""
        saved = r.get("saved_tokens", 0)
        pct = r.get("compression_pct", 0)
        tbl.add_row(ts, r.get("kind", "?"), r.get("description", "")[:50], f"+{saved:,}", f"{pct:.1f}%")
    console.print(tbl)

@cli.command(name="sql")
@click.argument("query_str")
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
def sql_cmd(query_str: str, json_out: bool):
    """Execute a read-only SQL query against the compression index"""
    if not INDEX_AVAILABLE:
        console.print("  [red]SQLite index not available. Run: python token_index.py[/]")
        return
    try:
        results = sql_query(query_str)
    except ValueError as e:
        console.print(f"  [red]{e}[/]")
        return
    except Exception as e:
        console.print(f"  [red]Query error: {e}[/]")
        return
    if json_out:
        console.print(json.dumps(results, indent=2, default=str))
        return
    if not results:
        console.print("  [dim]No results.[/]")
        return
    console.print(f"\n  [yellow]SQL query: {query_str[:80]}[/]  ({len(results)} rows)\n")
    if results:
        cols = list(results[0].keys())
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        for c in cols:
            tbl.add_column(c)
        for row in results:
            tbl.add_row(*[str(row.get(c, "")) for c in cols])
        console.print(tbl)

@cli.command()
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
def stats(json_out: bool):
    """Show aggregate compression statistics from the SQLite index"""
    if not INDEX_AVAILABLE:
        console.print("  [red]SQLite index not available. Run: python token_index.py[/]")
        return
    s = index_stats()
    if json_out:
        console.print(json.dumps(s, indent=2, default=str))
        return
    console.print(f"\n  [yellow]Token Saver Statistics[/]\n")
    console.print(f"  [cyan]Database:[/] {s.get('db_path', '?')}")
    console.print(f"  [cyan]Schema version:[/] {s.get('schema_version', '?')}")
    sess = s.get("sessions", {})
    console.print(f"  [cyan]Sessions:[/] {sess.get('total_sessions', 0)}")
    ev = s.get("events", {})
    console.print(f"  [cyan]Events:[/] {ev.get('total', 0)}")
    if ev.get("total", 0) > 0:
        console.print(f"  [cyan]Total saved:[/] [green]{ev.get('total_saved_tokens', 0):,} tokens[/]")
        console.print(f"  [cyan]Total raw:[/] {ev.get('total_raw_tokens', 0):,} tokens")
        console.print(f"  [cyan]Compression:[/] {ev.get('compression_pct', 0):.1f}%")
    by_kind = ev.get("by_kind", [])
    if by_kind:
        console.print(f"\n  [yellow]By kind:[/]")
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        tbl.add_column("Kind"); tbl.add_column("Count"); tbl.add_column("Saved"); tbl.add_column("Compression")
        for k in by_kind:
            raw = k.get("raw", 0)
            saved = k.get("saved", 0)
            pct = round(saved / raw * 100, 1) if raw > 0 else 0
            tbl.add_row(k.get("kind", "?"), str(k.get("count", 0)), f"{saved:,}", f"{pct}%")
        console.print(tbl)
    fs = s.get("files", {})
    if fs.get("total_files", 0) > 0:
        console.print(f"\n  [cyan]Files touched:[/] {fs.get('total_files', 0)} ({fs.get('unique_files', 0)} unique)")
        console.print(f"  [cyan]Avg file compression:[/] {fs.get('avg_compression', 0):.1f}%")
    px = s.get("proxy", {})
    if px.get("total_requests", 0) > 0:
        console.print(f"\n  [cyan]Proxy requests:[/] {px.get('total_requests', 0)}")
        console.print(f"  [cyan]Proxy saved:[/] [green]{px.get('total_saved', 0):,} tokens[/]")
    ca = s.get("cache", {})
    if ca.get("entries", 0) > 0:
        console.print(f"\n  [cyan]Cache entries:[/] {ca.get('entries', 0)} ({ca.get('total_hits', 0)} hits)")
    recent = s.get("recent_events", [])
    if recent:
        console.print(f"\n  [yellow]Recent events:[/]")
        for e in recent:
            ts = e.get("timestamp", "")[:16]
            console.print(f"    [dim]{ts}[/]  {e.get('kind', '?')}  {e.get('description', '')[:40]}  [green]+{e.get('saved_tokens', 0):,}[/]")

@cli.group()
def mcp():
    """MCP server for agent integration (inspired by ctxrs/ctx)"""
    pass

@mcp.command(name="start")
@click.option("--transport", type=click.Choice(["stdio", "http"]), default="stdio")
@click.option("--port", "-p", default=8201, type=int, help="HTTP port (only for http transport)")
def mcp_start(transport: str, port: int):
    """Start the MCP server for agent integration"""
    console.print(f"\n  [yellow]Starting Token Saver MCP server ({transport})...[/]")
    if INDEX_AVAILABLE:
        _init_index()
    try:
        from token_mcp import run_mcp_stdio, run_mcp_http
        if transport == "stdio":
            console.print("  [dim]Listening on stdin/stdout (JSON-RPC 2.0)[/]")
            run_mcp_stdio()
        else:
            run_mcp_http(port)
    except KeyboardInterrupt:
        console.print("\n  [green]MCP server stopped.[/]")

@mcp.command(name="status")
def mcp_status():
    """Show MCP server status"""
    mcp_cfg = Path.home() / ".config" / "opencode" / "compress" / "mcp.json"
    if not mcp_cfg.exists():
        console.print("  [dim]MCP server not configured. Start with: token-saver mcp start[/]")
        return
    try:
        cfg = json.loads(mcp_cfg.read_text("utf-8"))
    except: cfg = {}
    running = False
    if cfg.get("pid"):
        try:
            import psutil
            running = psutil.pid_exists(cfg["pid"])
        except ImportError:
            running = True  # assume running if we can't check
    console.print(f"\n  [cyan]Status:[/] {'[green]Running[/]' if running else '[red]Stopped[/]'}")
    console.print(f"  [cyan]Port:[/] {cfg.get('port', 8201)}")
    console.print(f"  [cyan]Transport:[/] {cfg.get('transport', 'stdio')}")
    console.print(f"  [cyan]PID:[/] {cfg.get('pid', '?')}")

@cli.command(name="skill")
@click.argument("action", type=click.Choice(["install", "status", "remove"]))
@click.option("--target", "-t", default="opencode", help="Target agent: opencode, cursor, codex, claude")
def skill_cmd(action: str, target: str):
    """Install/manage the Token Saver agent skill (inspired by ctxrs/ctx)"""
    skill_src = Path(__file__).parent / "skills" / "token-saver" / "SKILL.md"
    if action == "status":
        installed = []
        for agent_dir in _skill_install_dirs():
            if (agent_dir / "SKILL.md").exists():
                installed.append(str(agent_dir))
        if installed:
            console.print(f"\n  [green]Installed in:[/]")
            for d in installed:
                console.print(f"    {d}")
        else:
            console.print("  [dim]Not installed in any agent directory.[/]")
        return
    if action == "install":
        if not skill_src.exists():
            console.print(f"  [red]Skill manifest not found at {skill_src}[/]")
            return
        target_dirs = _skill_install_dirs(target)
        for d in target_dirs:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_src, d / "SKILL.md")
            console.print(f"  [green][OK] Installed to {d / 'SKILL.md'}[/]")
        if not target_dirs:
            console.print(f"  [yellow]No known install directory for target '{target}'.[/]")
            console.print(f"  [dim]Manually copy skills/token-saver/SKILL.md to your agent's skill directory.[/]")
    elif action == "remove":
        for agent_dir in _skill_install_dirs(target):
            skill_file = agent_dir / "SKILL.md"
            if skill_file.exists():
                skill_file.unlink()
                console.print(f"  [green][OK] Removed from {agent_dir}[/]")

def _skill_install_dirs(target: str = None) -> list[Path]:
    """Return possible skill install directories for known agents."""
    home = Path.home()
    dirs = []
    targets = [target] if target else ["opencode", "cursor", "codex", "claude"]
    for t in targets:
        if t == "opencode":
            d = home / ".config" / "opencode" / "skills" / "token-saver"
            dirs.append(d)
        elif t == "cursor":
            d = Path.cwd() / ".cursor" / "skills" / "token-saver"
            dirs.append(d)
        elif t == "codex":
            d = home / ".codex" / "skills" / "token-saver"
            dirs.append(d)
        elif t == "claude":
            d = home / ".claude" / "skills" / "token-saver"
            dirs.append(d)
    return dirs

@cli.command()
@click.option("--check", is_flag=True, help="Check for updates without installing")
@click.option("--apply", is_flag=True, help="Download and install the latest version")
def upgrade(check: bool, apply: bool):
    """Check for and apply Token Saver updates (inspired by ctxrs/ctx self-upgrade)"""
    console.print(f"\n  [yellow]Token Saver Upgrade[/]\n")
    console.print(f"  [cyan]Current version:[/] {TS_VERSION}")
    try:
        import requests
        r = requests.get("https://api.github.com/repos/zinzirobert/tokensaver/releases/latest", timeout=10)
        if r.status_code == 200:
            release = r.json()
            latest = release.get("tag_name", "?")
            console.print(f"  [cyan]Latest version:[/] {latest}")
            if latest == TS_VERSION:
                console.print("  [green]You are up to date![/]")
                return
            if check:
                console.print(f"  [yellow]Update available: {latest}[/]")
                console.print(f"  [dim]Run with --apply to install.[/]")
                return
            if apply:
                console.print(f"  [yellow]Updating to {latest}...[/]")
                # Download the latest release asset
                assets = release.get("assets", [])
                exe_asset = next((a for a in assets if "token-saver" in a.get("name", "").lower()), None)
                if exe_asset:
                    download_url = exe_asset.get("browser_download_url")
                    if download_url:
                        console.print(f"  [dim]Downloading from {download_url}[/]")
                        # For now, just show the URL
                        console.print(f"  [cyan]Download manually:[/] {download_url}")
                else:
                    console.print("  [dim]No binary asset found. Install via pip or download source.[/]")
            else:
                console.print(f"  [yellow]Update available: {latest}[/]")
                console.print(f"  [dim]Run with --apply to install.[/]")
        else:
            console.print("  [dim]Could not check for updates (GitHub API returned non-200).[/]")
    except Exception as e:
        console.print(f"  [dim]Could not check for updates: {e}[/]")

# ============================================================================
# INTERACTIVE MENU
# ============================================================================

def interactive_menu():
    cfg = read_config()
    current_model = cfg["model"] if cfg and cfg.get("model") else ""
    current_small = cfg["small_model"] if cfg and cfg.get("small_model") else ""

    items = [
        ("[bold yellow]>>> ONE-CLICK AUTO SETUP <<<[/]",    'auto_setup'),
        ("[bold green]Practical Saver (save-money)[/]",     'save_money'),
        ("",                                                'sep'),
        ("-- [cyan]COMPARE & PICK[/] --",                  'header'),
        ("Compare Models & Costs",                          'compare'),
        ("Switch Main Model",                               'model'),
        ("Switch Small Model",                              'small'),
        ("Model Heatmap",                                   'heatmap'),
        ("Cost Projection",                                 'calc'),
        ("",                                                'sep'),
        ("-- [cyan]COMPRESS[/] --",                        'header'),
        ("Compress File Read",                              'compress_read'),
        ("Compress Shell Output",                           'compress_shell'),
        ("Compress Batch Directory",                        'compress_batch'),
        ("Semantic AI Compress",                            'compress_semantic'),
        ("",                                                'sep'),
        ("-- [cyan]CACHE[/] --",                           'header'),
        ("Cache Stats / Clear",                             'cache'),
        ("Content Store",                                   'store'),
        ("Savings Ledger",                                  'savings'),
        ("",                                                'sep'),
        ("-- [cyan]PROXY[/] --",                           'header'),
        ("Start Compression Proxy",                         'proxy_start'),
        ("Stop Proxy",                                      'proxy_stop'),
        ("Proxy Status",                                    'proxy_stat'),
        ("",                                                'sep'),
        ("-- [cyan]EXTRAS[/] --",                          'header'),
        ("Providers & API Status",                          'providers'),
        ("Provider Health Check",                           'health'),
        ("Token Budget Planner",                            'budget'),
        ("Verify Config",                                   'verify'),
        ("Restore Backup",                                  'restore'),
        ("",                                                'sep'),
        ("Exit",                                            'exit'),
    ]

    while True:
        console.clear(); banner()
        console.print(status_panel())
        console.print("\n  [yellow]-- Menu --[/]\n")
        tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        selectable = []
        for label, action in items:
            if not label: continue
            if label.startswith("--"):
                tbl.add_row(f"  [dim]{label}[/]")
            else:
                selectable.append((label, action))
                tbl.add_row(f"  {len(selectable)}. {label}")
        console.print(tbl)
        console.print(f"\n  [dim]Enter number (1-{len(selectable)}) or 'q' to quit: [/]", end="")
        import msvcrt
        choice = b''
        while True:
            k = msvcrt.getch()
            if k in (b'q', b'Q', b'\x1b'): choice = b'q'; break
            if k in (b'\r', b'\n') and choice: break
            if k == b'\x08' or k == b'\x7f':
                if choice:
                    choice = choice[:-1]
                    print('\b \b', end='', flush=True)
                continue
            if k.isdigit(): choice += k; print(k.decode(), end='', flush=True)
        print(); console.print("")
        if choice == b'q': break
        try: idx = int(choice) - 1
        except (ValueError, IndexError): press_any(); continue
        if idx < 0 or idx >= len(selectable): press_any(); continue
        label, action = selectable[idx]

        if action == 'model':
            try:
                with console.status("[yellow]Fetching model catalog...[/]"):
                    catalog, _ = get_user_models()
                catalog = catalog or {}
                pick = select_model_from_provider(catalog, current_model, "Switch Main Model", configured_only=True)
                if pick and confirm(f"Apply {pick['name']} as main model?"):
                    write_config(pick["id"], current_small); current_model = pick["id"]
                    console.print(f"\n  [green][OK] Main model set to {pick['name']}[/]"); console.print("  [yellow]Restart opencode to take effect.[/]"); press_any()
            except Exception as e: console.print(f"  [red][ERR] {e}[/]"); import traceback; traceback.print_exc(); press_any()

        elif action == 'small':
            try:
                with console.status("[yellow]Fetching model catalog...[/]"):
                    catalog, _ = get_user_models()
                catalog = catalog or {}
                pick = select_model_from_provider(catalog, current_small, "Switch Small Model", configured_only=True)
                if pick and confirm(f"Apply {pick['name']} as small model?"):
                    write_config(current_model, pick["id"]); current_small = pick["id"]
                    console.print(f"\n  [green][OK] Small model set to {pick['name']}[/]"); console.print("  [yellow]Restart opencode to take effect.[/]"); press_any()
            except Exception as e: console.print(f"  [red][ERR] {e}[/]"); import traceback; traceback.print_exc(); press_any()

        elif action == 'compact':
            write_config(current_model, current_small)
            console.print("  [green][OK] Compaction: auto=ON  prune=ON  reserved=10000[/]"); console.print("  [yellow]Restart opencode to take effect.[/]"); press_any()

        elif action == 'calc':
            console.clear(); banner(); console.print("\n  [yellow]Token Calculator & Cost Projection[/]\n")
            catalog2 = None
            if CACHE_PATH.exists():
                try: catalog2, _ = get_user_models()
                except: pass
            model_info = find_model_in_catalog(catalog2, current_model) if catalog2 and current_model else None
            if model_info:
                inp = model_info['input_price']; outp = model_info['output_price']
                t = Table(box=box.SIMPLE, show_header=False)
                t.add_row(f"Model    : {model_info['name']}"); t.add_row(f"Provider : {model_info['provider']}")
                if inp > 0: t.add_row(f"Input    : ${inp:.4f}/M  ->  {round(1.0/inp,1)}M tokens per $1")
                else: t.add_row(f"Input    : [green]FREE[/]")
                if outp > 0: t.add_row(f"Output   : ${outp:.4f}/M  ->  {round(1.0/outp,1)}M tokens per $1")
                else: t.add_row(f"Output   : [green]FREE[/]")
                console.print(t)
            if catalog2: show_cost_projection(catalog2, current_model, current_small)
            if not model_info and not catalog2: console.print("  [dim]No pricing data. Run 'compare' first.[/]")
            press_any()

        elif action == 'save_max':
            console.clear(); banner()
            console.print("\n  [yellow]Maximize Savings — applying all optimizations...[/]\n")
            with console.status("[yellow]Fetching model catalog...[/]"):
                cat, _ = get_user_models()
            if not cat: console.print("  [red]Could not fetch data.[/]"); press_any(); continue
            configured = [m for k, pd in cat.items() if pd["configured"] for m in pd["models"]]
            if not configured: console.print("  [red]No configured providers.[/]"); press_any(); continue
            configured.sort(key=lambda x: x["input_price"] + x["output_price"])
            main_candidates = [m for m in configured if m["tool_call"]]
            if not main_candidates: main_candidates = configured
            main_model = main_candidates[0]
            small_model = configured[1] if len(configured) > 1 else configured[0]
            if small_model["id"] == main_model["id"]: small_model = configured[0]
            write_config(main_model["id"], small_model["id"])
            current_model = main_model["id"]; current_small = small_model["id"]
            steps = [(f"Model: {main_model['name']}", f"${main_model['input_price']+main_model['output_price']:.4f}/M"),
                     (f"Small: {small_model['name']}", f"${small_model['input_price']+small_model['output_price']:.4f}/M"),
                     ("Compaction", "auto+prune ON")]
            expensive = [m for m in configured[3:] if m["input_price"] + m["output_price"] > 5]
            for em in expensive[:3]:
                fallbacks = [m["id"] for m in configured[:3] if m["id"] != em["id"]]
                if fallbacks: FallbackChain.set_chain(em["id"], fallbacks); steps.append((f"Fallback: {em['name']}", f"-> {fallbacks[0]}"))
            s = CompressionProxy.status()
            if not s.get("running"):
                with console.status("[yellow]Starting compression proxy..."):
                    CompressionProxy.start_server()
                steps.append(("Proxy", "started (adaptive)"))
            else: steps.append(("Proxy", "already running"))
            tbl = Table(box=box.SIMPLE, show_header=False)
            tbl.add_column("Setting", style="cyan"); tbl.add_column("Value", style="green")
            for label, val in steps: tbl.add_row(f"  {label}", val)
            cost = main_model["input_price"] + main_model["output_price"]
            console.print(f"\n  [yellow]Optimizations Applied[/]\n"); console.print(tbl)
            if cost > 0:
                console.print(f"  [red]WARNING:[/] {main_model['name']} costs ${cost:.4f}/M tokens — not free.")
            console.print(f"  [yellow]>>> You MUST restart opencode for model + proxy to take effect <<<[/]")
            console.print(f"  [dim]Until restart: your current session still uses the old model without savings.[/]")
            press_any()

        elif action == 'save_money':
            console.clear(); banner()
            with console.status("[yellow]Checking provider availability..."):
                catalog, _ = get_user_models()
            console.print("\n  [yellow]Practical Saver[/]\n")
            console.print("  1. Free-tier mode (prefer free models, preserve limited tokens)")
            console.print("  2. Paid mode (cap paid model cost)")
            ch = input("  Choice: ").strip()
            mode = "free" if ch == "1" else "paid"
            max_cost_raw = input("  Max paid $/M input+output [5.0]: ").strip()
            try: max_cost = float(max_cost_raw) if max_cost_raw else 5.0
            except: max_cost = 5.0
            provider = input("  Provider filter [any]: ").strip() or None
            if catalog:
                configured = get_configured_providers()
                if not configured:
                    console.print("\n  [yellow]No API keys detected.[/] To use this feature, add at least one API key.\n")
                    free_providers = []
                    for pid, pdata in catalog.items():
                        if not isinstance(pdata, dict): continue
                        free_count = sum(1 for m in pdata.get("models", []) if m.get("is_free"))
                        if free_count > 0:
                            free_providers.append((pid, pdata.get("name", pid), free_count))
                    if free_providers:
                        console.print("  [green]Free models available (set one of these env vars):[/]\n")
                        known_free = [(pid, name, count) for pid, name, count in free_providers if pid in KNOWN_PROVIDER_ENV_VARS]
                        if not known_free:
                            known_free = free_providers
                        for pid, name, count in sorted(known_free, key=lambda x: -x[2])[:10]:
                            env_vars = KNOWN_PROVIDER_ENV_VARS.get(pid, [])
                            env_str = " or ".join(env_vars[:2]) if env_vars else f"{pid.upper()}_API_KEY"
                            console.print(f"    [cyan]{name}[/]  [dim]({count} free models)[/]  ->  set [yellow]{env_str}[/]")
                    console.print("\n  [dim]Example: set GROQ_API_KEY=your_key or OPENAI_API_KEY=your_key[/]")
                    console.print("  [dim]Then run this tool again.[/]")
                    press_any(); continue
            save_money.callback(save_mode=mode, task="coding", max_paid_cost=max_cost, daily_budget=1.0, free_token_limit=100000, provider=provider, apply=True, no_proxy=False)
            press_any()

        elif action == 'auto_setup':
            console.clear(); banner()
            console.print("\n  [bold yellow]=== ONE-CLICK FULL AUTO SETUP ===[/]\n")
            with console.status("[yellow]Fetching model catalog..."):
                catalog, _ = get_user_models()
            if not catalog:
                console.print("  [red]Could not fetch model data.[/]")
                press_any(); continue
            configured_list = [m for k, pd in catalog.items() if pd["configured"] for m in pd["models"]]
            if not configured_list:
                console.print("  [yellow]No configured providers detected.\n")
                console.print("  [yellow]Please add an API key first via environment variable or /connect in opencode.\n")
                free_any = sum(1 for k, pd in catalog.items() if sum(1 for m in pd.get("models", []) if m.get("is_free")))
                if free_any:
                    console.print("  [green]Free models available (set one):[/]")
                    for pid in sorted(KNOWN_PROVIDER_ENV_VARS)[:10]:
                        if pid in catalog:
                            free_n = sum(1 for m in catalog[pid].get("models", []) if m.get("is_free"))
                            if free_n > 0:
                                env_str = " or ".join(KNOWN_PROVIDER_ENV_VARS[pid][:2])
                                console.print(f"    [cyan]{catalog[pid]['name']}[/] ({free_n} free)  ->  set [yellow]{env_str}[/]")
                console.print("\n  [dim]Then run option 1 again.[/]")
                press_any(); continue
            configured_list.sort(key=lambda x: model_total_cost(x))
            free_models = [m for m in configured_list if m.get("is_free")]
            tool_models = [m for m in (free_models or configured_list) if m.get("tool_call")]
            main_model = (tool_models or free_models or configured_list)[0]
            small_candidates = [m for m in (free_models or configured_list) if m["id"] != main_model["id"]]
            small_model = small_candidates[0] if small_candidates else main_model
            cfg_before = read_config() or {}
            write_config(main_model["id"], small_model["id"])
            steps_applied = []
            steps_applied.append(f"[green]Main model[/]  {main_model['name']} ({'FREE' if main_model.get('is_free') else f'${model_total_cost(main_model):.4f}/M'})")
            steps_applied.append(f"[green]Small model[/] {small_model['name']} ({'FREE' if small_model.get('is_free') else f'${model_total_cost(small_model):.4f}/M'})")
            steps_applied.append(f"[green]Compaction[/] auto=ON  prune=ON  reserved=10000")
            expensive = [m for m in configured_list[3:] if model_total_cost(m) > 5]
            for em in expensive[:3]:
                cheap_fbs = [m["id"] for m in configured_list[:3] if m["id"] != em["id"]]
                if cheap_fbs:
                    FallbackChain.set_chain(em["id"], cheap_fbs)
                    steps_applied.append(f"[green]Fallback[/]  {em['name']} -> {cheap_fbs[0]}")
            s = CompressionProxy.status()
            if not s.get("running"):
                if CompressionProxy.start_server():
                    steps_applied.append(f"[green]Proxy[/]     started (adaptive — works with any provider)")
                else:
                    steps_applied.append("[yellow]Proxy[/]     couldn't start - may need restart")
            else:
                steps_applied.append(f"[green]Proxy[/]     already running")
            if free_models:
                steps_applied.append(f"[green]Free tier[/]  {len(free_models)} free models available")
            policy = read_saver_policy()
            policy.update({"mode": "free" if free_models else "paid", "last_applied": datetime.now().isoformat()})
            write_saver_policy(policy)
            tbl = Table(box=box.SIMPLE, show_header=False, title="[bold green]Setup Complete[/]")
            tbl.add_column("Setting", style="cyan")
            tbl.add_column("Value", style="white")
            for s in steps_applied:
                label, val = s.split("[/]", 1)
                tbl.add_row(f"  {label.strip()}[/]", val.strip())
            console.print(f"\n"); console.print(tbl)
            console.print(f"\n  [yellow]>>> Restart opencode for model + proxy changes to take effect <<<[/]")
            press_any()

        elif action == 'proxy_start':
            console.clear(); banner()
            s = CompressionProxy.status()
            if s.get("running"):
                console.print("  [yellow]Proxy is already running.[/]")
            else:
                with console.status("[yellow]Starting compression proxy..."):
                    CompressionProxy.start_server()
            console.print(f"  [cyan]Status:[/] {'[green]Running[/]' if CompressionProxy.status().get('running') else '[red]Stopped[/]'}")
            console.print(f"  [cyan]Port:[/] {CompressionProxy.status().get('port', 8199)}")
            console.print(f"  [cyan]Compression:[/] system prompts truncated, large content line-omitted, list items trimmed")
            console.print(f"  [cyan]Savings:[/] ~30-60% token reduction on forwarded requests")
            press_any()

        elif action == 'proxy_stop':
            console.clear(); banner()
            CompressionProxy.stop_server()
            press_any()

        elif action == 'proxy_stat':
            console.clear(); banner()
            s = CompressionProxy.status()
            console.print(f"\n  [cyan]Status:[/] {'[green]Running[/]' if s['running'] else '[red]Stopped[/]'}")
            console.print(f"  [cyan]Port:[/] {s['port']}")
            console.print(f"  [cyan]Requests served:[/] {s['requests_served']}")
            if s['total_saved_tokens'] > 0:
                console.print(f"  [cyan]Total tokens saved:[/] [green]{s['total_saved_tokens']:,}[/]")
            if s.get("models"):
                console.print(f"\n  [cyan]Models:[/]")
                for model, stats in sorted(s["models"].items(), key=lambda x: -x[1]["tokens"]):
                    console.print(f"    [bold]{model}[/]  [dim]{stats['requests']} reqs[/]  [green]{stats['tokens']:,} tokens saved[/]")
            press_any()

        elif action == 'compare':
            console.clear(); banner()
            with console.status("[yellow]Fetching model data...[/]"):
                catalog, new_models = get_user_models()
            if not catalog: console.print("  [red]Could not fetch data.[/]"); press_any(); continue
            show_new_models(new_models)
            for p in get_configured_providers(): console.print(f"  [green]> CONFIGURED:[/] {p}")
            show_models_table(catalog); press_any()

        elif action == 'free':
            console.clear(); banner()
            with console.status("[yellow]Fetching model data...[/]"):
                catalog, new_models = get_user_models()
            if not catalog: console.print("  [red]No data.[/]"); press_any(); continue
            show_new_models(new_models)
            cl = []; uf = {}
            for key, pd in catalog.items():
                fm = [m for m in pd["models"] if m["is_free"]]
                if not fm: continue
                if pd["configured"]: cl.append({**pd, "models": fm})
                else: uf[key] = {**pd, "models": fm}
            if cl:
                console.print(f"\n  [green]Free models from configured providers: {sum(len(pd['models']) for pd in cl)}[/]\n")
                show_models_table({f"{pd['id']} ({pd['name']})" if pd['name'] != pd['id'] else pd['id']: pd for pd in cl})
            if uf:
                console.print("\n  [yellow]Providers with free models (add API key):[/]")
                for key, pd in sorted(uf.items(), key=lambda x: -len(x[1]["models"])):
                    console.print(f"    [cyan]{pd['name']}[/]  [dim]({len(pd['models'])} free models)[/]")
            press_any()

        elif action == 'providers':
            console.clear(); banner()
            with console.status("[yellow]Fetching provider catalog...[/]"):
                catalog, _ = get_user_models()
            if not catalog: console.print("  [red]No data.[/]"); press_any(); continue
            configured = get_configured_providers()
            console.print(f"\n  [yellow]All Providers ({len(catalog)} found | {len(configured)} configured)[/]\n")
            tbl = Table(box=box.SIMPLE, show_header=False)
            tbl.add_column("Provider"); tbl.add_column("Status"); tbl.add_column("Models"); tbl.add_column("Details")
            for key, pd in sorted(catalog.items()):
                pid = pd["id"]
                status = "[green]CONFIGURED[/]" if pd["configured"] else "[red]NO API KEY[/]"
                detail = ""
                if pd["configured"]:
                    pconf = read_config().get("provider", {}).get(pid, {})
                    opts = pconf.get("options", {})
                    detail = f"timeout={opts.get('timeout','-')}ms"
                tbl.add_row(f"  [cyan]{pd['name']}[/]", status, str(len(pd["models"])), detail)
            console.print(tbl); press_any()

        elif action == 'verify':
            console.clear(); banner()
            oc = find_opencode()
            if not oc: console.print("  [red]opencode not found.[/]"); press_any(); continue
            console.print("\n  [yellow]Verify[/]")
            try: r = subprocess.run([oc, "debug", "config"], capture_output=True, text=True)
            except: console.print("  [red]Error running opencode[/]"); press_any(); continue
            if r.returncode != 0: console.print(f"  [red]opencode exit {r.returncode}[/]"); press_any(); continue
            try: parsed = json.loads(r.stdout)
            except: console.print("  [red]Parse error[/]"); press_any(); continue
            checks = [("compaction.auto", parsed.get("compaction",{}).get("auto")==True), ("compaction.prune", parsed.get("compaction",{}).get("prune")==True), ("compaction.reserved", parsed.get("compaction",{}).get("reserved",0)>0), ("small_model", bool(parsed.get("small_model"))), ("model", bool(parsed.get("model")))]
            all_ok = True
            for name, ok in checks:
                console.print(f"  [{'green' if ok else 'red'}]{'[OK]' if ok else '[ERR]'}[/]  {name}")
                if not ok: all_ok = False
            if all_ok: console.print(f"\n  [green]All active! Model: {parsed.get('model')}[/]")
            press_any()

        elif action == 'restore':
            console.clear(); banner()
            backups = list_backups()
            if not backups: console.print("  [red]No backups[/]")
            else:
                console.print("\n  [yellow]Available backups:[/]\n")
                for i, (label, _) in enumerate(backups, 1): console.print(f"  {i}. {label}")
                console.print("\n  [dim]Enter number (0 to cancel): [/]", end="")
                import msvcrt as m2
                rb = b''
                while True:
                    k = m2.getch()
                    if k in (b'\r', b'\n') and rb: break
                    if k.isdigit(): rb = k; print(k.decode(), end='', flush=True)
                print()
                if rb and rb != b'0':
                    bi = int(rb) - 1
                    if 0 <= bi < len(backups):
                        _, path = backups[bi]
                        if confirm(f"Restore {backups[bi][0]}?"): shutil.copy2(path, CONFIG_PATH); console.print(f"  [green][OK] Restored from {backups[bi][0]}[/]")
            press_any()

        elif action == 'recommend':
            console.clear(); banner()
            pick = menu("Select Task", [{"id":"coding","name":"Coding  — write code"},{"id":"review","name":"Review  — fast & cheap"},{"id":"planning","name":"Planning — strong reasoning"}])
            if not pick: continue
            with console.status("[yellow]Fetching catalog...[/]"):
                catalog, _ = get_user_models()
            if not catalog: press_any(); continue
            console.clear(); banner()
            console.print(f"\n  [yellow]Recommended models for [bold]{pick['name'].split('—')[0].strip()}[/][/]\n")
            recommend_models(catalog, pick["id"]); press_any()

        elif action == 'heatmap':
            console.clear(); banner()
            with console.status("[yellow]Fetching catalog...[/]"):
                catalog, _ = get_user_models()
            if not catalog: press_any(); continue
            show_heatmap(catalog); press_any()

        elif action == 'health':
            console.clear(); banner()
            with console.status("[yellow]Fetching catalog...[/]"):
                catalog, _ = get_user_models()
            if not catalog: press_any(); continue
            show_health_check(catalog); press_any()

        elif action == 'clean':
            console.clear(); banner()
            with console.status("[yellow]Fetching catalog...[/]"):
                catalog, _ = get_user_models()
            if not catalog: press_any(); continue
            clean_invalid_keys(catalog); press_any()

        elif action == 'compress_read':
            console.clear(); banner()
            console.print("\n  [yellow]Compress File Read[/]\n")
            fp = input("  File path: ").strip()
            if not fp: press_any(); continue
            print("  Mode (map/signatures/full/stats/density/lines/diff) [map]: ", end="")
            md = input().strip() or "map"
            result = ContentCache.cached_read(fp, mode=md)
            if "error" in result: console.print(f"  [red]{result['error']}[/]")
            else:
                cached = result.get("from_cache", False)
                console.print(f"\n  [cyan]Mode:[/] {result['mode']}{' [green](cached)[/]' if cached else ''}")
                console.print(f"  [cyan]Compression:[/] [green]{result.get('compression_pct',0):.1f}%[/]  (saved {result.get('saved_tokens',0):,} tokens)")
                if cached: console.print(f"  [cyan]Cache hit: re-read cost = ~13 tokens[/]")
                console.print(f"\n  [yellow]Content:[/]\n")
                c = result.get("content","")
                console.print(c[:3000] + (f"\n  [dim]... ({len(c)-3000} more chars)[/]" if len(c) > 3000 else ""))
            press_any()

        elif action == 'compress_shell':
            console.clear(); banner()
            console.print("\n  [yellow]Compress Shell Output[/]\n")
            cmd = input("  $ ").strip()
            if not cmd: press_any(); continue
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
                output = r.stdout + r.stderr
            except Exception as e: console.print(f"  [red][ERR] {e}[/]"); press_any(); continue
            if not output.strip(): console.print("  [dim](no output)[/]"); press_any(); continue
            result = ShellOutputCompressor.compress(cmd, output)
            console.print(f"  [cyan]Handler:[/] {result['handler']}")
            console.print(f"  [cyan]Compression:[/] [green]{result['compression_pct']:.1f}%[/]  (saved {result['saved_tokens']:,} tokens)")
            console.print(f"\n{result['compressed_output']}")
            press_any()

        elif action == 'compress_batch':
            console.clear(); banner()
            console.print("\n  [yellow]Compress Directory (Batch)[/]\n")
            dp = input("  Directory path: ").strip()
            if not dp or not Path(dp).is_dir(): console.print("  [red]Invalid directory.[/]"); press_any(); continue
            print("  Mode (map/signatures/full/stats) [map]: ", end="")
            md = input().strip() or "map"
            rec = input("  Recursive? (y/n) [y]: ").strip().lower() != "n"
            ext = input("  Extensions filter (comma-sep, e.g. .py,.js) [all]: ").strip() or None
            pattern = "**/*" if rec else "*"
            exts = [e.strip().lower() for e in ext.split(",")] if ext else None
            files = [f for f in Path(dp).glob(pattern) if f.is_file() and (not exts or f.suffix.lower() in exts)]
            if not files: console.print("  [yellow]No matching files.[/]"); press_any(); continue
            results = []; tr = 0; tc = 0
            with console.status(f"[yellow]Compressing {len(files)} files..."):
                for f in files:
                    r = FileReadCompressor.read(str(f), mode=md)
                    if "error" not in r: results.append(r); tr += r.get("size_bytes",0)//4; tc += r.get("compressed_tokens",0)
            tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
            tbl.add_column("File",style="white"); tbl.add_column("Lines",justify="right",style="dim"); tbl.add_column("Saved",justify="right",style="green"); tbl.add_column("%",justify="right",style="yellow")
            for r in results[:30]:
                tbl.add_row(r.get("file","?")[:45],str(r.get("lines",0)),str(r.get("saved_tokens",0)),f"{r.get('compression_pct',0):.1f}%")
            if len(results)>30: tbl.add_row(f"... ({len(results)-30} more)","","","")
            console.print(f"\n  [yellow]Batch: {len(results)} files | mode={md}[/]\n"); console.print(tbl)
            ts = tr-tc; pct = (1-tc/tr)*100 if tr>0 else 0
            console.print(f"\n  [cyan]Total:[/] {tr:,} -> {tc:,} tokens  [green]saved {ts:,} ({pct:.1f}%)[/]")
            SavingsLedger.log_entry("batch",f"batch {md}:{dp}",tr,tc,{"dir":dp,"mode":md,"files":len(results)})
            press_any()

        elif action == 'compress_semantic':
            console.clear(); banner()
            console.print("\n  [yellow]Semantic Compression (AI Summarize)[/]\n")
            fp = input("  File path: ").strip()
            if not fp: press_any(); continue
            result = SemanticCompressor.compress(fp)
            if "error" in result: console.print(f"  [red]{result['error']}[/]")
            else:
                note = result.get("note","")
                console.print(f"\n  [cyan]File:[/] {result['file']}")
                console.print(f"  [cyan]Mode:[/] semantic{' [dim]('+note+')[/]' if note else ''}")
                console.print(f"  [cyan]Compression:[/] [green]{result.get('compression_pct',0):.1f}%[/]  (saved {result.get('saved_tokens',0):,} tokens)")
                if "model_used" in result: console.print(f"  [cyan]Model:[/] {result['model_used']}")
                console.print(f"\n  [yellow]Summary:[/]\n")
                c = result.get("content","")
                console.print(c[:3000]+(f"\n  [dim]... ({len(c)-3000} more chars)[/]" if len(c)>3000 else ""))
            press_any()

        elif action == 'compress_msgs':
            console.clear(); banner()
            console.print("\n  [yellow]Messages Compression Test[/]\n")
            sample = [{"role":"system","content":"You are a helpful assistant."*50},{"role":"user","content":"Explain quantum computing."*30}]
            result = CompressionProxy.compress_messages(sample)
            console.print(f"  [cyan]Compression:[/] [green]{result['compression_pct']:.1f}%[/]")
            console.print(f"  [cyan]Raw:[/] {result['raw_tokens']:,} -> [green]{result['compressed_tokens']:,}[/] tokens")
            console.print(f"  [cyan]Saved:[/] [green]{result['saved_tokens']:,} tokens[/]")
            press_any()

        elif action == 'cache':
            console.clear(); banner(); s = ContentCache.stats()
            console.print(f"\n  [yellow]Content Cache[/]\n")
            console.print(f"  [cyan]Cached files:[/] {s['cached_files']}")
            if s['cached_files'] > 0: console.print(f"  [cyan]Total savings:[/] [green]{s['total_savings_tokens']:,} tokens[/]")
            console.print(f"\n  1. Clear cache")
            console.print(f"  2. Show cached list")
            console.print(f"  3. Back")
            ch = input("  Choice: ").strip()
            if ch == "1": ContentCache.clear(); console.print("  [green]Cache cleared.[/]")
            elif ch == "2": cache_list()
            press_any()

        elif action == 'store':
            console.clear(); banner(); ss = ContentStore.stats()
            console.print(f"\n  [yellow]Content-Addressed Store[/]\n")
            console.print(f"  [cyan]Entries:[/] {ss['entries']}")
            console.print(f"  [cyan]Total bytes:[/] {ss['total_bytes']:,}\n")
            console.print(f"  1. Store content (hash)")
            console.print(f"  2. Retrieve by hash")
            console.print(f"  3. Back")
            ch = input("  Choice: ").strip()
            if ch == "1":
                txt = input("  Content: ").strip()
                if txt: console.print(f"  [green]Hash:[/] {ContentStore.put(txt)}")
            elif ch == "2":
                h = input("  Hash: ").strip()
                if h:
                    d = ContentStore.get(h)
                    if d: console.print(f"\n{d[:1000]}")
                    else: console.print("  [red]Not found[/]")
            press_any()

        elif action == 'proxy':
            console.clear(); banner(); s = CompressionProxy.status()
            console.print(f"\n  [yellow]Compression Proxy[/]\n")
            console.print(f"  [cyan]Status:[/] {'[green]Running[/]' if s['running'] else '[red]Stopped[/]'}")
            console.print(f"  [cyan]Port:[/] {s['port']}")
            if s['total_saved_tokens'] > 0: console.print(f"  [cyan]Saved:[/] [green]{s['total_saved_tokens']:,} tokens[/]")
            console.print(f"\n  1. Start proxy")
            console.print(f"  2. Stop proxy")
            console.print(f"  3. Back")
            ch = input("  Choice: ").strip()
            if ch == "1": CompressionProxy.start_server()
            elif ch == "2": CompressionProxy.stop_server()
            press_any()

        elif action == 'dashboard':
            console.clear(); banner(); s = DashboardServer.status()
            console.print(f"\n  [yellow]Web Dashboard[/]\n")
            console.print(f"  [cyan]Status:[/] {'[green]Running[/]' if s.get('running') else '[red]Stopped[/]'}")
            if s.get('running'): console.print(f"  [cyan]URL:[/] http://127.0.0.1:{s.get('port',8200)}")
            console.print(f"\n  1. Start dashboard")
            console.print(f"  2. Stop dashboard")
            console.print(f"  3. Back")
            ch = input("  Choice: ").strip()
            if ch == "1": DashboardServer.start()
            elif ch == "2": DashboardServer.stop()
            press_any()

        elif action == 'budget':
            console.clear(); banner()
            console.print(f"\n  [yellow]Token Budget Planner[/]\n")
            print("  Task description: ", end="")
            desc = input().strip()
            if desc:
                print("  Budget limit [8000]: ", end="")
                lim = input().strip() or "8000"
                plan = TokenBudget.plan(desc, int(lim))
                TokenBudget.save_plan(plan)
                console.print(f"\n  [green]Budget planned: {plan['budget_limit']:,} tokens[/]")
                tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
                tbl.add_column("Category"); tbl.add_column("Tokens", justify="right"); tbl.add_column("%", justify="right")
                for k, v in plan["allocation"].items(): tbl.add_row(f"  {k}", f"{v:,}", f"{round(v/plan['budget_limit']*100,1)}%")
                console.print(tbl)
            press_any()

        elif action == 'savings':
            console.clear(); banner()
            console.print(f"\n  [yellow]Savings Ledger[/]\n")
            s = SavingsLedger.summary()
            console.print(f"  [cyan]Entries:[/] {s['total_entries']}")
            if s['total_entries'] > 0:
                console.print(f"  [cyan]Total saved:[/] [green]{s['total_saved_tokens']:,} tokens[/]")
                console.print(f"  [cyan]Compression:[/] {s['compression_pct']:.1f}%")
            v = SavingsLedger.verify()
            console.print(f"  [cyan]Integrity:[/] {'[green]Valid[/]' if v['valid'] else '[red]TAMPERED[/]'}")
            if v['entries'] > 0:
                console.print(f"\n  1. Show recent entries")
                console.print(f"  2. Back")
                ch = input("  Choice: ").strip()
                if ch == "1":
                    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
                    tbl.add_column("Time"); tbl.add_column("Kind"); tbl.add_column("Description"); tbl.add_column("Saved")
                    for e in SavingsLedger._load()[-10:]:
                        ts = e.get("timestamp","")[11:19]; tbl.add_row(ts, e.get("kind","?"), e.get("description","")[:40], f"[green]+{e.get('saved_tokens',0):,}[/]")
                    console.print(tbl)
            press_any()

        elif action == 'fallback':
            console.clear(); banner()
            console.print(f"\n  [yellow]Fallback Chains[/]\n")
            chains = FallbackChain.list_chains()
            if chains:
                tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
                tbl.add_column("Model", style="cyan"); tbl.add_column("Chain", style="white")
                for mid, flist in chains.items():
                    tbl.add_row(mid, " -> ".join(flist))
                console.print(tbl); console.print("")
            else: console.print("  [dim]No chains configured.\n")
            console.print(f"  1. Add chain")
            console.print(f"  2. Remove chain")
            console.print(f"  3. Resolve chain")
            console.print(f"  4. Back")
            ch = input("  Choice: ").strip()
            if ch == "1":
                mid = input("  Model ID: ").strip()
                flist = input("  Fallback models (comma-sep): ").strip()
                if mid and flist: FallbackChain.set_chain(mid, [f.strip() for f in flist.split(",")]); console.print("  [green]Chain saved.[/]")
            elif ch == "2":
                mid = input("  Model ID to remove: ").strip()
                if mid:
                    if FallbackChain.remove_chain(mid): console.print("  [green]Removed.[/]")
                    else: console.print("  [yellow]Not found.[/]")
            elif ch == "3":
                mid = input("  Model ID: ").strip()
                if mid:
                    resolved = FallbackChain.resolve(mid)
                    console.print(f"  [cyan]{' -> '.join(resolved)}[/]")
            press_any()

        elif action == 'exit': break

    console.clear(); banner()
    console.print("\n  [yellow]Bye! Restart opencode if you changed anything.[/]")

if __name__ == "__main__":
    known_commands = {"set", "save-max", "save-money", "compare", "free", "providers", "verify", "restore", "health", "recommend", "heatmap", "compress", "cache", "proxy", "budget", "savings", "store", "fallback", "dashboard", "search", "sql", "stats", "mcp", "skill", "upgrade", "--help", "-h"}
    first = sys.argv[1] if len(sys.argv) > 1 else ""
    if len(sys.argv) == 1:
        try: interactive_menu()
        except KeyboardInterrupt: pass
        sys.exit(0)
    if first not in known_commands:
        import io
        old_stderr = sys.stderr; sys.stderr = io.StringIO()
        sys.argv = [sys.argv[0]]
        interactive_menu()
        sys.stderr = old_stderr; sys.exit(0)
    try: cli()
    except KeyboardInterrupt:
        console.clear(); banner(); console.print("\n  [yellow]Bye![/]")



