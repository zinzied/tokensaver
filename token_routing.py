import time
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

BACKOFF_CONFIG = {"base_ms": 2000, "max_ms": 300000, "max_level": 15}
TRANSIENT_COOLDOWN_MS = 30000
COOLDOWN_LONG_MS = 120000
COOLDOWN_SHORT_MS = 5000

ERROR_RULES = [
    {"text": "no credentials",           "cooldown_ms": COOLDOWN_LONG_MS},
    {"text": "request not allowed",      "cooldown_ms": COOLDOWN_SHORT_MS},
    {"text": "improperly formed request", "cooldown_ms": COOLDOWN_LONG_MS},
    {"text": "rate limit",               "backoff": True},
    {"text": "too many requests",        "backoff": True},
    {"text": "quota exceeded",           "backoff": True},
    {"text": "capacity",                 "backoff": True},
    {"text": "overloaded",               "backoff": True},
    {"status": 401, "cooldown_ms": COOLDOWN_LONG_MS},
    {"status": 402, "cooldown_ms": COOLDOWN_LONG_MS},
    {"status": 403, "cooldown_ms": COOLDOWN_LONG_MS},
    {"status": 404, "cooldown_ms": COOLDOWN_LONG_MS},
    {"status": 429, "backoff": True},
]

PROVIDER_TIERS = {
    "subscription": ["claude-code", "codex", "github-copilot", "cursor", "gemini-cli"],
    "cheap": ["glm", "minimax", "kimi"],
    "free": ["kiro", "opencode-free", "vertex", "iflow", "qwen"],
}

TIER_PRIORITY = ["subscription", "cheap", "free"]


def get_quota_cooldown(backoff_level=0):
    level = max(0, backoff_level - 1)
    cooldown = BACKOFF_CONFIG["base_ms"] * (2 ** level)
    return min(cooldown, BACKOFF_CONFIG["max_ms"])


def check_fallback_error(status, error_text, backoff_level=0):
    lower_error = (str(error_text) if error_text else "").lower()

    for rule in ERROR_RULES:
        if "text" in rule and rule["text"] in lower_error:
            if rule.get("backoff"):
                new_level = min(backoff_level + 1, BACKOFF_CONFIG["max_level"])
                return {"should_fallback": True,
                        "cooldown_ms": get_quota_cooldown(new_level),
                        "new_backoff_level": new_level}
            return {"should_fallback": True, "cooldown_ms": rule["cooldown_ms"]}

        if "status" in rule and rule["status"] == status:
            if rule.get("backoff"):
                new_level = min(backoff_level + 1, BACKOFF_CONFIG["max_level"])
                return {"should_fallback": True,
                        "cooldown_ms": get_quota_cooldown(new_level),
                        "new_backoff_level": new_level}
            return {"should_fallback": True, "cooldown_ms": rule["cooldown_ms"]}

    return {"should_fallback": True, "cooldown_ms": TRANSIENT_COOLDOWN_MS}


