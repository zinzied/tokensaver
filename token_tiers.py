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

PROVIDER_MODEL_MAP = {
    "subscription": ["claude-sonnet-4-5", "claude-sonnet-4", "gpt-4o", "gemini-2.5-pro", "claude-haiku-3-5"],
    "cheap": ["glm-5.1", "minimax-m2.7", "kimi-k2.5"],
    "free": ["kiro-claude-sonnet", "opencode-gpt-4o", "gemini-2.0-flash", "iflow-default", "qwen-max"],
}

FALLBACK_ORDER = ["subscription", "cheap", "free"]


def get_tier_for_provider(provider_id):
    for tier, providers in PROVIDER_TIERS.items():
        if provider_id in providers:
            return tier
    return "free"


def get_providers_in_tier(tier):
    return dict(PROVIDER_TIERS.get(tier, {}))


def get_all_providers():
    result = {}
    for tier in FALLBACK_ORDER:
        result.update(PROVIDER_TIERS.get(tier, {}))
    return result


def get_provider_endpoint(provider_id):
    return PROVIDER_ENDPOINTS.get(provider_id, {})


def resolve_fallback_chain(provider_id):
    tier = get_tier_for_provider(provider_id)
    chain = []
    idx = FALLBACK_ORDER.index(tier)
    for t in FALLBACK_ORDER[idx + 1:]:
        chain.extend(PROVIDER_TIERS.get(t, {}).keys())
    return chain
