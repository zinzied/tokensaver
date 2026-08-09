"""Persistent savings ledger for the chef proxy (stdlib only, thread-safe).

Every forwarded request is appended as one JSON line so savings survive a
proxy restart. All functions are best-effort and never raise.
"""

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

LEDGER_PATH = Path.home() / ".config" / "opencode" / "compress" / "chef-ledger.jsonl"
MAX_ENTRIES = 20000

_lock = threading.Lock()


def record(entry):
    """Append one request record to the ledger (never raises)."""
    entry = dict(entry)
    entry.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    try:
        with _lock:
            with open(str(LEDGER_PATH), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if _line_count() > MAX_ENTRIES:
                _trim()
    except OSError:
        pass


def read():
    """All entries, oldest -> newest."""
    out = []
    try:
        with _lock:
            with open(str(LEDGER_PATH), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except (ValueError, TypeError):
                        continue
    except OSError:
        pass
    return out


def today():
    """Aggregate totals for the current calendar day."""
    return _aggregate(date.today().isoformat())


def week_series(days=7):
    """Per-day totals for the last `days` days, oldest -> newest (zero-filled)."""
    today_d = date.today()
    buckets = {}
    for entry in read():
        d = _entry_date(entry)
        if d is None or (today_d - d).days >= days:
            continue
        b = buckets.setdefault(d.isoformat(), _blank())
        _add(b, entry)
    return [
        {"date": (today_d - timedelta(days=i)).isoformat(), **buckets.get((today_d - timedelta(days=i)).isoformat(), _blank())}
        for i in range(days - 1, -1, -1)
    ]


def recent(n=20):
    """Last `n` entries (newest last)."""
    return read()[-n:]


def reset():
    try:
        with _lock:
            LEDGER_PATH.unlink()
    except OSError:
        pass


def _blank():
    return {"requests": 0, "chars_saved": 0, "frost_tokens": 0, "tokens_saved": 0, "usd_saved": 0.0}


def _add(b, entry):
    b["requests"] += 1
    b["chars_saved"] += int(entry.get("chars_saved", 0) or 0)
    b["frost_tokens"] += int(entry.get("frost_saved_tokens", 0) or 0)
    b["tokens_saved"] += int(entry.get("tokens_saved", 0) or 0)
    b["usd_saved"] += float(entry.get("usd_saved", 0.0) or 0.0)


def _entry_date(entry):
    try:
        return datetime.fromisoformat(entry["ts"]).date()
    except (KeyError, ValueError, TypeError):
        return None


def _aggregate(key):
    b = _blank()
    for entry in read():
        d = _entry_date(entry)
        if d is None or d.isoformat() != key:
            continue
        _add(b, entry)
    return b


def _line_count():
    try:
        with open(str(LEDGER_PATH), encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _trim():
    lines = _line_count()
    if lines <= MAX_ENTRIES:
        return
    try:
        with open(str(LEDGER_PATH), encoding="utf-8") as f:
            data = f.readlines()
        with open(str(LEDGER_PATH), "w", encoding="utf-8") as f:
            f.writelines(data[-MAX_ENTRIES:])
    except OSError:
        pass
