import { QUOTA_TRACKER_PATH } from './config.js';
import { readJson, writeJson, nowIsoUtc } from './utils.js';

export interface QuotaOpts {
  total?: number | null;
  used?: number | null;
  remaining?: number | null;
  reset_at?: string | null;
  account_id?: string | null;
  cost?: number | null;
}

interface QuotaEntry {
  provider: string;
  remaining?: number;
  total?: number;
  reset_in?: string;
  rate_limited?: boolean;
  cost?: number;
  requests?: number;
  last_checked?: string;
}

export class QuotaTracker {
  dataFile: string;
  _quotaData: { providers: Record<string, any>; accounts: Record<string, any> };

  constructor() {
    this.dataFile = QUOTA_TRACKER_PATH;
    this._quotaData = this._load();
  }

  _load(): { providers: Record<string, any>; accounts: Record<string, any> } {
    const data = readJson<{ providers?: Record<string, any>; accounts?: Record<string, any> }>(this.dataFile, null);
    if (data && data.providers && data.accounts) return { providers: data.providers, accounts: data.accounts };
    return { providers: {}, accounts: {} };
  }

  _save(): void {
    writeJson(this.dataFile, this._quotaData);
  }

  update_quota(provider: string, model: string | null = null, opts: QuotaOpts = {}): void {
    const { total, used, remaining, reset_at, account_id, cost } = opts;
    const now = nowIsoUtc();
    const prov = (this._quotaData.providers[provider] =
      this._quotaData.providers[provider] || {});
    prov.last_checked = now;
    if (model) prov.last_model = model;
    if (total !== undefined && total !== null) prov.total_quota = total;
    if (used !== undefined && used !== null) prov.used = used;
    if (remaining !== undefined && remaining !== null) prov.remaining = remaining;
    if (reset_at) prov.reset_at = reset_at;
    if (cost !== undefined && cost !== null) {
      prov.total_cost = (prov.total_cost || 0) + cost;
      prov.request_count = (prov.request_count || 0) + 1;
    }
    if (account_id) {
      const acc = (this._quotaData.accounts[account_id] =
        this._quotaData.accounts[account_id] || {});
      acc.provider = provider;
      if (model) acc.last_model = model;
      acc.last_used = now;
      if (remaining !== undefined && remaining !== null) acc.remaining = remaining;
      if (reset_at) acc.reset_at = reset_at;
    }
    this._save();
  }

  mark_rate_limited(provider: string, model: string | null = null, cooldownMs = 30000, accountId: string | null = null): void {
    const untilIso = new Date(Date.now() + cooldownMs).toISOString();
    const prov = (this._quotaData.providers[provider] =
      this._quotaData.providers[provider] || {});
    prov.rate_limited_until = untilIso;
    prov.rate_limited_model = model;
    if (accountId) {
      const acc = (this._quotaData.accounts[accountId] =
        this._quotaData.accounts[accountId] || {});
      acc.rate_limited_until = untilIso;
    }
    this._save();
  }

  get_quota(provider: string): Record<string, any> {
    return this._quotaData.providers[provider] || {};
  }

  get_account(accountId: string): Record<string, any> {
    return this._quotaData.accounts[accountId] || {};
  }

  get_reset_countdown(provider: string): string | null {
    const prov = this._quotaData.providers[provider] || {};
    const resetAt = prov.reset_at;
    if (!resetAt) return null;
    const resetMs = Date.parse(resetAt);
    if (Number.isNaN(resetMs)) return null;
    const remainingSec = Math.floor((resetMs - Date.now()) / 1000);
    if (remainingSec <= 0) return 'resetting now';
    const h = Math.floor(remainingSec / 3600);
    const m = Math.floor((remainingSec % 3600) / 60);
    const s = remainingSec % 60;
    const parts: string[] = [];
    if (h) parts.push(`${h}h`);
    if (m) parts.push(`${m}m`);
    parts.push(`${s}s`);
    return 'reset in ' + parts.join(' ');
  }

  is_rate_limited(provider: string, accountId: string | null = null): boolean {
    const now = Date.now();
    if (accountId) {
      const acc = this._quotaData.accounts[accountId] || {};
      const until = acc.rate_limited_until;
      if (until && Date.parse(until) > now) return true;
    }
    const prov = this._quotaData.providers[provider] || {};
    const until = prov.rate_limited_until;
    if (until && Date.parse(until) > now) return true;
    return false;
  }

  clear_rate_limit(provider: string, accountId: string | null = null): void {
    const prov = this._quotaData.providers[provider];
    if (prov) {
      delete prov.rate_limited_until;
      delete prov.rate_limited_model;
    }
    if (accountId && this._quotaData.accounts[accountId]) {
      delete this._quotaData.accounts[accountId].rate_limited_until;
    }
    this._save();
  }

