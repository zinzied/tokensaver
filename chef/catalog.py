import re

from . import config
from .difficulty import classify

MODELS = [
    {"id": "chef/deepseek-chat", "provider": "openrouter",
     "route": "openai/gpt-oss-20b:free",
     "label": "GPT-OSS 20B (OpenRouter :free)", "tags": ["chat", "code", "tool"], "score": 96},
    {"id": "chef/gemini-flash", "provider": "openrouter",
     "route": "google/gemma-4-31b-it:free",
     "label": "Gemma 4 31B (OpenRouter :free)", "tags": ["chat", "code", "tool", "long"], "score": 95},
    {"id": "gemini/gemini-2.5-flash", "provider": "gemini", "route": "gemini-2.5-flash",
     "label": "Gemini 2.5 Flash (Google free tier)", "tags": ["chat", "code", "tool", "long"], "score": 94},
    {"id": "chef/deepseek-reasoner", "provider": "openrouter",
     "route": "nvidia/nemotron-3-ultra-550b-a55b:free",
     "label": "Nemotron 3 Ultra 550B (OpenRouter :free)", "tags": ["reasoning", "chat"], "score": 93},
    {"id": "chef/qwen-coder", "provider": "openrouter",
     "route": "cohere/north-mini-code:free",
     "label": "Cohere North Mini Code (OpenRouter :free)", "tags": ["code", "tool"], "score": 92},
    {"id": "chef/gpt-oss", "provider": "openrouter", "route": "google/gemma-4-26b-a4b-it:free",
     "label": "Gemma 4 26B (OpenRouter :free)", "tags": ["chat", "code", "tool"], "score": 91},
    {"id": "chef/llama-70b", "provider": "openrouter", "route": "nvidia/nemotron-3-super-120b-a12b:free",
     "label": "Nemotron 3 Super 120B (OpenRouter :free)", "tags": ["chat", "code"], "score": 90},
    {"id": "groq/llama-70b", "provider": "groq", "route": "llama-3.3-70b-versatile",
     "label": "Llama 3.3 70B (Groq free tier)", "tags": ["chat", "code", "tool"], "score": 89},
    {"id": "chef/mistral", "provider": "openrouter", "route": "nvidia/nemotron-3-nano-30b-a3b:free",
     "label": "Nemotron 3 Nano 30B (OpenRouter :free)", "tags": ["chat"], "score": 85},
    {"id": "chef/ollama-coder", "provider": "ollama", "route": "qwen2.5-coder:14b",
     "label": "Qwen2.5 Coder 14B (Ollama local)", "tags": ["code", "tool"], "score": 80},
    {"id": "groq/llama-8b", "provider": "groq", "route": "llama-3.1-8b-instant",
     "label": "Llama 3.1 8B (Groq free tier)", "tags": ["chat"], "score": 75},
    {"id": "chef/ollama-llama", "provider": "ollama", "route": "llama3.1:8b",
     "label": "Llama 3.1 8B (Ollama local)", "tags": ["chat"], "score": 70},
]

CATALOG_BY_ID = {m["id"]: m for m in MODELS}
DEFAULT = "chef/deepseek-chat"

ROUTES = [
    (re.compile(r"^(gpt-5|gpt-4o|gpt-4\b|chatgpt)"), "chef/deepseek-chat"),
    (re.compile(r"^(claude|opus|sonnet|haiku)"), "chef/deepseek-chat"),
    (re.compile(r"^(o[1-9]|o3-mini|o4-mini|o5)"), "chef/deepseek-reasoner"),
    (re.compile(r"^(gpt-oss)"), "chef/gpt-oss"),
    (re.compile(r"^(gemini|gemma)"), "chef/gemini-flash"),
    (re.compile(r"^(deepseek)"), "chef/deepseek-chat"),
]


def resolve_candidates(model):
    """Return ordered [(provider, route)] candidates for a requested model."""
    model = (model or "").strip()
    if not model:
        model = DEFAULT
    if model.startswith("chef/"):
        entry = CATALOG_BY_ID.get(model)
        if entry:
            return [(entry["provider"], entry["route"])]
    low = model.lower()
    if ":free" in low:
        return [("openrouter", model)]
    best = DEFAULT
    for pattern, cid in ROUTES:
        if pattern.search(low):
            best = cid
            break
    cands = [CATALOG_BY_ID[best]]
    seen = {(c["provider"], c["route"]) for c in cands}
    for entry in sorted(MODELS, key=lambda m: -m["score"]):
        if entry["id"] == best:
            continue
        key = (entry["provider"], entry["route"])
        if key in seen:
            continue
        cands.append(entry)
        seen.add(key)
    return [(c["provider"], c["route"]) for c in cands[:3]]