class AccountManager:
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path.home() / ".config" / "opencode" / "compress"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_file = self.data_dir / "accounts.json"
        self._accounts = self._load()
        self._rotation_state = {}

    def _load(self):
        if self.accounts_file.exists():
            try:
                with open(self.accounts_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"accounts": []}

    def _save(self):
        with open(self.accounts_file, "w") as f:
            json.dump(self._accounts, f, indent=2, default=str)

    def add_account(self, provider, api_key=None, base_url=None, priority=0):
        account = {
            "id": f"{provider}_{len(self._accounts['accounts'])}",
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "priority": priority,
            "is_active": True,
            "consecutive_use": 0,
            "rate_limited_until": None,
            "backoff_level": 0,
            "last_error": None,
            "model_locks": {},
        }
        self._accounts["accounts"].append(account)
        self._save()
        return account["id"]

    def get_active_accounts(self, provider, exclude_ids=None):
        exclude = set(exclude_ids or [])
        accounts = [a for a in self._accounts["accounts"]
                    if a["provider"] == provider and a.get("is_active", True)
                    and a["id"] not in exclude]
        now = time.time()
        available = []
        for a in accounts:
            until = a.get("rate_limited_until")
            if until:
                try:
                    if isinstance(until, str):
                        until_ts = time.mktime(__import__('datetime').datetime.fromisoformat(until).timetuple())
                    else:
                        until_ts = until
                    if until_ts > now:
                        continue
                except (ValueError, TypeError):
                    pass
            model_locks = a.get("model_locks", {})
            if any(lock_ts > now for lock_ts in model_locks.values() if lock_ts):
                continue
            available.append(a)
        return sorted(available, key=lambda x: x.get("priority", 0))

    def select_account(self, provider, strategy="fill-first", sticky_limit=1, model=None):
        accounts = self.get_active_accounts(provider)
        if not accounts:
            return None

        if strategy == "round-robin":
            rotation_key = f"{provider}:{model or '__all__'}"
            state = self._rotation_state.get(rotation_key, {"index": 0, "use_count": 0})

            if len(accounts) > 0:
                idx = state["index"] % len(accounts)
                account = accounts[idx]
                state["use_count"] += 1
                if state["use_count"] >= sticky_limit:
                    state["index"] = (idx + 1) % len(accounts)
                    state["use_count"] = 0
                self._rotation_state[rotation_key] = state
                return account

        return accounts[0]

    def mark_success(self, account_id):
        for a in self._accounts["accounts"]:
            if a["id"] == account_id:
                a["rate_limited_until"] = None
                a["backoff_level"] = 0
                a["last_error"] = None
                a["consecutive_use"] = a.get("consecutive_use", 0) + 1
                break
        self._save()

    def mark_error(self, account_id, status, error_text):
        for a in self._accounts["accounts"]:
            if a["id"] == account_id:
                result = check_fallback_error(status, error_text, a.get("backoff_level", 0))
                a["backoff_level"] = result.get("new_backoff_level", a.get("backoff_level", 0))
                cooldown = result["cooldown_ms"]
                if cooldown > 0:
                    a["rate_limited_until"] = (datetime.now(timezone.utc) + timedelta(milliseconds=cooldown)).isoformat()
                a["last_error"] = {"status": status, "message": str(error_text)[:200],
                                   "timestamp": time.time()}
                break
        self._save()

    def lock_model(self, account_id, model, cooldown_ms):
        for a in self._accounts["accounts"]:
            if a["id"] == account_id:
                locks = a.setdefault("model_locks", {})
                locks[model] = (datetime.now(timezone.utc) + timedelta(milliseconds=cooldown_ms)).isoformat()
                break
        self._save()

    def get_summary(self):
        return [{"id": a["id"], "provider": a["provider"],
                 "status": "active" if not a.get("rate_limited_until") else "rate_limited",
                 "priority": a.get("priority", 0)}
                for a in self._accounts["accounts"]]


class TieredRouter:
    def __init__(self, account_manager=None):
        self.account_manager = account_manager or AccountManager()
        self._rotation_state_cache = {}

    def get_tier_for_provider(self, provider_id):
        for tier, providers in PROVIDER_TIERS.items():
            if provider_id in providers:
                return tier
        return "free"

    def build_fallback_chain(self, provider_id):
        tier = self.get_tier_for_provider(provider_id)
        chain = []
        started = False
        for t in TIER_PRIORITY:
            if t == tier:
                started = True
            if started:
                for p in PROVIDER_TIERS.get(t, []):
                    if p != provider_id:
                        chain.append(p)
        return chain

    def resolve_model_chain(self, primary_provider, model=None, extra_fallbacks=None):
        chain = [primary_provider]
        chain.extend(self.build_fallback_chain(primary_provider))
        if extra_fallbacks:
            chain.extend(f for f in extra_fallbacks if f not in chain)
        return chain

    def try_account(self, provider, strategy="fill-first", model=None, exclude_ids=None):
        accounts = self.account_manager.get_active_accounts(provider, exclude_ids)
        if not accounts:
            return None, None

        if strategy == "round-robin":
            rotation_key = f"{provider}:{model or '__all__'}"
            state = self._rotation_state_cache.get(rotation_key, {"index": 0, "use_count": 0})
            sticky_limit = 1
            idx = state["index"] % len(accounts)
            account = accounts[idx]
            state["use_count"] += 1
            if state["use_count"] >= sticky_limit:
                state["index"] = (idx + 1) % len(accounts)
                state["use_count"] = 0
            self._rotation_state_cache[rotation_key] = state
            return account["id"], account

        return accounts[0]["id"], accounts[0]
