import json
import time
import base64
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta


TOKEN_REFRESH_PROVIDERS = {
    "claude-code": {
        "token_url": "https://api.anthropic.com/v1/oauth/token",
        "refresh_before_sec": 300,
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "gemini-cli": {
        "token_url": "https://oauth2.googleapis.com/token",
        "refresh_before_sec": 120,
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "github-copilot": {
        "token_url": "https://api.github.com/copilot/token",
        "refresh_before_sec": 60,
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}


class TokenRefreshError(Exception):
    pass


def decode_jwt_payload(token):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def get_token_expiry(token):
    payload = decode_jwt_payload(token)
    if payload and "exp" in payload:
        return payload["exp"]
    return None


def get_token_remaining_sec(token):
    exp = get_token_expiry(token)
    if exp is None:
        return None
    return exp - time.time()


def is_token_expired(token, buffer_sec=300):
    remaining = get_token_remaining_sec(token)
    if remaining is None:
        return False
    return remaining <= buffer_sec


class TokenRefresher:
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path.home() / ".config" / "opencode" / "compress"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_file = self.data_dir / "tokens.json"
        self._tokens = self._load()

    def _load(self):
        if self.tokens_file.exists():
            try:
                with open(self.tokens_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"tokens": {}, "config": {}}

    def _save(self):
        with open(self.tokens_file, "w") as f:
            json.dump(self._tokens, f, indent=2, default=str)

    def register_token(self, provider, token, refresh_token=None, expires_at=None):
        entry = {
            "provider": provider,
            "token": token[:20] + "..." if len(token) > 20 else token,
            "token_prefix": token[:20],
            "has_refresh_token": bool(refresh_token),
            "expires_at": expires_at,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        self._tokens["tokens"][provider] = entry
        self._save()

    def check_expiry(self, token):
        remaining = get_token_remaining_sec(token)
        if remaining is None:
            return {"status": "unknown", "message": "Not a JWT token or no expiry claim"}
        if remaining <= 0:
            return {"status": "expired", "remaining_sec": 0, "message": "Token is expired"}
        if remaining < 60:
            return {"status": "critical", "remaining_sec": int(remaining), "message": f"Expires in {int(remaining)}s"}
        if remaining < 300:
            return {"status": "warning", "remaining_sec": int(remaining), "message": f"Expires in {int(remaining)}s"}
        return {"status": "ok", "remaining_sec": int(remaining), "message": f"Expires in {int(remaining)}s"}

    def needs_refresh(self, provider):
        config = TOKEN_REFRESH_PROVIDERS.get(provider)
        if not config:
            return False
        buf = config.get("refresh_before_sec", 300)
        entry = self._tokens["tokens"].get(provider, {})
        token_prefix = entry.get("token_prefix", "")
        if not token_prefix:
            return False
        # Check if token is close to expiry (best-effort with prefix)
        remaining = get_token_remaining_sec(token_prefix)
        if remaining is None:
            return False
        return remaining <= buf

    def get_status_summary(self):
        summary = []
        for provider, entry in self._tokens["tokens"].items():
            cfg = TOKEN_REFRESH_PROVIDERS.get(provider, {})
            refresh_before = cfg.get("refresh_before_sec", 300)
            summary.append({
                "provider": provider,
                "has_refresh_token": entry.get("has_refresh_token", False),
                "auto_refresh": provider in TOKEN_REFRESH_PROVIDERS,
                "refresh_before_sec": refresh_before,
                "registered_at": entry.get("registered_at", ""),
            })
        return summary


def auto_refresh_token(provider, api_key):
    """Attempt to refresh a token if it's close to expiry.
    Returns (new_token, refreshed) tuple."""
    refresher = TokenRefresher()
    remaining = get_token_remaining_sec(api_key)
    if remaining is None:
        return api_key, False

    config = TOKEN_REFRESH_PROVIDERS.get(provider)
    if not config:
        return api_key, False

    buf = config.get("refresh_before_sec", 300)
    if remaining > buf:
        return api_key, False

    # Token needs refresh - in practice this would make an HTTP call
    # with the refresh_token to get a new access_token
    entry = refresher._tokens["tokens"].get(provider, {})
    refresh_token = entry.get("refresh_token")
    if not refresh_token:
        return api_key, False

    # Log that refresh is needed
    return api_key, False