PAID_MODELS = [
    {"id": "paid/gpt-5", "provider": "openrouter", "route": "openai/gpt-5",
     "label": "OpenAI GPT-5", "tags": ["code", "reasoning", "tool"], "score": 100,
     "usd_per_m_input": 1.25, "usd_per_m_output": 10.0},
    {"id": "paid/claude-sonnet", "provider": "openrouter", "route": "anthropic/claude-sonnet-4-5",
     "label": "Claude Sonnet 4.5", "tags": ["code", "reasoning", "tool"], "score": 99,
     "usd_per_m_input": 3.0, "usd_per_m_output": 15.0},
    {"id": "paid/claude-opus", "provider": "openrouter", "route": "anthropic/claude-opus-4-1",
     "label": "Claude Opus 4.1", "tags": ["code", "reasoning", "tool"], "score": 98,
     "usd_per_m_input": 15.0, "usd_per_m_output": 75.0},
    {"id": "paid/gemini-pro", "provider": "openrouter", "route": "google/gemini-2.5-pro",
     "label": "Gemini 2.5 Pro", "tags": ["code", "reasoning", "tool", "long"], "score": 97,
     "usd_per_m_input": 1.25, "usd_per_m_output": 10.0},
    {"id": "paid/deepseek-chat", "provider": "openrouter", "route": "deepseek/deepseek-chat",
     "label": "DeepSeek Chat (paid)", "tags": ["chat", "code", "tool"], "score": 95,
     "usd_per_m_input": 0.14, "usd_per_m_output": 0.28},
    {"id": "paid/qwen-max", "provider": "openrouter", "route": "qwen/qwen3-max",
     "label": "Qwen3 Max", "tags": ["code", "reasoning"], "score": 94,
     "usd_per_m_input": 0.5, "usd_per_m_output": 1.6},
]
"""Strong paid models (served via OpenRouter). Prices are approximate per-million-token
input/output rates and are only used for budget-capping the HARD-task routing."""

PAID_CATALOG_BY_ID = {m["id"]: m for m in PAID_MODELS}

# Approximate $/M input-token rates for common models not in PAID_MODELS.
_COMMON_PRICES = [
    ("claude-opus", 15.0), ("opus", 15.0),
    ("claude-sonnet", 3.0), ("sonnet", 3.0), ("claude", 3.0),
    ("gpt-4o", 2.5), ("gpt-4.1", 2.0), ("gpt-4", 2.5),
    ("gpt-5-mini", 0.25), ("gpt-5", 1.25),
    ("gemini", 1.25), ("grok", 3.0), ("qwen3-max", 0.5),
    ("deepseek-chat", 0.14), ("llama-405b", 2.0),
]


def input_price_usd(model_id):
    """Approx $/M input tokens for a requested model (0 if free/local/unknown).

    Used only to estimate how much money routing paid -> free + compression
    actually saves. Free and local models carry no cost basis, so they yield 0.
    """
    if not model_id:
        return 0.0
    mid = model_id.lower()
    if ":free" in mid or mid.startswith("chef/") or mid.startswith("ollama"):
        return 0.0
    for m in PAID_MODELS:
        route = (m.get("route") or "").lower()
        name = route.rsplit("/", 1)[-1]
        if mid in (m["id"].lower(), route, name):
            return m["usd_per_m_input"]
    for token, price in _COMMON_PRICES:
        if token in mid:
            return price
    return 0.0

FREE_BY_LABEL = {
    "EASY": "chef/deepseek-chat",
    "MEDIUM": "chef/qwen-coder",
    "HARD": "chef/deepseek-reasoner",
}

# 3-tier labor ladder (Fable-orchestrator inspired):
#   bulk    -> mechanical volume: grep, format, rename, read          (free, effort low)
#   worker  -> implementation, tests, debug, routine judgment          (free, effort high)
#   expert  -> architecture, migrations, security, complex work        (paid, effort max)
TIER_ORDER = ["bulk", "worker", "expert"]
TIER_FREE = {
    "bulk": "chef/deepseek-chat",
    "worker": "chef/qwen-coder",
    "expert": "chef/deepseek-reasoner",
}
TIER_EFFORT = {"bulk": "low", "worker": "high", "expert": "max"}
TIER_NAMES = {"bulk": "mechanical volume", "worker": "implementation/judgment", "expert": "hard slices"}


def tier_for_score(score):
    if score >= config.DIFFICULTY_THRESHOLD:
        return "expert"
    if score >= 35:
        return "worker"
    return "bulk"


def tier_for_model(model_id):
    if (model_id or "").startswith("paid/"):
        return "expert"
    for tier, mid in TIER_FREE.items():
        if mid == model_id:
            return tier
    return None


def next_tier(tier):
    if tier not in TIER_ORDER:
        return None
    idx = TIER_ORDER.index(tier)
    if idx >= len(TIER_ORDER) - 1:
        return None
    return TIER_ORDER[idx + 1]


def model_for_tier(tier, max_paid_per_m=None):
    if tier == "expert":
        if not config.FREE_ONLY:
            paid = paid_candidates(max_paid_per_m)
            if paid:
                return paid[0][2]["id"]
        best = best_available_free(expert=True)
        if best:
            return best["id"]
        return TIER_FREE["expert"]
    return TIER_FREE[tier]


