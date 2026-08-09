import json
import urllib.error
import urllib.request

from . import config
from .catalog import resolve_candidates, resolve_difficulty_candidates


class UpstreamError(Exception):
    pass


class ConfigError(Exception):
    pass


_last_route = ["", ""]


def last_route():
    """(provider, route) of the most recently successful upstream call."""
    return tuple(_last_route)


def reset_last_route():
    _last_route[0] = ""
    _last_route[1] = ""


PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "ollama": (None, None),
}


def provider_available(provider):
    if provider == "ollama":
        return True
    _, key_env = PROVIDERS[provider]
    return bool(getattr(config, key_env))


def base_url(provider):
    if provider == "ollama":
        return config.OLLAMA_HOST
    return PROVIDERS[provider][0]


def _request(provider, route, payload):
    url = base_url(provider).rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider != "ollama":
        _, key_env = PROVIDERS[provider]
        headers["Authorization"] = "Bearer " + getattr(config, key_env)
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://chef.local"
        headers["X-Title"] = "chef-agent-proxy"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise UpstreamError("%s/%s: HTTP %s: %s" % (provider, route, exc.code, body[:400]))
    except urllib.error.URLError as exc:
        raise UpstreamError("%s/%s: %s" % (provider, route, exc.reason))


def candidates_for(model_hint):
    cands = []
    for provider, route in resolve_candidates(model_hint):
        if provider_available(provider):
            cands.append((provider, route))
    if not cands:
        raise ConfigError(
            "No provider configured. Set OPENROUTER_API_KEY, GROQ_API_KEY, "
            "GEMINI_API_KEY, or run Ollama locally (OLLAMA_HOST)."
        )
    return cands


def candidates_for_difficulty(model_hint, text=None):
    """Difficulty-aware candidates: hard tasks -> paid chain, easy -> free."""
    cands = []
    for provider, route in resolve_difficulty_candidates(text or "", model_hint):
        if provider_available(provider):
            cands.append((provider, route))
    if not cands:
        raise ConfigError(
            "No provider configured. Set OPENROUTER_API_KEY, GROQ_API_KEY, "
            "GEMINI_API_KEY, or run Ollama locally (OLLAMA_HOST)."
        )
    return cands


def complete(payload, model_hint="", text=None, reasoning_effort=None):
    """Non-streaming completion with automatic fallback (difficulty-aware when text given)."""
    payload = dict(payload)
    payload["stream"] = False
    errors = []
    for provider, route in candidates_for_difficulty(model_hint, text):
        pld = dict(payload)
        pld["model"] = route
        if reasoning_effort:
            pld["reasoning_effort"] = reasoning_effort
        try:
            resp = _request(provider, route, pld)
            _last_route[0] = provider
            _last_route[1] = route
            return json.loads(resp.read().decode("utf-8", "replace"))
        except UpstreamError as exc:
            errors.append(str(exc))
    raise UpstreamError("All providers failed: " + "; ".join(errors))


def stream_first(payload, model_hint, text=None, reasoning_effort=None):
    """Try providers until one accepts the streaming request (difficulty-aware when text given)."""
    payload = dict(payload)
    payload["stream"] = True
    errors = []
    for provider, route in candidates_for_difficulty(model_hint, text):
        pld = dict(payload)
        pld["model"] = route
        if reasoning_effort:
            pld["reasoning_effort"] = reasoning_effort
        try:
            resp = _request(provider, route, pld)
            _last_route[0] = provider
            _last_route[1] = route
            return provider, route, resp
        except UpstreamError as exc:
            errors.append(str(exc))
    raise UpstreamError("All providers failed: " + "; ".join(errors))
