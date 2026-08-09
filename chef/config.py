import json
import os
from pathlib import Path

HOST = os.environ.get("CHEF_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHEF_PORT", "8787"))

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Difficulty routing: tasks scoring >= this get the strong chain.
DIFFICULTY_THRESHOLD = int(os.environ.get("CHEF_DIFFICULTY_THRESHOLD", "65"))
# Max input price ($/M tokens) for the paid model used on HARD tasks.
MAX_PAID_PER_M = float(os.environ.get("CHEF_MAX_PAID_USD_PER_M", "20"))
# Free-only mode: never use paid models even if a key is set. Hard tasks use
# the best free reasoning model from whichever providers you have.
FREE_ONLY = os.environ.get("CHEF_FREE_ONLY", "0").strip().lower() in ("1", "true", "yes", "on")
# Compress every request forwarded by the proxy (json crush, log dedup, caps).
COMPRESS = os.environ.get("CHEF_COMPRESS", "1").strip().lower() in ("1", "true", "yes", "on")
# Skip compression for requests under this many estimated tokens (avoids paying
# any processing overhead on prompts too small to save anything).
COMPRESS_MIN_TOKENS = int(os.environ.get("CHEF_COMPRESS_MIN_TOKENS", "200"))


def _opencode_auth_keys():
    """Load API keys already stored in opencode's auth.json.

    Returns {provider_id: api_key} for entries of type "api" that carry a key.
    """
    out = {}
    for p in (Path.home() / ".local" / "share" / "opencode" / "auth.json",
              Path.home() / ".config" / "opencode" / "auth.json"):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for pid, entry in data.items():
            if isinstance(entry, dict) and entry.get("type") == "api" and entry.get("key"):
                out[pid] = entry["key"]
    return out


# Fall back to keys already configured in opencode (env vars take precedence).
_AUTH_KEYS = _opencode_auth_keys()
if not OPENROUTER_API_KEY:
    OPENROUTER_API_KEY = _AUTH_KEYS.get("openrouter", "")
if not GROQ_API_KEY:
    GROQ_API_KEY = _AUTH_KEYS.get("groq", "")
if not GEMINI_API_KEY:
    GEMINI_API_KEY = _AUTH_KEYS.get("gemini", "")
