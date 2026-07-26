import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


class QuotaTracker:
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path.home() / ".config" / "opencode" / "compress"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.quota_file = self.data_dir / "quota_tracker.json"
        self._quota_data = self._load()

    def _load(self):
        if self.quota_file.exists():
            try:
                with open(self.quota_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"providers": {}, "accounts": {}}

    def _save(self):
        with open(self.quota_file, "w") as f:
            json.dump(self._quota_data, f, indent=2, default=str)

    def update_quota(self, provider, model=None, total=None, used=None, remaining=None,
                     reset_at=None, account_id=None, cost=None):
        now = datetime.now(timezone.utc).isoformat()
        prov = self._quota_data["providers"].setdefault(provider, {})
        prov["last_checked"] = now
        if model:
            prov["last_model"] = model
        if total is not None:
            prov["total_quota"] = total
        if used is not None:
            prov["used"] = used
        if remaining is not None:
            prov["remaining"] = remaining
        if reset_at:
            prov["reset_at"] = reset_at
        if cost is not None:
            prov.setdefault("total_cost", 0)
            prov["total_cost"] += cost
            prov.setdefault("request_count", 0)
            prov["request_count"] += 1
        if account_id:
            acc = self._quota_data["accounts"].setdefault(account_id, {})
            acc["provider"] = provider
            if model:
                acc["last_model"] = model
            acc["last_used"] = now
            if remaining is not None:
                acc["remaining"] = remaining
            if reset_at:
                acc["reset_at"] = reset_at
        self._save()

    def mark_rate_limited(self, provider, model=None, cooldown_ms=30000, account_id=None):
        until = datetime.now(timezone.utc) + timedelta(milliseconds=cooldown_ms)
        until_iso = until.isoformat()
        prov = self._quota_data["providers"].setdefault(provider, {})
        prov["rate_limited_until"] = until_iso
        prov["rate_limited_model"] = model
        if account_id:
            acc = self._quota_data["accounts"].setdefault(account_id, {})
            acc["rate_limited_until"] = until_iso
        self._save()

    def get_quota(self, provider):
        return self._quota_data["providers"].get(provider, {})

    def get_account(self, account_id):
        return self._quota_data["accounts"].get(account_id, {})

    def get_reset_countdown(self, provider):
        prov = self._quota_data["providers"].get(provider, {})
        reset_at = prov.get("reset_at")
        if not reset_at:
            return None
        try:
            reset_dt = datetime.fromisoformat(reset_at)
            remaining = reset_dt - datetime.now(timezone.utc)
            if remaining.total_seconds() <= 0:
                return "resetting now"
            total_sec = int(remaining.total_seconds())
            h, m = divmod(total_sec, 3600)
            m, s = divmod(m, 60)
            parts = []
            if h:
                parts.append(f"{h}h")
            if m:
                parts.append(f"{m}m")
            parts.append(f"{s}s")
            return "reset in " + " ".join(parts)
        except (ValueError, TypeError):
            return None

    def is_rate_limited(self, provider, account_id=None):
        if account_id:
            acc = self._quota_data["accounts"].get(account_id, {})
            until = acc.get("rate_limited_until")
            if until:
                try:
                    if datetime.fromisoformat(until) > datetime.now(timezone.utc):
                        return True
                except (ValueError, TypeError):
                    pass
        prov = self._quota_data["providers"].get(provider, {})
        until = prov.get("rate_limited_until")
        if until:
            try:
                if datetime.fromisoformat(until) > datetime.now(timezone.utc):
                    return True
            except (ValueError, TypeError):
                pass
        return False

    def clear_rate_limit(self, provider, account_id=None):
        prov = self._quota_data["providers"].get(provider)
        if prov:
            prov.pop("rate_limited_until", None)
            prov.pop("rate_limited_model", None)
        if account_id and account_id in self._quota_data["accounts"]:
            self._quota_data["accounts"][account_id].pop("rate_limited_until", None)
        self._save()

    def get_summary(self):
        summary = []
        for provider, data in self._quota_data["providers"].items():
            entry = {"provider": provider}
            if "remaining" in data:
                entry["remaining"] = data["remaining"]
            if "total_quota" in data:
                entry["total"] = data["total_quota"]
            if "reset_at" in data:
                entry["reset_in"] = self.get_reset_countdown(provider)
            if "rate_limited_until" in data:
                entry["rate_limited"] = True
            if "total_cost" in data:
                entry["cost"] = round(data["total_cost"], 4)
                entry["requests"] = data.get("request_count", 0)
            entry["last_checked"] = data.get("last_checked", "")
            summary.append(entry)
        return summary

    def log_request(self, provider, model, tokens_in=0, tokens_out=0, cost=0, account_id=None):
        now = datetime.now(timezone.utc).isoformat()
        prov = self._quota_data["providers"].setdefault(provider, {})
        prov.setdefault("total_tokens_in", 0)
        prov["total_tokens_in"] += tokens_in
        prov.setdefault("total_tokens_out", 0)
        prov["total_tokens_out"] += tokens_out
        prov.setdefault("total_cost", 0.0)
        prov["total_cost"] += cost
        prov.setdefault("request_count", 0)
        prov["request_count"] += 1
        prov["last_request"] = now
        prov["last_model"] = model
        if account_id:
            acc = self._quota_data["accounts"].setdefault(account_id, {})
            acc["last_request"] = now
            acc["last_model"] = model
            acc.setdefault("total_cost", 0.0)
            acc["total_cost"] += cost
        self._save()