  get_summary(): QuotaEntry[] {
    const summary: QuotaEntry[] = [];
    for (const [provider, data] of Object.entries(this._quotaData.providers)) {
      const entry: QuotaEntry = { provider };
      if (data.remaining !== undefined) entry.remaining = data.remaining;
      if (data.total_quota !== undefined) entry.total = data.total_quota;
      if (data.reset_at) entry.reset_in = this.get_reset_countdown(provider) || '';
      if (data.rate_limited_until) entry.rate_limited = true;
      if (data.total_cost !== undefined) {
        entry.cost = Math.round(data.total_cost * 10000) / 10000;
        entry.requests = data.request_count || 0;
      }
      entry.last_checked = data.last_checked || '';
      summary.push(entry);
    }
    return summary;
  }

  log_request(provider: string, model: string, tokensIn = 0, tokensOut = 0, cost = 0, accountId: string | null = null): void {
    const now = nowIsoUtc();
    const prov = (this._quotaData.providers[provider] =
      this._quotaData.providers[provider] || {});
    prov.total_tokens_in = (prov.total_tokens_in || 0) + tokensIn;
    prov.total_tokens_out = (prov.total_tokens_out || 0) + tokensOut;
    prov.total_cost = (prov.total_cost || 0) + cost;
    prov.request_count = (prov.request_count || 0) + 1;
    prov.last_request = now;
    prov.last_model = model;
    if (accountId) {
      const acc = (this._quotaData.accounts[accountId] =
        this._quotaData.accounts[accountId] || {});
      acc.last_request = now;
      acc.last_model = model;
      acc.total_cost = (acc.total_cost || 0) + cost;
    }
    this._save();
  }
}

const RATE_LIMIT_HEADERS: { remaining: string[]; total: string[]; reset: string[] }[] = [
  { remaining: ['x-ratelimit-remaining-tokens', 'x-ratelimit-remaining-requests', 'x-ratelimit-remaining'], total: ['x-ratelimit-limit-tokens', 'x-ratelimit-limit-requests', 'x-ratelimit-limit'], reset: ['x-ratelimit-reset-tokens', 'x-ratelimit-reset-requests', 'x-ratelimit-reset'] },
  { remaining: ['anthropic-ratelimit-tokens-remaining', 'anthropic-ratelimit-requests-remaining'], total: ['anthropic-ratelimit-tokens-limit', 'anthropic-ratelimit-requests-limit'], reset: ['anthropic-ratelimit-tokens-reset', 'anthropic-ratelimit-requests-reset'] },
];

export interface ParsedRateLimit {
  total: number | null;
  used: number | null;
  remaining: number | null;
  reset_at: string | null;
}

export function parse_rate_limit_headers(headers: Record<string, string | string[] | undefined> | null): ParsedRateLimit | null {
  if (!headers) return null;
  const lower: Record<string, string | string[] | undefined> = {};
  for (const [k, v] of Object.entries(headers)) lower[String(k).toLowerCase()] = v;

  for (const spec of RATE_LIMIT_HEADERS) {
    const remainingRaw = pickHeader(lower, spec.remaining);
    if (remainingRaw === undefined || remainingRaw === null || remainingRaw === '') continue;
    const remaining = Number(remainingRaw);
    const totalRaw = pickHeader(lower, spec.total);
    const total = totalRaw !== undefined && totalRaw !== null ? Number(totalRaw) : null;
    const resetRaw = pickHeader(lower, spec.reset);
    let resetAt: string | null = null;
    if (resetRaw !== undefined && resetRaw !== null && resetRaw !== '') {
      resetAt = normalizeReset(resetRaw);
    }
    return { total: Number.isFinite(total as number) ? total : null, used: null, remaining: Number.isFinite(remaining) ? remaining : null, reset_at: resetAt };
  }

  return null;
}

function pickHeader(lower: Record<string, string | string[] | undefined>, names: string[]): string | string[] | undefined {
  for (const n of names) {
    if (lower[n] !== undefined) return Array.isArray(lower[n]) ? lower[n][0] : lower[n];
  }
  return undefined;
}

export function normalizeReset(raw: string | string[]): string | null {
  const text = String(raw).trim().toLowerCase();
  const secs = /^([\d.]+)\s*s$/.exec(text);
  if (secs) return new Date(Date.now() + Number(secs[1]) * 1000).toISOString();
  const numeric = Number(text);
  if (Number.isFinite(numeric)) {
    if (numeric > 1e12) return new Date(numeric).toISOString();
    return new Date(Date.now() + numeric * 1000).toISOString();
  }
  const d = Date.parse(String(raw));
  if (!Number.isNaN(d)) return new Date(d).toISOString();
  return null;
}