def recommend(text, max_paid_per_m=None):
    """Full difficulty-aware recommendation: label, score, tier, effort, model, chain."""
    d = classify(text or "")
    score = d["score"]
    tier = tier_for_score(score)
    effort = TIER_EFFORT[tier]
    if tier == "expert":
        if not config.FREE_ONLY:
            paid = paid_candidates(max_paid_per_m)
            if paid:
                top = paid[0][2]
                return {"label": d["label"], "score": score, "tier": tier, "effort": effort,
                        "model_id": top["id"], "cost": "paid", "price": top["usd_per_m_input"],
                        "model_label": top["label"],
                        "chain": [(p, r) for p, r, _ in paid] + free_expert_chain()}
        best = best_available_free(expert=True)
        mid = best["id"] if best else TIER_FREE["expert"]
        return {"label": d["label"], "score": score, "tier": tier, "effort": effort,
                "model_id": mid, "cost": "free", "price": 0.0,
                "model_label": CATALOG_BY_ID[mid]["label"],
                "chain": free_expert_chain()}
    mid = TIER_FREE[tier]
    return {"label": d["label"], "score": score, "tier": tier, "effort": effort,
            "model_id": mid, "cost": "free", "price": 0.0,
            "model_label": CATALOG_BY_ID[mid]["label"],
            "chain": free_chain(mid)}


def escalate(prompt, current_model="", max_paid_per_m=None):
    """Model one tier up for escalation; None when already at the ceiling."""
    d = classify(prompt or "")
    cur = tier_for_model(current_model) if current_model else tier_for_score(d["score"])
    nxt = next_tier(cur)
    if not nxt:
        return None
    return model_for_tier(nxt, max_paid_per_m)


def free_chain(primary_id, limit=3):
    """Ordered [(provider, route)] fallback chain starting from a free catalog model."""
    primary = CATALOG_BY_ID[primary_id]
    cands = [primary]
    seen = {(primary["provider"], primary["route"])}
    for entry in sorted(MODELS, key=lambda m: -m["score"]):
        key = (entry["provider"], entry["route"])
        if key in seen:
            continue
        cands.append(entry)
        seen.add(key)
        if len(cands) >= limit:
            break
    return [(c["provider"], c["route"]) for c in cands]


def _provider_ready(provider):
    if provider == "ollama":
        return True
    key = {"openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider)
    return bool(getattr(config, key, "")) if key else False


def best_available_free(expert=False):
    """Highest-scoring free model the user's providers can actually serve (None if no provider)."""
    models = sorted(MODELS, key=lambda m: -m["score"])
    if expert:
        for m in models:
            if "reasoning" in m["tags"] and _provider_ready(m["provider"]):
                return m
    for m in models:
        if _provider_ready(m["provider"]):
            return m
    return None


def free_expert_chain():
    """Expert-tier free fallback across ALL free providers (not just OpenRouter),
    reasoning first, so a user with only Groq/Gemini/Ollama still gets a strong
    free model for hard tasks."""
    primary = CATALOG_BY_ID["chef/deepseek-reasoner"]
    cands = [primary]
    seen = {(primary["provider"], primary["route"])}
    for entry in sorted(MODELS, key=lambda m: -m["score"]):
        key = (entry["provider"], entry["route"])
        if key in seen:
            continue
        cands.append(entry)
        seen.add(key)
    return [(c["provider"], c["route"]) for c in cands]


def paid_candidates(max_paid_per_m=None):
    """Paid models within budget, best score first, as [(provider, route, model)]."""
    if max_paid_per_m is None:
        max_paid_per_m = config.MAX_PAID_PER_M
    out = []
    for m in sorted(PAID_MODELS, key=lambda x: -x["score"]):
        if m["usd_per_m_input"] <= max_paid_per_m:
            out.append((m["provider"], m["route"], m))
    return out


def paid_route_candidates(model_id):
    for m in PAID_MODELS:
        if m["id"] == model_id:
            return [(m["provider"], m["route"])]
    return []


def resolve_difficulty_candidates(text, model_hint=""):
    """Difficulty-aware routing.

    - explicit chef/ or paid/ id or :free passthrough is honored as-is
    - HARD tasks (score >= CHEF_DIFFICULTY_THRESHOLD) -> paid chain within
      CHEF_MAX_PAID_USD_PER_M budget, falling back to free reasoning
    - MEDIUM -> free code/tool model, EASY -> free chat model
    """
    model_hint = (model_hint or "").strip()
    if model_hint.startswith("paid/"):
        return paid_route_candidates(model_hint)
    if model_hint.startswith("chef/") or ":free" in model_hint:
        return resolve_candidates(model_hint)
    d = classify(text or "")
    if d["score"] >= config.DIFFICULTY_THRESHOLD:
        if not config.FREE_ONLY:
            paid = paid_candidates()
            if paid:
                return [(p, r) for p, r, _ in paid] + free_expert_chain()
        return free_expert_chain()
    return free_chain(FREE_BY_LABEL.get(d["label"], DEFAULT))
